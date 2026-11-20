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

"""API-layer coverage tests for ``agent_registry/server.py``.

Every case runs the real FastAPI application against a real sqlite-backed
``RegistryCore``, a real event outbox and the real handler singletons, so the
assertions cover status code + response body + persisted side effect. No
external database, no network, no sleeps, no dependence on execution order:
each test builds its own registry file in ``tmp_path`` and every global it
touches (the ``config`` dict, the broadcast/health service singletons, handler
instances, signer cache) is restored by ``monkeypatch``/fixture teardown.

Case ids are ``TC-API-nnn``; each docstring carries input, expected output,
assertion points and the regression it prevents (see tests/TEST_DESIGN.md).
"""

import asyncio
import base64
import datetime
import json
import types

import pytest
from a2a.types import AgentCard
from fastapi import HTTPException
from fastapi.testclient import TestClient

import agent_registry.broadcast as broadcast_module
import agent_registry.broadcast.dispatcher as dispatcher_module
import agent_registry.core as core_module
import agent_registry.health as health_module
import common.custom.custom_handle as custom_handle_module
from agent_registry import server as server_module
from agent_registry.broadcast.event_bus import EventBus
from agent_registry.broadcast.events import EventType, build_event
from agent_registry.broadcast.outbox import MemoryOutbox, SqlOutbox
from agent_registry.broadcast.subscriptions import MemorySubscriptionStore, SqlSubscriptionStore
from agent_registry.core import RegistryCore
from agent_registry.errors import RegistryUnavailableError
from agent_registry.persistence.milvus_layer_migration import LayerMigrationRequiredError
from agent_registry.signature.agent_card_signature_validator import ValidationResult
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType

BASE = '/rest/v1/registry-center/agent-cards'
LAYER_BASE = '/rest/v1/registry-center/agent-cards-with-layer'
OPS_LOGS = '/rest/v1/registry-center/operation-logs'
JWKS = '/rest/v1/registry-center/keys'
SUBSCRIPTIONS = '/rest/v1/registry-center/subscriptions'
HEALTH_LIST = '/rest/v1/registry-center/agents/health'
CHANGES = '/rest/v1/registry-center/changes'
SIGNED_DESCRIPTION = 'card signed by the registry'
PUBLIC_JKU = 'https://registry.example.com/rest/keys'


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def card_body(name='alpha', org='org-a', description='alpha agent'):
    """A minimal valid AgentCard request body."""
    return {
        'name': name,
        'provider': {'organization': org, 'url': 'https://example.com/a'},
        'description': description,
        'version': '1.0.0',
        'capabilities': {'streaming': False},
        'default_input_modes': ['text/plain'],
        'default_output_modes': ['text/plain'],
        'skills': [],
    }


def make_card(name='alpha', org='org-a', description='alpha agent'):
    """The proto form of the same card, for direct core calls."""
    card = AgentCard(name=name, description=description, version='1.0.0',
                     provider={'organization': org, 'url': 'https://example.com/a'})
    card.default_input_modes.extend(['text/plain'])
    card.default_output_modes.extend(['text/plain'])
    return card


def write_signing_material(directory):
    """Generate a throwaway RSA key plus a matching self-signed certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'registry-sign')])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (x509.CertificateBuilder()
                   .subject_name(name).issuer_name(name)
                   .public_key(key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(days=1))
                   .not_valid_after(now + datetime.timedelta(days=1))
                   .sign(key, hashes.SHA256()))
    key_path = directory / 'sign_key.pem'
    cert_path = directory / 'sign.cer'
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return key_path, cert_path


class _OkValidator:
    """Signature validator whose verdict the case controls."""

    def __init__(self):
        self.result = ValidationResult(is_valid=True)
        self.seen = []

    async def validate_agent_card_async(self, agent):
        self.seen.append(agent.name)
        return self.result


class _RecordingSigner:
    """Registry signer stand-in: records calls and rewrites the description."""

    def __init__(self):
        self.enabled = False
        self.signed = []

    def is_enabled(self):
        return self.enabled

    def sign_agent_card(self, agent_card):
        self.signed.append(agent_card.name)
        signed = AgentCard()
        signed.CopyFrom(agent_card)
        signed.description = SIGNED_DESCRIPTION
        return signed


class _RecordingDispatcher:
    """Webhook dispatcher stand-in: keeps the subscription wiring observable."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.added = []
        self.removed = []

    def add_subscription(self, subscription):
        self.added.append(subscription.subscription_id)

    def remove_subscription(self, subscription_id):
        self.removed.append(subscription_id)


class _StubRequest:
    """Minimal Request stand-in for the cases that call handlers directly."""

    def __init__(self, method='GET', path='/rest/v1/registry-center/agents',
                 host='10.0.0.7', disconnected=False):
        self.method = method
        self.url = types.SimpleNamespace(path=path)
        self.client = types.SimpleNamespace(host=host)
        self._disconnected = disconnected

    async def is_disconnected(self):
        return self._disconnected


class _AsyncioShim:
    """Proxy for the asyncio module that overrides selected helpers.

    Only ``server_module``'s reference is replaced, so the real loop keeps
    working while an idle-timeout / closed-loop path becomes deterministic
    without a sleep.
    """

    def __init__(self, real_module, wait_for=None, get_running_loop=None):
        self._real = real_module
        self._wait_for = wait_for
        self._get_running_loop = get_running_loop

    def __getattr__(self, name):
        return getattr(self._real, name)

    def wait_for(self, awaitable, timeout=None):
        if self._wait_for is None:
            return self._real.wait_for(awaitable, timeout)
        return self._wait_for(awaitable, timeout)

    def get_running_loop(self):
        if self._get_running_loop is None:
            return self._real.get_running_loop()
        return self._get_running_loop()


class _StubSweeper:
    """Health sweeper stand-in recording construction and start/stop."""

    instances = []

    def __init__(self, health_service, registry, event_bus, **kwargs):
        self.health_service = health_service
        self.registry = registry
        self.event_bus = event_bus
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        _StubSweeper.instances.append(self)

    def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


class _StubService:
    """Broadcast service stand-in with an observable lifecycle."""

    def __init__(self, fail_start=False):
        self.fail_start = fail_start
        self.started = False
        self.stopped = False
        self.event_bus = types.SimpleNamespace()

    async def start(self):
        if self.fail_start:
            raise RuntimeError('broadcast start failed')
        self.started = True

    async def stop(self):
        self.stopped = True


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def registry(tmp_path):
    """A real sqlite-backed registry core living entirely in tmp_path."""
    core = RegistryCore(use_vectordb=False, persistence_mode='sqlite',
                        persistence_conf={'sqlite.path': str(tmp_path / 'registry.db')})
    try:
        yield core
    finally:
        core.close()


@pytest.fixture
def wire_bus(registry, monkeypatch):
    """Bind core event publishing to an outbox on the same storage."""
    bus = EventBus(SqlOutbox(registry.storage))
    monkeypatch.setattr(core_module, 'get_event_bus', lambda: bus)
    return bus


@pytest.fixture
def broadcast(monkeypatch):
    """Installable, isolated broadcast singleton (restored on teardown)."""
    original_service = broadcast_module._service
    broadcast_module.reset_for_tests()
    monkeypatch.setattr(dispatcher_module, 'WebhookDispatcher', _RecordingDispatcher)

    def install(enabled=False, outbox=None, subscription_store=None):
        service = broadcast_module.BroadcastService(
            outbox if outbox is not None else MemoryOutbox(),
            subscription_store if subscription_store is not None else MemorySubscriptionStore(),
            config={'broadcast.enabled': 'true' if enabled else 'false'},
        )
        broadcast_module._service = service
        return service

    try:
        yield install
    finally:
        broadcast_module._service = original_service


@pytest.fixture
def health(monkeypatch):
    """Installable, isolated health singleton (restored on teardown)."""
    original_service = health_module._service
    health_module.reset_for_tests()

    def install(interval=30, enabled='true', hide_unhealthy='false', failure_threshold=3):
        config = {
            'heartbeat.enabled': enabled,
            'heartbeat.interval': str(interval),
            'heartbeat.failure.threshold': str(failure_threshold),
            'heartbeat.grace.period': '10',
            'heartbeat.sweep.interval': '10',
            'heartbeat.offline.ttl': '0',
            'heartbeat.hide.unhealthy.results': hide_unhealthy,
        }
        return health_module.initialize_health_service(None, 'file', config=config)

    try:
        yield install
    finally:
        health_module._service = original_service


@pytest.fixture
def validator():
    return _OkValidator()


@pytest.fixture
def signer():
    return _RecordingSigner()


@pytest.fixture(autouse=True)
def isolated_handlers():
    """Default handler singletons per test; the previous set is restored."""
    snapshot = dict(HandlerRegistry._instances)
    for interface in InterfaceType:
        HandlerRegistry._instances.pop(interface.value, None)
    try:
        yield
    finally:
        HandlerRegistry._instances.clear()
        HandlerRegistry._instances.update(snapshot)


@pytest.fixture
def client(tmp_path, registry, wire_bus, broadcast, validator, signer, monkeypatch):
    """TestClient over the real app, wired to the tmp_path registry."""
    broadcast(enabled=False, outbox=SqlOutbox(registry.storage),
              subscription_store=SqlSubscriptionStore(registry.storage))
    monkeypatch.setattr(custom_handle_module, 'get_registry', lambda: registry)
    monkeypatch.setattr(server_module, 'OWNER_ISOLATION_ENABLED', False)
    monkeypatch.setattr(server_module, 'config', dict(server_module.config))
    server_module.config['file.path'] = str(tmp_path / 'agentcard.json')
    server_module.config['agent_approval_enabled'] = 'false'

    overrides = {
        server_module.get_registry: lambda: registry,
        server_module.get_signature_validator: lambda: validator,
        server_module.get_registry_signer: lambda: signer,
    }
    server_module.app.dependency_overrides.update(overrides)
    try:
        yield TestClient(server_module.app)
    finally:
        for dependency in overrides:
            server_module.app.dependency_overrides.pop(dependency, None)


# ==========================================================================
# Registration
# ==========================================================================

def test_register_rejected_when_agent_limit_reached(client, registry, monkeypatch):
    """TC-API-001 | Registration cap is enforced before anything is written

    输入: POST /agent-cards with one valid card, config agent.num.max = 0
    预期输出: 409；errorMessage = "Agent registration limit exceeded."
    断言点: 状态码 + 错误消息原文 + 存储里没有任何卡片（count()==0）
    防回归: 若上限检查被删除或改成 > 比较，注册会成功并返回 201
    """
    monkeypatch.setitem(server_module.config, 'agent.num.max', '0')

    response = client.post(BASE, json={'agentCards': [card_body()]})

    assert response.status_code == 409
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'Agent registration limit exceeded.'
    assert registry.count() == 0


