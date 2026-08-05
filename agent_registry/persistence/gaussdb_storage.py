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
from psycopg2 import pool, sql
from loguru import logger

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

        cls._ensure_database_exists(host, port, database, user, password)

        connection_pool = pool.ThreadedConnectionPool(
            minconn=min_size,
            maxconn=max_size,
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        logger.info("GaussDB connection pool initialized")

        instance = cls(connection_pool)
        instance._ensure_table_exists(connection_pool)
        return instance

    @classmethod
    def _ensure_database_exists(cls, host: str, port: int, database: str,
                                user: str, password: str):
        conn = psycopg2.connect(
            host=host, port=port, database='postgres', user=user, password=password
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

    @classmethod
    def _ensure_table_exists(cls, conn_pool: pool.ThreadedConnectionPool):
        conn = conn_pool.getconn()
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(GaussDBQueries.CREATE_TABLE.value)
                cur.execute(GaussDBQueries.ADD_COLUMN_STATUS.value)
                cur.execute(GaussDBQueries.ADD_COLUMN_TAGS.value)
                cur.execute(GaussDBQueries.ADD_COLUMN_OWNER.value)
                cur.execute(GaussDBQueries.DROP_OLD_UNIQUE_INDEX.value)
                cur.execute(GaussDBQueries.CREATE_OWNER_UNIQUE_INDEX.value)
                cur.execute(GaussDBQueries.CREATE_INDEX_ORG.value)
                cur.execute(GaussDBQueries.CREATE_INDEX_NAME.value)
                cur.execute(GaussDBQueries.CREATE_INDEX_STATUS.value)
                cur.execute(GaussDBQueries.CREATE_INDEX_OWNER.value)
                logger.info("Table 'agent_card' and indexes created/verified")

                cur.execute(GaussDBQueries.CREATE_TAG_TABLE.value)
                cur.execute(GaussDBQueries.CREATE_TAG_INDEX_NAME.value)
                logger.info("Table 'tag' and indexes created/verified")
        finally:
            conn_pool.putconn(conn)

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
