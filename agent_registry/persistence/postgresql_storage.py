# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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

import json
from datetime import datetime
from typing import List, Optional, Dict, Any

import psycopg2
from psycopg2 import pool
from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict
from loguru import logger

from .base import StorageBackend
from .sql_queries import PostgreSQLQueries


class PostgreSQLStorage(StorageBackend):
    def __init__(self, pool: pool.ThreadedConnectionPool):
        self.pool = pool

    @classmethod
    def init(cls, config: dict) -> 'PostgreSQLStorage':
        host = config.get('postgresql.host', 'localhost')
        port = int(config.get('postgresql.port', 5432))
        database = config.get('postgresql.name', 'a2a_registry')
        user = config.get('postgresql.username', 'a2a_user')
        password = config.get('postgresql.password', '')
        min_size = int(config.get('postgresql.pool.min', 5))
        max_size = int(config.get('postgresql.pool.max', 20))

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
        logger.info("PostgreSQL connection pool initialized")

        cls._ensure_table_exists(connection_pool)

        return cls(connection_pool)

    @classmethod
    def _ensure_database_exists(cls, host: str, port: int, database: str, user: str, password: str):
        conn = psycopg2.connect(
            host=host,
            port=port,
            database='postgres',
            user=user,
            password=password
        )
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
                exists = cur.fetchone()
                if not exists:
                    cur.execute(f'CREATE DATABASE "{database}"')
                    logger.info(f"Database '{database}' created successfully")
        finally:
            conn.close()

    @classmethod
    def _ensure_table_exists(cls, connection_pool: pool.ThreadedConnectionPool):
        conn = connection_pool.getconn()
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(PostgreSQLQueries.CREATE_TABLE.value)
                cur.execute(PostgreSQLQueries.CREATE_INDEX_ORG.value)
                cur.execute(PostgreSQLQueries.CREATE_INDEX_NAME.value)
                cur.execute(PostgreSQLQueries.CREATE_INDEX_GIN.value)
                logger.info("Table 'agent_card' and indexes created/verified")
        finally:
            connection_pool.putconn(conn)

    def _get_agent_fields(self, agent: AgentCard) -> tuple:
        agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
        now = datetime.utcnow()
        return (
            agent.name,
            agent.provider.organization,
            agent_dict.get('description'),
            agent_dict.get('documentation_url'),
            agent_dict.get('version'),
            json.dumps(agent_dict.get('provider', {})),
            json.dumps(agent_dict.get('capabilities', {})) if agent_dict.get('capabilities') else None,
            json.dumps(agent_dict.get('skills', [])) if agent_dict.get('skills') else None,
            json.dumps(agent_dict.get('default_input_modes', [])) if agent_dict.get('default_input_modes') else None,
            json.dumps(agent_dict.get('default_output_modes', [])) if agent_dict.get('default_output_modes') else None,
            json.dumps(agent_dict),
            now,
            now
        )

    def create(self, agent: AgentCard) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.CREATE_AGENT.value,
                    self._get_agent_fields(agent)
                )
                conn.commit()
            result = self.find_by_key(agent.name, agent.provider.organization)
            if result:
                logger.info(f"Created agent in PostgreSQL: {agent.name} (org={agent.provider.organization})")
            return result is not None
        finally:
            self.pool.putconn(conn)

    def find_by_key(self, name: str, organization: str) -> Optional[AgentCard]:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.FIND_BY_KEY.value,
                    (name, organization)
                )
                row = cur.fetchone()
            if row:
                data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                return AgentCard(**data)
            return None
        finally:
            self.pool.putconn(conn)

    def find_by_name(self, name: str) -> List[AgentCard]:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.FIND_BY_NAME.value,
                    (f"%{name}%",)
                )
                rows = cur.fetchall()
            result = [AgentCard(**(r[0] if isinstance(r[0], dict) else json.loads(r[0]))) for r in rows]
            logger.debug(f"Found {len(result)} agents by name '{name}' in PostgreSQL")
            return result
        finally:
            self.pool.putconn(conn)

    def find_by_organization(self, organization: str) -> List[AgentCard]:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.FIND_BY_ORG.value,
                    (organization,)
                )
                rows = cur.fetchall()
            result = [AgentCard(**(r[0] if isinstance(r[0], dict) else json.loads(r[0]))) for r in rows]
            logger.debug(f"Found {len(result)} agents by organization '{organization}' in PostgreSQL")
            return result
        finally:
            self.pool.putconn(conn)

    def find_all(self) -> List[AgentCard]:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(PostgreSQLQueries.FIND_ALL.value)
                rows = cur.fetchall()
            result = [AgentCard(**(r[0] if isinstance(r[0], dict) else json.loads(r[0]))) for r in rows]
            logger.debug(f"Found {len(result)} agents in PostgreSQL (find_all)")
            return result
        finally:
            self.pool.putconn(conn)

    def update(self, name: str, organization: str, agent_data: Dict[str, Any]) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                agent = AgentCard(**agent_data)
                agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
                now = datetime.utcnow()
                cur.execute(
                    PostgreSQLQueries.UPDATE_AGENT.value,
                    (
                        json.dumps(agent_dict),
                        now,
                        name,
                        organization
                    )
                )
                conn.commit()
                affected = cur.rowcount
            logger.info(f"Updated agent in PostgreSQL: {name} (org={organization}), affected={affected}")
            return affected > 0
        finally:
            self.pool.putconn(conn)

    def delete(self, name: str, organization: str) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.DELETE_AGENT.value,
                    (name, organization)
                )
                conn.commit()
                affected = cur.rowcount
            logger.info(f"Deleted agent from PostgreSQL: {name} (org={organization}), affected={affected}")
            return affected > 0
        finally:
            self.pool.putconn(conn)

    def count(self) -> int:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(PostgreSQLQueries.COUNT.value)
                result = cur.fetchone()
            return result[0] if result else 0
        finally:
            self.pool.putconn(conn)

    def close(self):
        if self.pool:
            self.pool.closeall()
            logger.info("PostgreSQL connection pool closed")