def test_register_non_object_item_reports_card_index(client, registry):
    """TC-API-002 | A malformed batch entry is reported with its 1-based index

    输入: POST /agent-cards {"agentCards": [false]}
    预期输出: 422；errorMessage = "Card 1/1: Each agentCards entry must be an object"；
              registeredAgents = []
    断言点: 状态码 + 卡片序号与原因 + 部分成功列表为空 + 未写入存储
    防回归: 若序号丢失或错误被吞成 500，定位批次坏卡片的能力消失
    """
    response = client.post(BASE, json={'agentCards': [False]})

    assert response.status_code == 422
    body = response.json()
    assert body['errors']['error'][0]['errorMessage'] == \
        'Card 1/1: Each agentCards entry must be an object'
    assert body['registeredAgents'] == []
    assert registry.count() == 0


def test_register_falsy_insert_result_is_conflict(client, registry):
    """TC-API-003 | A refused insert is reported as 409, never as 201

    输入: INSERT handler returns False (storage refused the write)
    预期输出: 409；errorMessage = "Agent 'alpha' already exists in organization 'org-a'"
    断言点: 状态码 + 消息中的 name/organization + 存储里没有该卡片
    防回归: 若 `if not result` 分支被删，丢失的写入会被报告为注册成功
    """
    class _RefusingInsert:
        async def handle(self, *args, **kwargs):
            return False

    HandlerRegistry._instances[InterfaceType.INSERT.value] = _RefusingInsert()

    response = client.post(BASE, json={'agentCards': [card_body()]})

    assert response.status_code == 409
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        "Agent 'alpha' already exists in organization 'org-a'"
    assert registry.get_status('alpha', 'org-a') is None


def test_register_invalid_signature_is_401_and_not_stored(client, registry, validator):
    """TC-API-004 | A card failing signature verification is rejected with 401

    输入: validator returns is_valid=False, error_message="signature mismatch"
    预期输出: 401；errorMessage 含卡片序号、名称与校验器消息
    断言点: 状态码 + 消息三段内容 + 存储无记录
    防回归: 若签名校验结果被忽略，未签名/伪签名卡片会被注册
    """
    validator.result = ValidationResult(is_valid=False, error_message='signature mismatch')

    response = client.post(BASE, json={'agentCards': [card_body()]})

    assert response.status_code == 401
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'Card 1/1 (alpha): signature mismatch'
    assert registry.get_status('alpha', 'org-a') is None


def test_register_applies_registry_signature_before_persisting(client, registry, signer):
    """TC-API-005 | A signing registry stores the signed card, not the submitted one

    输入: registry signer enabled; it returns a copy with description rewritten
    预期输出: 201 且 registrySigned = true；GET 到 description = 签名后的值
    断言点: 状态码 + registrySigned + 签名器被调用一次 + 持久化内容为签名结果
    防回归: 若 sign_agent_card 的返回值被丢弃，存储里仍是提交时的原始描述
    """
    signer.enabled = True

    response = client.post(BASE, json={'agentCards': [card_body()]})

    assert response.status_code == 201
    assert response.json()['results'] == [{
        'name': 'alpha', 'organization': 'org-a',
        'status': 'published', 'registrySigned': True,
    }]
    assert signer.signed == ['alpha']
    fetched = client.get(f'{BASE}/org-a/alpha').json()['agentCards']
    assert [card['description'] for card in fetched] == [SIGNED_DESCRIPTION]
    stored = registry.get_by_key('alpha', 'org-a')
    assert stored.description == SIGNED_DESCRIPTION


def test_register_with_approval_enabled_starts_pending(client, registry, monkeypatch):
    """TC-API-006 | Approval mode registers a card as pending, not published

    输入: config agent_approval_enabled = true, one valid card
    预期输出: 201 且 results[0].status = "registered"；评审状态为 registered；
              发现列表看不到该卡片
    断言点: 响应状态字段 + GET review-status + GET /agent-cards 为空
    防回归: 若初始状态写死为 published，审批流程会被绕过
    """
    monkeypatch.setitem(server_module.config, 'agent_approval_enabled', 'true')

    response = client.post(BASE, json={'agentCards': [card_body()]})

    assert response.status_code == 201
    assert response.json()['results'][0]['status'] == 'registered'
    review = client.get(f'{BASE}/org-a/alpha/review-status').json()
    assert review['status'] == 'registered'
    assert client.get(f'{BASE}/org-a/alpha').json() == {'agentCards': []}


# ==========================================================================
# Update
# ==========================================================================

def test_update_wrapped_item_persists_layer(client, registry):
    """TC-API-007 | Layer-aware update stores the layer and echoes it back

    输入: PUT with {"agentCards": [{"agentCard": {...}, "layer": "ServiceLayer"}]}
    预期输出: 200 且 results[0].layer = "ServiceLayer"；
              GET /agent-cards-with-layer/org-a/alpha 返回同样 layer
    断言点: 状态码 + 结果 layer + 读回 registration 元数据 + 存储记录 layer
    防回归: 若 update 丢掉 layer 参数，层信息被静默重置为 unknown
    """
    assert client.post(BASE, json={'agentCards': [card_body()]}).status_code == 201

    response = client.put(f'{BASE}/org-a/alpha', json={
        'agentCards': [{'agentCard': card_body(description='updated alpha'),
                        'layer': 'ServiceLayer'}],
    })

    assert response.status_code == 200
    assert response.json()['results'] == [{
        'name': 'alpha', 'organization': 'org-a',
        'registrySigned': False, 'layer': 'ServiceLayer',
    }]
    stored = client.get(f'{LAYER_BASE}/org-a/alpha').json()
    assert stored['layer'] == 'ServiceLayer'
    assert stored['agentCard']['description'] == 'updated alpha'
    assert registry.get_by_key_with_owner('alpha', 'org-a').layer == 'ServiceLayer'


def test_update_validation_failure_is_422_and_keeps_old_card(client, registry):
    """TC-API-008 | A card failing field validation is rejected, old content kept

    输入: PUT with description containing U+200B (dangerous character)
    预期输出: 422；errorMessage = "Card 1/1 (alpha): Agent description contains
              invalid or dangerous characters."
    断言点: 状态码 + 消息原文 + 读回的 description 仍是旧值
    防回归: 若 update 跳过 validate_agent_card，隐藏字符会被写进已发布卡片
    """
    assert client.post(BASE, json={'agentCards': [card_body()]}).status_code == 201

    response = client.put(f'{BASE}/org-a/alpha',
                          json={'agentCards': [card_body(description='bad\u200bvalue')]})

    assert response.status_code == 422
    assert response.json()['errors']['error'][0]['errorMessage'] == (
        'Card 1/1 (alpha): Agent description contains invalid or dangerous characters.')
    assert registry.get_by_key('alpha', 'org-a').description == 'alpha agent'


def test_update_invalid_signature_is_401_and_keeps_old_card(client, registry, validator):
    """TC-API-009 | Update rejects a card whose signature does not verify

    输入: validator returns is_valid=False, error_message="bad signature"
    预期输出: 401；errorMessage = "Card 1/1 (alpha): bad signature"
    断言点: 状态码 + 消息 + 旧描述未被覆盖
    防回归: 若 update 路径忘记校验签名，等于开放了无条件覆盖接口
    """
    assert client.post(BASE, json={'agentCards': [card_body()]}).status_code == 201
    validator.result = ValidationResult(is_valid=False, error_message='bad signature')

    response = client.put(f'{BASE}/org-a/alpha',
                          json={'agentCards': [card_body(description='hijacked')]})

    assert response.status_code == 401
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'Card 1/1 (alpha): bad signature'
    assert registry.get_by_key('alpha', 'org-a').description == 'alpha agent'


def test_update_applies_registry_signature(client, registry, signer):
    """TC-API-010 | Update signs the replacement card before storing it

    输入: PUT on an existing card with registry signer enabled
    预期输出: 200 且 registrySigned = true；读回描述为签名版本
    断言点: 状态码 + registrySigned + 签名器调用记录 + 持久化内容
    防回归: 若签名结果未用于写库，更新后的卡片会退化为未签名版本
    """
    assert client.post(BASE, json={'agentCards': [card_body()]}).status_code == 201
    signer.enabled = True

    response = client.put(f'{BASE}/org-a/alpha',
                          json={'agentCards': [card_body(description='v2')]})

    assert response.status_code == 200
    assert response.json()['results'][0]['registrySigned'] is True
    assert signer.signed == ['alpha']
    assert registry.get_by_key('alpha', 'org-a').description == SIGNED_DESCRIPTION


# ==========================================================================
# Deregister / exact get
# ==========================================================================

def test_deregister_removes_card_everywhere(client, registry):
    """TC-API-011 | DELETE removes the record and the card disappears everywhere

    输入: registered card alpha/org-a, DELETE /agent-cards/org-a/alpha
    预期输出: 200 {"name":"alpha","organization":"org-a","deleted":true}；
              再次 GET 返回空列表；管理列表不含该卡片
    断言点: 状态码 + 响应体 + 读回为空 + manage 列表为空 + 存储无记录
    防回归: 若删除只作用于缓存/索引而没删记录，卡片会“复活”
    """
    assert client.post(BASE, json={'agentCards': [card_body()]}).status_code == 201

    response = client.delete(f'{BASE}/org-a/alpha')

    assert response.status_code == 200
    assert response.json() == {'name': 'alpha', 'organization': 'org-a', 'deleted': True}
    assert client.get(f'{BASE}/org-a/alpha').json() == {'agentCards': []}
    assert client.get(f'{BASE}/manage').json()['agentCards'] == []
    assert registry.get_status('alpha', 'org-a') is None


def test_deregister_missing_card_with_owner_isolation_is_404(client, monkeypatch):
    """TC-API-012 | Owner guard answers 404 for a card that does not exist

    输入: owner isolation enabled, DELETE /agent-cards/org-a/ghost
    预期输出: 404；errorMessage = "Agent (ghost, org-a) not found"
    断言点: 状态码 + 消息含 name 与 organization
    防回归: 若 404 被换成 403/200，客户端无法区分“不存在”和“无权限”
    """
    monkeypatch.setattr(server_module, 'OWNER_ISOLATION_ENABLED', True)

    response = client.delete(f'{BASE}/org-a/ghost')

    assert response.status_code == 404
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'Agent (ghost, org-a) not found'


