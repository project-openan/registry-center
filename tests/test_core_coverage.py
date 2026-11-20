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

"""Coverage tests for ``agent_registry/core.py`` (registry core).

The core is exercised against its two real storage shapes:

* an authoritative sqlite backend (transactions, tags, status history), wired
  to a real outbox so every published change event can be asserted, and
* an injected vector index, used through the public ``use_vectordb=True``
  argument, i.e. exactly the "explicit argument wins" path documented on
  ``_uses_vectordb``. No Milvus/embedding service and no network is involved.

A third shape ("no record store") is produced by removing ``storage`` from an
initialised core, which is how the vector-only deployment looks to the
authoritative surfaces.

Every case is ``TC-CORE-nnn`` with input, expected output, assertion points and
the regression it prevents in its docstring (see tests/TEST_DESIGN.md). All
state lives in ``tmp_path`` or in ``monkeypatch``-restored attributes.
"""

import json
from unittest.mock import MagicMock

import pytest
from a2a.types import AgentCard

import agent_registry.core as core_module
import agent_registry.health as health_module
from agent_registry.broadcast.event_bus import EventBus
from agent_registry.broadcast.events import EventType
from agent_registry.broadcast.outbox import MemoryOutbox, SqlOutbox
from agent_registry.core import RegistryCore, make_agent_key, make_agent_id
from agent_registry.errors import SemanticSearchUnavailable
from agent_registry.model.agent_layer import UNKNOWN_LAYER
from agent_registry.persistence.base import AgentRecord
from agent_registry.status import DISCOVERABLE_STATUS, PENDING_STATUS


# --------------------------------------------------------------------------
# helpers / fakes
# --------------------------------------------------------------------------

def make_card(name='alpha', org='org-a', description='alpha agent', version='1.0.0'):
    card = AgentCard(name=name, description=description, version=version,
                     provider={'organization': org, 'url': 'https://example.com/a'})
    card.default_input_modes.extend(['text/plain'])
    card.default_output_modes.extend(['text/plain'])
    return card


def card_dict(name='alpha', org='org-a', description='alpha agent'):
    return {
        'name': name,
        'description': description,
        'version': '1.0.0',
        'provider': {'organization': org, 'url': 'https://example.com/a'},
    }


class _FakeEmbedding:
    def __init__(self, vector=None, fail=False):
        self.vector = vector if vector is not None else [0.1, 0.2]
        self.fail = fail
        self.texts = []

    def embed(self, text):
        self.texts.append(text)
        if self.fail:
            raise RuntimeError('embedding backend down')
        return self.vector


class _FakeLLM:
    """Minimal chat model returning a canned JSON payload."""

    def __init__(self, payload=None, text=None):
        self.payload = [{'name': 'alpha', 'organization': 'org-a'}] if payload is None else payload
        self.text = text
        self.prompts = []

    def ask_llm(self, prompt):
        self.prompts.append(prompt)
        if self.text is not None:
            return (None, self.text)
        return (None, json.dumps(self.payload))


class _LegacyVectorDB:
    """The pre-registration-metadata vector client (no find_records family)."""

    def __init__(self):
        self.entities = {}
        self.query_results = []
        self.retrieve_results = []
        self.insert_result = True
        self.update_result = True
        self.delete_result = True
        self.calls = []

    # -- write path
    def insert_entity(self, data):
        self.calls.append(('insert', data))
        entity = dict(data['entity'])
        self.entities[entity['id']] = entity
        return self.insert_result

    def update_entity(self, data):
        self.calls.append(('update', data))
        self.entities[data['entity']['id']] = dict(data['entity'])
        return self.update_result

    def delete_entity(self, data):
        self.calls.append(('delete', data))
        return self.delete_result

    # -- read path
    def get_all_entities(self, data):
        self.calls.append(('all', data))
        return list(self.entities.values())

    def query_by_key(self, data):
        self.calls.append(('query', data))
        return list(self.query_results)

    def retrieve_entity(self, data):
        self.calls.append(('retrieve', data))
        return list(self.retrieve_results)


class _FullVectorDB(_LegacyVectorDB):
    """A vector client that implements the registration-metadata API."""

    def __init__(self):
        super().__init__()
        self.records = []
        self.key_records = []
        self.retrieved_records = []
        self.record_filter = {}

    def find_records(self, **kwargs):
        self.calls.append(('find_records', kwargs))
        self.record_filter = kwargs
        return list(self.records)

    def find_records_by_key(self, collection, name, organization):
        self.calls.append(('find_records_by_key', (collection, name, organization)))
        return list(self.key_records)

    def retrieve_records(self, **kwargs):
        self.calls.append(('retrieve_records', kwargs))
        self.record_filter = kwargs
        return list(self.retrieved_records)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def registry(tmp_path, monkeypatch):
    """An authoritative sqlite core whose events go to a real bound outbox."""
    core = RegistryCore(use_vectordb=False, persistence_mode='sqlite',
                        persistence_conf={'sqlite.path': str(tmp_path / 'registry.db')})
    bus = EventBus(SqlOutbox(core.storage))
    monkeypatch.setattr(core_module, 'get_event_bus', lambda: bus)
    core._test_event_bus = bus
    try:
        yield core
    finally:
        core.close()


@pytest.fixture
def bus(registry):
    return registry._test_event_bus


@pytest.fixture
def vector(registry):
    """The same core with an injected index, used through use_vectordb=True."""
    db = _FullVectorDB()
    registry.vectordb = db
    registry.embedding_tool = _FakeEmbedding()
    return registry, db


@pytest.fixture
def legacy_vector(registry):
    db = _LegacyVectorDB()
    registry.vectordb = db
    registry.embedding_tool = _FakeEmbedding()
    return registry, db


@pytest.fixture
def bare(registry):
    """The same core with no record store (what vector-only mode looks like)."""
    registry.storage = None
    return registry


@pytest.fixture
def health(monkeypatch):
    """Isolated health singleton (restored on teardown)."""
    original_service = health_module._service
    health_module.reset_for_tests()

    def install(**conf):
        config = {'heartbeat.enabled': 'true',
                  'heartbeat.interval': '30',
                  'heartbeat.failure.threshold': '3',
                  'heartbeat.grace.period': '10'}
        config.update(conf)
        return health_module.initialize_health_service(None, 'file', config=config)

    try:
        yield install
    finally:
        health_module._service = original_service


# ==========================================================================
# Keys / initialisation
# ==========================================================================

def test_make_agent_key_trims_both_parts():
    """TC-CORE-001 | Registry keys are whitespace-normalized

    输入: make_agent_key('  alpha ', ' org-a  ')
    预期输出: ('alpha', 'org-a')
    断言点: 返回元组两个元素
    防回归: 若 trim 丢失，'alpha' 与 'alpha ' 会被当成两张卡片
    """
    assert make_agent_key('  alpha ', ' org-a  ') == ('alpha', 'org-a')
    assert make_agent_id('alpha', 'org-a') == 'alpha::org-a'
    assert RegistryCore._make_key(' beta', 'org-b ') == ('beta', 'org-b')


