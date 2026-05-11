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

import pytest
from fastapi.testclient import TestClient
from a2a.types import AgentCard
from google.protobuf.json_format import Parse, MessageToJson

from agent_registry.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_registry(mocker):
    return mocker.patch('agent_registry.core.RegistryCore')


@pytest.fixture
def valid_agent_data():
    return {
        "name": "TestAgent",
        "provider": {
            "organization": "TestOrg",
            "url": "https://test.org"
        },
        "description": "Test Description",
        "capabilities": {
            "streaming": False,
            "push_notifications": False
        },
        "default_input_modes": ["text/plain"],
        "default_output_modes": ["text/plain"],
        "version": "1.0.0",
        "skills": [
            {
                "id": "skill-1",
                "name": "TestSkill",
                "description": "Test Skill Description",
                "tags": ["test", "skill"],
                "input_modes": ["text/plain"],
                "output_modes": ["text/plain"]
            }
        ]
    }


def test_register_agent_success(client, mock_registry, valid_agent_data):
    mock_registry.return_value.register.return_value = True
    response = client.post("/rest/a2a-t/v1/agents/register", json=valid_agent_data)
    assert response.status_code == 201
    assert response.json() is True


def test_register_agent_duplicate(client, mock_registry, valid_agent_data):
    mock_registry.return_value.register.return_value = False
    response = client.post("/rest/a2a-t/v1/agents/register", json=valid_agent_data)
    assert response.status_code == 201
    assert response.json() is False


@pytest.mark.parametrize("field_to_remove", [
    "name",
    "provider",
    "description",
    "capabilities",
    "default_input_modes",
    "default_output_modes",
    "url",
    "version",
    "skills"
])
def test_register_agent_missing_required_field(client, mock_registry, valid_agent_data, field_to_remove):
    # Create test data missing specified field
    invalid_data = valid_agent_data.copy()

    # Handle nested fields like provider.organization
    del invalid_data[field_to_remove]

    # Attempt to register Agent with missing field
    response = client.post("/rest/a2a-t/v1/agents/register", json=invalid_data)

    # Verify return status code is 422 (invalid request)
    assert response.status_code == 422

    # Verify error message contains missing field
    error_detail = response.json()["detail"]
    assert any(f"Field required" in error["msg"] for error in error_detail)