def test_get_single_card_returns_exact_card(client):
    """TC-API-013 | Exact get returns the stored card only

    输入: two cards in different orgs, GET /agent-cards/org-a/alpha
    预期输出: 200 且只返回 alpha/org-a 一张卡
    断言点: 状态码 + 列表长度 + name/provider.organization
    防回归: 若精确查询退化为前缀/模糊匹配，会出现越权/串数据
    """
    client.post(BASE, json={'agentCards': [card_body(), card_body('beta', 'org-b')]})

    response = client.get(f'{BASE}/org-a/alpha')

    assert response.status_code == 200
    body = response.json()
    assert len(body['agentCards']) == 1
    assert body['agentCards'][0]['name'] == 'alpha'
    assert body['agentCards'][0]['provider']['organization'] == 'org-a'


# ==========================================================================
# Listing / management
# ==========================================================================

def test_list_rejects_invalid_layer(client):
    """TC-API-014 | An unparsable layer query is a client error

    输入: GET /agent-cards?layer=<65 chars>
    预期输出: 422；errorMessage = "layer must not exceed 64 characters"
    断言点: 状态码 + 消息原文
    防回归: 若层参数未校验，超长值会被当作过滤条件静默返回空集
    """
    response = client.get(BASE, params={'layer': 'x' * 65})

    assert response.status_code == 422
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'layer must not exceed 64 characters'


def test_list_layer_query_migration_required_is_503(client, registry, monkeypatch):
    """TC-API-015 | A layer query on an unmigrated index reports 503, not 500

    输入: registry.find_exact raises LayerMigrationRequiredError
    预期输出: 503；errorMessage 携带原始迁移提示
    断言点: 状态码 + 消息 + 未返回 agentCards 字段
    防回归: 若异常落进通用处理器，运维会看到 500 而非可操作的迁移指引
    """
    def _raise(*args, **kwargs):
        raise LayerMigrationRequiredError('reindex required')

    monkeypatch.setattr(registry, 'find_exact', _raise)

    response = client.get(BASE, params={'layer': 'ServiceLayer'})

    assert response.status_code == 503
    assert response.json()['errors']['error'][0]['errorMessage'] == 'reindex required'
    assert 'agentCards' not in response.json()


def test_manage_list_drops_record_deleted_after_query(client, registry, monkeypatch):
    """TC-API-016 | A card removed mid-flight must not be listed as published

    输入: QUERY returns one card but get_by_key_with_owner returns None
    预期输出: 200 {"agentCards": [], "statusCounts": {}}
    断言点: 卡片列表为空 + 计数为空
    防回归: 若缺失记录被当作 published，删除后的卡片会在管理台“复活”
    """
    assert client.post(BASE, json={'agentCards': [card_body()]}).status_code == 201
    monkeypatch.setattr(registry, 'get_by_key_with_owner', lambda *a, **k: None)

    response = client.get(f'{BASE}/manage')

    assert response.status_code == 200
    assert response.json() == {'agentCards': [], 'statusCounts': {}}


def test_manage_list_counts_and_filters_status(client, registry):
    """TC-API-017 | Manage list exposes publishStatus and per-state counts

    输入: one published card + one pending card, then ?status=pending_review
    预期输出: 未过滤时 statusCounts = {published:1, registered:1}；
              过滤后只返回 pending 卡片，计数仍是全量
    断言点: 卡片名集合 + publishStatus + statusCounts 数值
    防回归: 若计数被过滤条件影响，评审队列的徽章数字会随筛选漂移
    """
    client.post(BASE, json={'agentCards': [card_body('live', 'org-a')]})
    registry.register_with_status(make_card('pending', 'org-a'),
                                  initial_status='registered')

    everything = client.get(f'{BASE}/manage').json()
    assert everything['statusCounts'] == {'published': 1, 'registered': 1}

    filtered = client.get(f'{BASE}/manage', params={'status': 'pending_review'}).json()
    assert [entry['name'] for entry in filtered['agentCards']] == ['pending']
    assert filtered['agentCards'][0]['publishStatus'] == 'registered'
    assert filtered['statusCounts'] == {'published': 1, 'registered': 1}


# ==========================================================================
# Review transitions / operation log
# ==========================================================================

def test_publish_with_malformed_body_requires_remark(client, registry):
    """TC-API-018 | A non-JSON review body is treated as “no remark”, not as a 500

    输入: POST /agent-cards/org-a/alpha/publish with body "not-json"
    预期输出: 400；errorMessage = "Review remark is required"
    断言点: 状态码 + 消息 + 卡片状态仍为 registered
    防回归: 若 body 解析异常直接冒泡，审计要求的备注会被跳过
    """
    registry.register_with_status(make_card(), initial_status='registered')

    response = client.post(f'{BASE}/org-a/alpha/publish', content=b'not-json',
                           headers={'content-type': 'application/json'})

    assert response.status_code == 400
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'Review remark is required'
    assert registry.get_status('alpha', 'org-a') == 'registered'


def test_publish_reports_500_when_status_write_refused(client, registry, monkeypatch):
    """TC-API-019 | A refused status transition is a server error, not a success

    输入: core.update_status returns False
    预期输出: 500；errorMessage = "Failed to update agent status"
    断言点: 状态码 + 消息 + 未写操作日志
    防回归: 若 `if not ok` 被删，失败的状态变更会被报告为成功
    """
    registry.register_with_status(make_card(), initial_status='registered')
    monkeypatch.setattr(registry, 'update_status', lambda *a, **k: False)

    response = client.post(f'{BASE}/org-a/alpha/publish', json={'remark': 'ok'})

    assert response.status_code == 500
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'Failed to update agent status'
    assert server_module._read_operation_logs() == []


def test_publish_is_recorded_in_operation_log(client, registry):
    """TC-API-020 | Every approved transition is appended to the operation log

    输入: POST publish with remark "schema reviewed"; then GET /operation-logs
    预期输出: 200；日志中恰好一条 publish_review 记录，含 from/to/remark
    断言点: 状态码 + 条目字段值 + 卡片状态已变为 published
    防回归: 若 _append_operation_log 被跳过，审批行为无法追溯
    """
    registry.register_with_status(make_card(), initial_status='registered')

    transition = client.post(f'{BASE}/org-a/alpha/publish',
                             json={'remark': 'schema reviewed'})
    assert transition.status_code == 200
    assert transition.json() == {'status': 'success', 'publishStatus': 'published'}

    response = client.get(OPS_LOGS)

    assert response.status_code == 200
    entries = response.json()['operationLogs']
    assert len(entries) == 1
    entry = entries[0]
    assert entry['action'] == 'publish_review'
    assert entry['agent_name'] == 'alpha'
    assert entry['organization'] == 'org-a'
    assert entry['from_status'] == 'registered'
    assert entry['to_status'] == 'published'
    assert entry['remark'] == 'schema reviewed'
    assert entry['timestamp']
    assert registry.get_status('alpha', 'org-a') == 'published'


def test_operation_log_reader_skips_blank_and_corrupt_lines(tmp_path, monkeypatch):
    """TC-API-021 | Log reader tolerates blank/corrupt lines and honours limit

    输入: log file with 2 valid lines, one blank line and one corrupt line
    预期输出: limit=1 时返回最后一条可解析记录；默认返回两条有效记录
    断言点: 两次返回的完整内容 + 无异常
    防回归: 若解析错误直接抛出，一条坏行会让整个审计页面 500
    """
    log_path = tmp_path / 'operation_log.jsonl'
    log_path.write_text(
        json.dumps({'action': 'first', 'operator': 'op'}) + '\n'
        '\n'
        '{not json\n'
        + json.dumps({'action': 'second', 'operator': 'op'}) + '\n',
        encoding='utf-8')
    monkeypatch.setitem(server_module.config, 'file.path', str(tmp_path / 'agentcard.json'))

    assert server_module._read_operation_logs(limit=1) == [
        {'action': 'second', 'operator': 'op'}]
    assert [entry['action'] for entry in server_module._read_operation_logs()] == \
        ['first', 'second']


def test_operation_log_writer_survives_unwritable_path(tmp_path, monkeypatch):
    """TC-API-022 | A failing operation-log write never breaks the request

    输入: config file.path pointing below a regular file (mkdir must fail)
    预期输出: _append_operation_log 正常返回，不抛异常；日志文件不存在
    断言点: 无异常 + 读回列表为空
    防回归: 若写日志异常冒泡，磁盘只读会让审批接口整体 500
    """
    blocker = tmp_path / 'blocker'
    blocker.write_text('x', encoding='utf-8')
    monkeypatch.setitem(server_module.config, 'file.path',
                        str(blocker / 'nested' / 'agentcard.json'))

    assert server_module._append_operation_log('publish_review', '10.0.0.1',
                                               {'agent_name': 'alpha'}) is None
    assert server_module._read_operation_logs() == []


# ==========================================================================
# Layer-aware endpoints
# ==========================================================================

@pytest.mark.parametrize('body, expected', [
    ({'layer': None}, 'layer cannot be null'),
    ({'layer': 'y' * 65}, 'layer must not exceed 64 characters'),
    ({'task': None}, 'task cannot be null'),
    ({'task': 7}, 'task must be a string'),
    ({'topN': True, 'task': 'x'}, 'topN must be an integer'),
    ({'topN': 0, 'task': 'x'}, 'topN must be between 1 and 50'),
    ({'limit': '3'}, 'limit must be an integer'),
    ({'limit': 0}, 'limit must be between 1 and 1000'),
    ({'offset': -1}, 'offset must be between 0 and 2147483647'),
])
def test_layer_collection_rejects_invalid_bodies(client, body, expected):
    """TC-API-023 | Layer query body validation rejects every malformed shape

    输入: POST /agent-cards-with-layer with the parametrized body
    预期输出: 422 且 errorMessage 等于 parametrized 文案
    断言点: 状态码 + 精确消息（区分字段与越界原因）
    防回归: 若某个字段校验被删，非法值会被静默当成默认值执行查询
    """
    response = client.post(LAYER_BASE, json=body)

    assert response.status_code == 422
    assert response.json()['errors']['error'][0]['errorMessage'] == expected


def test_layer_collection_rejects_semantic_body(client):
    """TC-API-024 | The collection endpoint refuses task-based queries

    输入: POST /agent-cards-with-layer {"task": "find agents"}
    预期输出: 422；errorMessage = "use the /semantic-query endpoint ..."
    断言点: 状态码 + 消息原文
    防回归: 若两个端点共用语义判断而不区分路径，语义查询会落到分页接口
    """
    response = client.post(LAYER_BASE, json={'task': 'find agents'})

    assert response.status_code == 422
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'use the /semantic-query endpoint for task-based queries'


