# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Storage startup pre-check tests (no live database required).

Covers verify_storage_ready() success/failure paths, the boxed error
format, and the check_connection() implementations on file/SQLite backends.
"""

import sqlite3

import pytest
from loguru import logger

from agent_registry.persistence.file_storage import FileStorage
from agent_registry.persistence.precheck import format_storage_error, verify_storage_ready
from agent_registry.persistence.sqlite_storage import SQLiteStorage


# ---------- loguru <-> pytest caplog bridge ----------

@pytest.fixture
def loguru_caplog(caplog):
    handler_id = logger.add(caplog.handler, format="{message}")
    yield caplog
    logger.remove(handler_id)


# ---------- fakes ----------

class _FakeStorage:
    def __init__(self, error: Exception = None):
        self._error = error
        self.checked = False

    def check_connection(self):
        if self._error is not None:
            raise self._error
        self.checked = True


class _FakeRegistry:
    def __init__(self, storage):
        self.storage = storage


# ---------- verify_storage_ready ----------

def test_verify_storage_ready_passes(monkeypatch):
    storage = _FakeStorage()
    monkeypatch.setattr("agent_registry.registry_instance.get_registry",
                        lambda: _FakeRegistry(storage))
    verify_storage_ready()
    assert storage.checked


def test_verify_storage_ready_skips_check_without_storage(monkeypatch):
    """vectordb-style registry has storage=None; pre-check must be a no-op."""
    monkeypatch.setattr("agent_registry.registry_instance.get_registry",
                        lambda: _FakeRegistry(None))
    verify_storage_ready()


def test_verify_storage_ready_exits_on_check_failure(monkeypatch, loguru_caplog):
    storage = _FakeStorage(sqlite3.OperationalError("unable to open database file"))
    monkeypatch.setattr("agent_registry.registry_instance.get_registry",
                        lambda: _FakeRegistry(storage))
    with pytest.raises(SystemExit) as excinfo:
        verify_storage_ready()
    assert excinfo.value.code == 1
    assert "[storage pre-check] FAILED" in loguru_caplog.text
    assert "target" in loguru_caplog.text
    assert "config" in loguru_caplog.text


def test_verify_storage_ready_exits_on_init_failure(monkeypatch):
    def boom():
        raise RuntimeError("connection refused")
    monkeypatch.setattr("agent_registry.registry_instance.get_registry", boom)
    with pytest.raises(SystemExit) as excinfo:
        verify_storage_ready()
    assert excinfo.value.code == 1


# ---------- format_storage_error ----------

def test_format_storage_error_contains_diagnostics():
    conf = {"mysql.host": "db.internal", "mysql.port": 3306,
            "mysql.name": "rc", "mysql.username": "svc"}
    msg = format_storage_error("mysql", conf, RuntimeError("boom"))
    assert "mode    : mysql" in msg
    assert "mysql://db.internal:3306/rc (user: svc)" in msg
    assert "persistence.conf" in msg
    assert "RuntimeError: boom" in msg
    assert "errno 2003" in msg


def test_format_storage_error_describes_pg_target():
    conf = {"postgresql.host": "10.0.0.5", "postgresql.port": 5432,
            "postgresql.name": "registry_center", "postgresql.username": "opena2a_t"}
    msg = format_storage_error("postgresql", conf, RuntimeError("x"))
    assert "postgresql://10.0.0.5:5432/registry_center (user: opena2a_t)" in msg


def test_format_storage_error_handles_unknown_mode():
    msg = format_storage_error("weird-db", {}, RuntimeError("x"))
    assert "mode    : weird-db" in msg


# ---------- check_connection implementations ----------

def test_file_storage_check_connection_writes_probe(tmp_path):
    file_path = tmp_path / "sub" / "agentcard.json"  # parent does not exist yet
    storage = FileStorage.init({"file.path": str(file_path)})
    storage.check_connection()
    assert file_path.parent.is_dir()
    assert not list(tmp_path.glob(".precheck-*"))  # probe cleaned up


def test_sqlite_check_connection_round_trip(tmp_path):
    storage = SQLiteStorage.init({"sqlite.path": str(tmp_path / "t.db")})
    try:
        storage.check_connection()
    finally:
        storage.close()


def test_sqlite_check_connection_raises_when_unusable(tmp_path):
    storage = SQLiteStorage.init({"sqlite.path": str(tmp_path / "t.db")})
    storage._conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        storage.check_connection()


# ---------- ensure_index (dialect-aware index DDL) ----------

class _RecordingBackend:
    supports_create_index_if_not_exists = True

    def __init__(self):
        self.writes = []

    def _execute_write(self, ddl):
        self.writes.append(ddl)


def test_ensure_index_uses_if_not_exists_when_supported():
    from agent_registry.persistence.sql_backend import SqlStorageBackend
    backend = _RecordingBackend()
    SqlStorageBackend.ensure_index(
        backend,
        "CREATE INDEX IF NOT EXISTS i ON t(c)",
        "CREATE INDEX i ON t(c)",
    )
    assert backend.writes == ["CREATE INDEX IF NOT EXISTS i ON t(c)"]


def test_ensure_index_uses_plain_ddl_without_dialect_support():
    from agent_registry.persistence.sql_backend import SqlStorageBackend
    backend = _RecordingBackend()
    backend.supports_create_index_if_not_exists = False
    SqlStorageBackend.ensure_index(
        backend,
        "CREATE INDEX IF NOT EXISTS i ON t(c)",
        "CREATE INDEX i ON t(c)",
    )
    assert backend.writes == ["CREATE INDEX i ON t(c)"]


def test_ensure_index_swallows_duplicate_index_error_only():
    from agent_registry.persistence.sql_backend import SqlStorageBackend

    class _FailingBackend(_RecordingBackend):
        supports_create_index_if_not_exists = False

        def __init__(self, error):
            super().__init__()
            self._error = error

        def _execute_write(self, ddl):
            raise self._error

    duplicate = Exception()
    duplicate.args = (1061, "Duplicate key name 'idx_x'")
    SqlStorageBackend.ensure_index(_FailingBackend(duplicate), "a", "b")  # tolerated

    with pytest.raises(RuntimeError, match="privilege"):
        SqlStorageBackend.ensure_index(_FailingBackend(RuntimeError("missing privilege")), "a", "b")
