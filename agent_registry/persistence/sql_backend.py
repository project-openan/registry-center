# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Shared SQL storage backend for PostgreSQL, GaussDB, and SQLite.

Subclasses provide dialect-specific connection management, query sets, and
schema initialization while inheriting all CRUD logic from this base class.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict, Parse
from loguru import logger

from agent_registry.model.tag import Tag
from .base import StorageBackend, AgentRecord


class SqlStorageBackend(StorageBackend):
    """Shared SQL CRUD logic. Subclasses set `queries` and implement connections."""

    queries = None
    _integrity_error = Exception

    # ---- connection management (subclass implements) ----

    def _acquire_conn(self):
        raise NotImplementedError

    def _release_conn(self, conn):
        pass

    # ---- execution helpers ----

    def _execute_write(self, query: str, params: tuple = None) -> int:
        conn = self._acquire_conn()
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(query, params or ())
            conn.commit()
            return cur.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            if cur:
                cur.close()
            self._release_conn(conn)

    def _execute_read_one(self, query: str, params: tuple = None):
        conn = self._acquire_conn()
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(query, params or ())
            return cur.fetchone()
        finally:
            if cur:
                cur.close()
            self._release_conn(conn)

    def _execute_read_all(self, query: str, params: tuple = None):
        conn = self._acquire_conn()
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(query, params or ())
            return cur.fetchall()
        finally:
            if cur:
                cur.close()
            self._release_conn(conn)

    # ---- value parsing ----

    @staticmethod
    def _parse_json(val):
        if val is None:
            return None
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            return json.loads(val)
        return val

    @staticmethod
    def _parse_tags(val):
        if not val:
            return []
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            return json.loads(val)
        return []

    @staticmethod
    def _parse_timestamp(val):
        if val and hasattr(val, 'isoformat'):
            return val.isoformat()
        return str(val) if val else ''

    def _row_to_agent(self, row) -> AgentCard:
        data = self._parse_json(row[0])
        return AgentCard(**data)

    def _row_to_agent_record(self, row) -> AgentRecord:
        agent = self._row_to_agent(row)
        stored_owner = row[1] if len(row) > 1 else None
        stored_status = row[2] if len(row) > 2 else 'published'
        tags = self._parse_tags(row[3]) if len(row) > 3 else []
        created_at = self._parse_timestamp(row[4]) if len(row) > 4 else ''
        updated_at = self._parse_timestamp(row[5]) if len(row) > 5 else ''
        return AgentRecord(
            agent_card=agent, owner=stored_owner,
            status=stored_status, tags=tags,
            created_at=created_at, updated_at=updated_at
        )

    def _row_to_tag(self, row) -> Tag:
        return Tag(
            tag_id=row[0],
            name=row[1],
            created_at=self._parse_timestamp(row[2]),
            updated_at=self._parse_timestamp(row[3])
        )

    def _to_tag_query_param(self, tag: str):
        """Convert tag to FIND_BY_TAG parameter. Override for JSONB backends."""
        return tag

    def _get_agent_fields(self, agent: AgentCard, owner: Optional[str] = None,
                          status: str = 'published') -> tuple:
        agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
        now = datetime.now(timezone.utc)
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

    # ---- StorageBackend implementation ----

    def create(self, agent: AgentCard, owner: Optional[str] = None,
               status: str = 'published') -> bool:
        existing = self.find_by_key(agent.name, agent.provider.organization)
        if existing:
            logger.warning(f"Agent already exists: {agent.name} (org={agent.provider.organization})")
            return False
        affected = self._execute_write(
            self.queries.CREATE_AGENT_WITH_OWNER.value,
            self._get_agent_fields(agent, owner, status)
        )
        if affected > 0:
            logger.info(f"Created agent: {agent.name} (org={agent.provider.organization}, owner={owner}, status={status})")
        return affected > 0

    def find_by_key(self, name: str, organization: str,
                    owner: Optional[str] = None) -> Optional[AgentRecord]:
        if owner is not None:
            row = self._execute_read_one(
                self.queries.FIND_BY_KEY_WITH_OWNER.value,
                (name, organization, owner)
            )
        else:
            row = self._execute_read_one(
                self.queries.FIND_BY_KEY_ANY_OWNER.value,
                (name, organization)
            )
        if row:
            return self._row_to_agent_record(row)
        return None

    def find_by_name(self, name: str) -> List[AgentCard]:
        rows = self._execute_read_all(self.queries.FIND_BY_NAME.value, (f"%{name}%",))
        result = [self._row_to_agent(r) for r in rows]
        logger.debug(f"Found {len(result)} agents by name '{name}'")
        return result

    def find_by_organization(self, organization: str) -> List[AgentCard]:
        rows = self._execute_read_all(self.queries.FIND_BY_ORG.value, (organization,))
        result = [self._row_to_agent(r) for r in rows]
        logger.debug(f"Found {len(result)} agents by organization '{organization}'")
        return result

    def find_all(self) -> List[AgentCard]:
        rows = self._execute_read_all(self.queries.FIND_ALL.value)
        result = [self._row_to_agent(r) for r in rows]
        logger.debug(f"Found {len(result)} agents (find_all)")
        return result

    def find_by_owner(self, owner: str) -> List[AgentRecord]:
        rows = self._execute_read_all(self.queries.FIND_BY_OWNER.value, (owner,))
        result = []
        for row in rows:
            agent = self._row_to_agent(row)
            stored_owner = row[1] if len(row) > 1 else None
            result.append(AgentRecord(agent_card=agent, owner=stored_owner))
        logger.debug(f"Found {len(result)} agents by owner '{owner}'")
        return result

    def find_by_status(self, status: str) -> List[AgentCard]:
        rows = self._execute_read_all(self.queries.FIND_BY_STATUS.value, (status,))
        return [self._row_to_agent(r) for r in rows]

    def find_by_tag(self, tag: str) -> List[AgentCard]:
        param = self._to_tag_query_param(tag)
        rows = self._execute_read_all(self.queries.FIND_BY_TAG.value, (param,))
        result = [self._row_to_agent(r) for r in rows]
        logger.debug(f"Found {len(result)} agents by tag '{tag}'")
        return result

    def update(self, name: str, organization: str, agent_data: Dict[str, Any],
               owner: Optional[str] = None) -> bool:
        agent = Parse(json.dumps(agent_data), AgentCard())
        agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
        status_value = agent_data.get('status', 'published')
        now = datetime.now(timezone.utc)

        if owner is not None:
            affected = self._execute_write(
                self.queries.UPDATE_AGENT_WITH_OWNER.value,
                (json.dumps(agent_dict), status_value, now, name, organization, owner)
            )
        else:
            existing = self.find_by_key(name, organization)
            if existing and existing.owner:
                affected = self._execute_write(
                    self.queries.UPDATE_AGENT_WITH_OWNER.value,
                    (json.dumps(agent_dict), status_value, now, name, organization, existing.owner)
                )
            else:
                affected = self._execute_write(
                    self.queries.UPDATE_AGENT.value,
                    (json.dumps(agent_dict), status_value, now, name, organization)
                )
        logger.info(f"Updated agent: {name} (org={organization}, owner={owner}), affected={affected}")
        return affected > 0

    def update_status(self, name: str, organization: str, new_status: str) -> bool:
        now = datetime.now(timezone.utc)
        affected = self._execute_write(
            self.queries.UPDATE_STATUS.value,
            (new_status, now, name, organization)
        )
        return affected > 0

    def delete(self, name: str, organization: str,
               owner: Optional[str] = None) -> bool:
        if owner is not None:
            affected = self._execute_write(
                self.queries.DELETE_AGENT_WITH_OWNER.value,
                (name, organization, owner)
            )
        else:
            existing = self.find_by_key(name, organization)
            if existing and existing.owner:
                affected = self._execute_write(
                    self.queries.DELETE_AGENT_WITH_OWNER.value,
                    (name, organization, existing.owner)
                )
            else:
                affected = self._execute_write(
                    self.queries.DELETE_AGENT.value,
                    (name, organization)
                )
        logger.info(f"Deleted agent: {name} (org={organization}, owner={owner}), affected={affected}")
        return affected > 0

    def count(self) -> int:
        row = self._execute_read_one(self.queries.COUNT.value)
        return row[0] if row else 0

    def count_by_status(self, status: str) -> int:
        row = self._execute_read_one(self.queries.COUNT_BY_STATUS.value, (status,))
        return row[0] if row else 0

    def get_created_at(self, name: str, organization: str) -> str:
        row = self._execute_read_one(self.queries.GET_CREATED_AT.value, (name, organization))
        if row and row[0]:
            return self._parse_timestamp(row[0])
        return ''

    def get_updated_at(self, name: str, organization: str) -> str:
        row = self._execute_read_one(self.queries.GET_UPDATED_AT.value, (name, organization))
        if row and row[0]:
            return self._parse_timestamp(row[0])
        return ''

    def get_agent_tags(self, name: str, organization: str) -> List[str]:
        row = self._execute_read_one(self.queries.GET_AGENT_TAGS.value, (name, organization))
        if row and row[0]:
            return self._parse_tags(row[0])
        return []

    def update_agent_tags(self, name: str, organization: str,
                          new_tags: List[str]) -> bool:
        now = datetime.now(timezone.utc)
        affected = self._execute_write(
            self.queries.UPDATE_AGENT_TAGS.value,
            (json.dumps(new_tags), now, name, organization)
        )
        return affected > 0

    # ---- tag entity management ----

    def create_tag(self, tag: Tag) -> bool:
        try:
            self._execute_write(
                self.queries.CREATE_TAG.value,
                (tag.tag_id, tag.name, tag.created_at, tag.updated_at)
            )
            logger.info(f"Tag created: {tag.name} (ID: {tag.tag_id})")
            return True
        except self._integrity_error as e:
            logger.warning(f"Tag already exists: {tag.name} - {e}")
            return False

    def get_tag(self, tag_id: str) -> Optional[Tag]:
        row = self._execute_read_one(self.queries.GET_TAG_BY_ID.value, (tag_id,))
        if row:
            return self._row_to_tag(row)
        return None

    def get_tag_by_name(self, name: str) -> Optional[Tag]:
        row = self._execute_read_one(self.queries.GET_TAG_BY_NAME.value, (name,))
        if row:
            return self._row_to_tag(row)
        return None

    def update_tag(self, tag_id: str, tag: Tag) -> bool:
        try:
            now = datetime.now(timezone.utc).isoformat()
            affected = self._execute_write(
                self.queries.UPDATE_TAG.value,
                (tag.name, now, tag_id)
            )
            logger.info(f"Tag updated: {tag.name} (ID: {tag_id})")
            return affected > 0
        except self._integrity_error as e:
            logger.warning(f"Tag name already exists: {tag.name} - {e}")
            return False

    def delete_tag(self, tag_id: str) -> bool:
        affected = self._execute_write(self.queries.DELETE_TAG.value, (tag_id,))
        logger.info(f"Tag deleted: ID {tag_id}")
        return affected > 0

    def list_tags(self) -> List[Tag]:
        rows = self._execute_read_all(self.queries.LIST_TAGS.value)
        result = [self._row_to_tag(r) for r in rows]
        logger.debug(f"Listed {len(result)} tags")
        return result
