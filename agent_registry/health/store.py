# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Heartbeat storage backends: in-memory (default) and SQL (delegated)."""

import threading
import uuid
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from loguru import logger

from agent_registry.health.state import HealthState, HealthStatus

HISTORY_MEMORY_MAXLEN = 500


class HeartbeatStore(ABC):
    @abstractmethod
    def record_heartbeat(self, name: str, organization: str,
                         received_at: datetime) -> Tuple[Optional[HealthStatus], HealthState]:
        """
        Upsert a heartbeat. Returns (previous_status, new_state); previous_status
        is None when the agent had never sent a heartbeat before.
        """
        ...

    @abstractmethod
    def get(self, name: str, organization: str) -> Optional[HealthState]:
        ...

    @abstractmethod
    def list_monitored(self) -> List[HealthState]:
        ...

    @abstractmethod
    def update_status(self, name: str, organization: str,
                      new_status: HealthStatus, changed_at: datetime) -> bool:
        ...

    @abstractmethod
    def remove(self, name: str, organization: str) -> None:
        ...

    @abstractmethod
    def append_history(self, name: str, organization: str,
                       previous_status: HealthStatus, new_status: HealthStatus,
                       changed_at: datetime) -> None:
        """Record a health status transition (newest first on query)."""
        ...

    @abstractmethod
    def list_history(self, name: Optional[str] = None,
                     organization: Optional[str] = None,
                     limit: int = 50) -> List[dict]:
        ...

    @abstractmethod
    def close(self):
        ...


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class MemoryHeartbeatStore(HeartbeatStore):
    """Dict + lock; registry restart resets monitoring (agents re-heartbeat)."""

    def __init__(self):
        self._states = {}
        self._history = deque(maxlen=HISTORY_MEMORY_MAXLEN)
        self._lock = threading.Lock()

    def record_heartbeat(self, name, organization, received_at):
        with self._lock:
            existing = self._states.get((name, organization))
            if existing is not None:
                previous = existing.status
                existing.last_heartbeat_at = received_at
                if existing.status != HealthStatus.HEALTHY:
                    existing.status = HealthStatus.HEALTHY
                    existing.status_changed_at = received_at
                return previous, existing
            state = HealthState(
                name=name, organization=organization,
                last_heartbeat_at=received_at,
                status=HealthStatus.HEALTHY,
                status_changed_at=received_at,
            )
            self._states[(name, organization)] = state
            return None, state

    def get(self, name, organization):
        with self._lock:
            return self._states.get((name, organization))

    def list_monitored(self):
        with self._lock:
            return list(self._states.values())

    def update_status(self, name, organization, new_status, changed_at):
        with self._lock:
            state = self._states.get((name, organization))
            if state is None:
                return False
            state.status = new_status
            state.status_changed_at = changed_at
            return True

    def remove(self, name, organization):
        with self._lock:
            self._states.pop((name, organization), None)

    def append_history(self, name, organization, previous_status, new_status, changed_at):
        entry = {
            "name": name,
            "organization": organization,
            "previous_health_status": previous_status.value,
            "health_status": new_status.value,
            "changed_at": changed_at.isoformat(),
        }
        with self._lock:
            self._history.appendleft(entry)

    def list_history(self, name=None, organization=None, limit=50):
        with self._lock:
            matched = []
            for entry in self._history:
                if name is not None and entry["name"] != name:
                    continue
                if organization is not None and entry["organization"] != organization:
                    continue
                matched.append(dict(entry))
                if len(matched) >= limit:
                    break
            return matched

    def close(self):
        pass


