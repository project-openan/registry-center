# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Change broadcast subsystem: event bus, outbox, subscriptions, webhook dispatcher."""

import threading
from pathlib import Path
from typing import Optional

from loguru import logger

from agent_registry.broadcast.event_bus import EventBus
from agent_registry.broadcast.outbox import FileOutbox, MemoryOutbox, OutboxStore, SqlOutbox
from agent_registry.broadcast.subscriptions import (
    FileSubscriptionStore,
    MemorySubscriptionStore,
    SubscriptionStore,
    SqlSubscriptionStore,
)
from common.util.app_config import get_conf, get_root_path


def _int_conf(config: dict, key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except (ValueError, TypeError):
        logger.warning(f"Invalid integer value for '{key}', using default {default}")
        return default


def _float_conf(config: dict, key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (ValueError, TypeError):
        logger.warning(f"Invalid numeric value for '{key}', using default {default}")
        return default


def _truthy(config: dict, key: str, default: str = "false") -> bool:
    return str(config.get(key, default)).strip().lower() == "true"


class BroadcastService:
    """Wires the outbox, subscription store, event bus, and dispatcher together."""

    def __init__(self, outbox: OutboxStore, subscription_store: SubscriptionStore,
                 config: Optional[dict] = None):
        config = config or get_conf()
        self.outbox = outbox
        self.subscription_store = subscription_store
        self.broadcast_enabled = _truthy(config, "broadcast.enabled")
        self.event_bus = EventBus(outbox, dispatch_enabled=self.broadcast_enabled)
        self.dispatcher = None
        if self.broadcast_enabled:
            from agent_registry.broadcast.dispatcher import WebhookDispatcher
            self.dispatcher = WebhookDispatcher(
                subscription_store=subscription_store,
                outbox=outbox,
                debounce_window=_float_conf(config, "broadcast.debounce.window", 2.0),
                max_events_per_second=_float_conf(config, "broadcast.max.events.per.second", 50.0),
                webhook_timeout=_float_conf(config, "broadcast.webhook.timeout", 10.0),
                max_retries=_int_conf(config, "broadcast.webhook.max.retries", 5),
                backoff_base=_float_conf(config, "broadcast.webhook.backoff.base", 2.0),
                backoff_max=_float_conf(config, "broadcast.webhook.backoff.max", 300.0),
                retention_days=_int_conf(config, "broadcast.outbox.retention.days", 7),
            )
            self.event_bus.attach_dispatcher(self.dispatcher)

    async def start(self) -> None:
        self.event_bus.start_consumer()
        if self.dispatcher is not None:
            self.dispatcher.start()

    async def stop(self) -> None:
        await self.event_bus.stop_consumer()
        if self.dispatcher is not None:
            await self.dispatcher.stop()
        self.outbox.close()
        self.subscription_store.close()


_service: Optional[BroadcastService] = None
_lock = threading.Lock()


def _build_stores(backend, mode: Optional[str] = None) -> tuple:
    """
    Pick outbox/subscription store implementations from the registry's
    persistence mode. The mode must be passed explicitly by the startup hook
    because it lives in persistence.conf, not the main server config.
    """
    mode = (mode or "file").strip().lower()
    data_dir = Path(get_root_path()) / "data"
    if backend is not None and mode in ("sqlite", "postgresql", "gauss", "mysql"):
        return SqlOutbox(backend), SqlSubscriptionStore(backend)
    if mode == "vectordb":
        return MemoryOutbox(), MemorySubscriptionStore()
    return FileOutbox(str(data_dir / "events.jsonl")), FileSubscriptionStore(str(data_dir / "subscriptions.json"))


def initialize_broadcast_service(backend=None, mode: Optional[str] = None) -> BroadcastService:
    """Create the service singleton. Called during app startup with the SQL backend (if any)."""
    global _service
    with _lock:
        if _service is None:
            outbox, subscription_store = _build_stores(backend, mode)
            _service = BroadcastService(outbox, subscription_store)
            logger.info(f"Broadcast service initialized (enabled={_service.broadcast_enabled})")
    return _service


def get_broadcast_service() -> BroadcastService:
    """Lazily build the singleton with default stores (used by tests and endpoints)."""
    global _service
    with _lock:
        if _service is None:
            outbox, subscription_store = _build_stores(None)
            _service = BroadcastService(outbox, subscription_store)
    return _service


def get_event_bus() -> EventBus:
    return get_broadcast_service().event_bus


def reset_for_tests() -> None:
    global _service
    with _lock:
        _service = None
