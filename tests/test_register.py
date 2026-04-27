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

# tests/test_register.py
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
    # 创建一个缺少指定字段的测试数据
    invalid_data = valid_agent_data.copy()

    # 处理嵌套字段，如 provider.organization
    del invalid_data[field_to_remove]

    # 尝试注册缺少字段的 Agent
    response = client.post("/rest/a2a-t/v1/agents/register", json=invalid_data)

    # 验证返回状态码为 422（请求无效）
    assert response.status_code == 422

    # 验证错误信息中包含缺失字段
    error_detail = response.json()["detail"]
    assert any(f"Field required" in error["msg"] for error in error_detail)
