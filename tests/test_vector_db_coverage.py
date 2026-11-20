# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``common.vector_db`` with no Milvus service available.

The production code talks to ``pymilvus.MilvusClient``.  Here that client is
replaced by a ``MagicMock`` double so every branch — connection failure,
collection/index creation, dimension validation, batch insert, vector search,
empty result, backend exception — can be driven deterministically.  Cases
assert the payload handed to the client, the value returned to the registry
core, the log line that operators rely on, and the exception type/message on
the paths that are documented to raise.

Nothing here opens a socket, sleeps, or leaves a global singleton modified:
the module-level ``vectordb_tool_instance`` cache is snapshotted and restored,
and the package ``__init__`` is probed through a throw-away module object.
"""

import importlib.util
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from pymilvus import DataType, MilvusException

import common.vector_db as vector_db_package
from agent_registry.model.agent_layer import UNKNOWN_LAYER
from agent_registry.persistence.base import AgentRecord
from agent_registry.persistence.milvus_layer_migration import (
    LayerMigrationRequiredError,
)
from common.vector_db.vector_db_client import milvus_client as milvus_module
from common.vector_db.vector_db_client.config import vector_db_config as config_module
from common.vector_db.vector_db_client.config import (
    vector_db_client_registry as registry_module,
)
from common.vector_db.vector_db_client.config.vector_db_client import VectorDBClient
from common.vector_db.vector_db_client.config.vector_db_config import (
    VectorDBConfig,
    VectorDBType,
    convert_vectordb_type,
    get_vectordb_config,
    get_vectordb_config_by_type,
)
from common.vector_db.vector_db_client.milvus_client import (
    EMBEDDING_VECTOR_DIVISION_LENGTH,
    VARCHAR_MAX_LENGTH,
    MilvusDBClient,
)


DIM = EMBEDDING_VECTOR_DIVISION_LENGTH
EMBEDDING = [0.5] * DIM
COLLECTION = "agents"

ALL_FIELDS = [
    "id", "embedding", "name", "description", "organization", "agent_card",
    "status", "owner", "layer",
]
LEGACY_FIELDS = ["id", "embedding", "name", "description", "organization", "agent_card"]

AGENT_CARD = {
    "name": "agent-a",
    "description": "test agent",
    "version": "1.0.0",
    "provider": {"organization": "org-a", "url": "https://example.com/a"},
    "capabilities": {"streaming": False},
    "default_input_modes": ["text/plain"],
    "default_output_modes": ["text/plain"],
    "skills": [
        {"id": "s1", "name": "skill-1", "description": "first skill", "tags": ["t1"]},
    ],
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _schema(fields=None, dynamic=False):
    """Collection description as ``describe_collection`` returns it."""

    return {
        "fields": [{"name": name} for name in (ALL_FIELDS if fields is None else fields)],
        "enable_dynamic_field": dynamic,
    }


def _card_json(**overrides):
    card = dict(AGENT_CARD)
    card.update(overrides)
    return json.dumps(card)


def _entity(agent_id="agent-a", name="agent-a", organization="org-a", layer="omc",
            card=None):
    entity = {
        "id": agent_id,
        "embedding": EMBEDDING,
        "name": name,
        "description": "test agent",
        "organization": organization,
        "agent_card": _card_json(
            name=name,
            provider={"organization": organization, "url": "https://example.com/a"},
        ) if card is None else card,
    }
    if layer is not None:
        entity["layer"] = layer
    return entity


def _fake_client(*, has_collection=True, schema=None, insert_result=None,
                 search_result=None, query_result=None):
    """A Milvus client double that records every call."""

    client = MagicMock(name="milvus_client_double")
    client.has_collection.return_value = has_collection
    client.describe_collection.return_value = (
        _schema() if schema is None else schema
    )
    client.insert.return_value = (
        {"insert_count": 1, "ids": ["agent-a"]}
        if insert_result is None else insert_result
    )
    client.search.return_value = [] if search_result is None else search_result
    client.query.return_value = [] if query_result is None else query_result
    return client


def _self_creating_client(**kwargs):
    """Client double whose collection starts absent and exists after creation."""

    client = _fake_client(has_collection=False, **kwargs)
    state = {"created": False}
    client.has_collection.side_effect = lambda collection_name: state["created"]

    def _create(**call_kwargs):
        state["created"] = True
        return MagicMock(name=f"created:{call_kwargs.get('collection_name')}")

    client.create_collection.side_effect = _create
    return client


def _client_for(client):
    """Build a MilvusDBClient without running ``__init__`` (no real connect)."""

    db = MilvusDBClient.__new__(MilvusDBClient)
    db.client = client
    db.config = {}
    return db


def _hit(entity):
    """One search hit as ``MilvusClient.search`` returns it."""

    return {"id": entity["id"], "distance": 0.1, "entity": entity}


# ---------------------------------------------------------------------------
# construction / connection failure
# ---------------------------------------------------------------------------

def test_init_connects_with_uri_and_token():
    """TC-VEC-001 | 构造时用 uri/token 建立 Milvus 连接

    输入: config = {"uri": "http://milvus:19530", "token": "tok"}
    预期输出: self.client 即底层客户端，config 原样保存在 self.config
    断言点: MilvusClient 只被调用一次且 kwargs 精确匹配 + client 身份相等
    防回归: 若 uri/token 传参顺序或键名被改（例如 token 被漏传），断言失败
    """

    sentinel = MagicMock(name="connected_client")
    with patch.object(milvus_module, "MilvusClient", return_value=sentinel) as ctor:
        db = MilvusDBClient({"uri": "http://milvus:19530", "token": "tok"})

    ctor.assert_called_once_with(uri="http://milvus:19530", token="tok")
    assert db.client is sentinel
    assert db.config == {"uri": "http://milvus:19530", "token": "tok"}


def test_init_defaults_missing_token_to_empty_string():
    """TC-VEC-002 | 未配置 token 时以空串连接（无认证 Milvus）

    输入: config = {"uri": "http://milvus:19530"}
    预期输出: MilvusClient(uri=..., token="")
    断言点: kwargs 中 token 精确为 ""（而非 None，pymilvus 会因 None 报错）
    防回归: 若 config.get("token", "") 退化为 config["token"]，会抛 KeyError
    """

    with patch.object(milvus_module, "MilvusClient") as ctor:
        MilvusDBClient({"uri": "http://milvus:19530"})

    ctor.assert_called_once_with(uri="http://milvus:19530", token="")


def test_init_connection_failure_is_logged_and_swallowed():
    """TC-VEC-003 | 连接失败不向上抛，只记一条错误日志

    输入: MilvusClient 抛 MilvusException("connect refused")
    预期输出: 构造成功；错误日志 "Milvus initiation failed: connect refused"；
              client 属性存在但为 None（明确"不可用"状态，而非缺失属性）
    断言点: 构造未抛异常 + logger.error 消息精确 + db.client is None
    防回归: 若把 except 去掉，本用例在构造处就炸；若改回不留属性，
            后续调用会退化成 AttributeError（由 TC-VEC-003b 覆盖）
    """

    error = MilvusException(message="connect refused")
    with patch.object(
        milvus_module, "MilvusClient", side_effect=error,
    ), patch.object(milvus_module, "logger") as logger:
        db = MilvusDBClient({"uri": "http://milvus:19530", "token": ""})

    logger.error.assert_called_once_with(f"Milvus initiation failed: {error}")
    assert db.client is None


# ---------------------------------------------------------------------------
# create_collection
# ---------------------------------------------------------------------------

def test_create_collection_rejects_empty_name_without_touching_backend():
    """TC-VEC-004 | collection_name 为空时返回 None 且不调用底层

    输入: data = {"collection_name": ""}
    预期输出: None + 一条 "collection_name cannot be empty" 错误日志
    断言点: 返回 None + 日志消息 + 未调用 create_schema/create_collection
    防回归: 删除校验会建出一个匿名集合，两条 not_called 断言失败
    """

    client = _fake_client()
    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).create_collection({"collection_name": ""})

    assert result is None
    logger.error.assert_called_once_with(
        "Error: There is Exception in create collection method: "
        "collection_name cannot be empty"
    )
    client.create_schema.assert_not_called()
    client.create_collection.assert_not_called()


def test_create_collection_returns_existing_client_and_skips_creation():
    """TC-VEC-005 | 集合已存在时直接返回 client，不重复建表

    输入: has_collection=True, collection_name="agents"
    预期输出: 返回同一个 client 对象 + "already exists" 日志
    断言点: 返回值 is client + create_schema/create_collection 未调用 + 日志文案
    防回归: 若存在性判断被删除，会对已存在集合重复建表导致 Milvus 报错
    """

    client = _fake_client(has_collection=True)
    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).create_collection({"collection_name": COLLECTION})

    assert result is client
    logger.info.assert_called_once_with("Collection agents already exists")
    client.create_schema.assert_not_called()
    client.create_collection.assert_not_called()


def test_create_collection_declares_full_schema_and_vector_index():
    """TC-VEC-006 | 新建集合声明主键/向量/元数据字段并建 FLAT-L2 索引

    输入: has_collection=False, collection_name="agents"
    预期输出: 7 个字段（id,embedding,name,description,organization,agent_card,layer）、
              一个 FLAT/L2 索引，返回 client
    断言点: add_field 的字段名顺序与每项 datatype/max_length/dim 精确匹配 +
              add_index 入参 + create_collection/create_index 入参 + 返回身份
    防回归: 漏字段、维度写错、metric 改 IP、sync 改 True 都会让某条断言失败
    """

    client = _fake_client(has_collection=False)
    schema = client.create_schema.return_value
    index_params = client.prepare_index_params.return_value

    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).create_collection({"collection_name": COLLECTION})

    assert result is client
    client.create_schema.assert_called_once_with(
        auto_id=False,
        enable_dynamic_field=True,
        description="create collection named: agents",
    )

    declared = [call.kwargs for call in schema.add_field.call_args_list]
    assert [field["field_name"] for field in declared] == [
        "id", "embedding", "name", "description", "organization", "agent_card", "layer"
    ]
    id_field = declared[0]
    assert id_field["datatype"] is DataType.VARCHAR
    assert id_field["is_primary"] is True
    assert id_field["auto_id"] is False
    assert id_field["max_length"] == VARCHAR_MAX_LENGTH == 65535
    embedding_field = declared[1]
    assert embedding_field["datatype"] is DataType.FLOAT_VECTOR
    assert embedding_field["dim"] == DIM == 1024
    for field in declared[2:6]:
        assert field["datatype"] is DataType.VARCHAR
        assert field["max_length"] == VARCHAR_MAX_LENGTH
    assert declared[6]["field_name"] == "layer"
    assert declared[6]["max_length"] == 64

    index_params.add_index.assert_called_once_with(
        field_name="embedding",
        index_type="FLAT",
        metric_type="L2",
        index_name="embedding_index",
        params={"nlist": 128},
    )
    client.create_collection.assert_called_once_with(
        collection_name=COLLECTION, schema=schema
    )
    client.create_index.assert_called_once_with(
        collection_name=COLLECTION, index_params=index_params, sync=False
    )
    logger.info.assert_called_once_with("Collection agents created")


def test_create_collection_returns_none_when_backend_rejects_schema():
    """TC-VEC-007 | 建表过程中后端异常被吞，返回 None 并记录原始错误

    输入: create_schema 抛 MilvusException("invalid schema")
    预期输出: None + 错误日志包含原始异常文本
    断言点: 返回 None + 日志精确消息 + 未调用 create_collection/create_index
    防回归: 若异常被放行，注册流程会在建表处崩；若吞掉却不记日志，运维失明
    """

    client = _fake_client(has_collection=False)
    client.create_schema.side_effect = error = MilvusException(message="invalid schema")

    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).create_collection({"collection_name": COLLECTION})

    assert result is None
    logger.error.assert_called_once_with(
        f"Error: There is Exception in create collection method: {error}"
    )
    client.create_collection.assert_not_called()
    client.create_index.assert_not_called()


# ---------------------------------------------------------------------------
# insert_entity
# ---------------------------------------------------------------------------

def test_insert_entity_rejects_missing_collection_name():
    """TC-VEC-008 | insert 缺少 collection_name 时返回 False，不写后端

    输入: data = {"entity": {...}}
    预期输出: False + "collection_name cannot be empty" 日志
    断言点: 返回值 is False + 日志消息 + client.insert 未调用
    防回归: 若校验前移失败或返回值改为 None，断言失败
    """

    client = _fake_client()
    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).insert_entity({"entity": _entity()})

    assert result is False
    logger.error.assert_called_once_with(
        "Error: There is Exception in insert method: collection_name cannot be empty"
    )
    client.insert.assert_not_called()


def test_insert_entity_creates_missing_collection_then_inserts():
    """TC-VEC-009 | 首次写入时先建集合再插入，并记录 insert_id/insert_count

    输入: has_collection=False, 合法 1024 维向量
    预期输出: True；底层 create_collection + insert 各一次
    断言点: insert kwargs（collection_name/data 原样）+ 日志含 insert_id 与 count
    防回归: 若建表分支被删除，首次注册会失败；若日志字段错位，断言失败
    """

    client = _fake_client(has_collection=False)
    entity = _entity(layer=None)

    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).insert_entity(
            {"collection_name": COLLECTION, "entity": entity}
        )

    assert result is True
    client.create_collection.assert_called_once()
    client.insert.assert_called_once_with(
        collection_name=COLLECTION, data=entity
    )
    logger.info.assert_called_with("Insert success! insert_id:agent-a, insert_count:1")


def test_insert_entity_reports_false_when_backend_inserts_nothing():
    """TC-VEC-010 | insert_count 为 0 视为失败

    输入: client.insert 返回 {"insert_count": 0, "ids": []}
    预期输出: False + "zero insert count" 错误日志
    断言点: 返回值 is False + 日志消息精确（含集合名）
    防回归: 若只看异常不看 insert_count，空写会被当成成功
    """

    client = _fake_client(insert_result={"insert_count": 0, "ids": []})
    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).insert_entity(
            {"collection_name": COLLECTION, "entity": _entity()}
        )

    assert result is False
    logger.error.assert_called_once_with(
        "Insert returned zero insert count: collection=agents"
    )


def test_insert_entity_rejects_wrong_vector_dimension():
    """TC-VEC-011 | 向量维度不是 1024 时抛 VectorDimensionError

    输入: embedding = [0.1, 0.2]
    预期输出: VectorDimensionError（ValueError 子类），消息 "Vector dimension must be 1024"
    断言点: 异常类型 + 消息 + client.insert 未调用
    防回归: 若异常被通用 except 吞成 False，调用方无法区分"参数错"与"后端失败"
    """

    client = _fake_client()
    entity = _entity()
    entity["embedding"] = [0.1, 0.2]

    with pytest.raises(milvus_module.VectorDimensionError,
                       match="Vector dimension must be 1024"):
        _client_for(client).insert_entity(
            {"collection_name": COLLECTION, "entity": entity}
        )

    client.insert.assert_not_called()


def test_insert_entity_rejects_non_list_embedding():
    """TC-VEC-012 | 非 list 的 embedding（如 numpy 数组/tuple）被拒绝

    输入: embedding = (0.5,) * 1024（tuple）
    预期输出: VectorDimensionError，且不写入
    断言点: 异常类型 + insert 未调用
    防回归: 若 isinstance 校验被删除，tuple 会原样发给 pymilvus
    """

    client = _fake_client()
    entity = _entity()
    entity["embedding"] = (0.5,) * DIM

    with pytest.raises(milvus_module.VectorDimensionError):
        _client_for(client).insert_entity(
            {"collection_name": COLLECTION, "entity": entity}
        )

    client.insert.assert_not_called()


def test_insert_entity_with_layer_requires_migrated_collection():
    """TC-VEC-013 | 带 layer 的写入在未迁移集合上必须抛 LayerMigrationRequiredError

    输入: 集合 schema 无 layer 字段，entity 含 layer="omc"
    预期输出: LayerMigrationRequiredError("... has no layer field ...")
    断言点: 异常类型 + 消息含集合名与 migrate-milvus-layer 提示 + 未写入
    防回归: 若 except LayerMigrationRequiredError: raise 被删除，会退化为 False，
            注册方将静默丢层
    """

    client = _fake_client(schema=_schema(LEGACY_FIELDS))

    with pytest.raises(LayerMigrationRequiredError) as excinfo:
        _client_for(client).insert_entity(
            {"collection_name": "legacy_agents", "entity": _entity()}
        )

    message = str(excinfo.value)
    assert "'legacy_agents' has no layer field" in message
    assert "migrate-milvus-layer" in message
    client.insert.assert_not_called()


def test_insert_entity_with_layer_on_migrated_collection_writes():
    """TC-VEC-014 | 已迁移集合上带 layer 的写入正常落库

    输入: schema 含 layer 字段，entity 含 layer="omc"
    预期输出: True，insert 收到完整 entity（layer 未丢失）
    断言点: insert kwargs 中 data["layer"] == "omc" + 返回 True
    防回归: 若 layer 在写入前被剥离，断言失败
    """

    client = _fake_client(schema=_schema())
    entity = _entity(layer="omc")

    result = _client_for(client).insert_entity(
        {"collection_name": COLLECTION, "entity": entity}
    )

    assert result is True
    assert client.insert.call_args.kwargs["data"]["layer"] == "omc"


def test_insert_entity_logs_scalar_id_when_backend_returns_string():
    """TC-VEC-015 | 后端返回标量 ids 时日志仍给出正确 insert_id

    输入: insert 返回 {"insert_count": 1, "ids": "agent-a"}
    预期输出: True；日志 insert_id:agent-a
    断言点: 日志字符串精确相等（标量分支未把字符串拆成首字符）
    防回归: 若去掉 isinstance(list) 判断，"agent-a"[0] 会记成 "a"
    """

    client = _fake_client(insert_result={"insert_count": 1, "ids": "agent-a"})
    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).insert_entity(
            {"collection_name": COLLECTION, "entity": _entity()}
        )

    assert result is True
    logger.info.assert_called_once_with(
        "Insert success! insert_id:agent-a, insert_count:1"
    )


def test_insert_entity_returns_false_when_backend_raises():
    """TC-VEC-016 | 后端 insert 异常转为 False + 原始错误日志

    输入: client.insert 抛 MilvusException("write quorum lost")
    预期输出: False，异常不外泄
    断言点: 返回值 is False + 日志精确 + 只调用了一次 insert（无隐藏重试）
    防回归: 若异常透传，注册接口会 500；若擅自加重试，调用次数断言失败
    """

    client = _fake_client()
    error = client.insert.side_effect = MilvusException(message="write quorum lost")

    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).insert_entity(
            {"collection_name": COLLECTION, "entity": _entity()}
        )

    assert result is False
    assert client.insert.call_count == 1
    logger.error.assert_called_once_with(
        f"Error: There is Exception in insert method: {error}"
    )


# ---------------------------------------------------------------------------
# delete_entity
# ---------------------------------------------------------------------------

def test_delete_entity_creates_missing_collection_and_reports_false():
    """TC-VEC-017 | 集合不存在时建空集合并返回 False（无可删数据）

    输入: has_collection=False, id="agent-a"
    预期输出: False，且底层 create_collection 被调用、delete 未被调用
    断言点: 返回值 is False + create_collection 一次 + delete 零次 + 日志
    防回归: 若删除不存在的集合时不建表而直接 delete，Milvus 报错
    """

    client = _fake_client(has_collection=False)
    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).delete_entity(
            {"collection_name": COLLECTION, "id": "agent-a"}
        )

    assert result is False
    client.create_collection.assert_called_once()
    client.delete.assert_not_called()
    assert [item.args for item in logger.info.call_args_list] == [
        ("Collection agents created",),
        (
            "Collection does not exist in database, created it. "
            "Collection is empty, no delete needed.",
        ),
    ]


def test_delete_entity_rejects_missing_id():
    """TC-VEC-018 | 缺少 id 时返回 False，不调用 delete

    输入: data = {"collection_name": "agents"}（无 id）
    预期输出: False + "Delete failed: id cannot be empty"
    断言点: 返回值 is False + 日志精确 + delete 未调用
    防回归: 若 None 判断被删除，ids=[None] 会被发给 Milvus
    """

    client = _fake_client()
    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).delete_entity({"collection_name": COLLECTION})

    assert result is False
    client.delete.assert_not_called()
    logger.error.assert_called_once_with("Delete failed: id cannot be empty")


def test_delete_entity_sends_primary_key_list():
    """TC-VEC-019 | 删除把主键包成 ids 列表并返回 True

    输入: id="agent-a"
    预期输出: True；delete(collection_name="agents", ids=["agent-a"])
    断言点: delete 入参精确 + 返回值 is True + 成功日志含集合与 id
    防回归: 若 ids 传成裸字符串，Milvus 会把字符串按字符展开
    """

    client = _fake_client()
    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).delete_entity(
            {"collection_name": COLLECTION, "id": "agent-a"}
        )

    assert result is True
    client.delete.assert_called_once_with(
        collection_name=COLLECTION, ids=["agent-a"]
    )
    logger.info.assert_called_once_with(
        "Delete successful: collection=agents, id=agent-a"
    )


def test_delete_entity_returns_false_when_backend_raises():
    """TC-VEC-020 | 后端删除异常转为 False + 日志

    输入: client.delete 抛 MilvusException("compaction busy")
    预期输出: False
    断言点: 返回值 is False + 日志精确
    防回归: 异常透传会让删除接口 500
    """

    client = _fake_client()
    error = client.delete.side_effect = MilvusException(message="compaction busy")

    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).delete_entity(
            {"collection_name": COLLECTION, "id": "agent-a"}
        )

    assert result is False
    logger.error.assert_called_once_with(f"Delete failed: {error}")


# ---------------------------------------------------------------------------
# update_entity
# ---------------------------------------------------------------------------

def test_update_entity_falls_back_to_insert_for_missing_collection():
    """TC-VEC-021 | 集合不存在时 update 退化为 insert

    输入: 集合初始不存在（建表后存在），合法 entity
    预期输出: insert 的结果（True）
    断言点: 返回值 is True + 底层走 insert（upsert 未调用）+ 建表只发生一次 + 日志
    防回归: 若退化分支被删除，首次更新会 upsert 到不存在的集合
    """

    client = _self_creating_client()
    entity = _entity(layer=None)

    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).update_entity(
            {"collection_name": COLLECTION, "entity": entity}
        )

    assert result is True
    client.upsert.assert_not_called()
    client.insert.assert_called_once_with(collection_name=COLLECTION, data=entity)
    client.create_collection.assert_called_once()
    assert [item.args for item in logger.info.call_args_list] == [
        ("Collection agents created",),
        ("Collection does not exist in database, created it",),
        ("Insert success! insert_id:agent-a, insert_count:1",),
    ]


def test_update_entity_upserts_existing_entity():
    """TC-VEC-022 | 集合已存在时直接 upsert

    输入: has_collection=True, entity id="agent-a"
    预期输出: True；upsert(collection_name="agents", data=entity)
    断言点: upsert 入参精确 + 返回值 is True + 成功日志含 id
    防回归: 若 update 误用 insert，重复注册会撞主键
    """

    client = _fake_client()
    entity = _entity(layer=None)

    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).update_entity(
            {"collection_name": COLLECTION, "entity": entity}
        )

    assert result is True
    client.upsert.assert_called_once_with(
        collection_name=COLLECTION, data=entity
    )
    logger.info.assert_called_once_with(
        "Upsert successful: collection=agents, id=agent-a"
    )


def test_update_entity_with_layer_requires_migrated_collection():
    """TC-VEC-023 | 带 layer 的更新在未迁移集合上抛迁移异常

    输入: schema 无 layer，entity 含 layer="omc"
    预期输出: LayerMigrationRequiredError
    断言点: 异常类型 + 消息含集合名 + upsert 未调用
    防回归: 若丢失 raise 分支，更新会静默丢掉 layer 过滤能力
    """

    client = _fake_client(schema=_schema(LEGACY_FIELDS))

    with pytest.raises(LayerMigrationRequiredError, match="no layer field"):
        _client_for(client).update_entity(
            {"collection_name": "legacy_agents", "entity": _entity()}
        )

    client.upsert.assert_not_called()


def test_update_entity_returns_false_on_milvus_exception():
    """TC-VEC-024 | MilvusException 分支记录专用日志并返回 False

    输入: client.upsert 抛 MilvusException("schema mismatch")
    预期输出: False + "There is MilvusException in update method" 日志
    断言点: 返回值 is False + 日志前缀区分于通用异常分支
    防回归: 若两个 except 顺序颠倒，日志前缀变化即被断言捕获
    """

    client = _fake_client()
    error = client.upsert.side_effect = MilvusException(message="schema mismatch")

    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).update_entity(
            {"collection_name": COLLECTION, "entity": _entity(layer=None)}
        )

    assert result is False
    logger.error.assert_called_once_with(
        f"Error: There is MilvusException in update method: {error}"
    )


def test_update_entity_returns_false_on_generic_exception():
    """TC-VEC-025 | 非 Milvus 异常走通用分支并返回 False

    输入: client.upsert 抛 ValueError("bad payload")
    预期输出: False + "There is Exception in update method" 日志
    断言点: 返回值 is False + 日志文案精确（非 MilvusException 前缀）
    防回归: 若通用 except 被删除，异常会冒泡到注册接口
    """

    client = _fake_client()
    client.upsert.side_effect = ValueError("bad payload")

    with patch.object(milvus_module, "logger") as logger:
        result = _client_for(client).update_entity(
            {"collection_name": COLLECTION, "entity": _entity(layer=None)}
        )

    assert result is False
    logger.error.assert_called_once_with(
        "Error: There is Exception in update method: bad payload"
    )


# ---------------------------------------------------------------------------
# retrieve_entity (vector search on the legacy facade)
# ---------------------------------------------------------------------------

def test_retrieve_entity_creates_missing_collection_then_searches():
    """TC-VEC-026 | 集合不存在时建表后继续检索（不会提前返回）

    输入: 集合初始不存在（建表后存在）；search 返回空
    预期输出: []；底层 create_collection 与 load_collection 都被调用
    断言点: 返回 [] + create_collection 一次 + load_collection 一次 + search 一次
    防回归: 若建表后提前 return，load/search 调用次数断言失败
    """

    client = _self_creating_client(search_result=[])

    result = _client_for(client).retrieve_entity(
        {"collection_name": COLLECTION, "embedding": EMBEDDING}
    )

    assert result == []
    client.create_collection.assert_called_once()
    client.load_collection.assert_called_once_with(collection_name=COLLECTION)
    client.search.assert_called_once()


def test_retrieve_entity_requires_layer_field_when_filtering():
    """TC-VEC-027 | 带 layer 的检索在未迁移集合上抛迁移异常

    输入: schema 无 layer，data 含 layer="omc"
    预期输出: LayerMigrationRequiredError（迁移校验在 try 之外，不被吞）
    断言点: 异常类型 + 消息含集合名与迁移指引 + search 未执行
    防回归: 若校验被移进 try/except，脏查询会退化为"无结果"，层隔离失效
    """

    client = _fake_client(schema=_schema(LEGACY_FIELDS))

    with pytest.raises(LayerMigrationRequiredError) as excinfo:
        _client_for(client).retrieve_entity(
            {"collection_name": "legacy_agents", "embedding": EMBEDDING, "layer": "omc"}
        )

    assert "has no layer field" in str(excinfo.value)
    client.search.assert_not_called()


def test_retrieve_entity_returns_empty_for_no_hits():
    """TC-VEC-028 | 检索无命中返回空列表

    输入: search 返回 []
    预期输出: []
    断言点: 返回值精确等于 [] 且 search 的 limit 为默认 10
    防回归: 若空结果分支被删除，会抛 IndexError 被吞成 []——但 limit 断言仍校验参数
    """

    client = _fake_client(search_result=[])

    result = _client_for(client).retrieve_entity(
        {"collection_name": COLLECTION, "embedding": EMBEDDING}
    )

    assert result == []
    assert client.search.call_args.kwargs["limit"] == 10


def test_retrieve_entity_returns_empty_when_inner_hit_list_is_empty():
    """TC-VEC-029 | 外层有结果但内层为空时返回空列表

    输入: search 返回 [[]]
    预期输出: []
    断言点: 返回值 == []（len(results[0]) == 0 分支）
    防回归: 若只判断 len(results)==0，遍历空内层仍返回 []，但若实现改成访问
            results[0][0]，本用例会失败
    """

    client = _fake_client(search_result=[[]])

    assert _client_for(client).retrieve_entity(
        {"collection_name": COLLECTION, "embedding": EMBEDDING}
    ) == []


def test_retrieve_entity_returns_parsed_agent_cards_with_search_params():
    """TC-VEC-030 | 命中记录被解析为 AgentCard dict，检索参数符合约定

    输入: search 返回一条 agent_card JSON 命中
    预期输出: [{"name": "agent-a", ...}]（dict 而非字符串）
    断言点: search kwargs 全字段精确（data 包一层列表、anns_field、L2/nprobe）
            + 返回列表长度 + 元素是 dict 且 name 正确
    防回归: data 未包 list、metric 改 IP、nprobe 变 10→1 等都会失败
    """

    hit = _hit(_entity())
    client = _fake_client(search_result=[[hit]])

    results = _client_for(client).retrieve_entity(
        {"collection_name": COLLECTION, "embedding": EMBEDDING, "top_n": 3}
    )

    client.load_collection.assert_called_once_with(collection_name=COLLECTION)
    assert client.search.call_args.kwargs == {
        "collection_name": COLLECTION,
        "data": [EMBEDDING],
        "anns_field": "embedding",
        "limit": 3,
        "output_fields": [
            "id", "name", "description", "organization", "agent_card",
            "status", "owner", "layer",
        ],
        "search_params": {"metric_type": "L2", "param": {"nprobe": 10}},
    }
    assert len(results) == 1
    assert isinstance(results[0], dict)
    assert results[0]["name"] == "agent-a"
    assert results[0]["provider"]["organization"] == "org-a"


def test_retrieve_entity_applies_layer_and_status_filter():
    """TC-VEC-031 | layer/status 被编成 Milvus 过滤表达式

    输入: layer=" omc ", status="published"
    预期输出: search kwargs["filter"] == 'layer == "omc" and status == "published"'
    断言点: filter 表达式精确（含去空格）且 layer 校验通过
    防回归: 若 normalize 丢失，空白层会被当成不同层，过滤失效
    """

    client = _fake_client(search_result=[[]])

    _client_for(client).retrieve_entity({
        "collection_name": COLLECTION,
        "embedding": EMBEDDING,
        "layer": " omc ",
        "status": "published",
    })

    assert client.search.call_args.kwargs["filter"] == (
        'layer == "omc" and status == "published"'
    )


def test_retrieve_entity_returns_empty_when_search_raises():
    """TC-VEC-032 | 检索异常转为空列表并记录原始错误

    输入: client.search 抛 MilvusException("collection not loaded")
    预期输出: [] + "Vector search failed: ..." 日志
    断言点: 返回值 == [] + 日志消息精确
    防回归: 异常透传会让检索接口 500
    """

    client = _fake_client()
    error = client.search.side_effect = MilvusException(message="collection not loaded")

    with patch.object(milvus_module, "logger") as logger:
        results = _client_for(client).retrieve_entity(
            {"collection_name": COLLECTION, "embedding": EMBEDDING}
        )

    assert results == []
    logger.error.assert_called_once_with(f"Vector search failed: {error}")


# ---------------------------------------------------------------------------
# query_by_key
# ---------------------------------------------------------------------------

def test_query_by_key_quotes_string_values():
    """TC-VEC-033 | 字符串值加双引号后作为过滤表达式

    输入: key="name", value="agent-a"
    预期输出: [{"name": "agent-a", ...}]，过滤表达式 'name == "agent-a"'
    断言点: query 的 filter 精确 + output_fields + 返回元素是解析后的 dict
    防回归: 去掉引号会变成非法表达式；用 repr 会产生单引号
    """

    entity = _entity()
    client = _fake_client(query_result=[entity])

    results = _client_for(client).query_by_key({
        "collection_name": COLLECTION,
        "key": "name",
        "value": "agent-a",
    })

    client.load_collection.assert_called_once_with(collection_name=COLLECTION)
    assert client.query.call_args.kwargs["filter"] == 'name == "agent-a"'
    assert client.query.call_args.kwargs["output_fields"] == [
        "id", "name", "description", "organization", "agent_card",
        "status", "owner", "layer",
    ]
    assert results == [json.loads(entity["agent_card"])]


def test_query_by_key_leaves_non_string_values_unquoted():
    """TC-VEC-034 | 非字符串值（数字）不加引号

    输入: key="priority", value=5
    预期输出: filter == "priority == 5"
    断言点: filter 字符串精确相等
    防回归: 若统一加引号，数字过滤会被 Milvus 判为类型不匹配
    """

    client = _fake_client(query_result=[])

    _client_for(client).query_by_key({
        "collection_name": COLLECTION,
        "key": "priority",
        "value": 5,
    })

    assert client.query.call_args.kwargs["filter"] == "priority == 5"


def test_query_by_key_returns_all_rows_for_multi_hit():
    """TC-VEC-035 | 多行命中时全部解析返回

    输入: query 返回 2 条记录
    预期输出: 2 个 dict，顺序与返回顺序一致
    断言点: 列表长度 + 两个 name 精确有序
    防回归: 若多行分支被删（只取 results[0]），长度断言失败
    """

    first = _entity(agent_id="a1", name="agent-a")
    second = _entity(agent_id="a2", name="agent-b")
    client = _fake_client(query_result=[first, second])

    results = _client_for(client).query_by_key({
        "collection_name": COLLECTION,
        "key": "organization",
        "value": "org-a",
    })

    assert len(results) == 2
    assert [item["name"] for item in results] == ["agent-a", "agent-b"]


def test_query_by_key_returns_empty_list_for_no_rows():
    """TC-VEC-036 | 无命中返回空列表（不返回 None）

    输入: query 返回 []
    预期输出: []
    断言点: 返回值精确等于 []
    防回归: 若空分支返回 None，调用方遍历会 TypeError
    """

    client = _fake_client(query_result=[])

    assert _client_for(client).query_by_key({
        "collection_name": COLLECTION, "key": "name", "value": "missing",
    }) == []


def test_query_by_key_creates_missing_collection_then_queries():
    """TC-VEC-037 | 集合不存在时建表后仍继续查询

    输入: has_collection=False
    预期输出: []，create_collection 与 query 都发生
    断言点: create_collection 一次 + query 一次 + 返回 []
    防回归: 若查询前不建集合，Milvus 直接报错（并被吞成 []），难以定位
    """

    client = _self_creating_client(query_result=[])

    results = _client_for(client).query_by_key({
        "collection_name": COLLECTION, "key": "name", "value": "agent-a",
    })

    assert results == []
    client.create_collection.assert_called_once()
    client.query.assert_called_once()


def test_query_by_key_returns_empty_when_query_raises():
    """TC-VEC-038 | 查询异常转为空列表并记录日志

    输入: client.query 抛 MilvusException("index not ready")
    预期输出: [] + "Query failed: ..." 日志
    断言点: 返回值 == [] + 日志精确
    防回归: 异常透传会让按 key 查询接口 500
    """

    client = _fake_client()
    error = client.query.side_effect = MilvusException(message="index not ready")

    with patch.object(milvus_module, "logger") as logger:
        results = _client_for(client).query_by_key({
            "collection_name": COLLECTION, "key": "name", "value": "agent-a",
        })

    assert results == []
    logger.error.assert_called_once_with(f"Query failed: {error}")


# ---------------------------------------------------------------------------
# get_all_entities
# ---------------------------------------------------------------------------

def test_get_all_entities_creates_missing_collection_and_returns_empty():
    """TC-VEC-039 | 集合不存在时建表并立即返回空列表（不查询）

    输入: has_collection=False
    预期输出: []
    断言点: create_collection 一次 + query 零次 + 返回 []
    防回归: 若建表后继续查询，query 调用次数断言失败
    """

    client = _fake_client(has_collection=False)

    results = _client_for(client).get_all_entities({"collection_name": COLLECTION})

    assert results == []
    client.create_collection.assert_called_once()
    client.query.assert_not_called()


def test_get_all_entities_uses_configured_max_and_parses_rows():
    """TC-VEC-040 | 查询上限取自 agent.num.max 配置，命中全部解析

    输入: get_conf() → {"agent.num.max": "7"}，query 返回 2 行
    预期输出: 2 个 dict；query 的 limit == 7
    断言点: limit 精确为 int(7) + filter + 返回长度与 name 顺序
    防回归: 若配置键名写错，limit 会退回 40，断言失败
    """

    first = _entity(agent_id="a1", name="agent-a")
    second = _entity(agent_id="a2", name="agent-b")
    client = _fake_client(query_result=[first, second])

    with patch.object(
        milvus_module, "get_conf", return_value={"agent.num.max": "7"}
    ):
        results = _client_for(client).get_all_entities({"collection_name": COLLECTION})

    assert len(results) == 2
    assert [item["name"] for item in results] == ["agent-a", "agent-b"]
    assert client.query.call_args.kwargs["limit"] == 7
    assert client.query.call_args.kwargs["filter"] == 'id != ""'


def test_get_all_entities_defaults_limit_to_40_without_config():
    """TC-VEC-041 | 配置缺失时上限取默认 40

    输入: get_conf() → {}
    预期输出: query 的 limit == 40
    断言点: limit 精确等于 40
    防回归: 默认值被改（如 100/无 limit）会导致一次拉全量
    """

    client = _fake_client(query_result=[])

    with patch.object(milvus_module, "get_conf", return_value={}):
        assert _client_for(client).get_all_entities(
            {"collection_name": COLLECTION}
        ) == []

    assert client.query.call_args.kwargs["limit"] == 40


def test_get_all_entities_logs_empty_collection():
    """TC-VEC-042 | 空集合时返回 [] 并记录 "Collection is empty"

    输入: query 返回 []
    预期输出: []
    断言点: 返回值 == [] + 日志精确
    防回归: 空集合与失败难以区分，日志是唯一线索
    """

    client = _fake_client(query_result=[])

    with patch.object(milvus_module, "logger") as logger:
        results = _client_for(client).get_all_entities({"collection_name": COLLECTION})

    assert results == []
    logger.info.assert_called_once_with("Collection is empty")


def test_get_all_entities_returns_empty_when_query_raises():
    """TC-VEC-043 | 全量查询异常转换为空列表并记录日志

    输入: client.query 抛 MilvusException("quota exceeded")
    预期输出: [] + "Failed to get all entities: ..." 日志
    断言点: 返回值 == [] + 日志精确
    防回归: 异常透传会让列举接口 500
    """

    client = _fake_client()
    error = client.query.side_effect = MilvusException(message="quota exceeded")

    with patch.object(milvus_module, "logger") as logger:
        results = _client_for(client).get_all_entities({"collection_name": COLLECTION})

    assert results == []
    logger.error.assert_called_once_with(
        f"Failed to get all entities: {error}"
    )


# ---------------------------------------------------------------------------
# _build_filter / _entity_to_record
# ---------------------------------------------------------------------------

def test_build_filter_returns_none_without_metadata():
    """TC-VEC-044 | 无 layer/status 时不生成过滤表达式

    输入: {}
    预期输出: None
    断言点: 返回值 is None（而非空串，否则 search 会带空 filter）
    防回归: 若返回 ""，search 会收到非法表达式
    """

    assert MilvusDBClient._build_filter({}) is None


def test_build_filter_normalizes_layer_and_quotes_values():
    """TC-VEC-045 | layer 去空格并与 status 用 and 连接

    输入: {"layer": "  omc  ", "status": "published"}
    预期输出: 'layer == "omc" and status == "published"'
    断言点: 表达式精确相等
    防回归: 去空格丢失或引号丢失都会使 Milvus 匹配失败
    """

    assert MilvusDBClient._build_filter(
        {"layer": "  omc  ", "status": "published"}
    ) == 'layer == "omc" and status == "published"'


def test_build_filter_status_only():
    """TC-VEC-046 | 仅 status 时表达式只含 status

    输入: {"status": "pending"}
    预期输出: 'status == "pending"'
    断言点: 表达式精确相等（无多余 and）
    防回归: 若把 None 的 layer 也拼进去，会产生 'layer == null and ...'
    """

    assert MilvusDBClient._build_filter(
        {"layer": None, "status": "pending"}
    ) == 'status == "pending"'


def test_build_filter_rejects_non_string_layer():
    """TC-VEC-047 | 非字符串 layer 抛出 ValueError（不静默忽略）

    输入: {"layer": 123}
    预期输出: ValueError("layer must be a string")
    断言点: 异常类型 + 消息
    防回归: 若过滤校验被吞掉，数字层会生成非法表达式
    """

    with pytest.raises(ValueError, match="layer must be a string"):
        MilvusDBClient._build_filter({"layer": 123})


def test_entity_to_record_parses_json_card_string():
    """TC-VEC-048 | 字符串 agent_card 被解析为 AgentCard 并保留元数据

    输入: entity = 含 agent_card JSON 字符串、owner/status/layer
    预期输出: AgentRecord(agent_card.name="agent-a", ...)
    断言点: 类型 AgentRecord + 卡片字段 + owner/status/layer 四项精确
    防回归: 若不解析字符串，agent_card 会保持 str，调用方 .name 报错
    """

    entity = _entity()
    entity.update({"owner": "alice", "status": "pending", "layer": " omc "})

    record = MilvusDBClient._entity_to_record(entity)

    assert isinstance(record, AgentRecord)
    assert record.agent_card.name == "agent-a"
    assert record.agent_card.provider.organization == "org-a"
    assert [skill.name for skill in record.agent_card.skills] == ["skill-1"]
    assert record.owner == "alice"
    assert record.status == "pending"
    assert record.layer == "omc"


def test_entity_to_record_accepts_dict_card():
    """TC-VEC-049 | dict 形式的 agent_card 直接转换为 AgentCard

    输入: entity["agent_card"] = dict
    预期输出: AgentRecord，agent_card.name == "agent-a"
    断言点: 卡片 name + skills 数量
    防回归: 若只处理 str，dict 会被 json.dumps 再 Parse 也能过；但把 dict 当 str
            调用 json.loads 会抛 TypeError，被断言捕获
    """

    record = MilvusDBClient._entity_to_record({"agent_card": dict(AGENT_CARD)})

    assert record.agent_card.name == "agent-a"
    assert len(record.agent_card.skills) == 1


def test_entity_to_record_falls_back_to_unknown_layer():
    """TC-VEC-050 | 非法 layer 回退为 unknown

    输入: entity["layer"] = "   "（normalize_layer 会抛 ValueError）
    预期输出: record.layer == UNKNOWN_LAYER
    防回归: 若回退分支被删除，脏数据会让整条查询失败
    """

    record = MilvusDBClient._entity_to_record(_entity(layer="   "))

    assert record.layer == UNKNOWN_LAYER == "unknown"


def test_entity_to_record_defaults_card_owner_status_layer():
    """TC-VEC-051 | 缺失字段时的默认值：空卡片/published/unknown

    输入: entity = {}（除默认空卡片外无任何键）
    预期输出: agent_card 为空卡片、status="published"、layer="unknown"、owner=None
    断言点: 四个默认值精确断言
    防回归: status 默认值被改为 pending 会改变可见性语义
    """

    record = MilvusDBClient._entity_to_record({})

    assert record.agent_card.name == ""
    assert record.status == "published"
    assert record.layer == UNKNOWN_LAYER
    assert record.owner is None


# ---------------------------------------------------------------------------
# find_records / find_records_by_key
# ---------------------------------------------------------------------------

def test_find_records_without_filters_queries_all_ids():
    """TC-VEC-052 | 无过滤条件时使用默认 filter 'id != ""' 且不带 limit/offset

    输入: find_records(name=None, organization=None, layer=None, status=None,
                       owner=None, limit=None, offset=0)
    预期输出: 空记录列表；query 无 limit/offset 键
    断言点: filter 精确 + kwargs 中不含 limit/offset + 返回 []
    防回归: 若默认 filter 变成 None，Milvus 会拒绝空表达式
    """

    client = _fake_client(query_result=[])

    records = _client_for(client).find_records(COLLECTION)

    assert records == []
    kwargs = client.query.call_args.kwargs
    assert kwargs["filter"] == 'id != ""'
    assert "limit" not in kwargs
    assert "offset" not in kwargs
    client.load_collection.assert_called_once_with(collection_name=COLLECTION)


def test_find_records_creates_missing_collection_and_returns_empty():
    """TC-VEC-053 | 集合缺失时建表并直接返回空列表

    输入: has_collection=False
    预期输出: []
    断言点: create_collection 一次 + query 零次
    防回归: 若建表后继续查询，会命中空集合并掩盖首次注册时序问题
    """

    client = _fake_client(has_collection=False)

    assert _client_for(client).find_records(COLLECTION) == []
    client.create_collection.assert_called_once()
    client.query.assert_not_called()


def test_find_records_combines_all_filters_in_order():
    """TC-VEC-054 | name/organization/owner/layer/status 按固定顺序拼成表达式

    输入: name="agent", organization="org-a", owner="alice",
          layer=" omc ", status="published"
    预期输出: name like ... and organization == ... and owner == ... and
              layer == ... and status == ...
    断言点: 过滤表达式逐段精确（含 like 的 % 通配与 OR 顺序）
    防回归: 任一条件漏拼（如 owner 未参与过滤）都会返回越权数据
    """

    client = _fake_client(query_result=[])

    _client_for(client).find_records(
        COLLECTION,
        name="agent",
        organization="org-a",
        owner="alice",
        layer=" omc ",
        status="published",
    )

    assert client.query.call_args.kwargs["filter"] == (
        'name like "%agent%" and organization == "org-a" and owner == "alice" '
        'and layer == "omc" and status == "published"'
    )


def test_find_records_requires_layer_field_when_layer_given():
    """TC-VEC-055 | 带 layer 的查询在未迁移集合上抛迁移异常

    输入: schema 无 layer，layer="omc"
    预期输出: LayerMigrationRequiredError
    断言点: 异常类型 + 消息含集合名 + query 未执行
    防回归: 若迁移校验被删除，会返回缺少分层信息的旧数据
    """

    client = _fake_client(schema=_schema(LEGACY_FIELDS))

    with pytest.raises(LayerMigrationRequiredError, match="legacy_agents"):
        _client_for(client).find_records("legacy_agents", layer="omc")

    client.query.assert_not_called()


def test_find_records_maps_rows_to_agent_records():
    """TC-VEC-056 | 查询结果被转换为 AgentRecord 列表

    输入: query 返回 2 条 entity（layer 分别为 omc/未知）
    预期输出: 2 个 AgentRecord，layer 正确归一
    断言点: 类型 + 两个 name + 两个 layer 精确有序
    防回归: 若返回原始 dict，调用方 .agent_card 报错
    """

    client = _fake_client(query_result=[
        _entity(agent_id="a1", name="agent-a", layer="omc"),
        _entity(agent_id="a2", name="agent-b", layer="unknown"),
    ])

    records = _client_for(client).find_records(COLLECTION)

    assert [type(record) for record in records] == [AgentRecord, AgentRecord]
    assert [record.agent_card.name for record in records] == ["agent-a", "agent-b"]
    assert [record.layer for record in records] == ["omc", "unknown"]


def test_find_records_passes_limit_and_positive_offset():
    """TC-VEC-057 | limit 与正 offset 透传给底层查询

    输入: limit=5, offset=10
    预期输出: query kwargs 含 limit=5, offset=10
    断言点: 两个数值精确相等
    防回归: offset 被丢弃会导致翻页重复返回第一页
    """

    client = _fake_client(query_result=[])

    _client_for(client).find_records(COLLECTION, limit=5, offset=10)

    kwargs = client.query.call_args.kwargs
    assert kwargs["limit"] == 5
    assert kwargs["offset"] == 10


def test_find_records_omits_zero_offset():
    """TC-VEC-058 | offset=0 不传给底层（避免非法参数）

    输入: limit=5, offset=0
    预期输出: kwargs 含 limit=5 且不含 offset
    断言点: "offset" not in kwargs + limit 精确
    防回归: 若把 offset>0 判断删掉，Milvus 会收到 offset=0 并在部分版本报错
    """

    client = _fake_client(query_result=[])

    _client_for(client).find_records(COLLECTION, limit=5, offset=0)

    kwargs = client.query.call_args.kwargs
    assert "offset" not in kwargs
    assert kwargs["limit"] == 5


def test_find_records_by_key_uses_composite_primary_key_and_limit_one():
    """TC-VEC-059 | 按 name::organization 复合主键精确查询且只取一条

    输入: name="agent-a", organization="org-a"
    预期输出: filter == 'id == "agent-a::org-a"', limit == 1
    断言点: filter 与 limit 精确相等 + 返回记录 name
    防回归: 分隔符改动（:: → /）会让主键查询永远落空
    """

    client = _fake_client(query_result=[_entity()])

    records = _client_for(client).find_records_by_key(
        COLLECTION, "agent-a", "org-a"
    )

    kwargs = client.query.call_args.kwargs
    assert kwargs["filter"] == 'id == "agent-a::org-a"'
    assert kwargs["limit"] == 1
    assert len(records) == 1
    assert records[0].agent_card.name == "agent-a"


# ---------------------------------------------------------------------------
# retrieve_records (layer-aware search used by the registry core)
# ---------------------------------------------------------------------------

def test_retrieve_records_creates_missing_collection_and_returns_empty():
    """TC-VEC-060 | 集合缺失时建表并返回空列表（不检索）

    输入: has_collection=False
    预期输出: []
    断言点: create_collection 一次 + load/search 零次
    防回归: 未建集合就检索会在真实 Milvus 上报错
    """

    client = _fake_client(has_collection=False)

    assert _client_for(client).retrieve_records(
        COLLECTION, EMBEDDING, 5
    ) == []
    client.create_collection.assert_called_once()
    client.load_collection.assert_not_called()
    client.search.assert_not_called()


def test_retrieve_records_returns_empty_for_no_hits():
    """TC-VEC-061 | 检索无命中返回空列表

    输入: search 返回 []
    预期输出: []
    断言点: 返回值 == [] + search limit 等于 top_n
    防回归: 空结果分支删除后会 IndexError
    """

    client = _fake_client(search_result=[])

    assert _client_for(client).retrieve_records(
        COLLECTION, EMBEDDING, 4
    ) == []
    assert client.search.call_args.kwargs["limit"] == 4


def test_retrieve_records_returns_records_with_full_search_params():
    """TC-VEC-062 | 命中记录转为 AgentRecord，检索参数完整

    输入: search 返回一条命中，top_n=2
    预期输出: 单条 AgentRecord
    断言点: search kwargs 全字段精确 + 返回类型与 layer 归一
    防回归: anns_field 写错（如 "vector"）会查到错误字段
    """

    client = _fake_client(search_result=[[_hit(_entity(layer="omc"))]])

    records = _client_for(client).retrieve_records(COLLECTION, EMBEDDING, 2)

    assert client.search.call_args.kwargs == {
        "collection_name": COLLECTION,
        "data": [EMBEDDING],
        "anns_field": "embedding",
        "limit": 2,
        "output_fields": [
            "id", "name", "description", "organization", "agent_card",
            "status", "owner", "layer",
        ],
        "search_params": {"metric_type": "L2", "param": {"nprobe": 10}},
    }
    assert len(records) == 1
    assert isinstance(records[0], AgentRecord)
    assert records[0].layer == "omc"


def test_retrieve_records_applies_selector_to_filter_results():
    """TC-VEC-063 | selector 收到 (task, agents_info, top_n) 并按其选择裁剪结果

    输入: 两条命中；selector 只保留 ("org-a", "agent-a")
    预期输出: 一条记录；selector 入参的 agents_info 结构正确
    断言点: selector 调用参数精确（task/agents_info/top_n）+ 返回列表长度与 name
    防回归: 若 agents_info 字段名变更或 selector 结果未生效，断言失败
    """

    hit_a = _hit(_entity(agent_id="a1", name="agent-a", organization="org-a"))
    hit_b = _hit(_entity(agent_id="a2", name="agent-b", organization="org-b"))
    client = _fake_client(search_result=[[hit_a, hit_b]])

    seen = {}

    def selector(task, agents_info, top_n):
        seen["task"] = task
        seen["agents_info"] = agents_info
        seen["top_n"] = top_n
        return [("org-a", "agent-a")]

    records = _client_for(client).retrieve_records(
        COLLECTION, EMBEDDING, 2, selector=selector, task="route this"
    )

    assert seen["task"] == "route this"
    assert seen["top_n"] == 2
    assert seen["agents_info"] == [
        {
            "name": "agent-a",
            "description": "test agent",
            "organization": "org-a",
            "skills": ["skill-1"],
        },
        {
            "name": "agent-b",
            "description": "test agent",
            "organization": "org-b",
            "skills": ["skill-1"],
        },
    ]
    assert len(records) == 1
    assert records[0].agent_card.name == "agent-a"


def test_retrieve_records_with_layer_filter_requires_migration():
    """TC-VEC-064 | 带 layer 检索在未迁移集合上抛迁移异常

    输入: schema 无 layer，layer="omc"
    预期输出: LayerMigrationRequiredError
    断言点: 异常类型 + prune 消息 + search 未执行
    防回归: 分层检索失去校验会返回未分层数据
    """

    client = _fake_client(schema=_schema(LEGACY_FIELDS))

    with pytest.raises(LayerMigrationRequiredError, match="no layer field"):
        _client_for(client).retrieve_records(
            "legacy_agents", EMBEDDING, 3, layer="omc"
        )

    client.search.assert_not_called()


def test_retrieve_records_propagates_search_failure():
    """TC-VEC-065 | 检索失败向上抛（不静默返回空结果）

    输入: client.search 抛 MilvusException("segment missing")
    预期输出: MilvusException("segment missing")
    断言点: 异常类型 + 消息（该层没有 try/except，必须原样透传）
    防回归: 若有人加了 return []，调用方无法区分"没结果"和"后端故障"
    """

    client = _fake_client()
    client.search.side_effect = MilvusException(message="segment missing")

    with pytest.raises(MilvusException, match="segment missing"):
        _client_for(client).retrieve_records(COLLECTION, EMBEDDING, 3)


# ---------------------------------------------------------------------------
# config objects
# ---------------------------------------------------------------------------

def test_convert_vectordb_type_maps_known_value():
    """TC-VEC-066 | 已知类型字符串映射到枚举成员

    输入: "milvus"
    预期输出: VectorDBType.Milvus
    断言点: 枚举成员身份相等（is）
    防回归: 若映射改为字符串拼接，会比较出不等
    """

    assert convert_vectordb_type("milvus") is VectorDBType.Milvus


def test_convert_vectordb_type_rejects_unknown_value():
    """TC-VEC-067 | 未知类型抛出 ValueError

    输入: "redis"
    预期输出: ValueError("Unsupported vector database type")
    断言点: 异常类型 + 完整消息
    防回归: 若静默返回默认 Milvus，错配的配置会连到错误后端
    """

    with pytest.raises(
        ValueError, match="^Unsupported vector database type$"
    ):
        convert_vectordb_type("redis")


def test_vectordb_config_reads_connection_profile():
    """TC-VEC-068 | VectorDBConfig 从连接配置读取 uri/version/description/token

    输入: load_connection_config("milvus") 返回四项配置
    预期输出: VectorDBConfig 四个属性与配置一致
    断言点: 四个属性精确相等
    防回归: 键名改动（uri→url）会抛 KeyError，本用例直接失败
    """

    profile = {
        "description": "milvus vector store",
        "uri": "http://milvus:19530",
        "version": "2.6",
        "token": "tok",
    }
    with patch.object(config_module, "load_connection_config", return_value=profile) as load:
        config = get_vectordb_config()

    load.assert_called_once_with("milvus")
    assert set(config) == {"milvus"}
    assert config["milvus"].vectordb_type is VectorDBType.Milvus
    assert config["milvus"].description == "milvus vector store"
    assert config["milvus"].uri == "http://milvus:19530"
    assert config["milvus"].version == "2.6"
    assert config["milvus"].token == "tok"


def test_get_vectordb_config_by_type_looks_up_by_value():
    """TC-VEC-069 | 按枚举类型取配置

    输入: VectorDBType.Milvus（连接配置已 mock）
    预期输出: 对应 VectorDBConfig，uri 正确
    断言点: uri 精确相等
    防回归: 若用 str(enum) 作键，会取不到并返回 None
    """

    profile = {"description": "d", "uri": "http://milvus:19530", "version": "2.6"}
    with patch.object(config_module, "load_connection_config", return_value=profile):
        config = get_vectordb_config_by_type(VectorDBType.Milvus)

    assert config is not None
    assert config.uri == "http://milvus:19530"
    assert config.token == ""


def test_create_vectordb_tool_instance_returns_registered_client():
    """TC-VEC-070 | 注册表按类型实例化 MilvusDBClient 并传入配置字典

    输入: VectorDBConfig("milvus", {...})
    预期输出: MilvusDBClient 实例，且构造函数收到 config.__dict__
    断言点: 返回类型 + 底层 MilvusClient 收到的 uri/token
    防回归: 若装饰器注册键从 VectorDBType.Milvus 改成字符串，查找会 KeyError
    """

    config = VectorDBConfig(
        "milvus",
        {"description": "d", "uri": "http://milvus:19530", "version": "2.6", "token": "tok"},
    )
    with patch.object(milvus_module, "MilvusClient") as ctor:
        instance = registry_module.create_vectordb_tool_instance(config)

    assert isinstance(instance, MilvusDBClient)
    assert instance.config["token"] == "tok"
    ctor.assert_called_once_with(uri="http://milvus:19530", token="tok")


def test_get_or_create_vectordb_tool_instance_caches_per_type(monkeypatch):
    """TC-VEC-071 | 同一类型只创建一次实例（缓存生效）

    输入: 连续两次调用 get_or_create_vectordb_tool_instance(同一 config)
    预期输出: 同一个对象；底层 MilvusClient 只构造一次
    断言点: 两次返回 is 相等 + 构造调用计数 == 1
    防回归: 若缓存字典被绕过，每个请求都会新建连接池
    """

    config = VectorDBConfig(
        "milvus", {"description": "d", "uri": "http://milvus:19530", "version": "2.6"}
    )
    cache = {}
    monkeypatch.setattr(registry_module, "vectordb_tool_instance", cache)

    with patch.object(milvus_module, "MilvusClient") as ctor:
        first = registry_module.get_or_create_vectordb_tool_instance(config)
        second = registry_module.get_or_create_vectordb_tool_instance(config)

    assert first is second
    assert ctor.call_count == 1
    assert cache[VectorDBType.Milvus] is first


def test_base_client_cannot_be_instantiated():
    """TC-VEC-072 | 抽象基类不可实例化（强制子类实现全部接口）

    输入: VectorDBClient()
    预期输出: TypeError（缺少抽象方法实现）
    断言点: 异常类型 + 消息点名 create_collection
    防回归: 若 @abstractmethod 被移除，空实现会被实例化并在运行期报错
    """

    with pytest.raises(TypeError, match="create_collection"):
        VectorDBClient()


# ---------------------------------------------------------------------------
# package __init__ switch (loaded into a throw-away module object)
# ---------------------------------------------------------------------------

def _load_package_module(**conf):
    """Execute common/vector_db/__init__.py against a fake configuration."""

    init_path = os.path.join(
        os.path.dirname(os.path.abspath(vector_db_package.__file__)), "__init__.py"
    )
    spec = importlib.util.spec_from_file_location("vector_db_init_probe", init_path)
    module = importlib.util.module_from_spec(spec)
    with patch("common.util.app_config.get_conf", return_value=conf):
        spec.loader.exec_module(module)
    return module


def test_package_exports_client_when_vectordb_enabled():
    """TC-VEC-073 | use_vectordb=true 时导出 MilvusDBClient

    输入: get_conf() → {"use_vectordb": "TRUE"}
    预期输出: module.MilvusDBClient 为 MilvusDBClient 类，__all__ == ["MilvusDBClient"]
    断言点: 属性身份 + __all__ 精确相等（大小写不敏感开关）
    防回归: 若分支判断改成严格 "true"，大写配置会静默禁用向量库
    """

    module = _load_package_module(use_vectordb="TRUE")

    assert module.MilvusDBClient is MilvusDBClient
    assert module.__all__ == ["MilvusDBClient"]


def test_package_hides_client_when_vectordb_disabled():
    """TC-VEC-074 | use_vectordb=false/缺省时 MilvusDBClient 为 None

    输入: get_conf() → {}
    预期输出: module.MilvusDBClient is None，__all__ == []
    断言点: 属性 is None + __all__ 空列表
    防回归: 若默认值改为 True，未部署 Milvus 的实例会在导入期连库
    """

    module = _load_package_module()

    assert module.MilvusDBClient is None
    assert module.__all__ == []


# ---------------------------------------------------------------------------
# layer guard edge: layer filter on a collection that does not exist yet
# ---------------------------------------------------------------------------

def test_find_records_with_layer_creates_collection_before_guard():
    """TC-VEC-075 | 带 layer 查询遇到不存在的集合时先建表再校验

    输入: 集合初始不存在（建表后存在），layer="omc"，query 返回一条记录
    预期输出: 一条 AgentRecord；建表一次，guard 校验通过后执行查询
    断言点: create_collection 一次 + query filter == 'layer == "omc"' +
            返回记录 layer == "omc"
    防回归: 若 _require_layer_field 不先建表，真实 Milvus 会抛集合不存在，
            空库上的首次带层查询直接失败
    """

    client = _self_creating_client(query_result=[_entity(layer="omc")])

    records = _client_for(client).find_records(COLLECTION, layer="omc")

    client.create_collection.assert_called_once()
    assert client.query.call_args.kwargs["filter"] == 'layer == "omc"'
    assert len(records) == 1
    assert records[0].layer == "omc"


def test_retrieve_records_applies_layer_and_status_filter():
    """TC-VEC-076 | 分层向量检索把 layer/status 编入 search filter

    输入: 已迁移集合，layer=" omc ", status="published"
    预期输出: search kwargs["filter"] == 'layer == "omc" and status == "published"'
    断言点: filter 表达式精确相等（含 layer 去空格）
    防回归: 若 filter 只拼 status 或漏掉去空格，会检索到其它层的数据
    """

    client = _fake_client(search_result=[[]])

    _client_for(client).retrieve_records(
        COLLECTION, EMBEDDING, 2, layer=" omc ", status="published"
    )

    assert client.search.call_args.kwargs["filter"] == (
        'layer == "omc" and status == "published"'
    )


# ---------------------------------------------------------------------------
# previously reported defects (fixed; kept as regression guards)
# ---------------------------------------------------------------------------

def test_retrieve_entity_after_failed_connection_returns_empty_not_attribute_error():
    """TC-VEC-077 | 连接失败后检索返回空列表而非 AttributeError

    输入: 构造时 MilvusClient 抛 MilvusException("connect refused")，随后
          retrieve_entity({"collection_name": "agents", "embedding": ...})
    预期输出: []（与 insert_entity 返回 False 的失败面一致）
    断言点: db.client is None + insert_entity 返回 False + retrieve_entity 返回 []
    防回归: 若 __init__ 改回"不设置 client"，retrieve_entity 会重新抛
            AttributeError 而不是返回 []，本用例失败
    历史: 修复前 __init__ 吞掉连接异常且不留属性，retrieve_entity 的
          has_collection 调用在 try 之外，AttributeError 直接冒给调用方
    """

    with patch.object(
        milvus_module, "MilvusClient",
        side_effect=MilvusException(message="connect refused"),
    ):
        db = MilvusDBClient({"uri": "http://milvus:19530", "token": ""})

    assert db.client is None
    assert db.insert_entity({
        "collection_name": COLLECTION,
        "entity": _entity(layer=None),
    }) is False
    assert db.retrieve_entity({
        "collection_name": COLLECTION,
        "embedding": EMBEDDING,
    }) == []
    assert db.find_records(COLLECTION) == []
    assert db.retrieve_records(COLLECTION, EMBEDDING, top_n=5) == []


def test_failed_connection_degrades_every_operation():
    """TC-VEC-079 | 连接失败时所有公开操作都返回空结果而不是抛异常

    输入: 构造时 MilvusClient 抛 MilvusException("down")，随后依次调用
          create_collection / insert / delete / update / query_by_key /
          get_all_entities / retrieve_entity / find_records / retrieve_records
    预期输出: 布尔方法返回 False，列表方法返回 []
    断言点: 九次调用的返回值（全部走 _client_ready 守卫）+ 全程无异常
    防回归: 若任一方法漏掉守卫，会退化成 AttributeError，本用例失败
    """

    with patch.object(
        milvus_module, "MilvusClient",
        side_effect=MilvusException(message="down"),
    ):
        db = MilvusDBClient({"uri": "http://milvus:19530", "token": ""})

    assert db.client is None
    assert db.create_collection({"collection_name": COLLECTION}) is False
    assert db.insert_entity({
        "collection_name": COLLECTION, "entity": _entity(layer=None),
    }) is False
    assert db.delete_entity({"collection_name": COLLECTION, "id": "a::o"}) is False
    assert db.update_entity({
        "collection_name": COLLECTION, "entity": _entity(layer=None),
    }) is False
    assert db.query_by_key({
        "collection_name": COLLECTION, "key": "name", "value": "a",
    }) == []
    assert db.get_all_entities({"collection_name": COLLECTION}) == []
    assert db.retrieve_entity({
        "collection_name": COLLECTION, "embedding": EMBEDDING,
    }) == []
    assert db.find_records(COLLECTION) == []
    assert db.retrieve_records(COLLECTION, EMBEDDING, top_n=5) == []


def test_insert_entity_surfaces_invalid_dimension_as_value_error():
    """TC-VEC-078 | 非法维度以 ValueError 明确报错

    输入: entity["embedding"] 长度 2
    预期输出: VectorDimensionError（ValueError 子类），消息 "Vector dimension must be 1024"
    断言点: 异常类型 + 消息
    防回归: 若通用 except 再次吞掉该异常并返回 False，本用例失败
    历史: 修复前 insert_entity 的通用 except 把维度校验异常一并吞掉，调用方
          无法区分"维度非法"与"后端写失败"
    """

    client = _fake_client()

    with pytest.raises(ValueError, match="Vector dimension must be 1024"):
        _client_for(client).insert_entity({
            "collection_name": COLLECTION,
            "entity": {**_entity(layer=None), "embedding": [0.1, 0.2]},
        })
