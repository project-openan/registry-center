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
from typing import List, Optional, Dict, Any, Tuple

import psycopg2
from psycopg2 import pool
from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict, Parse
from loguru import logger

from .base import StorageBackend, AgentRecord
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
                cur.execute(PostgreSQLQueries.ADD_COLUMN_STATUS.value)
                cur.execute(PostgreSQLQueries.ADD_COLUMN_TAGS.value)
                cur.execute(PostgreSQLQueries.ADD_COLUMN_OWNER.value)
                cur.execute(PostgreSQLQueries.DROP_OLD_UNIQUE_INDEX.value)
                cur.execute(PostgreSQLQueries.CREATE_OWNER_UNIQUE_INDEX.value)
                cur.execute(PostgreSQLQueries.CREATE_INDEX_ORG.value)
                cur.execute(PostgreSQLQueries.CREATE_INDEX_NAME.value)
                cur.execute(PostgreSQLQueries.CREATE_INDEX_STATUS.value)
                cur.execute(PostgreSQLQueries.CREATE_INDEX_OWNER.value)
                cur.execute(PostgreSQLQueries.CREATE_INDEX_GIN.value)
                logger.info("Table 'agent_card' and indexes created/verified")
        finally:
            connection_pool.putconn(conn)

    def _get_agent_fields(self, agent: AgentCard, owner: Optional[str] = None, status: str = 'published') -> tuple:
        agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
        now = datetime.utcnow()
        return (
            agent.name,
            agent.provider.organization,
            owner,
            agent_dict.get('description'),
            agent_dict.get('documentation_url'),
            agent_dict.get('version'),
            status,
            json.dumps(agent_dict.get('provider', {})),
            json.dumps(agent_dict.get('capabilities', {})) if agent_dict.get('capabilities') else None,
            json.dumps(agent_dict.get('skills', [])) if agent_dict.get('skills') else None,
            json.dumps(agent_dict.get('default_input_modes', [])) if agent_dict.get('default_input_modes') else None,
            json.dumps(agent_dict.get('default_output_modes', [])) if agent_dict.get('default_output_modes') else None,
            json.dumps(agent_dict),
            now,
            now
        )

    def create(self, agent: AgentCard, owner: Optional[str] = None, status: str = 'published') -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.CREATE_AGENT_WITH_OWNER.value,
                    self._get_agent_fields(agent, owner, status)
                )
                conn.commit()
                affected = cur.rowcount
            if affected > 0:
                logger.info(f"Created agent in PostgreSQL: {agent.name} (org={agent.provider.organization}, owner={owner}, status={status})")
            return affected > 0
        finally:
            self.pool.putconn(conn)

    def find_by_key(self, name: str, organization: str, owner: Optional[str] = None) -> Optional[AgentRecord]:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                if owner is not None:
                    cur.execute(
                        PostgreSQLQueries.FIND_BY_KEY_WITH_OWNER.value,
                        (name, organization, owner)
                    )
                else:
                    cur.execute(
                        PostgreSQLQueries.FIND_BY_KEY_ANY_OWNER.value,
                        (name, organization)
                    )
                row = cur.fetchone()
            if row:
                data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                agent = AgentCard(**data)
                stored_owner = row[1] if len(row) > 1 else None
                return AgentRecord(agent_card=agent, owner=stored_owner)
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

    def update(self, name: str, organization: str, agent_data: Dict[str, Any], owner: Optional[str] = None) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                agent = Parse(json.dumps(agent_data), AgentCard())
                agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
                now = datetime.utcnow()
                if owner is not None:
                    cur.execute(
                        PostgreSQLQueries.UPDATE_AGENT_WITH_OWNER.value,
                        (json.dumps(agent_dict), now, name, organization, owner)
                    )
                else:
                    existing = self.find_by_key(name, organization)
                    if existing and existing.owner:
                        cur.execute(
                            PostgreSQLQueries.UPDATE_AGENT_WITH_OWNER.value,
                            (json.dumps(agent_dict), now, name, organization, existing.owner)
                        )
                    else:
                        cur.execute(
                            PostgreSQLQueries.UPDATE_AGENT.value,
                            (json.dumps(agent_dict), now, name, organization)
                        )
                conn.commit()
                affected = cur.rowcount
            logger.info(f"Updated agent in PostgreSQL: {name} (org={organization}, owner={owner}), affected={affected}")
            return affected > 0
        finally:
            self.pool.putconn(conn)

    def delete(self, name: str, organization: str, owner: Optional[str] = None) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                if owner is not None:
                    cur.execute(
                        PostgreSQLQueries.DELETE_AGENT_WITH_OWNER.value,
                        (name, organization, owner)
                    )
                else:
                    existing = self.find_by_key(name, organization)
                    if existing and existing.owner:
                        cur.execute(
                            PostgreSQLQueries.DELETE_AGENT_WITH_OWNER.value,
                            (name, organization, existing.owner)
                        )
                    else:
                        cur.execute(
                            PostgreSQLQueries.DELETE_AGENT.value,
                            (name, organization)
                        )
                conn.commit()
                affected = cur.rowcount
            logger.info(f"Deleted agent from PostgreSQL: {name} (org={organization}, owner={owner}), affected={affected}")
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

    def find_by_status(self, status: str) -> List[AgentCard]:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.FIND_BY_STATUS.value,
                    (status,)
                )
                rows = cur.fetchall()
            return [AgentCard(**(r[0] if isinstance(r[0], dict) else json.loads(r[0]))) for r in rows]
        finally:
            self.pool.putconn(conn)

    def update_status(self, name: str, organization: str, new_status: str) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                now = datetime.utcnow()
                cur.execute(
                    PostgreSQLQueries.UPDATE_STATUS.value,
                    (new_status, now, name, organization)
                )
                conn.commit()
                affected = cur.rowcount
            return affected > 0
        finally:
            self.pool.putconn(conn)

    def count_by_status(self, status: str) -> int:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.COUNT_BY_STATUS.value,
                    (status,)
                )
                result = cur.fetchone()
            return result[0] if result else 0
        finally:
            self.pool.putconn(conn)

    def get_tags(self, name: str, organization: str) -> List[str]:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.GET_TAGS.value,
                    (name, organization)
                )
                result = cur.fetchone()
            if result and result[0]:
                tags = result[0] if isinstance(result[0], list) else json.loads(result[0])
                return tags
            return []
        finally:
            self.pool.putconn(conn)

    def update_tags(self, name: str, organization: str, new_tags: List[str]) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                now = datetime.utcnow()
                cur.execute(
                    PostgreSQLQueries.UPDATE_TAGS.value,
                    (json.dumps(new_tags), now, name, organization)
                )
                conn.commit()
                affected = cur.rowcount
            return affected > 0
        finally:
            self.pool.putconn(conn)

    def get_created_at(self, name: str, organization: str) -> str:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.GET_CREATED_AT.value,
                    (name, organization)
                )
                result = cur.fetchone()
            if result and result[0]:
                return result[0].isoformat() if hasattr(result[0], 'isoformat') else str(result[0])
            return ''
        finally:
            self.pool.putconn(conn)

    def get_updated_at(self, name: str, organization: str) -> str:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.GET_UPDATED_AT.value,
                    (name, organization)
                )
                result = cur.fetchone()
            if result and result[0]:
                return result[0].isoformat() if hasattr(result[0], 'isoformat') else str(result[0])
            return ''
        finally:
            self.pool.putconn(conn)

    def find_by_owner(self, owner: str) -> List[AgentRecord]:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.FIND_BY_OWNER.value,
                    (owner,)
                )
                rows = cur.fetchall()
            result = []
            for row in rows:
                data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                agent = AgentCard(**data)
                stored_owner = row[1] if len(row) > 1 else None
                result.append(AgentRecord(agent_card=agent, owner=stored_owner))
            logger.debug(f"Found {len(result)} agents by owner '{owner}' in PostgreSQL")
            return result
        finally:
            self.pool.putconn(conn)

    def find_by_tag(self, tag: str) -> List[AgentCard]:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.FIND_BY_TAG.value,
                    (json.dumps([tag]),)
                )
                rows = cur.fetchall()
            result = [AgentCard(**(r[0] if isinstance(r[0], dict) else json.loads(r[0]))) for r in rows]
            logger.debug(f"Found {len(result)} agents by tag '{tag}' in PostgreSQL")
            return result
        finally:
            self.pool.putconn(conn)

    def close(self):
        if self.pool:
            self.pool.closeall()
            logger.info("PostgreSQL connection pool closed")