def test_initialize_builds_storage_once(tmp_path, registry):
    """TC-CORE-002 | initialize() rebuilds a missing backend exactly once

    输入: storage removed, persistence_mode='file' with tmp paths
    预期输出: 首次 initialize() 建好 FileStorage；再次调用复用同一实例
    断言点: storage 类型 + 两次调用后的对象标识相同
    防回归: 若每次调用都重建后端，文件模式会在启动时丢失已加载的数据
    """
    from agent_registry.persistence.file_storage import FileStorage

    registry.storage.close()
    registry.storage = None
    registry.persistence_mode = 'file'
    registry.persistence_conf = {
        'file.path': str(tmp_path / 'agents.json'),
        'metadata.file': str(tmp_path / 'meta.json'),
        'tags.file': str(tmp_path / 'tags.json'),
    }

    registry.initialize()
    first = registry.storage
    registry.initialize()

    assert isinstance(first, FileStorage)
    assert registry.storage is first


# ==========================================================================
# Vector-index writes
# ==========================================================================

def test_register_in_vector_mode_writes_index_entity(vector):
    """TC-CORE-003 | Registration through the index stores one full entity

    输入: register(alpha/org-a, use_vectordb=True), layer omitted
    预期输出: insert_entity 收到 id=alpha::org-a、name、organization、status、
              owner、layer=unknown 与 embedding
    断言点: 返回 True + 写入实体字段逐项比对 + 索引里只有这一条
    防回归: 若 id/name 拼错，按 (name, organization) 的查询永远查不到该卡片
    """
    core, db = vector

    assert core.register(make_card(), use_vectordb=True, owner='owner-1') is True

    payload = db.calls[0][1]
    entity = payload['entity']
    assert payload['collection_name'] == core_module.COLLECTION_NAME
    assert entity['id'] == 'alpha::org-a'
    assert entity['name'] == 'alpha'
    assert entity['organization'] == 'org-a'
    assert entity['status'] == DISCOVERABLE_STATUS
    assert entity['owner'] == 'owner-1'
    assert entity['layer'] == UNKNOWN_LAYER
    assert entity['embedding'] == [0.1, 0.2]
    assert json.loads(entity['agent_card'])['name'] == 'alpha'
    assert list(db.entities) == ['alpha::org-a']


def test_register_in_vector_mode_reports_index_refusal(vector):
    """TC-CORE-004 | A refused index insert returns False and emits no event

    输入: insert_entity returns False
    预期输出: register 返回 False；outbox 中没有任何事件
    断言点: 返回值 + outbox 事件数为 0
    防回归: 若失败仍发事件，订阅方会收到一张并不存在的卡片
    """
    core, db = vector
    db.insert_result = False

    assert core.register(make_card(), use_vectordb=True) is False
    assert db.calls[0][0] == 'insert'
    assert core._test_event_bus._outbox.list_after(0, 100) == []


def test_update_in_vector_mode_keeps_stored_owner_and_layer(vector):
    """TC-CORE-005 | Index update preserves owner/layer when they are not given

    输入: index holds alpha with owner 'stored-owner' and layer 'NetworkLayer';
          update(...) without owner/layer
    预期输出: 写入实体的 owner 仍为 stored-owner，layer 仍为 NetworkLayer
    断言点: update_entity 收到的 owner/layer + 返回 True
    防回归: 若更新把 owner/layer 置空，卡片会失去归属与层信息
    """
    core, db = vector
    db.key_records = [AgentRecord(agent_card=make_card(), owner='stored-owner',
                                  status='published', layer='NetworkLayer')]

    assert core.update('alpha', 'org-a', card_dict(description='v2'),
                       use_vectordb=True) is True

    entity = db.calls[-1][1]['entity']
    assert entity['owner'] == 'stored-owner'
    assert entity['layer'] == 'NetworkLayer'
    assert entity['status'] == 'published'
    assert entity['id'] == 'alpha::org-a'


def test_update_in_vector_mode_honours_explicit_layer(vector):
    """TC-CORE-006 | An explicit layer on update is normalized before writing

    输入: update(..., use_vectordb=True, layer='  ServiceLayer  ')
    预期输出: 写入实体的 layer = "ServiceLayer"
    断言点: 写入实体 layer + update_entity 调用次数 1
    防回归: 若显式 layer 被已有值覆盖，换层操作会静默失效
    """
    core, db = vector
    db.key_records = [AgentRecord(agent_card=make_card(), status='published',
                                  layer='NetworkLayer')]

    assert core.update('alpha', 'org-a', card_dict(), use_vectordb=True,
                       layer='  ServiceLayer  ') is True

    assert db.calls[-1][1]['entity']['layer'] == 'ServiceLayer'


def test_update_rejects_primary_key_change_in_vector_mode(vector):
    """TC-CORE-007 | Changing (name, organization) through update is refused

    输入: update('alpha', 'org-a', data with organization 'org-b')
    预期输出: ValueError('Cannot change primary key...')
    断言点: 异常类型 + 消息 + 未写入索引
    防回归: 若主键可改，索引里会留下两份指向同一逻辑卡片的实体
    """
    core, db = vector

    with pytest.raises(ValueError, match='Cannot change primary key'):
        core.update('alpha', 'org-a', card_dict(org='org-b'), use_vectordb=True)

    assert db.calls == []


def test_deregister_in_vector_mode_deletes_entity(vector):
    """TC-CORE-008 | Deregistration removes the index entity by its id

    输入: deregister('alpha', 'org-a', use_vectordb=True)
    预期输出: delete_entity 收到 id=alpha::org-a，返回 True
    断言点: 返回值 + 调用参数 + 索引条目被删除
    防回归: 若删除用错主键字段，索引里的卡片永远删不掉
    """
    core, db = vector
    core.register(make_card(), use_vectordb=True)

    assert core.deregister('alpha', 'org-a', use_vectordb=True) is True

    assert db.calls[-1] == ('delete', {'collection_name': core_module.COLLECTION_NAME,
                                       'id': 'alpha::org-a'})
    assert db.delete_result is True


# ==========================================================================
# Vector-index reads
# ==========================================================================

