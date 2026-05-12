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

from enum import Enum


class PostgreSQLQueries(str, Enum):
    CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS agent_card (
            id              SERIAL PRIMARY KEY,
            name            VARCHAR(100) NOT NULL,
            organization    VARCHAR(100) NOT NULL,
            owner           VARCHAR(100) NULL,
            description     VARCHAR(1000),
            url             VARCHAR(1024),
            version         VARCHAR(50),
            status          VARCHAR(20) DEFAULT 'published',
            provider_json   JSONB        NOT NULL,
            capabilities_json JSONB,
            skills_json     JSONB,
            default_input_modes  JSONB,
            default_output_modes JSONB,
            agent_card_json JSONB        NOT NULL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, organization, owner)
        )
    """

    CREATE_INDEX_ORG = "CREATE INDEX IF NOT EXISTS idx_agent_org ON agent_card(organization)"
    CREATE_INDEX_NAME = "CREATE INDEX IF NOT EXISTS idx_agent_name ON agent_card(name)"
    CREATE_INDEX_STATUS = "CREATE INDEX IF NOT EXISTS idx_agent_status ON agent_card(status)"
    CREATE_INDEX_GIN = "CREATE INDEX IF NOT EXISTS idx_agent_card_json ON agent_card USING GIN(agent_card_json)"

    ADD_COLUMN_STATUS = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name='agent_card' AND column_name='status') THEN
                ALTER TABLE agent_card ADD COLUMN status VARCHAR(20) DEFAULT 'published';
            END IF;
        END $$;
    """

    CREATE_AGENT = """
        INSERT INTO agent_card (name, organization, description, url, version, status, provider_json,
                                capabilities_json, skills_json, default_input_modes, default_output_modes,
                                agent_card_json, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (name, organization) DO NOTHING
    """

    FIND_BY_KEY = """
        SELECT agent_card_json FROM agent_card
        WHERE name = %s AND organization = %s
    """

    FIND_BY_NAME = """
        SELECT agent_card_json FROM agent_card WHERE name LIKE %s
    """

    FIND_BY_ORG = """
        SELECT agent_card_json FROM agent_card WHERE organization = %s
    """

    FIND_BY_STATUS = """
        SELECT agent_card_json FROM agent_card WHERE status = %s
    """

    FIND_ALL = "SELECT agent_card_json FROM agent_card"

    UPDATE_AGENT = """
        UPDATE agent_card SET agent_card_json = %s, updated_at = %s
        WHERE name = %s AND organization = %s
    """

    UPDATE_STATUS = """
        UPDATE agent_card SET status = %s, updated_at = %s
        WHERE name = %s AND organization = %s
    """

    DELETE_AGENT = """
        DELETE FROM agent_card WHERE name = %s AND organization = %s
    """

    COUNT = "SELECT COUNT(*) FROM agent_card"

    COUNT_BY_STATUS = "SELECT COUNT(*) FROM agent_card WHERE status = %s"

    GET_METADATA = """
        SELECT name, organization, status, tags FROM agent_card
        WHERE name = %s AND organization = %s
    """

    GET_ALL_METADATA = """
        SELECT name, organization, status, tags FROM agent_card
    """

    GET_CREATED_AT = """
        SELECT created_at FROM agent_card
        WHERE name = %s AND organization = %s
    """

    GET_UPDATED_AT = """
        SELECT updated_at FROM agent_card
        WHERE name = %s AND organization = %s
    """

    ADD_COLUMN_OWNER = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name='agent_card' AND column_name='owner') THEN
                ALTER TABLE agent_card ADD COLUMN owner VARCHAR(100) NULL;
            END IF;
        END $$;
    """

    CREATE_INDEX_OWNER = "CREATE INDEX IF NOT EXISTS idx_agent_owner ON agent_card(owner)"

    DROP_OLD_UNIQUE_INDEX = """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_card_name_organization_key') THEN
                ALTER TABLE agent_card DROP CONSTRAINT agent_card_name_organization_key;
            END IF;
        END $$;
    """

    CREATE_OWNER_UNIQUE_INDEX = """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_owner_unique ON agent_card(name, organization, owner)
    """

    CREATE_AGENT_WITH_OWNER = """
        INSERT INTO agent_card (name, organization, owner, description, url, version, status, provider_json,
                                capabilities_json, skills_json, default_input_modes, default_output_modes,
                                agent_card_json, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (name, organization, owner) DO NOTHING
    """

    FIND_BY_KEY_WITH_OWNER = """
        SELECT agent_card_json, owner FROM agent_card
        WHERE name = %s AND organization = %s AND owner = %s
    """

    FIND_BY_KEY_ANY_OWNER = """
        SELECT agent_card_json, owner FROM agent_card
        WHERE name = %s AND organization = %s
        ORDER BY owner NULLS LAST
        LIMIT 1
    """

    FIND_BY_OWNER = """
        SELECT agent_card_json, owner FROM agent_card WHERE owner = %s
    """

    UPDATE_AGENT_WITH_OWNER = """
        UPDATE agent_card SET agent_card_json = %s, updated_at = %s
        WHERE name = %s AND organization = %s AND (owner = %s OR owner IS NULL)
    """

    DELETE_AGENT_WITH_OWNER = """
        DELETE FROM agent_card 
        WHERE name = %s AND organization = %s AND (owner = %s OR owner IS NULL)
    """

    # Agent card tags column
    ADD_COLUMN_TAGS = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name='agent_card' AND column_name='tags') THEN
                ALTER TABLE agent_card ADD COLUMN tags JSONB DEFAULT '[]'::jsonb;
            END IF;
        END $$;
    """

    GET_AGENT_TAGS = """
        SELECT tags FROM agent_card WHERE name = %s AND organization = %s
    """

    UPDATE_AGENT_TAGS = """
        UPDATE agent_card SET tags = %s, updated_at = %s
        WHERE name = %s AND organization = %s
    """

    # Independent tag table (for tag entity management)
    CREATE_TAG_TABLE = """
        CREATE TABLE IF NOT EXISTS tag (
            tag_id VARCHAR(50) PRIMARY KEY,
            name VARCHAR(50) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    CREATE_TAG_INDEX_NAME = "CREATE INDEX IF NOT EXISTS idx_tag_name ON tag(name)"

    CREATE_TAG = """
        INSERT INTO tag (tag_id, name, created_at, updated_at)
        VALUES (%s, %s, %s, %s)
    """

    GET_TAG_BY_ID = """
        SELECT tag_id, name, created_at, updated_at FROM tag
        WHERE tag_id = %s
    """

    GET_TAG_BY_NAME = """
        SELECT tag_id, name, created_at, updated_at FROM tag
        WHERE name = %s
    """

    UPDATE_TAG = """
        UPDATE tag SET name = %s, updated_at = %s
        WHERE tag_id = %s
    """

    DELETE_TAG = """
        DELETE FROM tag WHERE tag_id = %s
    """

    LIST_TAGS = """
        SELECT tag_id, name, created_at, updated_at FROM tag
        ORDER BY created_at DESC
    """