class SqlHeartbeatStore(HeartbeatStore):
    """SQL-backed health store delegating connections to the main storage backend."""

    def __init__(self, backend):
        self._backend = backend
        self._lock = threading.Lock()
        self._ensure_table()

    @property
    def _ph(self):
        return getattr(self._backend, "param_ph", "%s")

    def _ensure_table(self):
        self._backend._execute_write("""
            CREATE TABLE IF NOT EXISTS agent_health (
                agent_name         VARCHAR(100) NOT NULL,
                organization       VARCHAR(100) NOT NULL,
                last_heartbeat_at  VARCHAR(64)  NOT NULL,
                status             VARCHAR(16)  NOT NULL,
                status_changed_at  VARCHAR(64)  NOT NULL,
                PRIMARY KEY (agent_name, organization)
            )
        """)
        self._backend.ensure_index(
            "CREATE INDEX IF NOT EXISTS idx_agent_health_status ON agent_health(status)",
            "CREATE INDEX idx_agent_health_status ON agent_health(status)"
        )
        self._backend._execute_write("""
            CREATE TABLE IF NOT EXISTS agent_health_history (
                event_id           VARCHAR(64)  PRIMARY KEY,
                agent_name         VARCHAR(100) NOT NULL,
                organization       VARCHAR(100) NOT NULL,
                previous_status    VARCHAR(16)  NOT NULL,
                new_status         VARCHAR(16)  NOT NULL,
                changed_at         VARCHAR(64)  NOT NULL
            )
        """)
        self._backend.ensure_index(
            "CREATE INDEX IF NOT EXISTS idx_agent_health_history_agent "
            "ON agent_health_history(agent_name, organization)",
            "CREATE INDEX idx_agent_health_history_agent "
            "ON agent_health_history(agent_name, organization)"
        )
        logger.info("Health tables 'agent_health'/'agent_health_history' created/verified")

    def _row_to_state(self, row) -> HealthState:
        return HealthState(
            name=row[0], organization=row[1],
            last_heartbeat_at=_from_iso(row[2]),
            status=HealthStatus(row[3]),
            status_changed_at=_from_iso(row[4]),
        )

    def record_heartbeat(self, name, organization, received_at):
        with self._lock:
            row = self._backend._execute_read_one(
                f"SELECT agent_name, organization, last_heartbeat_at, status, "
                f"status_changed_at FROM agent_health WHERE agent_name = {self._ph} "
                f"AND organization = {self._ph}",
                (name, organization)
            )
            if row is not None:
                previous = HealthStatus(row[3])
                new_status = HealthStatus.HEALTHY if previous != HealthStatus.HEALTHY else previous
                changed_at = received_at if new_status != previous else _from_iso(row[4])
                self._backend._execute_write(
                    f"UPDATE agent_health SET last_heartbeat_at = {self._ph}, "
                    f"status = {self._ph}, status_changed_at = {self._ph} "
                    f"WHERE agent_name = {self._ph} AND organization = {self._ph}",
                    (received_at.isoformat(), new_status.value, changed_at.isoformat(),
                     name, organization)
                )
                return previous, HealthState(
                    name=name, organization=organization,
                    last_heartbeat_at=received_at,
                    status=new_status,
                    status_changed_at=changed_at,
                )
            self._backend._execute_write(
                f"INSERT INTO agent_health (agent_name, organization, last_heartbeat_at, "
                f"status, status_changed_at) VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph})",
                (name, organization, received_at.isoformat(),
                 HealthStatus.HEALTHY.value, received_at.isoformat())
            )
            return None, HealthState(
                name=name, organization=organization,
                last_heartbeat_at=received_at,
                status=HealthStatus.HEALTHY,
                status_changed_at=received_at,
            )

    def get(self, name, organization):
        row = self._backend._execute_read_one(
            f"SELECT agent_name, organization, last_heartbeat_at, status, "
            f"status_changed_at FROM agent_health WHERE agent_name = {self._ph} "
            f"AND organization = {self._ph}",
            (name, organization)
        )
        return self._row_to_state(row) if row else None

    def list_monitored(self):
        rows = self._backend._execute_read_all(
            "SELECT agent_name, organization, last_heartbeat_at, status, "
            "status_changed_at FROM agent_health"
        )
        return [self._row_to_state(r) for r in rows]

    def update_status(self, name, organization, new_status, changed_at):
        return self._backend._execute_write(
            f"UPDATE agent_health SET status = {self._ph}, status_changed_at = {self._ph} "
            f"WHERE agent_name = {self._ph} AND organization = {self._ph}",
            (new_status.value, changed_at.isoformat(), name, organization)
        ) > 0

    def remove(self, name, organization):
        self._backend._execute_write(
            f"DELETE FROM agent_health WHERE agent_name = {self._ph} AND organization = {self._ph}",
            (name, organization)
        )

    def append_history(self, name, organization, previous_status, new_status, changed_at):
        with self._lock:
            self._backend._execute_write(
                f"INSERT INTO agent_health_history (event_id, agent_name, organization, "
                f"previous_status, new_status, changed_at) "
                f"VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph})",
                (str(uuid.uuid4()), name, organization, previous_status.value,
                 new_status.value, changed_at.isoformat())
            )

    def list_history(self, name=None, organization=None, limit=50):
        clauses, params = [], []
        if name is not None:
            clauses.append(f"agent_name = {self._ph}")
            params.append(name)
        if organization is not None:
            clauses.append(f"organization = {self._ph}")
            params.append(organization)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._backend._execute_read_all(
            f"SELECT agent_name, organization, previous_status, new_status, changed_at "
            f"FROM agent_health_history{where} "
            f"ORDER BY changed_at DESC LIMIT {int(limit)}",
            tuple(params)
        )
        return [{
            "name": r[0],
            "organization": r[1],
            "previous_health_status": r[2],
            "health_status": r[3],
            "changed_at": r[4],
        } for r in rows]

    def close(self):
        pass