def test_layer_semantic_endpoint_requires_task(client):
    """TC-API-025 | The semantic endpoint refuses a body without a task

    输入: POST /agent-cards-with-layer/semantic-query {}
    预期输出: 422；errorMessage = "task is required for semantic queries"
    断言点: 状态码 + 消息原文
    防回归: 若缺少 task 时回退到普通查询，调用方会拿到全量卡片
    """
    response = client.post(f'{LAYER_BASE}/semantic-query', json={})

    assert response.status_code == 422
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'task is required for semantic queries'


def test_layer_collection_paginates_with_has_more(client):
    """TC-API-026 | Layer collection pagination reports count and hasMore correctly

    输入: 3 published cards; (limit=2, offset=0) then (limit=2, offset=2)
    预期输出: 第一页 2 条 + hasMore true；第二页 1 条 + hasMore false
    断言点: 两页的 name 列表 + count + hasMore + 每张卡的 layer 字段
    防回归: 若 hasMore 恒为 false（或取反），客户端会漏页或空转
    """
    for name in ('alpha', 'beta', 'gamma'):
        response = client.post(BASE, json={'agentCards': [
            {'agentCard': card_body(name, 'org-a'), 'layer': 'ServiceLayer'}]})
        assert response.status_code == 201

    first = client.post(LAYER_BASE, json={'layer': 'ServiceLayer', 'limit': 2})
    second = client.post(LAYER_BASE, json={'layer': 'ServiceLayer', 'limit': 2, 'offset': 2})

    assert first.status_code == 200
    assert [entry['agentCard']['name'] for entry in first.json()['agents']] == \
        ['alpha', 'beta']
    assert first.json()['count'] == 2
    assert first.json()['hasMore'] is True
    assert second.json()['count'] == 1
    assert [entry['agentCard']['name'] for entry in second.json()['agents']] == ['gamma']
    assert second.json()['hasMore'] is False
    assert {entry['layer'] for entry in first.json()['agents']} == {'ServiceLayer'}


def test_layer_collection_hides_pending_cards(client, registry):
    """TC-API-027 | The layer collection never serves a pending card

    输入: one published card + one registered (pending) card
    预期输出: 只返回 published 卡片，count = 1
    断言点: name 列表 + count
    防回归: 若可见性过滤被移除，未审批卡片会出现在公开查询里
    """
    client.post(BASE, json={'agentCards': [card_body('live', 'org-a')]})
    registry.register_with_status(make_card('pending', 'org-a'), initial_status='registered')

    response = client.post(LAYER_BASE, json={})

    assert response.status_code == 200
    assert [entry['agentCard']['name'] for entry in response.json()['agents']] == ['live']
    assert response.json()['count'] == 1


def test_hidden_unhealthy_filter_removes_discoverable_card(monkeypatch):
    """TC-API-028 | Unhealthy cards are filtered out of layer query results

    输入: _published_healthy_records with a published record whose health is
          hidden by the health service
    预期输出: 空列表
    断言点: 返回值为 []（卡片确实被丢弃，而不是仅被排序）
    防回归: 若健康过滤只作用于列表接口，层查询会继续返回已下线卡片
    """
    from agent_registry.persistence.base import AgentRecord

    monkeypatch.setattr(server_module, '_is_hidden_unhealthy', lambda name, org: True)
    records = [AgentRecord(agent_card=make_card(), status='published')]

    assert server_module._published_healthy_records(records) == []


def test_health_lookup_failure_keeps_card_visible(monkeypatch):
    """TC-API-029 | A broken health subsystem must not hide every card

    输入: get_health_service raises RuntimeError
    预期输出: _is_hidden_unhealthy returns False
    断言点: 返回值 False
    防回归: 若异常未兜底，一次健康服务故障会让整个发现面返回空
    """
    def _boom():
        raise RuntimeError('health store unavailable')

    monkeypatch.setattr(server_module, 'get_health_service', _boom)

    assert server_module._is_hidden_unhealthy('alpha', 'org-a') is False


# ==========================================================================
# Semantic retrieve
# ==========================================================================

@pytest.mark.parametrize('body, expected', [
    ({'task': 'x', 'layer': 'z' * 65}, 'layer must not exceed 64 characters'),
    ({'layer': None}, 'layer cannot be null'),
    ({'layer': 'ServiceLayer'}, 'task must be a non-empty string for semantic queries'),
])
def test_semantic_query_rejects_invalid_layer_and_missing_task(client, body, expected):
    """TC-API-030 | Semantic query body validation covers layer and task

    输入: POST /agent-cards/semantic-query with the parametrized body
    预期输出: 422 且 errorMessage 等于 parametrized 文案
    断言点: 状态码 + 精确消息
    防回归: 若某分支被删，语义端点会以空 task 触发模型调用
    """
    response = client.post(f'{BASE}/semantic-query', json=body)

    assert response.status_code == 422
    assert response.json()['errors']['error'][0]['errorMessage'] == expected


def test_semantic_query_migration_required_is_503(client, registry, monkeypatch):
    """TC-API-031 | A layer-scoped semantic query reports an unmigrated index as 503

    输入: registry.retrieve_by_task raises LayerMigrationRequiredError
    预期输出: 503；errorMessage = "reindex required"
    断言点: 状态码 + 消息 + 响应里没有 agentCards
    防回归: 若迁移异常被当 500，索引重建指引会丢失
    """
    def _raise(*args, **kwargs):
        raise LayerMigrationRequiredError('reindex required')

    monkeypatch.setattr(registry, 'retrieve_by_task', _raise)

    response = client.post(f'{BASE}/semantic-query',
                           json={'task': 'diagnostics', 'layer': 'ServiceLayer'})

    assert response.status_code == 503
    assert response.json()['errors']['error'][0]['errorMessage'] == 'reindex required'
    assert 'agentCards' not in response.json()


# ==========================================================================
# Heartbeat / health
# ==========================================================================

def test_health_list_rejects_unknown_status_filter(client, health):
    """TC-API-032 | The health overview validates its status filter

    输入: GET /agents/health?status=zombie
    预期输出: 400；errorMessage = "Invalid status filter 'zombie'"
    断言点: 状态码 + 消息原文
    防回归: 若过滤值不校验，非法参数会静默返回空监控面板
    """
    health()

    response = client.get(HEALTH_LIST, params={'status': 'zombie'})

    assert response.status_code == 400
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        "Invalid status filter 'zombie'"


def test_health_list_only_reports_public_agents(client, health):
    """TC-API-033 | Health overview hides agents that are not published

    输入: heartbeat for the published card alpha and for the unknown card ghost
    预期输出: 只列出 alpha；config 中带 interval/threshold
    断言点: name 列表 + health_status + config 数值
    防回归: 若监控列表不做可见性过滤，未审批/已删除卡片的心跳会泄露
    """
    client.post(BASE, json={'agentCards': [card_body('alpha', 'org-a')]})
    service = health(interval=45)
    service.record_heartbeat('alpha', 'org-a')
    service.record_heartbeat('ghost', 'org-a')

    response = client.get(HEALTH_LIST, params={'status': 'healthy'})

    assert response.status_code == 200
    body = response.json()
    assert [entry['name'] for entry in body['agents']] == ['alpha']
    assert body['agents'][0]['organization'] == 'org-a'
    assert body['agents'][0]['health_status'] == 'healthy'
    assert body['config']['interval'] == 45
    assert body['config']['failure_threshold'] == 3


def test_heartbeat_reports_enabled_config_and_status(client, health):
    """TC-API-034 | A heartbeat returns the effective detection configuration

    输入: heartbeat enabled with interval 45, POST heartbeat for a published card
    预期输出: 200；heartbeat_enabled true，interval 45，health_status healthy
    断言点: 三个字段值 + 服务端时间存在 + 存储中健康状态为 healthy
    防回归: 若响应配置与实际阈值脱节，客户端会按错误周期上报
    """
    client.post(BASE, json={'agentCards': [card_body('alpha', 'org-a')]})
    service = health(interval=45)

    response = client.post(f'{BASE}/org-a/alpha/heartbeat')

    assert response.status_code == 200
    body = response.json()
    assert body['heartbeat_enabled'] is True
    assert body['interval'] == 45
    assert body['health_status'] == 'healthy'
    assert body['server_time']
    assert service.status_of('alpha', 'org-a') == 'healthy'


def test_hidden_unhealthy_card_leaves_discovery_only(client, health):
    """TC-API-035 | A suspect card disappears from discovery but stays monitored

    输入: heartbeat enabled with hide.unhealthy.results; alpha marked suspect
    预期输出: GET /agent-cards/org-a/alpha 返回空列表；健康接口仍能看到 alpha
    断言点: 发现接口为空 + 监控列表状态为 suspect
    防回归: 若隐藏只作用于列表接口，精确查询会继续返回故障卡片
    """
    from agent_registry.health.state import HealthStatus

    client.post(BASE, json={'agentCards': [card_body('alpha', 'org-a')]})
    service = health(hide_unhealthy='true')
    service.record_heartbeat('alpha', 'org-a')
    service.update_status('alpha', 'org-a', HealthStatus.SUSPECT,
                          datetime.datetime.now(datetime.timezone.utc))

    assert client.get(f'{BASE}/org-a/alpha').json() == {'agentCards': []}
    monitored = client.get(HEALTH_LIST).json()
    assert [entry['name'] for entry in monitored['agents']] == ['alpha']
    assert monitored['agents'][0]['health_status'] == 'suspect'


# ==========================================================================
# SSE health stream
# ==========================================================================