def test_find_exact_vector_mode_uses_the_narrowest_key(vector):
    """TC-CORE-009 | Exact search picks id/name/organization per given filters

    输入: find_exact with (name+org), (name), (organization) and no filters
    预期输出: 前三种分别用 id / name / organization 查询；无过滤时回读全部实体
    断言点: 每次调用传给索引的 key/value + 无过滤时解析出的卡片名
    防回归: 若总是全表扫描或用错键，精确查询会随注册量线性退化或串数据
    """
    core, db = vector

    db.query_results = [{'name': 'alpha'}]
    assert core.find_exact('alpha', 'org-a', use_vectordb=True) == [{'name': 'alpha'}]
    assert db.calls[-1] == ('query', {'collection_name': core_module.COLLECTION_NAME,
                                      'key': 'id', 'value': 'alpha::org-a'})

    assert core.find_exact('alpha', None, use_vectordb=True) == [{'name': 'alpha'}]
    assert db.calls[-1][1]['key'] == 'name'

    assert core.find_exact(None, 'org-a', use_vectordb=True) == [{'name': 'alpha'}]
    assert db.calls[-1][1]['key'] == 'organization'

    db.entities = {
        'alpha::org-a': {'id': 'alpha::org-a', 'name': 'alpha', 'organization': 'org-a',
                         'agent_card': json.dumps(card_dict())},
    }
    every = core.find_exact(use_vectordb=True)
    assert [card.name for card in every] == ['alpha']
    assert every[0].provider.organization == 'org-a'


def test_find_exact_with_layer_delegates_to_record_query(vector):
    """TC-CORE-010 | A layer filter turns exact search into a record query

    输入: find_exact(layer='ServiceLayer', use_vectordb=True)
    预期输出: 返回带该层的记录的卡片
    断言点: 卡片名 + 传给索引的 layer 过滤条件
    防回归: 若 layer 参数被忽略，层过滤查询会返回所有层的卡片
    """
    core, db = vector
    db.records = [AgentRecord(agent_card=make_card(), layer='ServiceLayer'),
                  AgentRecord(agent_card=make_card('beta'), layer='NetworkLayer')]

    cards = core.find_exact(layer='ServiceLayer', use_vectordb=True)

    # the injected index returns both; the core forwards the layer predicate
    assert [(card.name, card.description) for card in cards] == \
        [('alpha', 'alpha agent'), ('beta', 'alpha agent')]
    assert db.calls[-1][0] == 'find_records'
    assert db.calls[-1][1]['layer'] == 'ServiceLayer'


def test_find_records_vector_mode_forwards_filters_and_sorting(vector):
    """TC-CORE-011 | Record queries forward filters, paging and sort the result

    输入: index returns two records out of order; limit=2, offset=1
    预期输出: 按 (organization, name) 稳定排序；索引收到 limit/offset/layer/status
    断言点: 返回顺序 + 索引收到的查询参数
    防回归: 若排序丢失，分页会在不同后端之间抖动、重复或漏项
    """
    core, db = vector
    db.records = [AgentRecord(agent_card=make_card('zulu', 'org-b')),
                  AgentRecord(agent_card=make_card('alpha', 'org-a'))]

    records = core.find_records(name='alpha', organization='org-a',
                                layer='ServiceLayer', status='published',
                                use_vectordb=True, limit=2, offset=1)

    assert [record.agent_card.name for record in records] == ['alpha', 'zulu']
    query = db.record_filter
    assert query['collection_name'] == core_module.COLLECTION_NAME
    assert (query['name'], query['organization']) == ('alpha', 'org-a')
    assert (query['layer'], query['status']) == ('ServiceLayer', 'published')
    assert (query['limit'], query['offset']) == (2, 1)


def test_find_records_vector_fallback_filters_every_predicate(legacy_vector):
    """TC-CORE-012 | The legacy index fallback applies name/org/layer/status filters

    输入: legacy index (no find_records) holding 4 entities: matching card,
          a str card with another org, a card with an unknown layer value and
          a non-published card
    预期输出: 只有同时满足四类条件的实体被返回
    断言点: 每次查询返回的卡片名 + 非法 layer 被归一为 unknown
    防回归: 若任一过滤被跳过，旧索引部署会把未审批/别层的卡片暴露出去
    """
    core, db = legacy_vector
    db.entities = {
        'alpha::org-a': {'id': 'alpha::org-a', 'name': 'alpha', 'organization': 'org-a',
                         'agent_card': json.dumps(card_dict('alpha', 'org-a')),
                         'layer': 'ServiceLayer', 'status': 'published', 'owner': 'o1'},
        'beta::org-b': {'id': 'beta::org-b', 'name': 'beta', 'organization': 'org-b',
                        'agent_card': card_dict('beta', 'org-b'),
                        'layer': 'NetworkLayer', 'status': 'published'},
        'gamma::org-a': {'id': 'gamma::org-a', 'name': 'gamma', 'organization': 'org-a',
                         'agent_card': json.dumps(card_dict('gamma', 'org-a')),
                         'layer': 'x' * 70, 'status': 'published'},
        'delta::org-a': {'id': 'delta::org-a', 'name': 'delta', 'organization': 'org-a',
                         'agent_card': json.dumps(card_dict('delta', 'org-a')),
                         'layer': 'ServiceLayer', 'status': 'registered'},
    }

    by_name = core.find_records(name='ALPHA', use_vectordb=True)
    assert [record.agent_card.name for record in by_name] == ['alpha']

    by_org = core.find_records(organization='org-a', use_vectordb=True)
    assert [record.agent_card.name for record in by_org] == ['alpha', 'delta', 'gamma']

    by_layer = core.find_records(layer='ServiceLayer', use_vectordb=True)
    assert [record.agent_card.name for record in by_layer] == ['alpha', 'delta']

    published = core.find_records(status='published', layer='ServiceLayer',
                                  use_vectordb=True)
    assert [record.agent_card.name for record in published] == ['alpha']
    assert published[0].owner == 'o1'
    assert published[0].layer == 'ServiceLayer'

    gamma = [record for record in by_org if record.agent_card.name == 'gamma'][0]
    assert gamma.layer == UNKNOWN_LAYER


def test_get_by_key_vector_mode_parses_both_payload_shapes(vector):
    """TC-CORE-013 | get_by_key parses either an agent_card string or a raw dict

    输入: index returns {"agent_card": "<json>"}, then a bare card dict, then []
    预期输出: 前两种都解析出卡片；空结果返回 None
    断言点: 卡片名 + 无记录时 None
    防回归: 若只处理一种载荷形状，另一种存储版本的精确查询会整体失效
    """
    core, db = vector

    db.query_results = [{'agent_card': json.dumps(card_dict())}]
    assert core.get_by_key('alpha', 'org-a', use_vectordb=True).name == 'alpha'

    db.query_results = [card_dict('beta', 'org-b')]
    assert core.get_by_key('beta', 'org-b', use_vectordb=True).name == 'beta'

    db.query_results = []
    assert core.get_by_key('ghost', 'org-a', use_vectordb=True) is None


