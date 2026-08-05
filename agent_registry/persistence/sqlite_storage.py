# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
SQLite storage backend.

Uses Python's built-in sqlite3 module (zero external dependency).
JSON columns are stored as TEXT. WAL mode + busy_timeout for concurrency.
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional

from loguru import logger

from .sql_backend import SqlStorageBackend
from .sql_queries import SQLiteQueries


class SQLiteStorage(SqlStorageBackend):
    """SQLite storage backend using the standard-library sqlite3 module."""

    queries = SQLiteQueries
    _integrity_error = sqlite3.IntegrityError

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @classmethod
    def init(cls, config: dict) -> 'SQLiteStorage':
        db_path = config.get('sqlite.path', 'data/agents.db')
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('PRAGMA foreign_keys=ON')

        instance = cls(conn)
        instance._ensure_table_exists()
        logger.info(f"SQLiteStorage initialized with path: {db_path}")
        return instance

    def _ensure_table_exists(self):
        conn = self._acquire_conn()
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(SQLiteQueries.CREATE_TABLE.value)
            cur.execute(SQLiteQueries.CREATE_INDEX_ORG.value)
            cur.execute(SQLiteQueries.CREATE_INDEX_NAME.value)
            cur.execute(SQLiteQueries.CREATE_INDEX_STATUS.value)
            cur.execute(SQLiteQueries.CREATE_INDEX_OWNER.value)
            cur.execute(SQLiteQueries.CREATE_TAG_TABLE.value)
            cur.execute(SQLiteQueries.CREATE_TAG_INDEX_NAME.value)
            conn.commit()
            logger.info("SQLite tables and indexes created/verified")
        finally:
            if cur:
                cur.close()
            self._release_conn(conn)

    # ---- connection management ----

    def _acquire_conn(self) -> sqlite3.Connection:
        return self._conn

    def _release_conn(self, conn):
        pass

    # ---- tag param: SQLite uses plain string (json_each matches value) ----

    def _to_tag_query_param(self, tag: str):
        return tag

    def close(self):
        if self._conn:
            self._conn.close()
            logger.info("SQLite connection closed")