@pytest.mark.asyncio
async def test_health_stream_delivers_only_health_events(registry, health, broadcast,
                                                        wire_bus):
    """TC-API-036 | SSE health stream forwards health changes only

    输入: 已发布卡片 alpha；先发布 AGENT_REGISTERED，再发布
          AGENT_HEALTH_CHANGED(alpha)，然后客户端断开
    预期输出: 首帧 ": connected\\n\\n"；注册事件不产生帧；健康事件产生
              "event: health_changed" 帧；断开后生成器结束
    断言点: 三帧原文 + data 中的 name + 结束后监听器被摘除
    防回归: 若监听器不过滤类型，注册/更新流量会全部推给健康流
    """
    service = health()
    broadcast(enabled=False)
    request = _StubRequest(path='/rest/v1/registry-center/agents/health/stream')

    registry.register(make_card('alpha', 'org-a'))
    response = await server_module.stream_agent_health(
        request=request, registry=registry, _=True)
    stream = response.body_iterator

    assert await stream.__anext__() == ': connected\n\n'

    bus = broadcast_module._service.event_bus
    bus.publish(EventType.AGENT_REGISTERED, {'name': 'alpha', 'organization': 'org-a'})
    await asyncio.sleep(0)  # let the loop run the queued listener callback
    bus.publish(EventType.AGENT_HEALTH_CHANGED, {'name': 'alpha', 'organization': 'org-a'})
    await asyncio.sleep(0)

    frame = await stream.__anext__()
    assert frame.startswith('event: health_changed\ndata: ')
    payload = json.loads(frame.split('data: ', 1)[1])
    assert payload['event_type'] == 'AGENT_HEALTH_CHANGED'
    assert payload['data']['name'] == 'alpha'

    request._disconnected = True
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
    assert bus._listeners == []
    assert service.enabled is True


@pytest.mark.asyncio
async def test_health_stream_pings_when_idle(registry, health, broadcast, wire_bus,
                                             monkeypatch):
    """TC-API-037 | An idle SSE stream emits keep-alive pings

    输入: 队列空；wait_for 立即超时（模拟 15s 无事件）
    预期输出: 首帧 ": connected\\n\\n"，随后 ": ping\\n\\n"
    断言点: 两帧原文
    防回归: 若 ping 分支被删，中间代理会因长时间静默掐断健康流
    """
    health()
    broadcast(enabled=False)
    request = _StubRequest(path='/rest/v1/registry-center/agents/health/stream')

    async def _timeout(awaitable, timeout=None):
        awaitable.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(server_module, 'asyncio',
                        _AsyncioShim(asyncio, _timeout))
    response = await server_module.stream_agent_health(
        request=request, registry=registry, _=True)
    stream = response.body_iterator

    assert await stream.__anext__() == ': connected\n\n'
    assert await stream.__anext__() == ': ping\n\n'

    request._disconnected = True
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()


# ==========================================================================
# Subscriptions / change feed
# ==========================================================================

def test_create_subscription_disabled_is_503(client, broadcast):
    """TC-API-038 | Creating a subscription on a disabled deployment is 503

    输入: broadcast.enabled = false, POST /subscriptions with a valid body
    预期输出: 503；errorMessage = "Change broadcast is disabled"
    断言点: 状态码 + 消息原文
    防回归: 若开关未生效，未部署 dispatcher 的实例会写入永不投递的订阅
    """
    broadcast(enabled=False)

    response = client.post(SUBSCRIPTIONS,
                           json={'callback_url': 'https://hooks.example.com/cb'})

    assert response.status_code == 503
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'Change broadcast is disabled'


def test_list_and_delete_subscription_disabled_are_503(client, broadcast):
    """TC-API-039 | Listing/deleting subscriptions obeys the same kill switch

    输入: broadcast.enabled = false; GET /subscriptions; DELETE /subscriptions/x
    预期输出: 两个请求都返回 503 与同一句消息
    断言点: 两个状态码 + 两条消息
    防回归: 若开关只在创建时检查，关闭广播后仍可枚举/删除订阅
    """
    broadcast(enabled=False)

    listed = client.get(SUBSCRIPTIONS)
    deleted = client.delete(f'{SUBSCRIPTIONS}/sub_x')

    assert listed.status_code == 503
    assert listed.json()['errors']['error'][0]['errorMessage'] == \
        'Change broadcast is disabled'
    assert deleted.status_code == 503
    assert deleted.json()['errors']['error'][0]['errorMessage'] == \
        'Change broadcast is disabled'


@pytest.mark.parametrize('body, expected', [
    ({'event_types': ['AGENT_CREATED']}, 'callback_url is required'),
    ({'callback_url': 'https://hooks.example.com/cb', 'event_types': 'AGENT_REGISTERED'},
     'event_types must be a list of valid event type names'),
    ({'callback_url': 'https://hooks.example.com/cb',
      'event_types': ['AGENT_CREATED']},
     'event_types must be a list of valid event type names'),
    ({'callback_url': 'https://hooks.example.com/cb', 'filters': ['org']},
     'filters must be an object'),
])
def test_create_subscription_validates_body(client, broadcast, body, expected,
                                            monkeypatch):
    """TC-API-040 | Subscription creation validates callback, types and filters

    输入: POST /subscriptions with the parametrized malformed body; the callback
          host is authorized so the validation under test is the failing rule
    预期输出: 422 且 errorMessage 等于 parametrized 文案
    断言点: 状态码 + 精确消息 + 订阅存储仍为空
    防回归: 若缺省字段被放行，会生成永不匹配或永远匹配的订阅
    """
    service = broadcast(enabled=True)
    monkeypatch.setattr(
        'agent_registry.broadcast.callback_policy.get_conf',
        lambda: {'broadcast.callback.allowlist': 'hooks.example.com'})

    response = client.post(SUBSCRIPTIONS, json=body)

    assert response.status_code == 422
    assert response.json()['errors']['error'][0]['errorMessage'] == expected
    assert service.subscription_store.list_all() == []


def test_create_list_delete_subscription_round_trip(client, broadcast, monkeypatch):
    """TC-API-041 | A created subscription is listed, dispatched and deletable

    输入: broadcast enabled + allowlist authorizing hooks.example.com;
          POST then GET then DELETE then DELETE again
    预期输出: 201 带 subscription_id；列表含该订阅；删除 200；重复删除 404
    断言点: 三处响应体 + dispatcher.add/remove 记录 + 存储最终为空
    防回归: 若 dispatcher 未同步增删，webhook 会漏投或向已删订阅投递
    """
    service = broadcast(enabled=True)
    monkeypatch.setattr(
        'agent_registry.broadcast.callback_policy.get_conf',
        lambda: {'broadcast.callback.allowlist': 'hooks.example.com'})

    created = client.post(SUBSCRIPTIONS, json={
        'callback_url': 'https://hooks.example.com/cb',
        'event_types': ['AGENT_REGISTERED'],
        'filters': {'organizations': ['org-a']},
    })

    assert created.status_code == 201
    subscription_id = created.json()['subscription_id']
    assert subscription_id
    assert created.json()['callback_url'] == 'https://hooks.example.com/cb'
    assert created.json()['event_types'] == ['AGENT_REGISTERED']
    assert created.json()['filters'] == {'organizations': ['org-a'], 'tags': None}
    assert service.dispatcher.added == [subscription_id]

    listed = client.get(SUBSCRIPTIONS)
    assert [entry['subscription_id'] for entry in listed.json()['subscriptions']] == \
        [subscription_id]

    removed = client.delete(f'{SUBSCRIPTIONS}/{subscription_id}')
    assert removed.status_code == 200
    assert removed.json() == {'subscription_id': subscription_id, 'deleted': True}
    assert service.dispatcher.removed == [subscription_id]
    assert service.subscription_store.list_all() == []

    again = client.delete(f'{SUBSCRIPTIONS}/{subscription_id}')
    assert again.status_code == 404
    assert again.json()['errors']['error'][0]['errorMessage'] == 'Subscription not found'


def test_create_subscription_rejects_unauthorized_destination(client, broadcast):
    """TC-API-042 | Callback destinations must be operator-authorized

    输入: broadcast enabled, empty callback allowlist in the ambient config
    预期输出: 422；errorMessage 提示 allowlist 未授权该目标
    断言点: 状态码 + 消息关键字 + 未创建订阅
    防回归: 若回调策略被绕过，注册中心会向任意主机发起 webhook（SSRF）
    """
    service = broadcast(enabled=True)

    response = client.post(SUBSCRIPTIONS,
                           json={'callback_url': 'https://evil.example.org/cb'})

    assert response.status_code == 422
    assert 'allowlist' in response.json()['errors']['error'][0]['errorMessage']
    assert service.subscription_store.list_all() == []


def test_changes_feed_replays_registration_event(client, registry):
    """TC-API-043 | The change feed replays persisted events with a cursor

    输入: register alpha through the API, then GET /changes?since=0
    预期输出: 200；一条 AGENT_REGISTERED 事件，data 含 name/organization，
              has_more = false，next_since = 该事件版本
    断言点: 事件类型 + data 关键字段 + has_more/next_since 数值
    防回归: 若事件没有落库或游标不前进，订阅方会重复或漏掉变更
    """
    assert client.post(BASE, json={'agentCards': [card_body()]}).status_code == 201

    response = client.get(CHANGES, params={'since': 0})

    assert response.status_code == 200
    body = response.json()
    assert len(body['changes']) == 1
    change = body['changes'][0]
    assert change['event_type'] == 'AGENT_REGISTERED'
    assert change['data']['name'] == 'alpha'
    assert change['data']['organization'] == 'org-a'
    assert body['has_more'] is False
    assert body['next_since'] == change['registry_version']

    caught_up = client.get(CHANGES, params={'since': body['next_since']})
    assert caught_up.json() == {'changes': [], 'has_more': False,
                               'next_since': body['next_since']}
    assert registry.count() == 1


# ==========================================================================
# Rate limiting / config helpers
# ==========================================================================

def test_parse_rate_limit_unknown_interface_returns_none():
    """TC-API-044 | An unknown interface name has no rate limit

    输入: parse_rate_limit('no-such-interface')
    预期输出: None
    断言点: 返回值 is None
    防回归: 若未知接口回退到某个默认配额，新接口会被意外的限流值约束
    """
    assert server_module.parse_rate_limit('no-such-interface') is None


def test_rate_limiter_rejects_unknown_interface():
    """TC-API-045 | Building a limiter for an unknown interface fails fast

    输入: RateLimiter('no-such-interface')
    预期输出: ValueError("Invalid rate limit configuration")
    断言点: 异常类型 + 消息
    防回归: 若构造器容忍 None，接口会以“从不限流”状态静默上线
    """
    with pytest.raises(ValueError, match='Invalid rate limit configuration'):
        server_module.RateLimiter('no-such-interface')


def test_parse_rate_limit_falls_back_on_invalid_config(monkeypatch):
    """TC-API-046 | A non-numeric rate-limit config falls back to the default

    输入: flowcontrol.ratelimit.register = "not-a-number"
    预期输出: 仍返回配额为 50/second 的 RateLimitItem
    断言点: 返回值非 None 且 amount == 50（默认值）+ multiples == 1
    防回归: 若解析失败被当成 0，注册接口会被永久限流
    """
    monkeypatch.setitem(server_module.config, 'flowcontrol.ratelimit.register',
                        'not-a-number')

    item = server_module.parse_rate_limit('register')

    assert item is not None
    assert item.amount == 50
    assert item.multiples == 1