def test_get_by_key_with_owner_enforces_index_ownership(vector):
    """TC-CORE-014 | Ownership is enforced when the index keeps records

    输入: index record owned by 'owner-1'; lookups with None / matching / other
    预期输出: None owner 放行；相同 owner 放行；其他 owner 返回 None
    断言点: 三次返回的 owner 字段与 None
    防回归: 若索引分支跳过 owner 校验，跨租户覆盖成为可能
    """
    core, db = vector
    db.key_records = [AgentRecord(agent_card=make_card(), owner='owner-1',
                                  status='published', layer='ServiceLayer')]

    assert core.get_by_key_with_owner('alpha', 'org-a', use_vectordb=True).owner == \
        'owner-1'
    matched = core.get_by_key_with_owner('alpha', 'org-a', owner='owner-1',
                                         use_vectordb=True)
    assert matched.owner == 'owner-1'
    assert matched.layer == 'ServiceLayer'
    assert core.get_by_key_with_owner('alpha', 'org-a', owner='intruder',
                                      use_vectordb=True) is None


def test_get_by_key_with_owner_legacy_index_path(legacy_vector):
    """TC-CORE-015 | The legacy index path rebuilds a record and checks ownership

    输入: legacy index query returns a str card owned by 'owner-1', a dict card
          with an invalid layer, an owner mismatch, and an empty result
    预期输出: 记录带 owner/status/layer；非法 layer 归一为 unknown；
              owner 不匹配与空结果都返回 None
    断言点: 记录字段 + 两次 None
    防回归: 若旧索引不做归属校验，越权更新/删除会绕过 owner 隔离
    """
    core, db = legacy_vector

    db.query_results = [{'agent_card': json.dumps(card_dict()), 'owner': 'owner-1',
                         'status': 'registered', 'layer': 'ServiceLayer'}]
    record = core.get_by_key_with_owner('alpha', 'org-a', owner='owner-1',
                                        use_vectordb=True)
    assert (record.owner, record.status, record.layer) == \
        ('owner-1', 'registered', 'ServiceLayer')

    db.query_results = [{'agent_card': card_dict(), 'owner': None,
                         'layer': 'x' * 70}]
    fallback = core.get_by_key_with_owner('alpha', 'org-a', use_vectordb=True)
    assert fallback.layer == UNKNOWN_LAYER
    assert fallback.status == 'published'

    db.query_results = [{'agent_card': card_dict(), 'owner': 'owner-1'}]
    assert core.get_by_key_with_owner('alpha', 'org-a', owner='intruder',
                                      use_vectordb=True) is None

    db.query_results = []
    assert core.get_by_key_with_owner('ghost', 'org-a', use_vectordb=True) is None

    # the same index generation answers ownership listings through query_by_key
    db.query_results = [card_dict()]
    legacy = core.find_by_owner('owner-1', use_vectordb=True)
    assert [record.agent_card.name for record in legacy] == ['alpha']
    assert db.calls[-1][1] == {'collection_name': core_module.COLLECTION_NAME,
                               'key': 'owner', 'value': 'owner-1'}


def test_find_by_owner_supports_the_modern_index(vector):
    """TC-CORE-016 | find_by_owner delegates to the index record query

    输入: modern index (find_records) holding one record for owner-1
    预期输出: 返回该记录；索引收到 collection/owner/status=None
    断言点: 记录数量 + owner + 委托参数
    防回归: 若 owner 查询退化成按 id 查询，按归属列出卡片会得到空集
    """
    modern_core, modern_db = vector
    modern_db.records = [AgentRecord(agent_card=make_card(), owner='owner-1')]

    owned = modern_core.find_by_owner('owner-1', use_vectordb=True)

    assert [record.owner for record in owned] == ['owner-1']
    assert modern_db.calls[-1][1] == {'collection_name': core_module.COLLECTION_NAME,
                                      'owner': 'owner-1', 'status': None}


def test_retrieve_by_task_vector_mode_selects_published_candidates(vector):
    """TC-CORE-017 | Vector retrieval filters by status then by the model selection

    输入: index returns one published and one pending candidate; the model
          selects alpha/org-a; layer filter given
    预期输出: 只返回被选中且已发布的卡片；索引收到 embedding/layer/top_n
    断言点: 返回卡片名 + 检索参数 + 提示词只包含已发布候选
    防回归: 若状态过滤在模型选择之后丢失，未审批卡片会被语义检索返回
    """
    core, db = vector
    core._llm = _FakeLLM(payload=[{'name': 'alpha', 'organization': 'org-a'}])
    db.retrieve_results = [
        {'name': 'alpha', 'organization': 'org-a', 'description': 'alpha agent',
         'status': 'published'},
        {'name': 'pending', 'organization': 'org-a', 'description': 'pending agent',
         'status': 'registered'},
    ]

    result = core.retrieve_by_task('diagnostics', 3, use_vectordb=True,
                                   layer='ServiceLayer')

    assert [candidate['name'] for candidate in result] == ['alpha']
    retrieve = db.calls[-1][1]
    assert retrieve['embedding'] == [0.1, 0.2]
    assert retrieve['top_n'] == 3
    assert retrieve['layer'] == 'ServiceLayer'
    prompt = core._llm.prompts[0]
    assert 'alpha' in prompt
    assert 'pending' not in prompt


def test_retrieve_by_task_vector_mode_returns_empty_without_candidates(vector):
    """TC-CORE-018 | No published candidate short-circuits before the model call

    输入: index returns only a pending candidate
    预期输出: 返回 []，且模型从未被调用
    断言点: 空列表 + 提示词列表为空
    防回归: 若空候选仍然调用模型，语义搜索会在冷启动时花钱且报错
    """
    core, db = vector
    core._llm = _FakeLLM()
    db.retrieve_results = [{'name': 'pending', 'organization': 'org-a',
                            'status': 'registered'}]

    assert core.retrieve_by_task('diagnostics', 3, use_vectordb=True) == []
    assert core._llm.prompts == []


def test_retrieve_records_by_task_uses_index_selector(vector):
    """TC-CORE-019 | The index-side record retrieval receives the selector contract

    输入: index implements retrieve_records; layer and status filters given
    预期输出: 索引收到 collection/embedding/top_n/layer/status/selector/task
    断言点: 返回记录 + 全部委托参数
    防回归: 若 selector 未传下去，索引会退化为纯向量近邻、绕过审批过滤
    """
    core, db = vector
    core._llm = _FakeLLM()
    expected = [AgentRecord(agent_card=make_card(), status='published')]
    db.retrieved_records = expected

    records = core.retrieve_records_by_task('diagnostics', 4, layer='ServiceLayer',
                                            status='published', use_vectordb=True)

    assert records == expected
    args = db.record_filter
    assert args['collection_name'] == core_module.COLLECTION_NAME
    assert args['embedding'] == [0.1, 0.2]
    assert args['top_n'] == 4
    assert args['layer'] == 'ServiceLayer'
    assert args['status'] == 'published'
    assert args['task'] == 'diagnostics'
    assert callable(args['selector'])


