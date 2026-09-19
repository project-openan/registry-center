# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Startup storage pre-check.

`verify_storage_ready()` is called synchronously from `agent_registry.start`
BEFORE any port is bound (including the internal UDS/TCP service). Building
the registry already initializes the backend eagerly — create-database,
connection pool, and schema DDL — so the pre-check adds a trivial round-trip
query on top and turns any failure into a fast, actionable process exit
instead of a traceback after the server is already up.
"""

import os
import sys

from loguru import logger

_LIKELY_CAUSES = {
    'postgresql': [
        "server not running / wrong host or port",
        "wrong username or password",
        "database missing and user lacks CREATE privilege",
        "postgresql.connect_timeout too small for slow networks",
    ],
    'gauss': [
        "server not running / wrong host or port",
        "wrong username or password",
        "database missing and user lacks CREATE privilege",
        "gauss.connect_timeout too small for slow networks",
    ],
    'mysql': [
        "server not running / wrong host or port (errno 2003)",
        "wrong username or password (errno 1045)",
        "database missing and user lacks CREATE privilege (errno 1049)",
        "mysql.connect_timeout too small for slow networks",
    ],
    'sqlite': [
        "parent directory of sqlite.path missing and not creatable",
        "database file locked by another process",
    ],
    'file': [
        "data directory missing and not creatable",
        "persistence files unreadable or corrupted",
    ],
}


def _describe_target(mode: str, conf: dict) -> str:
    """Human-readable connection target for the configured mode."""
    if mode == 'postgresql':
        return (f"postgresql://{conf.get('postgresql.host', 'localhost')}:"
                f"{conf.get('postgresql.port', 5432)}/{conf.get('postgresql.name', 'a2a_registry')} "
                f"(user: {conf.get('postgresql.username', 'a2a_user')})")
    if mode == 'gauss':
        return (f"gaussdb://{conf.get('gauss.host', 'localhost')}:"
                f"{conf.get('gauss.port', 5432)}/{conf.get('gauss.database', 'a2a_registry')} "
                f"(user: {conf.get('gauss.username', 'a2a_user')})")
    if mode == 'mysql':
        return (f"mysql://{conf.get('mysql.host', 'localhost')}:"
                f"{conf.get('mysql.port', 3306)}/{conf.get('mysql.name', 'registry_center')} "
                f"(user: {conf.get('mysql.username', 'a2a_user')})")
    if mode == 'sqlite':
        return str(conf.get('sqlite.path', 'data/agents.db'))
    if mode == 'file':
        return str(conf.get('file.path', 'data/agentcard.json'))
    return mode


def format_storage_error(mode: str, conf: dict, exc: Exception) -> str:
    """Render a boxed, actionable message for a storage init/connect failure."""
    from common.util.app_config import get_root_path
    config_path = os.path.join(get_root_path(), "etc", "conf", "persistence.conf")
    causes = _LIKELY_CAUSES.get(mode, ["configuration or connectivity problem"])
    cause_lines = "\n".join(f"    - {c}" for c in causes)
    return (
        "\n" + "=" * 80 + "\n"
        "[storage pre-check] FAILED to initialize storage backend.\n"
        f"  mode    : {mode}\n"
        f"  target  : {_describe_target(mode, conf)}\n"
        f"  config  : {config_path}\n"
        f"  error   : {type(exc).__name__}: {exc}\n"
        f"  Likely causes ({mode}):\n"
        f"{cause_lines}\n"
        "  Fix persistence.conf (or the corresponding environment variable\n"
        "  overrides, e.g. DB_* / MYSQL_* / GAUSS_* / SQLITE_PATH) and restart.\n"
        "  Exiting before the service port is bound.\n"
        + "=" * 80
    )


def verify_storage_ready() -> None:
    """Initialize the storage backend and verify connectivity; exit(1) on failure.

    On the happy path this leaves the registry singleton fully initialized,
    so the later FastAPI startup event becomes a cheap no-op.
    """
    from agent_registry.config import PERSISTENCE_CONF, PERSISTENCE_MODE, USE_VECTORDB
    from agent_registry.registry_instance import get_registry
    try:
        registry = get_registry()
        if registry is not None and registry.storage is not None:
            registry.storage.check_connection()
        logger.info(f"Storage pre-check passed (mode={PERSISTENCE_MODE})")
    except SystemExit:
        raise
    except Exception as exc:
        if USE_VECTORDB:
            # The backend is the vector DB here; storage-mode diagnostics
            # would point the operator at the wrong configuration.
            logger.error(
                f"[storage pre-check] FAILED to initialize vectordb backend "
                f"(use_vectordb=true): {type(exc).__name__}: {exc}\n"
                "Check the vector database (Milvus) configuration/connectivity "
                "and embedding service settings, then restart. "
                "Exiting before the service port is bound."
            )
        else:
            logger.error(format_storage_error(PERSISTENCE_MODE, PERSISTENCE_CONF, exc))
        sys.exit(1)