def test_parse_rate_limit_returns_none_when_parse_fails(monkeypatch):
    """TC-API-047 | An unparsable rate string is reported as “no limit”

    输入: parse_many raises ValueError('bad grammar')
    预期输出: None
    断言点: 返回值 is None
    防回归: 若解析异常冒泡，一个配置笔误会让整个服务在启动时崩溃
    """
    def _boom(text):
        raise ValueError('bad grammar')

    monkeypatch.setattr(server_module, 'parse_many', _boom)

    assert server_module.parse_rate_limit('query') is None


def test_get_int_config_falls_back_on_invalid_value():
    """TC-API-048 | Invalid integer config values fall back to the given default

    输入: _get_int_config with 'abc', a missing key and a valid numeric string
    预期输出: 7 / 7 / 11
    断言点: 三个返回值
    防回归: 若配置错误直接抛出，任一环境变量笔误都会阻断启动
    """
    assert server_module._get_int_config({'x': 'abc'}, 'x', 7) == 7
    assert server_module._get_int_config({}, 'x', 7) == 7
    assert server_module._get_int_config({'x': '11'}, 'x', 7) == 11


@pytest.mark.asyncio
async def test_semaphore_guard_rejects_when_saturated():
    """TC-API-049 | A saturated endpoint semaphore answers 503 “Server is busy”

    输入: semaphore with capacity 1 already acquired
    预期输出: 进入 semaphore_guard 时抛出 503 CustomHTTPException
    断言点: 异常类型 + status_code + detail 原文
    防回归: 若并发上限被忽略，过载会转化成超时/内存膨胀而不是快速失败
    """
    import anyio

    semaphore = anyio.Semaphore(1)
    semaphore.acquire_nowait()

    with pytest.raises(server_module.CustomHTTPException) as exc:
        async with server_module.semaphore_guard(semaphore):
            pytest.fail('body must not run when the semaphore is exhausted')

    assert exc.value.status_code == 503
    assert exc.value.detail == 'Server is busy'


@pytest.mark.asyncio
async def test_semaphore_guard_maps_registry_unavailable_to_503():
    """TC-API-050 | A missing record store is a 503, not a 500

    输入: body raises RegistryUnavailableError('no record store')
    预期输出: 503 CustomHTTPException 携带原始消息
    断言点: 异常类型 + 状态码 + detail
    防回归: 若被通用异常分支捕获，运维看到的是 500，而问题其实是部署缺存储
    """
    import anyio

    with pytest.raises(server_module.CustomHTTPException) as exc:
        async with server_module.semaphore_guard(anyio.Semaphore(1)):
            raise RegistryUnavailableError('no record store')

    assert exc.value.status_code == 503
    assert exc.value.detail == 'no record store'


@pytest.mark.asyncio
async def test_semaphore_guard_hides_unexpected_error_details():
    """TC-API-051 | An unexpected endpoint error is a generic 500

    输入: body raises RuntimeError('secret internal detail')
    预期输出: 500 且 detail = "Internal server error"
    断言点: 状态码 + detail 不含内部细节
    防回归: 若异常文本透出，内部路径/凭据可能泄露给调用方
    """
    import anyio

    with pytest.raises(server_module.CustomHTTPException) as exc:
        async with server_module.semaphore_guard(anyio.Semaphore(1)):
            raise RuntimeError('secret internal detail')

    assert exc.value.status_code == 500
    assert exc.value.detail == 'Internal server error'


@pytest.mark.asyncio
async def test_rate_limiter_rejects_over_quota(monkeypatch):
    """TC-API-052 | The rate-limit dependency returns 429 when the quota is spent

    输入: async_hit returns False
    预期输出: 429 CustomHTTPException("Too Many Requests")
    断言点: 状态码 + detail + 限流标识符为请求方地址
    防回归: 若判定取反或忽略返回值，配额形同虚设
    """
    seen = []

    async def _deny(item, *identifiers, cost=1):
        seen.append(identifiers)
        return False

    monkeypatch.setattr(server_module, 'async_hit', _deny)
    limiter = server_module.RateLimiter('query')

    with pytest.raises(server_module.CustomHTTPException) as exc:
        await limiter(_StubRequest(host='10.9.9.9'))

    assert exc.value.status_code == 429
    assert exc.value.detail == 'Too Many Requests'
    assert seen == [('10.9.9.9',)]


@pytest.mark.asyncio
async def test_owner_guard_is_bypassed_when_isolation_disabled(registry, monkeypatch):
    """TC-API-053 | Owner isolation off means no ownership lookup at all

    输入: OWNER_ISOLATION_ENABLED = False, _verify_owner_permission(...)
    预期输出: None（不查库、不鉴权）
    断言点: 返回值为 None
    防回归: 若关闭开关仍然返回 owner，单租户部署会被意外限制
    """
    monkeypatch.setattr(server_module, 'OWNER_ISOLATION_ENABLED', False)

    result = await server_module._verify_owner_permission(
        _StubRequest(method='PUT'), 'alpha', 'org-a', registry)

    assert result is None


def test_register_layer_aware_item_with_invalid_layer_is_422(client, registry):
    """TC-API-074 | A layer-aware item with a bad layer is rejected up front

    输入: POST /agent-cards {"agentCards": [{"agentCard": {...}, "layer": <65 字符>}]}
    预期输出: 422；errorMessage = "layer must not exceed 64 characters"
    断言点: 状态码 + 消息原文 + 未写入存储
    防回归: 若非法 layer 被当成默认值，用户提交的层信息会被静默丢弃
    """
    response = client.post(BASE, json={'agentCards': [
        {'agentCard': card_body(), 'layer': 'x' * 65}]})

    assert response.status_code == 422
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'layer must not exceed 64 characters'
    assert registry.count() == 0


def test_layer_query_body_parser_rejects_non_object():
    """TC-API-075 | The unified layer query parser refuses a non-object body

    输入: _parse_layer_query_body(["not", "an", "object"])
    预期输出: 422 CustomHTTPException("request body must be an object")
    断言点: 异常类型 + 状态码 + detail
    防回归: 若解析器假定 dict，非对象 body 会以 AttributeError 变成 500
    """
    with pytest.raises(server_module.CustomHTTPException) as exc:
        server_module._parse_layer_query_body(['not', 'an', 'object'])

    assert exc.value.status_code == 422
    assert exc.value.detail == 'request body must be an object'


def test_published_healthy_records_drops_non_published_cards():
    """TC-API-076 | A pending record never passes the publication filter

    输入: _published_healthy_records with one registered (pending) record
    预期输出: 空列表
    断言点: 返回值为 []
    防回归: 若状态过滤只依赖存储层的 SQL 谓词，内存过滤路径会泄露未审批卡片
    """
    from agent_registry.persistence.base import AgentRecord

    records = [AgentRecord(agent_card=make_card(), status='registered')]

    assert server_module._published_healthy_records(records) == []


@pytest.mark.asyncio
async def test_health_stream_listener_survives_a_closed_loop(registry, health,
                                                             broadcast, wire_bus,
                                                             monkeypatch):
    """TC-API-077 | A closed event loop must not break SSE event publishing

    输入: 拿到 SSE 生成器注册的真实监听器后，用 call_soon_threadsafe 抛
          RuntimeError 的 loop 触发一次健康事件
    预期输出: 监听器吞掉 RuntimeError 并返回（发布方不受影响）
    断言点: 调用不抛异常 + 监听器已被注册
    防回归: 若 RuntimeError 未被捕获，进程退出阶段的广播会打印未处理异常
    """
    health()
    broadcast(enabled=False)

    class _ClosedLoop:
        def call_soon_threadsafe(self, *args, **kwargs):
            raise RuntimeError('Event loop is closed')

    request = _StubRequest(path='/rest/v1/registry-center/agents/health/stream')
    monkeypatch.setattr(server_module, 'asyncio', _AsyncioShim(
        asyncio, get_running_loop=lambda: _ClosedLoop()))
    response = await server_module.stream_agent_health(
        request=request, registry=registry, _=True)
    stream = response.body_iterator
    assert await stream.__anext__() == ': connected\n\n'

    bus = broadcast_module._service.event_bus
    assert len(bus._listeners) == 1
    listener = bus._listeners[0]
    assert listener(
        build_event(EventType.AGENT_HEALTH_CHANGED, {'name': 'alpha'}, 0)) is None

    request._disconnected = True
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
    assert bus._listeners == []


# ==========================================================================
# SSE health stream helper (kept together with the stream cases)
# ==========================================================================

def test_enqueue_drop_oldest_never_raises():
    """TC-API-054 | The SSE queue helper degrades instead of raising

    输入: a queue whose put_nowait always raises QueueFull and whose get_nowait
          raises QueueEmpty
    预期输出: 函数返回 None，不抛异常，且 put 被尝试两次
    断言点: 无异常 + 调用次数 2（先进队失败 -> 尝试丢弃 -> 再次入队失败）
    防回归: 若 QueueFull 冒泡到 loop.call_soon_threadsafe，慢消费者会静默
              失去整条健康事件流
    """
    calls = {'put': 0, 'get': 0}

    class _FullQueue:
        def put_nowait(self, event):
            calls['put'] += 1
            raise asyncio.QueueFull()

        def get_nowait(self):
            calls['get'] += 1
            raise asyncio.QueueEmpty()

    assert server_module._enqueue_drop_oldest(_FullQueue(), object()) is None
    assert calls == {'put': 2, 'get': 1}


def test_enqueue_drop_oldest_replaces_oldest_entry():
    """TC-API-055 | A full queue drops the oldest event, keeping the newest

    输入: asyncio.Queue(maxsize=1) already holding "first"
    预期输出: 队列只剩最新事件 "second"
    断言点: 剩余元素 == "second"
    防回归: 若丢弃逻辑写反，消费者会永远看到最旧的健康状态
    """
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait('first')

    server_module._enqueue_drop_oldest(queue, 'second')

    assert queue.qsize() == 1
    assert queue.get_nowait() == 'second'


# ==========================================================================
# Registration / update error mapping (direct handler calls)
# ==========================================================================

