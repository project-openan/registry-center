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
            UNIQUE(name, organization)
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

    ADD_COLUMN_TAG = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name='agent_card' AND column_name='tag') THEN
                ALTER TABLE agent_card ADD COLUMN tag JSONB DEFAULT '[]'::jsonb;
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

    GET_TAGS = """
        SELECT tag FROM agent_card
        WHERE name = %s AND organization = %s
    """

    UPDATE_TAGS = """
        UPDATE agent_card SET tag = tag || %s::jsonb, updated_at = %s
        WHERE name = %s AND organization = %s
    """

    DELETE_AGENT = """
        DELETE FROM agent_card WHERE name = %s AND organization = %s
    """

    COUNT = "SELECT COUNT(*) FROM agent_card"

    COUNT_BY_STATUS = "SELECT COUNT(*) FROM agent_card WHERE status = %s"

    GET_METADATA = """
        SELECT name, organization, status, tag FROM agent_card
        WHERE name = %s AND organization = %s
    """

    GET_ALL_METADATA = """
        SELECT name, organization, status, tag FROM agent_card
    """

    GET_CREATED_AT = """
        SELECT created_at FROM agent_card
        WHERE name = %s AND organization = %s
    """

    GET_UPDATED_AT = """
        SELECT updated_at FROM agent_card
        WHERE name = %s AND organization = %s
    """