# ==========================================================================
# Vector-only mode (no record store)
# ==========================================================================

def test_vector_only_mode_registers_and_counts_from_the_index(registry):
    """TC-CORE-020 | Vector-only mode still registers and counts via the index

    输入: core.use_vectordb flipped True with an injected index
    预期输出: register 返回 True；count() 等于索引实体数；
              事件 payload 的 tags 为空（没有记录库可读）
    断言点: 返回值 + count + 事件 data['tags'] == []
    防回归: 若 tags 读取直接抛错，向量模式下注册会整体失败
    """
    db = _LegacyVectorDB()
    registry.use_vectordb = True
    registry.vectordb = db
    registry.embedding_tool = _FakeEmbedding()

    assert registry.register(make_card()) is True
    assert registry.count() == 1

    events = registry._test_event_bus._outbox.list_after(0, 100)
    assert [event.event_type for event in events] == [EventType.AGENT_REGISTERED]
    assert events[0].data['tags'] == []
    assert events[0].data['discovery_public'] is True


# ==========================================================================
# No record store (authoritative surfaces)
# ==========================================================================

def test_without_record_store_reads_report_unknown_instead_of_guessing(bare):
    """TC-CORE-021 | Missing storage yields explicit “unknown”, not empty success

    输入: storage=None; get_status / _stored_status / find_all
    预期输出: get_status None；_stored_status pending；find_all []
    断言点: 三个返回值
    防回归: 若返回 published/空列表冒充“没有这个卡片”，运维无法区分
              “部署缺存储”和“确实没注册”
    """
    assert bare.get_status('alpha', 'org-a') is None
    assert bare._stored_status('alpha', 'org-a') == PENDING_STATUS
    assert bare.find_all() == []


def test_without_record_store_writes_are_refused(bare):
    """TC-CORE-022 | Mutations without storage report False and change nothing

    输入: storage=None; update_status / update_agent_tags
    预期输出: 两者都返回 False
    断言点: 两个返回值
    防回归: 若返回 True，调用方会以为状态/标签已经落盘
    """
    assert bare.update_status('alpha', 'org-a', 'published') is False
    assert bare.update_agent_tags('alpha', 'org-a', ['prod']) is False


def test_without_record_store_queries_return_empty(bare):
    """TC-CORE-023 | Listing surfaces without storage return empty collections

    输入: storage=None; get_status_history / get_agents_by_status / tags queries
    预期输出: 空列表 / None
    断言点: 每个返回值
    防回归: 若返回 None 而不是 []，调用方枚举时会 TypeError
    """
    assert bare.get_status_history('alpha', 'org-a') == []
    assert bare.get_agents_by_status('published') == []
    assert bare.get_agent_tags('alpha', 'org-a') == []
    assert bare.find_agents_by_tag('prod') == []
    assert bare.get_tag('tag-1') is None
    assert bare.get_tag_by_name('prod') is None
    assert bare.list_tags() == []


def test_without_record_store_tag_crud_is_refused(bare):
    """TC-CORE-024 | Tag management without storage fails closed

    输入: storage=None; create_tag / update_tag / delete_tag
    预期输出: 分别返回 None / False / False
    断言点: 三个返回值
    防回归: 若 create_tag 返回 Tag 对象，调用方会持久化一个不存在的标签
    """
    assert bare.create_tag('prod') is None
    assert bare.update_tag('tag-1', 'staging') is False
    assert bare.delete_tag('tag-1') is False
    assert bare.get_created_at('alpha', 'org-a') == ''
    assert bare.get_updated_at('alpha', 'org-a') == ''


# ==========================================================================
# Authoritative tag lifecycle
# ==========================================================================

def test_tag_lifecycle_rename_and_delete_rewrites_agent_references(registry, bus):
    """TC-CORE-025 | Renaming/deleting a tag rewrites and then unbinds agent tags

    输入: agent alpha tagged ['prod', 'edge']; tag 'prod' created; renamed to
          'staging'; then the 'staging' tag deleted
    预期输出: alpha 的标签先变为 ['staging', 'edge']，删除后只剩 ['edge']；
              每次变更发出一条 AGENT_UPDATED 事件
    断言点: 每次读回的标签列表 + 事件类型序列 + 标签实体最终不存在
    防回归: 若引用重写被跳过，重命名后会留下指向旧名字的悬空标签
    """
    registry.register(make_card(), owner='owner-1')
    assert registry.update_agent_tags('alpha', 'org-a', ['prod', 'edge']) is True

    tag = registry.create_tag('prod')
    assert tag is not None
    assert registry.get_tag_by_name('prod').tag_id == tag.tag_id

    assert registry.update_tag(tag.tag_id, 'staging') is True
    assert registry.get_agent_tags('alpha', 'org-a') == ['staging', 'edge']
    assert registry.get_tag_by_name('staging') is not None
    assert registry.get_tag_by_name('prod') is None

    assert registry.delete_tag(tag.tag_id) is True
    assert registry.get_agent_tags('alpha', 'org-a') == ['edge']
    assert registry.get_tag(tag.tag_id) is None
    assert [event.event_type for event in bus._outbox.list_after(0, 100)] == [
        EventType.AGENT_REGISTERED,
        EventType.AGENT_UPDATED,
        EventType.AGENT_UPDATED,
        EventType.AGENT_UPDATED,
    ]


def test_tag_rename_is_idempotent_and_rejects_taken_names(registry):
    """TC-CORE-026 | Tag rename handles no-op, conflicts and unknown ids

    输入: rename 'prod' to itself; rename 'prod' to an existing 'edge'; rename
          an unknown id; delete an unknown id
    预期输出: True / False / False / False
    断言点: 四个返回值 + 'edge' 与 'prod' 都仍然存在
    防回归: 若冲突未检查，两个标签会合并成一条，历史引用丢失
    """
    prod = registry.create_tag('prod')
    edge = registry.create_tag('edge')
    assert registry.get_tag_by_name('edge').tag_id == edge.tag_id

    assert registry.update_tag(prod.tag_id, 'prod') is True
    assert registry.update_tag(prod.tag_id, 'edge') is False
    assert registry.update_tag('missing-tag', 'other') is False
    assert registry.delete_tag('missing-tag') is False
    assert registry.get_tag_by_name('prod') is not None
    assert registry.get_tag_by_name('edge') is not None


def test_create_tag_reports_duplicate_as_none(registry):
    """TC-CORE-027 | A duplicate tag name is reported as None, not raised

    输入: create_tag('prod') twice
    预期输出: 第一次返回 Tag，第二次返回 None
    断言点: 两次返回值的类型 + 标签表里只有一条
    防回归: 若重复被静默接受，标签名冲突会破坏按名查询
    """
    first = registry.create_tag('prod')
    second = registry.create_tag('prod')

    assert first is not None
    assert second is None
    assert [tag.name for tag in registry.list_tags()] == ['prod']