@pytest.mark.asyncio
async def test_perform_registration_maps_domain_errors():
    """TC-API-056 | _perform_registration maps each failure to its HTTP contract

    输入: INSERT handler raising LayerMigrationRequiredError, ValueError,
          RegistryUnavailableError and RuntimeError in turn
    预期输出: 503 / 400 / 原样抛出 / 500，details["message"] 记录原因
    断言点: 四种异常的类型、状态码与消息
    防回归: 若任一分支被合并，迁移/参数/内部错误会被混为同一种状态码
    """
    def _install(exc):
        class _Raising:
            async def handle(self, *args, **kwargs):
                raise exc
        HandlerRegistry._instances[InterfaceType.INSERT.value] = _Raising()

    details = {}
    _install(LayerMigrationRequiredError('reindex required'))
    with pytest.raises(server_module.CustomHTTPException) as exc:
        await server_module._perform_registration(make_card(), '10.0.0.1', details)
    assert (exc.value.status_code, exc.value.detail) == (503, 'reindex required')
    assert details['message'] == 'reindex required'

    details = {}
    _install(ValueError('bad layer'))
    with pytest.raises(server_module.CustomHTTPException) as exc:
        await server_module._perform_registration(make_card(), '10.0.0.1', details)
    assert (exc.value.status_code, exc.value.detail) == (400, 'bad layer')
    assert details['message'] == 'bad layer'

    _install(RegistryUnavailableError('no record store'))
    with pytest.raises(RegistryUnavailableError):
        await server_module._perform_registration(make_card(), '10.0.0.1', {})

    details = {}
    _install(RuntimeError('boom'))
    with pytest.raises(server_module.CustomHTTPException) as exc:
        await server_module._perform_registration(make_card(), '10.0.0.1', details)
    assert (exc.value.status_code, exc.value.detail) == (500, 'Internal server error')
    assert details['message'] == 'Internal server error'


@pytest.mark.asyncio
async def test_perform_update_passes_layer_and_maps_errors():
    """TC-API-057 | _perform_update forwards the layer and maps each failure

    输入: UPDATE handler recording kwargs; then raising ValueError,
          LayerMigrationRequiredError, RegistryUnavailableError, RuntimeError
    预期输出: 成功调用带 layer 关键字；400 / 503 / 原样抛出 / 500
    断言点: 记录到的 kwargs + 四种异常的状态码与消息
    防回归: 若 layer 未透传，PUT 会把层信息重置；若错误映射丢失，客户端
              会拿到 500 而不是可处理的 4xx/503
    """
    seen = {}

    class _RecordingUpdate:
        async def handle(self, *args, **kwargs):
            seen['args'] = args
            seen['kwargs'] = kwargs
            return True

    HandlerRegistry._instances[InterfaceType.UPDATE.value] = _RecordingUpdate()
    assert await server_module._perform_update(
        '10.0.0.1', 'alpha', 'org-a', {'name': 'alpha'}, {},
        owner='owner-1', layer='ServiceLayer') is True
    assert seen['kwargs'] == {'owner': 'owner-1', 'layer': 'ServiceLayer'}
    assert seen['args'][:2] == ('alpha', 'org-a')

    def _install(exc):
        class _Raising:
            async def handle(self, *args, **kwargs):
                raise exc
        HandlerRegistry._instances[InterfaceType.UPDATE.value] = _Raising()

    details = {}
    _install(ValueError('bad payload'))
    with pytest.raises(server_module.CustomHTTPException) as exc:
        await server_module._perform_update('10.0.0.1', 'alpha', 'org-a', {}, details)
    assert (exc.value.status_code, exc.value.detail) == (400, 'bad payload')
    assert details['message'] == 'bad payload'

    _install(LayerMigrationRequiredError('reindex required'))
    with pytest.raises(server_module.CustomHTTPException) as exc:
        await server_module._perform_update('10.0.0.1', 'alpha', 'org-a', {}, {})
    assert (exc.value.status_code, exc.value.detail) == (503, 'reindex required')

    _install(RegistryUnavailableError('no record store'))
    with pytest.raises(RegistryUnavailableError):
        await server_module._perform_update('10.0.0.1', 'alpha', 'org-a', {}, {})

    _install(RuntimeError('boom'))
    with pytest.raises(server_module.CustomHTTPException) as exc:
        await server_module._perform_update('10.0.0.1', 'alpha', 'org-a', {}, {})
    assert (exc.value.status_code, exc.value.detail) == (500, 'Internal server error')


# ==========================================================================
# Signer / JWK
# ==========================================================================

def _signer_config(**overrides):
    config = {
        'registry.sign.enabled': 'true',
        'registry.sign.jwks_url': PUBLIC_JKU,
        'registry.public.base_url': '',
        'ip': '127.0.0.1',
        'enable_https': 'true',
        'port': 5000,
        'jwk_private_key_path': '',
        'jwk_cert_path': '',
        'jwk_private_key_password': '',
    }
    config.update(overrides)
    return config


def test_signer_rejects_unusable_public_key_address(monkeypatch):
    """TC-API-058 | An unusable public-key address fails closed at startup

    输入: signing enabled with registry.sign.jwks_url containing credentials
    预期输出: HTTPException 503 "Registry public key address invalid"
    断言点: 状态码 + detail 原文
    防回归: 若异常被吞，签发的卡片会带一个无法解析的 jku
    """
    monkeypatch.setattr(server_module, '_registry_signer', None)
    monkeypatch.setattr(server_module, 'config', _signer_config(
        **{'registry.sign.jwks_url': 'https://user:pass@registry.example.com/keys'}))

    with pytest.raises(HTTPException) as exc:
        server_module.get_registry_signer()

    assert exc.value.status_code == 503
    assert exc.value.detail == 'Registry public key address invalid'


def test_signer_disabled_branch_returns_disabled_signer(monkeypatch):
    """TC-API-059 | Signing disabled yields a disabled signer, never an error

    输入: registry.sign.enabled = false
    预期输出: AgentCardSigner with is_enabled() False
    断言点: 类型 + is_enabled() 为 False
    防回归: 若关闭签名时抛错，关闭该功能的部署将无法启动
    """
    from agent_registry.agent_registry.agent_card_signer import AgentCardSigner

    monkeypatch.setattr(server_module, '_registry_signer', None)
    monkeypatch.setattr(server_module, 'config',
                        _signer_config(**{'registry.sign.enabled': 'false'}))

    signer = server_module.get_registry_signer()

    assert isinstance(signer, AgentCardSigner)
    assert signer.is_enabled() is False


def test_signer_initialises_from_valid_material(tmp_path, monkeypatch):
    """TC-API-060 | Valid signing material produces an enabled, working signer

    输入: freshly generated RSA key + matching self-signed certificate
    预期输出: is_enabled() True；签出的卡片带 RS256 签名，header 含 jku 与 kid
    断言点: is_enabled + 签名数量 + 解码后的 alg/jku/kid
    防回归: 若成功路径被破坏（例如写反的开关），签名部署会静默不签名
    """
    key_path, cert_path = write_signing_material(tmp_path)
    monkeypatch.setattr(server_module, '_registry_signer', None)
    monkeypatch.setattr(server_module, 'config', _signer_config(
        **{'jwk_private_key_path': str(key_path),
           'jwk_cert_path': str(cert_path)}))

    signer = server_module.get_registry_signer()

    assert signer.is_enabled() is True
    signed = signer.sign_agent_card(make_card())
    assert len(signed.signatures) == 1
    protected = signed.signatures[0].protected
    header = json.loads(base64.urlsafe_b64decode(
        protected + '=' * (-len(protected) % 4)))
    assert header['alg'] == 'RS256'
    assert header['jku'] == PUBLIC_JKU
    assert header['kid']


def test_jwk_endpoint_disabled_is_503(client, monkeypatch):
    """TC-API-061 | The JWK endpoint is closed while signing is disabled

    输入: registry.sign.enabled = false, GET /rest/v1/registry-center/keys
    预期输出: 503；errorMessage 说明签名未启用
    断言点: 状态码 + 消息原文
    防回归: 若端点无条件返回公钥，未启用签名的部署会暴露无关证书
    """
    monkeypatch.setitem(server_module.config, 'registry.sign.enabled', 'false')

    response = client.get(JWKS)

    assert response.status_code == 503
    assert response.json()['errors']['error'][0]['errorMessage'] == \
        'JWK endpoint is not available when registry signing is disabled'


def test_jwk_endpoint_rate_limited_is_429(client, monkeypatch):
    """TC-API-062 | The JWK endpoint honours its own rate limit

    输入: signing enabled, async_hit returns False
    预期输出: 429；errorMessage = "Too Many Requests"
    断言点: 状态码 + 消息原文
    防回归: 若限流判定结果被忽略，密钥端点会成为无成本的目标
    """
    async def _deny(item, *identifiers, cost=1):
        return False

    monkeypatch.setitem(server_module.config, 'registry.sign.enabled', 'true')
    monkeypatch.setattr(server_module, 'async_hit', _deny)
    monkeypatch.setattr(server_module, 'get_registry_signer', lambda: None)

    response = client.get(JWKS)

    assert response.status_code == 429
    assert response.json()['errors']['error'][0]['errorMessage'] == 'Too Many Requests'


@pytest.mark.parametrize('error, expected_status, expected_detail', [
    ('cert_load', 503, 'Unable to load JWK certificate'),
    ('unexpected', 500, 'Internal server error'),
])
def test_jwk_endpoint_maps_certificate_failures(client, monkeypatch,
                                               error, expected_status, expected_detail):
    """TC-API-063 | Certificate problems are mapped to explicit 503/500 answers

    输入: jwk_provider.get_jwk_set raises CertLoadError / RuntimeError
    预期输出: 503 "Unable to load JWK certificate" / 500 "Internal server error"
    断言点: 状态码 + 消息原文 + 信号量已释放（可再次访问）
    防回归: 若 finally 释放被删，一次证书故障会永久占满 JWK 并发位
    """
    from agent_registry.agent_registry.jwk_provider import CertLoadError

    class _Provider:
        def get_jwk_set(self):
            if error == 'cert_load':
                raise CertLoadError('missing cert')
            raise RuntimeError('unexpected blowup')

    async def _allow(item, *identifiers, cost=1):
        return True

    monkeypatch.setitem(server_module.config, 'registry.sign.enabled', 'true')
    monkeypatch.setattr(server_module, 'get_registry_signer', lambda: None)
    monkeypatch.setattr(server_module, 'async_hit', _allow)
    monkeypatch.setattr(server_module, 'jwk_provider', _Provider())

    response = client.get(JWKS)

    assert response.status_code == expected_status
    assert response.json()['errors']['error'][0]['errorMessage'] == expected_detail
    assert server_module.jwk_semaphore.value == 1


# ==========================================================================
# Middleware / validation handlers / probes
# ==========================================================================

