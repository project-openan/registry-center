# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Shared pytest fixtures for storage backend tests.

Provides:
- DB connection config fixtures (PG / GaussDB) with auto-skip when DB unavailable
- Sample AgentCard factory reused across SQLite/PG/GaussDB test modules
"""

import os
import pytest

import psycopg2

from a2a.types import AgentCard


# ---------- DB availability gates ----------

def _pg_available(config: dict) -> bool:
    try:
        conn = psycopg2.connect(
            host=config['host'], port=config['port'],
            database=config['database'], user=config['user'],
            password=config['password'], connect_timeout=3
        )
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def pg_config():
    cfg = {
        'host': os.environ.get('PG_TEST_HOST', '127.0.0.1'),
        'port': int(os.environ.get('PG_TEST_PORT', '5432')),
        'database': os.environ.get('PG_TEST_DB', 'registry_center'),
        'user': os.environ.get('PG_TEST_USER', 'opena2a_t'),
        'password': os.environ.get('PG_TEST_PASSWORD', 'openA2A_T'),
    }
    if not _pg_available(cfg):
        pytest.skip("PostgreSQL not available, set PG_TEST_* env vars to enable")
    return cfg


@pytest.fixture(scope="session")
def gauss_config(pg_config):
    """GaussDB uses PG as protocol-compatible surrogate in CI/local."""
    return {
        'host': pg_config['host'],
        'port': pg_config['port'],
        'database': pg_config['database'],
        'user': pg_config['user'],
        'password': pg_config['password'],
    }


# ---------- storage config dicts ----------

@pytest.fixture
def postgresql_storage_config(pg_config):
    return {
        'postgresql.host': pg_config['host'],
        'postgresql.port': pg_config['port'],
        'postgresql.name': pg_config['database'],
        'postgresql.username': pg_config['user'],
        'postgresql.password': pg_config['password'],
        'postgresql.pool.min': '2',
        'postgresql.pool.max': '5',
    }


@pytest.fixture
def gauss_storage_config(gauss_config):
    return {
        'gauss.host': gauss_config['host'],
        'gauss.port': gauss_config['port'],
        'gauss.database': gauss_config['database'],
        'gauss.username': gauss_config['user'],
        'gauss.password': gauss_config['password'],
        'gauss.pool.min': '2',
        'gauss.pool.max': '5',
    }


# ---------- table cleanup (shared by PG & GaussDB tests) ----------

@pytest.fixture
def clean_pg_tables(postgresql_storage_config):
    """Truncate tables before/after test for isolation (keeps schema)."""
    from agent_registry.persistence.postgresql_storage import PostgreSQLStorage
    storage = PostgreSQLStorage.init(postgresql_storage_config)
    _truncate_all_tables(storage)
    yield storage
    _truncate_all_tables(storage)
    storage.close()


@pytest.fixture
def clean_gauss_tables(gauss_storage_config):
    """Rebuild tables with GaussDB TEXT schema for isolation.

    PG and GaussDB tests share the same PG surrogate DB but use different
    column types (JSONB vs TEXT), so we DROP and re-init to guarantee the
    correct schema on every run.
    """
    from agent_registry.persistence.gaussdb_storage import GaussDBStorage
    storage = GaussDBStorage.init(gauss_storage_config)
    _drop_all_tables(storage)
    storage._ensure_table_exists(storage.pool)
    yield storage
    _drop_all_tables(storage)
    storage.close()


def _truncate_all_tables(storage):
    conn = storage._acquire_conn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute('TRUNCATE TABLE agent_card CASCADE')
            cur.execute('TRUNCATE TABLE tag CASCADE')
    except Exception:
        pass
    finally:
        storage._release_conn(conn)


def _drop_all_tables(storage):
    conn = storage._acquire_conn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS agent_card CASCADE')
            cur.execute('DROP TABLE IF EXISTS tag CASCADE')
    finally:
        storage._release_conn(conn)


# ---------- sample data ----------

@pytest.fixture
def make_agent():
    def _make(name="test_agent", org="test_org", version="1.0.0"):
        return AgentCard(
            name=name,
            provider={"organization": org, "url": "https://test.com"},
            description=f"Test agent {name}",
            version=version,
            skills=[]
        )
    return _make
