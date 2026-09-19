# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
MySQL storage backend (MySQL 5.7+ / 8.0).

Uses PyMySQL (pure Python, DB-API 2.0) with a DBUtils PooledDB connection
pool. Dialect differences handled here vs the PG backends:

- autocommit=True on every pooled connection: SqlStorageBackend commits
  writes explicitly but never commits reads, and MySQL's default
  REPEATABLE READ isolation would serve stale snapshots on pooled read
  connections.
- No CLIENT_FOUND_ROWS flag: the default changed-rows semantics keep
  ON DUPLICATE KEY UPDATE rowcount at 0 for a no-op duplicate, so
  create() returns False on a registration race (mirroring PG's
  ON CONFLICT DO NOTHING). Trade-off: update() reports changed rows
  instead of matched rows, so an update that changes nothing returns
  False on MySQL (PG returns True for the same call).
- ping=1 re-validates each connection when fetched: MySQL's wait_timeout
  kills idle server-side connections, unlike the PG backends.
- blocking=True makes pool exhaustion wait for a free connection instead
  of raising immediately (psycopg2's PoolError behavior).
- JSON columns use the native JSON type; tag containment via JSON_CONTAINS.
- No CREATE INDEX IF NOT EXISTS: indexes are inlined in CREATE TABLE DDL
  and ad-hoc index DDL elsewhere falls back to a tolerant plain
  CREATE INDEX (see supports_create_index_if_not_exists).
"""

import json
import re

import pymysql
from dbutils.pooled_db import PooledDB
from loguru import logger

from .sql_backend import SqlStorageBackend
from .sql_queries import MySQLQueries

DEFAULT_CONNECT_TIMEOUT = 10


class MySQLStorage(SqlStorageBackend):
    """MySQL storage backend using PyMySQL + DBUtils PooledDB."""

    queries = MySQLQueries
    _integrity_error = pymysql.err.IntegrityError
    # MySQL lacks CREATE INDEX IF NOT EXISTS; health/broadcast stores use
    # this flag to pick a duplicate-tolerant plain CREATE INDEX instead.
    supports_create_index_if_not_exists = False

    def __init__(self, conn_pool: PooledDB):
        self.pool = conn_pool

    @classmethod
    def init(cls, config: dict) -> 'MySQLStorage':
        host = config.get('mysql.host', 'localhost')
        port = int(config.get('mysql.port', 3306))
        database = config.get('mysql.name', 'registry_center')
        user = config.get('mysql.username', 'a2a_user')
        password = config.get('mysql.password', '')
        min_size = int(config.get('mysql.pool.min', 5))
        max_size = int(config.get('mysql.pool.max', 20))
        connect_timeout = int(config.get('mysql.connect_timeout', DEFAULT_CONNECT_TIMEOUT))

        cls._ensure_database_exists(host, port, database, user, password, connect_timeout)

        connection_pool = PooledDB(
            creator=pymysql,
            mincached=min_size,
            maxconnections=max_size,
            blocking=True,
            ping=1,
            autocommit=True,
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=connect_timeout,
            charset='utf8mb4',
        )
        logger.info("MySQL connection pool initialized")

        instance = cls(connection_pool)
        instance._ensure_table_exists(connection_pool)
        return instance

    @classmethod
    def _ensure_database_exists(cls, host: str, port: int, database: str,
                                user: str, password: str,
                                connect_timeout: int = DEFAULT_CONNECT_TIMEOUT):
        # Connect without a database first, then create the target schema.
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            connect_timeout=connect_timeout, charset='utf8mb4'
        )
        try:
            conn.autocommit(True)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                    (database,)
                )
                if not cur.fetchone():
                    # PyMySQL has no identifier-quoting helper; validate instead.
                    if not re.match(r'^[A-Za-z0-9_]+$', database):
                        raise ValueError(f"Invalid MySQL database name: {database}")
                    cur.execute(
                        f"CREATE DATABASE `{database}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
                    )
                    logger.info(f"Database '{database}' created successfully")
        finally:
            conn.close()

    @classmethod
    def _ensure_table_exists(cls, conn_pool: PooledDB):
        conn = conn_pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(MySQLQueries.CREATE_TABLE.value)
                logger.info("Table 'agent_card' and indexes created/verified")
                cur.execute(MySQLQueries.CREATE_TAG_TABLE.value)
                logger.info("Table 'tag' and indexes created/verified")
        finally:
            conn.close()

    # ---- connection management ----

    def _acquire_conn(self):
        return self.pool.connection()

    def _release_conn(self, conn):
        conn.close()

    # ---- tag param: JSON_CONTAINS expects a JSON array document ----

    def _to_tag_query_param(self, tag: str):
        return json.dumps([tag])

    def close(self):
        if self.pool:
            self.pool.close()
            logger.info("MySQL connection pool closed")