def test_uri_too_long_is_414(client, monkeypatch):
    """TC-API-064 | Over-long URLs are rejected before routing

    输入: MAX_URL_LENGTH lowered to 10, GET /health
    预期输出: 414，响应体 "URI Too Long"
    断言点: 状态码 + 响应文本
    防回归: 若长度检查被删，超长 URL 会进入路由/日志，放大资源消耗
    """
    monkeypatch.setattr(server_module, 'MAX_URL_LENGTH', 10)

    response = client.get('/health')

    assert response.status_code == 414
    assert response.text == 'URI Too Long'


def test_oversized_body_is_413(client, registry, monkeypatch):
    """TC-API-065 | Request bodies above the limit are rejected while streaming

    输入: MAX_REQUEST_BODY_SIZE lowered to 16, POST a longer JSON body
    预期输出: 413，响应文本以 "Request body is too large" 开头；未写入存储
    断言点: 状态码 + 文本前缀 + registry.count() == 0
    防回归: 若只在读完整个 body 后校验，内存会被大包打满
    """
    monkeypatch.setattr(server_module, 'MAX_REQUEST_BODY_SIZE', 16)

    response = client.post(BASE, json={'agentCards': [card_body()]})

    assert response.status_code == 413
    assert response.text.startswith('Request body is too large')
    assert registry.count() == 0


@pytest.mark.asyncio
async def test_body_read_failure_is_400():
    """TC-API-066 | A broken request stream is a 400, and the route never runs

    输入: request.stream() yields a chunk then raises OSError
    预期输出: 400，响应体 "Bad Request"；call_next 未被调用
    断言点: 状态码 + 响应体 + call_next 调用列表为空
    防回归: 若读取异常冒泡，客户端断连会被记录成服务端 500
    """
    called = []

    class _BrokenStream:
        method = 'POST'
        url = 'http://testserver/rest/v1/registry-center/agent-cards'

        async def stream(self):
            yield b'{"agentCards":'
            raise OSError('connection reset by peer')

    async def _call_next(request):
        called.append(request)
        return 'should-not-happen'

    response = await server_module.security_middleware(_BrokenStream(), _call_next)

    assert response.status_code == 400
    assert response.body == b'Bad Request'
    assert called == []


def test_request_validation_error_uses_uniform_envelope(client):
    """TC-API-067 | Query-parameter validation errors use the unified error shape

    输入: GET /agent-cards/org-a/alpha/review-status?limit=0 (ge=1)
    预期输出: 422；errorMessage 含参数位置与原因
    断言点: 状态码 + errors.error[0].errorMessage 含 "limit" 与下界说明
    防回归: 若走 FastAPI 默认 422 结构，客户端解析器会漏掉这类错误
    """
    response = client.get(f'{BASE}/org-a/alpha/review-status', params={'limit': 0})

    assert response.status_code == 422
    message = response.json()['errors']['error'][0]['errorMessage']
    assert 'limit' in message
    assert 'greater than or equal to 1' in message


@pytest.mark.asyncio
async def test_health_probe_reports_missing_registry(monkeypatch):
    """TC-API-068 | /health fails with 503 when no registry is available

    输入: get_registry returns None
    预期输出: HTTPException 503 "Registry storage unavailable"
    断言点: 状态码 + detail
    防回归: 若探针在无存储时返回 200，负载均衡会把流量打到残废实例
    """
    monkeypatch.setattr(server_module, 'get_registry', lambda: None)

    with pytest.raises(HTTPException) as exc:
        await server_module.health_probe()

    assert exc.value.status_code == 503
    assert exc.value.detail == 'Registry storage unavailable'


def test_health_probe_ok_with_registry(client, registry, monkeypatch):
    """TC-API-069 | /health answers 200 ok for a ready deployment

    输入: registry present, signer resolvable, certificate identity mode
    预期输出: 200 {"status": "ok"}
    断言点: 状态码 + 响应体
    防回归: 若探针依赖签名材料/鉴权配置，一个配置缺口会让所有副本被判死
    """
    monkeypatch.setattr(server_module, 'get_registry', lambda: registry)
    monkeypatch.setattr(server_module, 'get_registry_signer', lambda: None)

    response = client.get('/health')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_initialize_registry_guarded_reraises_after_logging(monkeypatch):
    """TC-API-070 | Startup storage failure is logged and re-raised

    输入: initialize_registry raises RuntimeError('storage down')
    预期输出: 同一个异常向上抛出
    断言点: 异常类型 + 消息
    防回归: 若异常被吞，进程会以“无存储”状态对外提供服务
    """
    def _boom():
        raise RuntimeError('storage down')

    monkeypatch.setattr(server_module, 'initialize_registry', _boom)

    with pytest.raises(RuntimeError, match='storage down'):
        server_module._initialize_registry_guarded()


# ==========================================================================
# Service lifecycle
# ==========================================================================

@pytest.mark.asyncio
async def test_startup_services_starts_sweeper_in_vectordb_mode(monkeypatch):
    """TC-API-071 | Startup wires health/broadcast and starts the sweeper

    输入: registry in vector mode, health service enabled, broadcast stub
    预期输出: sweeper 以 health 参数构造并 start；广播服务 start；
              健康/广播初始化收到 "vectordb" 模式
    断言点: sweeper 的构造参数与 started + 服务 started + 传入的模式字符串
    防回归: 若 sweeper 未启动，心跳超时永远不会把卡片判为不可用
    """
    _StubSweeper.instances = []
    seen_modes = []
    health_stub = types.SimpleNamespace(
        enabled=True, interval=15, failure_threshold=2, grace_period=3,
        sweep_interval=4, offline_ttl=5)
    broadcast_stub = _StubService()
    registry_stub = types.SimpleNamespace(use_vectordb=True, storage=None,
                                         persistence_mode='file')

    def _init_health(backend, mode):
        seen_modes.append(('health', backend, mode))
        return health_stub

    def _init_broadcast(backend, mode):
        seen_modes.append(('broadcast', backend, mode))
        return broadcast_stub

    monkeypatch.setattr(server_module, 'get_registry_signer', lambda: None)
    monkeypatch.setattr(server_module, 'get_registry', lambda: registry_stub)
    monkeypatch.setattr(server_module, 'initialize_health_service', _init_health)
    monkeypatch.setattr(server_module, 'initialize_broadcast_service', _init_broadcast)
    monkeypatch.setattr(server_module, 'get_health_service', lambda: health_stub)
    monkeypatch.setattr(server_module, 'get_broadcast_service', lambda: broadcast_stub)
    monkeypatch.setattr(server_module, '_health_sweeper', None)
    monkeypatch.setattr('agent_registry.health.sweeper.HealthSweeper', _StubSweeper)

    await server_module.startup_services()

    assert seen_modes == [('health', None, 'vectordb'), ('broadcast', None, 'vectordb')]
    sweeper = server_module._health_sweeper
    assert isinstance(sweeper, _StubSweeper)
    assert sweeper.health_service is health_stub
    assert sweeper.registry is registry_stub
    assert sweeper.kwargs == {'interval': 15, 'failure_threshold': 2,
                             'grace_period': 3, 'sweep_interval': 4,
                             'offline_ttl': 5}
    assert sweeper.started is True
    assert broadcast_stub.started is True


@pytest.mark.asyncio
async def test_startup_services_rolls_back_when_broadcast_fails(monkeypatch):
    """TC-API-072 | A failed startup unwinds the sweeper and broadcast service

    输入: broadcast service start raises RuntimeError
    预期输出: 异常传播；sweeper.stop() 与 broadcast.stop() 都被调用
    断言点: 异常类型 + stopped 标志 + _health_sweeper 复位为 None
    防回归: 若失败不回滚，半启动实例会继续跑后台任务
    """
    _StubSweeper.instances = []
    health_stub = types.SimpleNamespace(
        enabled=True, interval=15, failure_threshold=2, grace_period=3,
        sweep_interval=4, offline_ttl=5)
    broadcast_stub = _StubService(fail_start=True)
    registry_stub = types.SimpleNamespace(use_vectordb=False, storage=None,
                                         persistence_mode='file')

    monkeypatch.setattr(server_module, 'get_registry_signer', lambda: None)
    monkeypatch.setattr(server_module, 'get_registry', lambda: registry_stub)
    monkeypatch.setattr(server_module, 'initialize_health_service',
                        lambda backend, mode: health_stub)
    monkeypatch.setattr(server_module, 'initialize_broadcast_service',
                        lambda backend, mode: broadcast_stub)
    monkeypatch.setattr(server_module, 'get_health_service', lambda: health_stub)
    monkeypatch.setattr(server_module, 'get_broadcast_service', lambda: broadcast_stub)
    monkeypatch.setattr(server_module, '_health_sweeper', None)
    monkeypatch.setattr(server_module, '_signature_validator', None)
    monkeypatch.setattr('agent_registry.health.sweeper.HealthSweeper', _StubSweeper)

    with pytest.raises(RuntimeError, match='broadcast start failed'):
        await server_module.startup_services()

    assert _StubSweeper.instances[0].stopped is True
    assert broadcast_stub.stopped is True
    assert server_module._health_sweeper is None


@pytest.mark.asyncio
async def test_shutdown_services_stops_sweeper_and_closes_validator(monkeypatch):
    """TC-API-073 | Shutdown stops the sweeper and closes the JWK fetcher

    输入: registered sweeper stub and a validator whose jwk_fetcher.aclose()
          records the call
    预期输出: sweeper.stop 被 await；aclose 被 await；两个全局变量归零
    断言点: stopped 标志 + closed 记录 + _health_sweeper/_signature_validator
    防回归: 若资源未关闭，热重启会泄漏后台线程与 HTTP 连接
    """
    closed = {}

    class _Fetcher:
        async def aclose(self):
            closed['fetcher'] = True

    validator = types.SimpleNamespace(jwk_fetcher=_Fetcher())
    sweeper = _StubSweeper(types.SimpleNamespace(), types.SimpleNamespace(),
                           types.SimpleNamespace())
    broadcast_stub = _StubService()

    monkeypatch.setattr(server_module, '_health_sweeper', sweeper)
    monkeypatch.setattr(server_module, '_signature_validator', validator)
    monkeypatch.setattr(server_module, 'get_broadcast_service', lambda: broadcast_stub)

    await server_module.shutdown_services()

    assert sweeper.stopped is True
    assert closed == {'fetcher': True}
    assert broadcast_stub.stopped is True
    assert server_module._health_sweeper is None
    assert server_module._signature_validator is None
