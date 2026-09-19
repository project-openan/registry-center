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
GaussDB storage backend.

GaussDB is PG-protocol compatible, so this backend uses psycopg2 just like
PostgreSQLStorage. The key difference is JSON columns are stored as TEXT
(not JSONB) for maximum portability across GaussDB versions. Casts to jsonb
happen at query time where JSON operators are needed.
"""

import json

import psycopg2
from psycopg2 import pool
from loguru import logger

from .connection import (
    DEFAULT_CONNECT_TIMEOUT,
    build_pg_pool,
    ensure_pg_database,
    ensure_pg_tables,
)
from .sql_backend import SqlStorageBackend
from .sql_queries import GaussDBQueries


class GaussDBStorage(SqlStorageBackend):
    """GaussDB storage backend using psycopg2 connection pool."""

    queries = GaussDBQueries
    _integrity_error = psycopg2.IntegrityError

    def __init__(self, conn_pool: pool.ThreadedConnectionPool):
        self.pool = conn_pool

    @classmethod
    def init(cls, config: dict) -> 'GaussDBStorage':
        host = config.get('gauss.host', 'localhost')
        port = int(config.get('gauss.port', 5432))
        database = config.get('gauss.database', 'a2a_registry')
        user = config.get('gauss.username', 'a2a_user')
        password = config.get('gauss.password', '')
        min_size = int(config.get('gauss.pool.min', 5))
        max_size = int(config.get('gauss.pool.max', 20))
        connect_timeout = int(config.get('gauss.connect_timeout', DEFAULT_CONNECT_TIMEOUT))

        cls._ensure_database_exists(host, port, database, user, password, connect_timeout)

        connection_pool = build_pg_pool(host, port, database, user, password,
                                        min_size, max_size, connect_timeout)
        logger.info("GaussDB connection pool initialized")

        instance = cls(connection_pool)
        instance._ensure_table_exists(connection_pool)
        return instance

    @classmethod
    def _ensure_database_exists(cls, host: str, port: int, database: str,
                                user: str, password: str,
                                connect_timeout: int = DEFAULT_CONNECT_TIMEOUT):
        ensure_pg_database(host, port, database, user, password, connect_timeout)

    @classmethod
    def _ensure_table_exists(cls, conn_pool: pool.ThreadedConnectionPool):
        ensure_pg_tables(conn_pool, GaussDBQueries)

    # ---- connection management ----

    def _acquire_conn(self):
        return self.pool.getconn()

    def _release_conn(self, conn):
        self.pool.putconn(conn)

    # ---- tag param: GaussDB uses JSONB containment via cast ----

    def _to_tag_query_param(self, tag: str):
        return json.dumps([tag])

    def close(self):
        if self.pool:
            self.pool.closeall()
            logger.info("GaussDB connection pool closed")