def test_tag_update_and_delete_failures_surface_as_false_or_runtimeerror(registry,
                                                                        monkeypatch):
    """TC-CORE-028 | Storage refusals during tag writes are surfaced, never hidden

    输入: storage.update_tag returns False; then storage.delete_tag returns False
    预期输出: update_tag 返回 False；delete_tag 抛 RuntimeError
    断言点: 返回值 / 异常类型与消息
    防回归: 若删除失败被吞掉，管理层会以为标签已删而留下孤儿引用
    """
    tag = registry.create_tag('prod')
    monkeypatch.setattr(registry.storage, 'update_tag', lambda *a, **k: False)
    assert registry.update_tag(tag.tag_id, 'staging') is False

    monkeypatch.setattr(registry.storage, 'delete_tag', lambda *a, **k: False)
    with pytest.raises(RuntimeError, match='Tag disappeared during deletion'):
        registry.delete_tag(tag.tag_id)


def test_tag_reference_rewrite_failure_aborts_the_rename(registry, monkeypatch):
    """TC-CORE-029 | A failed agent-tag rewrite aborts the whole rename

    输入: agent tagged 'prod'; storage.update_agent_tags returns False
    预期输出: RuntimeError('Agent tag references could not be updated')
    断言点: 异常类型与消息 + 标签名未被改成 staging
    防回归: 若失败被忽略，标签改名但卡片仍带旧名，按标签查询全部失效
    """
    registry.register(make_card())
    registry.update_agent_tags('alpha', 'org-a', ['prod'])
    tag = registry.create_tag('prod')
    monkeypatch.setattr(registry.storage, 'update_agent_tags', lambda *a, **k: False)

    with pytest.raises(RuntimeError, match='Agent tag references could not be updated'):
        registry.update_tag(tag.tag_id, 'staging')

    assert registry.get_tag_by_name('prod') is not None


# ==========================================================================
# Status transitions
# ==========================================================================

def test_status_transition_is_recorded_and_published(registry, bus):
    """TC-CORE-030 | Approval records history and announces the new visibility

    输入: card registered as pending; update_status('published', reason, operator)
    预期输出: 状态变 published；历史一条 registered->published；事件
              AGENT_REGISTERED 带完整卡片
    断言点: 状态 + 历史字段 + 事件类型与 data 里的 name
    防回归: 若历史或事件缺失，发布者与订阅方都无法解释“何时可见”
    """
    registry.register_with_status(make_card(), initial_status='registered')

    assert registry.update_status('alpha', 'org-a', 'published',
                                  reason='approved', operator='reviewer') is True

    assert registry.get_status('alpha', 'org-a') == 'published'
    history = registry.get_status_history('alpha', 'org-a')
    assert len(history) == 1
    assert (history[0]['from_status'], history[0]['to_status']) == \
        ('registered', 'published')
    assert history[0]['reason'] == 'approved'
    assert history[0]['operator'] == 'reviewer'

    events = bus._outbox.list_after(0, 100)
    assert [event.event_type for event in events] == [EventType.AGENT_REGISTERED]
    assert events[0].data['agent_card']['name'] == 'alpha'


def test_same_status_write_is_an_idempotent_noop(registry, bus):
    """TC-CORE-031 | Rewriting the current status changes nothing

    输入: published card; update_status('published')
    预期输出: 返回 True；没有新增历史，也没有新事件
    断言点: 返回值 + 历史长度 0 + 事件数仍为 1（注册事件）
    防回归: 若同状态写也追加历史，审计里会堆满无意义的转换记录
    """
    registry.register(make_card())
    baseline = len(bus._outbox.list_after(0, 100))

    assert registry.update_status('alpha', 'org-a', 'published') is True
    assert registry.get_status_history('alpha', 'org-a') == []
    assert len(bus._outbox.list_after(0, 100)) == baseline


def test_legacy_uppercase_status_is_normalized_without_visibility_change(registry, bus):
    """TC-CORE-032 | A legacy mixed-case status is normalized in place

    输入: stored status forced to 'PUBLISHED'; update_status('published')
    预期输出: 返回 True；状态归一为 published；事件为 AGENT_UPDATED
              （可见性未变化，不算重新发布）
    断言点: 状态值 + 事件类型
    防回归: 若大小写差异被当成可见性变化，会重复广播“已注册”事件
    """
    registry.register(make_card())
    registry.storage.update_status('alpha', 'org-a', 'PUBLISHED')
    bus._outbox.list_after(0, 100)  # drain baseline for readability

    assert registry.update_status('alpha', 'org-a', 'published') is True

    assert registry.get_status('alpha', 'org-a') == 'published'
    events = bus._outbox.list_after(0, 100)
    assert events[-1].event_type == EventType.AGENT_UPDATED


def test_invalid_status_and_illegal_transition_are_rejected(registry):
    """TC-CORE-033 | Unknown statuses and illegal transitions raise ValueError

    输入: update_status('archived'); then published -> registered -> published
          is fine but deprecated -> published must fail
    预期输出: 两次 ValueError，消息分别指出状态名与允许的目标
    断言点: 异常类型 + 消息关键字 + 状态未被破坏
    防回归: 若非法迁移被接受，deprecated 卡片可以被重新发布
    """
    registry.register(make_card())

    with pytest.raises(ValueError, match="Invalid status 'archived'"):
        registry.update_status('alpha', 'org-a', 'archived')

    assert registry.update_status('alpha', 'org-a', 'deprecated',
                                  reason='eol') is True
    with pytest.raises(ValueError, match='Invalid status transition'):
        registry.update_status('alpha', 'org-a', 'published')
    assert registry.get_status('alpha', 'org-a') == 'deprecated'


def test_update_status_on_missing_card_returns_false(registry):
    """TC-CORE-034 | A status change on an absent card is a no-op

    输入: update_status for a card that was never registered
    预期输出: False
    断言点: 返回值
    防回归: 若缺失记录被当作 pending 再写入历史，会凭空产生一行转换
    """
    assert registry.update_status('ghost', 'org-a', 'published') is False
    assert registry.get_status_history('ghost', 'org-a') == []


def test_rejected_card_resubmission_returns_to_pending(registry, bus):
    """TC-CORE-035 | Replacing a rejected card returns it to pending review

    输入: card registered as pending, then rejected with a reason; update() with
          corrected content
    预期输出: 状态变回 registered；历史记录 rejected->registered，原因
              'resubmitted'；不发出公开事件
    断言点: 状态 + 历史最后一条 + 事件数量不变
    防回归: 若重投递保持 rejected，发布者的申诉路径被永久堵死
    """
    registry.register_with_status(make_card(), initial_status='registered')
    registry.update_status('alpha', 'org-a', 'rejected', reason='bad schema',
                           operator='reviewer')
    before = len(bus._outbox.list_after(0, 100))

    assert registry.update('alpha', 'org-a', card_dict(description='fixed')) is True

    assert registry.get_status('alpha', 'org-a') == 'registered'
    history = registry.get_status_history('alpha', 'org-a')
    assert (history[0]['from_status'], history[0]['to_status']) == \
        ('rejected', 'registered')
    assert history[0]['reason'] == 'resubmitted'
    # the correction is not publicly announced while the card is pending
    assert len(bus._outbox.list_after(0, 100)) == before


