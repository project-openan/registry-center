# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Subscription model, persistence, and event-matching rules."""

import json
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

from agent_registry.broadcast.events import RegistryEvent


@dataclass
class Subscription:
    subscription_id: str
    callback_url: str
    event_types: Optional[List[str]] = None
    organizations: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    secret: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self, include_secret: bool = False) -> Dict:
        payload = {
            "subscription_id": self.subscription_id,
            "callback_url": self.callback_url,
            "event_types": self.event_types,
            "filters": {"organizations": self.organizations, "tags": self.tags},
            "created_at": self.created_at,
        }
        if include_secret:
            payload["secret"] = self.secret
        return payload

    @classmethod
    def from_dict(cls, payload: Dict) -> "Subscription":
        filters = payload.get("filters") or {}
        return cls(
            subscription_id=payload.get("subscription_id", ""),
            callback_url=payload.get("callback_url", ""),
            event_types=payload.get("event_types"),
            organizations=filters.get("organizations"),
            tags=filters.get("tags"),
            secret=payload.get("secret"),
            created_at=payload.get("created_at", ""),
        )


def event_matches(event: RegistryEvent, subscription: Subscription) -> bool:
    """True when the event passes the subscription's type/organization/tag filters."""
    if subscription.event_types and event.event_type.value not in subscription.event_types:
        return False
    if subscription.organizations:
        if event.data.get("organization") not in subscription.organizations:
            return False
    if subscription.tags:
        event_tags = event.data.get("tags") or []
        if not set(subscription.tags) & set(event_tags):
            return False
    return True


class SubscriptionStore(ABC):
    @abstractmethod
    def create(self, subscription: Subscription) -> Subscription:
        """Assign a subscription_id, persist, and return the subscription."""
        ...

    @abstractmethod
    def get(self, subscription_id: str) -> Optional[Subscription]:
        ...

    @abstractmethod
    def list_all(self) -> List[Subscription]:
        ...

    @abstractmethod
    def delete(self, subscription_id: str) -> bool:
        ...

    @abstractmethod
    def close(self):
        ...


class MemorySubscriptionStore(SubscriptionStore):
    def __init__(self):
        self._subs: Dict[str, Subscription] = {}
        self._lock = threading.Lock()

    def create(self, subscription: Subscription) -> Subscription:
        with self._lock:
            subscription.subscription_id = f"sub_{uuid.uuid4().hex[:20]}"
            self._subs[subscription.subscription_id] = subscription
            return subscription

    def get(self, subscription_id: str) -> Optional[Subscription]:
        with self._lock:
            return self._subs.get(subscription_id)

    def list_all(self) -> List[Subscription]:
        with self._lock:
            return list(self._subs.values())

    def delete(self, subscription_id: str) -> bool:
        with self._lock:
            return self._subs.pop(subscription_id, None) is not None

    def close(self):
        pass


class SqlSubscriptionStore(SubscriptionStore):
    """SQL-backed subscription store delegating connections to the main backend."""

    def __init__(self, backend):
        self._backend = backend
        self._lock = threading.Lock()
        self._ensure_table()

    @property
    def _ph(self):
        return getattr(self._backend, "param_ph", "%s")

    def _ensure_table(self):
        # No column DEFAULTs on TEXT: MySQL rejects them (error 1101), and the
        # INSERT path always supplies explicit values anyway.
        self._backend._execute_write("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                subscription_id  VARCHAR(64)   PRIMARY KEY,
                callback_url     VARCHAR(2048) NOT NULL,
                event_types_json TEXT          NOT NULL,
                filters_json     TEXT          NOT NULL,
                secret           VARCHAR(256),
                created_at       VARCHAR(64)   NOT NULL
            )
        """)
        logger.info("Subscription table 'subscriptions' created/verified")

    def create(self, subscription: Subscription) -> Subscription:
        with self._lock:
            subscription.subscription_id = f"sub_{uuid.uuid4().hex[:20]}"
            payload = subscription.to_dict(include_secret=True)
            self._backend._execute_write(
                "INSERT INTO subscriptions (subscription_id, callback_url, event_types_json, "
                f"filters_json, secret, created_at) VALUES ({self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph}, {self._ph})",
                (subscription.subscription_id, subscription.callback_url,
                 json.dumps(subscription.event_types or []),
                 json.dumps({"organizations": subscription.organizations, "tags": subscription.tags}),
                 subscription.secret, subscription.created_at)
            )
            return subscription

    def _row_to_sub(self, row) -> Subscription:
        filters = json.loads(row[3] or "{}")
        return Subscription(
            subscription_id=row[0],
            callback_url=row[1],
            event_types=json.loads(row[2] or "[]") or None,
            organizations=filters.get("organizations"),
            tags=filters.get("tags"),
            secret=row[4],
            created_at=row[5] or "",
        )

    def get(self, subscription_id: str) -> Optional[Subscription]:
        row = self._backend._execute_read_one(
            f"SELECT subscription_id, callback_url, event_types_json, filters_json, "
            f"secret, created_at FROM subscriptions WHERE subscription_id = {self._ph}",
            (subscription_id,)
        )
        return self._row_to_sub(row) if row else None

    def list_all(self) -> List[Subscription]:
        rows = self._backend._execute_read_all(
            "SELECT subscription_id, callback_url, event_types_json, filters_json, "
            "secret, created_at FROM subscriptions ORDER BY created_at ASC"
        )
        return [self._row_to_sub(r) for r in rows]

    def delete(self, subscription_id: str) -> bool:
        return self._backend._execute_write(
            f"DELETE FROM subscriptions WHERE subscription_id = {self._ph}",
            (subscription_id,)
        ) > 0

    def close(self):
        pass


class FileSubscriptionStore(SubscriptionStore):
    """JSON-file-backed subscription store, mirroring the repo's file storage style."""

    def __init__(self, file_path: str):
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._subs: Dict[str, Subscription] = self._load()

    def _load(self) -> Dict[str, Subscription]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {s["subscription_id"]: Subscription.from_dict(s) for s in data}
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to load subscriptions file: {e}")
            return {}

    def _save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump([s.to_dict(include_secret=True) for s in self._subs.values()],
                      f, ensure_ascii=False, indent=2)

    def create(self, subscription: Subscription) -> Subscription:
        with self._lock:
            subscription.subscription_id = f"sub_{uuid.uuid4().hex[:20]}"
            self._subs[subscription.subscription_id] = subscription
            self._save()
            return subscription

    def get(self, subscription_id: str) -> Optional[Subscription]:
        with self._lock:
            return self._subs.get(subscription_id)

    def list_all(self) -> List[Subscription]:
        with self._lock:
            return list(self._subs.values())

    def delete(self, subscription_id: str) -> bool:
        with self._lock:
            if self._subs.pop(subscription_id, None) is None:
                return False
            self._save()
            return True

    def close(self):
        pass
