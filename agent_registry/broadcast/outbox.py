# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Event outbox: events are persisted before dispatch so a registry restart
never loses broadcast data.

Event status lifecycle: pending -> dispatched | delivery_failed | degraded.
"degraded" marks events skipped because a subscriber hit its rate limit and
received a SYNC_REQUIRED summary instead; they remain queryable via /changes.
"""

import json
import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from loguru import logger

from agent_registry.broadcast.events import RegistryEvent, utc_now_iso


class OutboxStore(ABC):
    @abstractmethod
    def append(self, event: RegistryEvent) -> RegistryEvent:
        """Assign the next registry_version, persist, and return the event."""
        ...

    @abstractmethod
    def mark_status(self, event_id: str, status: str,
                    dispatched_at: Optional[str] = None) -> bool:
        ...

    @abstractmethod
    def list_pending(self) -> List[RegistryEvent]:
        ...

    @abstractmethod
    def list_after(self, version: int, limit: int) -> List[RegistryEvent]:
        """Events with registry_version > version, ascending."""
        ...

    @abstractmethod
    def max_version(self) -> int:
        ...

    @abstractmethod
    def cleanup(self, retention_days: int) -> int:
        """Remove non-pending events older than the retention window."""
        ...

    @abstractmethod
    def close(self):
        ...


def _iso_minus_days(days: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.isoformat()


class MemoryOutbox(OutboxStore):
    """In-memory outbox. Used for vectordb persistence mode and tests."""

    def __init__(self):
        self._events: List[RegistryEvent] = []
        self._lock = threading.Lock()

    def append(self, event: RegistryEvent) -> RegistryEvent:
        with self._lock:
            event.registry_version = self.max_version() + 1
            event.status = "pending"  # type: ignore[attr-defined]
            self._events.append(event)
            return event

    def mark_status(self, event_id: str, status: str,
                    dispatched_at: Optional[str] = None) -> bool:
        with self._lock:
            for event in self._events:
                if event.event_id == event_id:
                    event.status = status  # type: ignore[attr-defined]
                    event.dispatched_at = dispatched_at or utc_now_iso()  # type: ignore[attr-defined]
                    return True
            return False

    def list_pending(self) -> List[RegistryEvent]:
        with self._lock:
            return [e for e in self._events if getattr(e, "status", "pending") == "pending"]

    def list_after(self, version: int, limit: int) -> List[RegistryEvent]:
        with self._lock:
            matched = [e for e in self._events if e.registry_version > version]
            return matched[:limit]

    def max_version(self) -> int:
        return max((e.registry_version for e in self._events), default=0)

    def cleanup(self, retention_days: int) -> int:
        cutoff = _iso_minus_days(retention_days)
        with self._lock:
            kept, removed = [], 0
            for event in self._events:
                status = getattr(event, "status", "pending")
                if status != "pending" and event.timestamp < cutoff:
                    removed += 1
                else:
                    kept.append(event)
            self._events = kept
            return removed

    def close(self):
        pass


class SqlOutbox(OutboxStore):
    """
    SQL-backed outbox delegating connection management to the registry's main
    storage backend (works for PostgreSQL, GaussDB, and SQLite alike).
    """

    def __init__(self, backend):
        self._backend = backend
        self._lock = threading.Lock()
        self._ensure_table()

    @property
    def _ph(self):
        return getattr(self._backend, "param_ph", "%s")

    def _ensure_table(self):
        ddl = """
            CREATE TABLE IF NOT EXISTS registry_events (
                event_id         VARCHAR(64) PRIMARY KEY,
                registry_version BIGINT      NOT NULL,
                event_type       VARCHAR(32) NOT NULL,
                payload          TEXT        NOT NULL,
                status           VARCHAR(16) NOT NULL DEFAULT 'pending',
                retry_count      INT         NOT NULL DEFAULT 0,
                created_at       VARCHAR(64) NOT NULL,
                dispatched_at    VARCHAR(64)
            )
        """
        self._backend._execute_write(ddl)
        self._backend.ensure_index(
            "CREATE INDEX IF NOT EXISTS idx_registry_events_version "
            "ON registry_events(registry_version)",
            "CREATE INDEX idx_registry_events_version ON registry_events(registry_version)"
        )
        self._backend.ensure_index(
            "CREATE INDEX IF NOT EXISTS idx_registry_events_status "
            "ON registry_events(status)",
            "CREATE INDEX idx_registry_events_status ON registry_events(status)"
        )
        logger.info("Outbox table 'registry_events' created/verified")

    def append(self, event: RegistryEvent) -> RegistryEvent:
        with self._lock:
            row = self._backend._execute_read_one(
                "SELECT COALESCE(MAX(registry_version), 0) FROM registry_events"
            )
            event.registry_version = int(row[0] or 0) + 1
            self._backend._execute_write(
                "INSERT INTO registry_events (event_id, registry_version, event_type, "
                "payload, status, retry_count, created_at, dispatched_at) "
                f"VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph}, 'pending', 0, {self._ph}, NULL)",
                (event.event_id, event.registry_version, event.event_type.value,
                 json.dumps(event.to_dict()), event.timestamp)
            )
            return event

    def mark_status(self, event_id: str, status: str,
                    dispatched_at: Optional[str] = None) -> bool:
        return self._backend._execute_write(
            f"UPDATE registry_events SET status = {self._ph}, "
            f"dispatched_at = {self._ph} WHERE event_id = {self._ph}",
            (status, dispatched_at or utc_now_iso(), event_id)
        ) > 0

    def _row_to_event(self, row) -> RegistryEvent:
        event = RegistryEvent.from_dict(json.loads(row[0]))
        event.status = row[1]  # type: ignore[attr-defined]
        return event

    def list_pending(self) -> List[RegistryEvent]:
        rows = self._backend._execute_read_all(
            f"SELECT payload, status FROM registry_events WHERE status = {self._ph} "
            "ORDER BY registry_version ASC",
            ("pending",)
        )
        return [self._row_to_event(r) for r in rows]

    def list_after(self, version: int, limit: int) -> List[RegistryEvent]:
        rows = self._backend._execute_read_all(
            f"SELECT payload, status FROM registry_events WHERE registry_version > {self._ph} "
            f"ORDER BY registry_version ASC LIMIT {int(limit)}",
            (version,)
        )
        return [self._row_to_event(r) for r in rows]

    def max_version(self) -> int:
        row = self._backend._execute_read_one(
            "SELECT COALESCE(MAX(registry_version), 0) FROM registry_events"
        )
        return int(row[0] or 0)

    def cleanup(self, retention_days: int) -> int:
        cutoff = _iso_minus_days(retention_days)
        return self._backend._execute_write(
            f"DELETE FROM registry_events WHERE status != {self._ph} AND created_at < {self._ph}",
            ("pending", cutoff)
        )

    def close(self):
        pass


class FileOutbox(OutboxStore):
    """
    JSONL append-only outbox for file persistence mode. Each mutation appends
    a full event snapshot line; the latest line per event_id wins on load.
    """

    def __init__(self, file_path: str):
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._events: List[RegistryEvent] = self._load()

    def _load(self) -> List[RegistryEvent]:
        if not self._path.exists():
            return []
        latest: dict = {}
        order: List[str] = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = RegistryEvent.from_dict(json.loads(line))
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Skipping malformed outbox line: {e}")
                        continue
                    if event.event_id not in latest:
                        order.append(event.event_id)
                    latest[event.event_id] = event
        except OSError as e:
            logger.error(f"Failed to load outbox file: {e}")
            return []
        return [latest[eid] for eid in order]

    def _append_line(self, event: RegistryEvent):
        payload = dict(event.to_dict())
        payload["status"] = getattr(event, "status", "pending")
        payload["dispatched_at"] = getattr(event, "dispatched_at", None)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        os.chmod(self._path, 0o600)

    def append(self, event: RegistryEvent) -> RegistryEvent:
        with self._lock:
            event.registry_version = self.max_version() + 1
            event.status = "pending"  # type: ignore[attr-defined]
            self._events.append(event)
            self._append_line(event)
            return event

    def mark_status(self, event_id: str, status: str,
                    dispatched_at: Optional[str] = None) -> bool:
        with self._lock:
            for event in self._events:
                if event.event_id == event_id:
                    event.status = status  # type: ignore[attr-defined]
                    event.dispatched_at = dispatched_at or utc_now_iso()  # type: ignore[attr-defined]
                    self._append_line(event)
                    return True
            return False

    def list_pending(self) -> List[RegistryEvent]:
        with self._lock:
            return [e for e in self._events if getattr(e, "status", "pending") == "pending"]

    def list_after(self, version: int, limit: int) -> List[RegistryEvent]:
        with self._lock:
            matched = [e for e in self._events if e.registry_version > version]
            return matched[:limit]

    def max_version(self) -> int:
        return max((e.registry_version for e in self._events), default=0)

    def cleanup(self, retention_days: int) -> int:
        cutoff = _iso_minus_days(retention_days)
        with self._lock:
            kept, removed = [], 0
            for event in self._events:
                status = getattr(event, "status", "pending")
                if status != "pending" and event.timestamp < cutoff:
                    removed += 1
                else:
                    kept.append(event)
            if removed > 0:
                self._events = kept
                lines = []
                for event in self._events:
                    payload = dict(event.to_dict())
                    payload["status"] = getattr(event, "status", "pending")
                    payload["dispatched_at"] = getattr(event, "dispatched_at", None)
                    lines.append(json.dumps(payload, ensure_ascii=False))
                tmp_path = self._path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + ("\n" if lines else ""))
                os.replace(tmp_path, self._path)
                os.chmod(self._path, 0o600)
            return removed

    def close(self):
        pass