# ==========================================================================
# Events
# ==========================================================================

def test_notifier_failure_does_not_fail_the_mutation(registry, bus, monkeypatch):
    """TC-CORE-036 | A consumer notification failure never rolls back a commit

    输入: bus.notify raises RuntimeError during the commit hook
    预期输出: register 返回 True 且记录已落库
    断言点: 返回值 + 存储中的记录
    防回归: 若通知异常冒泡出提交钩子，一次消费者故障就会回滚成功写入
    """
    def _boom(event):
        raise RuntimeError('listener exploded')

    monkeypatch.setattr(bus, 'notify', _boom)

    assert registry.register(make_card()) is True
    assert registry.get_status('alpha', 'org-a') == 'published'


def test_health_state_cleanup_failure_is_only_logged(registry, monkeypatch):
    """TC-CORE-037 | A failing health-state cleanup does not fail deregistration

    输入: get_health_service raises RuntimeError during deregister
    预期输出: deregister 返回 True 且记录已删除
    断言点: 返回值 + get_status None
    防回归: 若清理异常冒泡，健康服务故障会让卡片永远删不掉
    """
    registry.register(make_card())

    def _boom():
        raise RuntimeError('health store unavailable')

    monkeypatch.setattr(health_module, 'get_health_service', _boom)

    assert registry.deregister('alpha', 'org-a') is True
    assert registry.get_status('alpha', 'org-a') is None


def test_deregister_publishes_a_removal_only_for_published_cards(registry, bus):
    """TC-CORE-038 | Pending cards never produce a public removal event

    输入: a pending card and a published card, both deregistered
    预期输出: 只有 published 卡片产生 AGENT_DEREGISTERED
    断言点: 事件类型序列 + 卡片确实删除
    防回归: 若 pending 卡片也广播删除，订阅方会看到从未公布过的名字
    """
    registry.register(make_card('live', 'org-a'))
    registry.register_with_status(make_card('pending', 'org-a'), initial_status='registered')
    baseline = len(bus._outbox.list_after(0, 100))

    assert registry.deregister('pending', 'org-a') is True
    assert registry.get_status('pending', 'org-a') is None
    assert len(bus._outbox.list_after(0, 100)) == baseline

    assert registry.deregister('live', 'org-a') is True
    events = bus._outbox.list_after(0, 100)
    assert events[-1].event_type == EventType.AGENT_DEREGISTERED
    assert events[-1].data['name'] == 'live'


# ==========================================================================
# Metadata
# ==========================================================================

def test_metadata_includes_health_and_registration_fields(registry, health):
    """TC-CORE-039 | get_metadata returns status, tags, layer, timestamps and health

    输入: published card with owner, tag and layer; heartbeat healthy
    预期输出: status=published；tag=['prod']；layer=ServiceLayer；
              created_at/updated_at 非空；health='healthy'
    断言点: 六个字段值
    防回归: 若健康字段被漏掉，运维面板会把健康卡片显示为 unknown
    """
    registry.register(make_card(), owner='owner-1', layer='ServiceLayer')
    registry.update_agent_tags('alpha', 'org-a', ['prod'])
    service = health()
    service.record_heartbeat('alpha', 'org-a')

    metadata = registry.get_metadata('alpha', 'org-a')

    assert metadata['agent_name'] == 'alpha'
    assert metadata['organization'] == 'org-a'
    assert metadata['status'] == 'published'
    assert metadata['tag'] == ['prod']
    assert metadata['layer'] == 'ServiceLayer'
    assert metadata['created_at']
    assert metadata['updated_at']
    assert metadata['health'] == 'healthy'


def test_metadata_survives_a_health_lookup_failure(registry, monkeypatch):
    """TC-CORE-040 | Metadata enrichment is best-effort

    输入: get_health_service raises RuntimeError
    预期输出: 元数据仍返回，且不带 health 字段
    断言点: status 字段 + 'health' not in 结果
    防回归: 若健康查询异常冒泡，一次健康服务故障会让元数据接口 500
    """
    registry.register(make_card())

    def _boom():
        raise RuntimeError('health store unavailable')

    monkeypatch.setattr(health_module, 'get_health_service', _boom)

    metadata = registry.get_metadata('alpha', 'org-a')

    assert metadata['status'] == 'published'
    assert 'health' not in metadata


# ==========================================================================
# Semantic selection helpers
# ==========================================================================

def test_llm_response_parser_accepts_fenced_and_bare_json():
    """TC-CORE-041 | The selection parser accepts fenced, embedded and bare JSON

    输入: ```json [...] ```, prose + [...], and a bare JSON array
    预期输出: 三种都解析成 list
    断言点: 三个返回值的长度与首元素
    防回归: 若只支持裸 JSON，模型加代码围栏后语义搜索会整体 503
    """
    core = RegistryCore.__new__(RegistryCore)

    fenced = core._parse_llm_json_response(
        '```json\n[{"name": "alpha"}]\n```')
    embedded = core._parse_llm_json_response(
        'selected: [{"name": "alpha", "organization": "org-a"}] done')
    bare = core._parse_llm_json_response('[]')

    assert fenced == [{'name': 'alpha'}]
    assert embedded == [{'name': 'alpha', 'organization': 'org-a'}]
    assert bare == []


def test_llm_response_parser_rejects_empty_text():
    """TC-CORE-042 | An empty model answer is a hard error

    输入: _parse_llm_json_response('   ')
    预期输出: ValueError('Empty semantic selection response')
    断言点: 异常类型 + 消息
    防回归: 若空字符串被当成“没有匹配”，模型故障会被伪装成零结果
    """
    core = RegistryCore.__new__(RegistryCore)

    with pytest.raises(ValueError, match='Empty semantic selection response'):
        core._parse_llm_json_response('   ')


