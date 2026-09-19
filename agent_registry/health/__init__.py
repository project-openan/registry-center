# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Agent heartbeat detection subsystem."""

import threading
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from loguru import logger

from agent_registry.health.state import HealthState, HealthStatus
from agent_registry.health.store import HeartbeatStore, MemoryHeartbeatStore, SqlHeartbeatStore


def _int_conf(config: dict, key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except (ValueError, TypeError):
        logger.warning(f"Invalid integer value for '{key}', using default {default}")
        return default


def _truthy(config: dict, key: str, default: str = "false") -> bool:
    return str(config.get(key, default)).strip().lower() == "true"


class HealthService:
    """Facade over the heartbeat store with feature toggles and detection config."""

    def __init__(self, store: HeartbeatStore, config: Optional[dict] = None):
        config = config or {}
        self.store = store
        self.enabled = _truthy(config, "heartbeat.enabled")
        self.interval = max(_int_conf(config, "heartbeat.interval", 30), 1)
        self.failure_threshold = max(_int_conf(config, "heartbeat.failure.threshold", 3), 1)
        self.grace_period = max(_int_conf(config, "heartbeat.grace.period", 10), 0)
        self.sweep_interval = max(_int_conf(config, "heartbeat.sweep.interval", 10), 1)
        self.offline_ttl = max(_int_conf(config, "heartbeat.offline.ttl", 0), 0)
        self.hide_unhealthy_results = _truthy(config, "heartbeat.hide.unhealthy.results")

    def record_heartbeat(self, name: str, organization: str) -> Tuple[Optional[HealthStatus], HealthState]:
        received_at = datetime.now(timezone.utc)
        previous, state = self.store.record_heartbeat(name, organization, received_at)
        if previous is not None and previous != state.status:
            self.store.append_history(name, organization, previous, state.status, received_at)
        return previous, state

    def get(self, name: str, organization: str) -> Optional[HealthState]:
        return self.store.get(name, organization)

    def status_of(self, name: str, organization: str) -> Optional[str]:
        """Current health status, or None when the agent has never heartbeated."""
        if not self.enabled:
            return None
        state = self.store.get(name, organization)
        return state.status.value if state else None

    def metadata_health(self, name: str, organization: str) -> str:
        return self.status_of(name, organization) or HealthStatus.UNKNOWN.value

    def list_monitored(self) -> List[HealthState]:
        return self.store.list_monitored()

    def update_status(self, name: str, organization: str,
                      new_status: HealthStatus, changed_at: datetime) -> bool:
        current = self.store.get(name, organization)
        if current is not None and current.status != new_status:
            self.store.append_history(name, organization, current.status, new_status, changed_at)
        return self.store.update_status(name, organization, new_status, changed_at)

    def history(self, name: Optional[str] = None, organization: Optional[str] = None,
                limit: int = 50) -> List[dict]:
        """Recent health status transitions, newest first."""
        return self.store.list_history(name, organization, limit)

    def detection_config(self) -> dict:
        """Effective detection parameters (served to frontend dashboards)."""
        return {
            "enabled": self.enabled,
            "interval": self.interval,
            "failure_threshold": self.failure_threshold,
            "grace_period": self.grace_period,
            "sweep_interval": self.sweep_interval,
            "offline_ttl": self.offline_ttl,
        }

    def remove(self, name: str, organization: str) -> None:
        self.store.remove(name, organization)

    def close(self) -> None:
        self.store.close()


_service: Optional[HealthService] = None
_lock = threading.Lock()


def initialize_health_service(backend=None, mode: Optional[str] = None,
                              config: Optional[dict] = None) -> HealthService:
    """Create the service singleton. Called during app startup with the SQL backend (if any)."""
    global _service
    with _lock:
        if _service is None:
            config = config if config is not None else _load_config()
            mode = (mode or "file").strip().lower()
            if backend is not None and mode in ("sqlite", "postgresql", "gauss", "mysql"):
                store = SqlHeartbeatStore(backend)
            else:
                store = MemoryHeartbeatStore()
            _service = HealthService(store, config)
            logger.info(f"Health service initialized (enabled={_service.enabled}, "
                        f"interval={_service.interval}s, threshold={_service.failure_threshold}, "
                        f"grace={_service.grace_period}s)")
    return _service


def _load_config() -> dict:
    from common.util.app_config import get_conf
    return get_conf()


def get_health_service() -> HealthService:
    """Lazily build the singleton (used by tests and endpoints without lifespan)."""
    global _service
    with _lock:
        if _service is None:
            _service = HealthService(MemoryHeartbeatStore(), _load_config())
    return _service


def reset_for_tests() -> None:
    global _service
    with _lock:
        _service = None
