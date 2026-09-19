# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Shared psycopg2 connection helpers for the PostgreSQL and GaussDB backends.

Both databases are PG-protocol compatible, so database bootstrap, pool
construction, and schema initialization are identical apart from the query
enum. Centralizing them here keeps the backend classes thin and gives both
a uniform connect-timeout behavior.
"""

import psycopg2
from psycopg2 import pool, sql
from loguru import logger

DEFAULT_CONNECT_TIMEOUT = 10


def ensure_pg_database(host: str, port: int, database: str, user: str,
                       password: str,
                       connect_timeout: int = DEFAULT_CONNECT_TIMEOUT) -> None:
    """Connect to the 'postgres' maintenance database and create `database` if missing."""
    conn = psycopg2.connect(
        host=host, port=port, database='postgres', user=user, password=password,
        connect_timeout=connect_timeout
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if not cur.fetchone():
                cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
                logger.info(f"Database '{database}' created successfully")
    finally:
        conn.close()


def build_pg_pool(host: str, port: int, database: str, user: str, password: str,
                  min_size: int, max_size: int,
                  connect_timeout: int = DEFAULT_CONNECT_TIMEOUT) -> pool.ThreadedConnectionPool:
    """Build a ThreadedConnectionPool with an explicit connect timeout.

    connect_timeout is forwarded to psycopg2.connect and prevents startup
    from hanging forever on an unreachable host.
    """
    return pool.ThreadedConnectionPool(
        minconn=min_size,
        maxconn=max_size,
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        connect_timeout=connect_timeout
    )


def ensure_pg_tables(conn_pool: pool.ThreadedConnectionPool, queries,
                     extra_statements: tuple = ()) -> None:
    """Run the shared agent_card/tag DDL sequence on a fresh pooled connection.

    `extra_statements` holds backend-specific index DDL appended after the
    common set (e.g. the PostgreSQL GIN index).
    """
    conn = conn_pool.getconn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for statement in (
                queries.CREATE_TABLE.value,
                queries.ADD_COLUMN_STATUS.value,
                queries.ADD_COLUMN_TAGS.value,
                queries.ADD_COLUMN_OWNER.value,
                queries.DROP_OLD_UNIQUE_INDEX.value,
                queries.CREATE_OWNER_UNIQUE_INDEX.value,
                queries.CREATE_INDEX_ORG.value,
                queries.CREATE_INDEX_NAME.value,
                queries.CREATE_INDEX_STATUS.value,
                queries.CREATE_INDEX_OWNER.value,
                *extra_statements,
            ):
                cur.execute(statement)
            logger.info("Table 'agent_card' and indexes created/verified")

            cur.execute(queries.CREATE_TAG_TABLE.value)
            cur.execute(queries.CREATE_TAG_INDEX_NAME.value)
            logger.info("Table 'tag' and indexes created/verified")
    finally:
        conn_pool.putconn(conn)