def test_agents_info_builds_entries_for_cards_and_dicts():
    """TC-CORE-043 | Candidate summaries cover both proto cards and index dicts

    输入: one AgentCard with a skill and one dict candidate
    预期输出: 两条摘要，字段齐全，dict 条目不含 skills
    断言点: 两条摘要的完整内容
    防回归: 若技能列表丢失，模型无法按能力选择代理
    """
    core = RegistryCore.__new__(RegistryCore)
    card = AgentCard(name='alpha', description='alpha agent', version='1.0.0',
                     provider={'organization': 'org-a', 'url': 'https://example.com/a'})
    card.skills.add(id='s1', name='diagnose', description='diagnose faults', tags=[])

    info = core._build_agents_info([card, {'name': 'beta', 'description': 'b',
                                           'organization': 'org-b'}])

    assert info == [
        {'name': 'alpha', 'description': 'alpha agent', 'organization': 'org-a',
         'skills': ['diagnose']},
        {'name': 'beta', 'description': 'b', 'organization': 'org-b'},
    ]


def test_semantic_selection_failure_maps_to_semantic_unavailable(registry):
    """TC-CORE-044 | A model failure becomes “semantic search unavailable”

    输入: llm.ask_llm raises RuntimeError
    预期输出: SemanticSearchUnavailable('Semantic search is temporarily unavailable')
    断言点: 异常类型 + 消息
    防回归: 若异常原样冒泡，模型故障会被报告为 500 而不是可重试的 503
    """
    registry._llm = MagicMock()
    registry._llm.ask_llm.side_effect = RuntimeError('model exploded')

    with pytest.raises(SemanticSearchUnavailable,
                       match='Semantic search is temporarily unavailable'):
        registry._select_agents_by_llm('task', [{'name': 'alpha'}], 3)


def test_embedding_failure_maps_to_semantic_unavailable(vector):
    """TC-CORE-045 | A broken embedding model is a retryable search outage

    输入: embedding_tool.embed raises RuntimeError
    预期输出: SemanticSearchUnavailable
    断言点: 异常类型 + 消息
    防回归: 若写路径复用该封装，注册失败会被误报成“搜索暂不可用”
    """
    core, _ = vector
    core.embedding_tool = _FakeEmbedding(fail=True)

    with pytest.raises(SemanticSearchUnavailable):
        core._embed_for_search('diagnostics')


def test_retrieve_records_by_task_returns_empty_without_candidates(registry):
    """TC-CORE-046 | No candidate records short-circuits before the model call

    输入: empty registry; retrieve_records_by_task('task', 5)
    预期输出: []，模型从未被调用
    断言点: 空列表 + 提示词列表为空
    防回归: 若空候选仍调用模型，冷启动部署会白花钱并暴露延迟
    """
    registry._llm = _FakeLLM()

    assert registry.retrieve_records_by_task('diagnostics', 5) == []
    assert registry._llm.prompts == []


def test_empty_task_skips_semantic_retrieval(registry):
    """TC-CORE-047 | An empty task never reaches the model

    输入: retrieve_by_task('') and retrieve_records_by_task('')
    预期输出: 两者都返回 [] 且不调用模型
    断言点: 两个空列表 + 提示词列表为空
    防回归: 若空 task 进入模型，调用方拼错参数会变成一次付费请求
    """
    registry._llm = _FakeLLM()

    assert registry.retrieve_by_task('', 5) == []
    assert registry.retrieve_records_by_task('', 5) == []
    assert registry._llm.prompts == []


def test_retrieve_records_by_task_selects_from_authoritative_records(registry):
    """TC-CORE-048 | Non-vector retrieval filters records by the model selection

    输入: two published cards; model selects alpha/org-a
    预期输出: 只返回 alpha 的记录，保留 owner 等注册元数据
    断言点: 记录里的卡片名与 owner + 提示词包含两个候选
    防回归: 若返回的是卡片而非记录，调用方会丢失归属信息
    """
    registry.register(make_card('alpha', 'org-a'), owner='owner-1')
    registry.register(make_card('beta', 'org-a'))
    registry._llm = _FakeLLM(payload=[{'name': 'alpha', 'organization': 'org-a'}])

    records = registry.retrieve_records_by_task('diagnostics', 5)

    assert [record.agent_card.name for record in records] == ['alpha']
    assert records[0].owner == 'owner-1'
    assert 'beta' in registry._llm.prompts[0]


def test_retrieve_by_task_drops_cards_unpublished_after_selection(registry):
    """TC-CORE-049 | A card pending approval is dropped even if the model picked it

    输入: published + pending card; model selects the pending one
    预期输出: 结果为空
    断言点: 返回值为 []
    防回归: 若选择后不复核权威状态，模型可以在两次读之间泄露未审批卡片
    """
    registry.register(make_card('live', 'org-a'))
    registry.register_with_status(make_card('pending', 'org-a'), initial_status='registered')
    registry._llm = _FakeLLM(payload=[{'name': 'pending', 'organization': 'org-a'}])

    assert registry.retrieve_by_task('diagnostics', 5) == []


# ==========================================================================
# Authoritative storage wiring
# ==========================================================================

def test_register_persists_owner_status_and_timestamps(registry, bus):
    """TC-CORE-050 | Registration writes owner/status/layer plus timestamps

    输入: register(card, owner='owner-1', layer='ServiceLayer')
    预期输出: 记录 owner/status/layer 正确，created_at/updated_at 非空，
              outbox 里一条 AGENT_REGISTERED 且 data 带卡片
    断言点: 记录字段 + count + 事件 data
    防回归: 若注册绕过记录库，owner 隔离与审批状态全部失效
    """
    assert registry.register(make_card(), owner='owner-1',
                             layer='ServiceLayer') is True

    record = registry.get_by_key_with_owner('alpha', 'org-a')
    assert record.owner == 'owner-1'
    assert record.status == DISCOVERABLE_STATUS
    assert record.layer == 'ServiceLayer'
    assert record.agent_card.description == 'alpha agent'
    assert registry.get_created_at('alpha', 'org-a')
    assert registry.get_updated_at('alpha', 'org-a')
    assert registry.count() == 1

    events = bus._outbox.list_after(0, 100)
    assert [event.event_type for event in events] == [EventType.AGENT_REGISTERED]
    assert events[0].data['layer'] == 'ServiceLayer'
    assert events[0].data['agent_card']['name'] == 'alpha'


def test_register_duplicate_returns_false(registry):
    """TC-CORE-051 | A duplicate (name, organization) is refused by the core

    输入: register the same card twice
    预期输出: 第二次返回 False，记录数仍为 1
    断言点: 返回值 + count
    防回归: 若重复被接受，后一次注册会覆盖前一次的 owner
    """
    assert registry.register(make_card(), owner='owner-1') is True
    assert registry.register(make_card(), owner='intruder') is False

    assert registry.count() == 1
    assert registry.get_by_key_with_owner('alpha', 'org-a').owner == 'owner-1'


def test_deregister_missing_card_returns_false(registry):
    """TC-CORE-052 | Removing an absent card reports False

    输入: deregister for a card that was never registered
    预期输出: False
    断言点: 返回值
    防回归: 若缺失删除返回 True，DELETE 接口会把 404 报成 200
    """
    assert registry.deregister('ghost', 'org-a') is False
