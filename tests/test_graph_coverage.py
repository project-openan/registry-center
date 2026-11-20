# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Statement-coverage tests for ``agent_registry.agent_to_graph.graph``.

The module is a thin synchronous facade over the async knowledge-graph router
endpoints.  Every case below drives the facade with an ``AsyncMock`` router and
asserts on the three things a refactor can break: the payload handed to the
router, the value converted back to Neo4j objects, and the failure behaviour
(``None`` / ``False`` / ``[]`` plus one error log).

No Neo4j server, no network and no real event loop leak into these cases.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from neo4j.graph import Graph, Node, Relationship

import agent_registry.knowledge_graph_api.router as kg_router
from agent_registry.agent_to_graph import graph as graph_module
from agent_registry.agent_to_graph.graph import (
    _run_async,
    _to_node,
    _to_relationship,
    create_node,
    create_relationship,
    delete_node,
    delete_relationship,
    list_nodes,
    list_relationships,
    update_node,
)


NODE_PAYLOAD = {
    "id": "4:abc:42",
    "labels": ["agent", "asset"],
    "properties": {"name": "fault-agent-01", "organization": "wireless"},
}

REL_PAYLOAD = {
    "id": "5:abc:7",
    "type": "has_role",
    "startNodeId": "4:abc:42",
    "endNodeId": "4:abc:99",
    "properties": {"type": "has_role", "targetNode": "operator"},
}


def _router_mock(name, **kwargs):
    """Return an ``AsyncMock`` bound to a router coroutine for one case."""

    return patch.object(kg_router, name, new=AsyncMock(**kwargs))


# ---------------------------------------------------------------------------
# _run_async / converters
# ---------------------------------------------------------------------------

def test_run_async_uses_asyncio_run_without_running_loop():
    """TC-GRAPH-001 | 无运行中事件循环时用 asyncio.run 同步执行协程

    输入: 一个返回 "done" 的协程
    预期输出: 返回 "done"
    断言点: 返回值精确相等（而非非空）
    防回归: 若 _run_async 改成 new_event_loop().run_until_complete 之外的
            错误实现（例如返回协程对象本身），返回值断言失败
    """

    async def coro():
        return "done"

    assert _run_async(coro()) == "done"


def test_run_async_no_loop_returns_computed_value():
    """TC-GRAPH-002 | 无运行中循环时协程内的计算真实执行

    输入: 协程内部 6 * 7
    预期输出: 42
    断言点: 结果值；若实现只返回协程而未执行，将得到协程对象而非 42
    防回归: 防止把 asyncio.run 替换为直接 return coro()
    """

    async def coro():
        return 6 * 7

    result = _run_async(coro())
    assert result == 42
    assert not asyncio.iscoroutine(result)


@pytest.mark.asyncio
async def test_run_async_spawns_thread_when_loop_already_running():
    """TC-GRAPH-003 | 已有事件循环时改在子线程里运行，不死锁

    输入: 在 pytest 的 asyncio 用例（循环已运行）中调用返回 5 的协程
    预期输出: 5，且当前线程不是执行线程
    断言点: 返回值 + 当前事件循环仍在运行（未被 asyncio.run 关闭）
    防回归: 若实现直接在已有循环上 asyncio.run，将抛 RuntimeError 而非返回 5
    """

    async def coro():
        return 5

    loop = asyncio.get_running_loop()
    result = _run_async(coro())
    assert result == 5
    assert loop.is_running()


@pytest.mark.asyncio
async def test_run_async_thread_path_is_repeatable():
    """TC-GRAPH-004 | 线程回退路径可重复调用且互不串值

    输入: 同一循环内连续两次调用 _run_async
    预期输出: 分别得到 "first" / "second"
    断言点: 两次返回值各自正确（共享 result 字典未串值）
    防回归: 若线程结果字典被复用或 join 缺失，第二次结果会错或为 None
    """

    async def make(value):
        return value

    assert _run_async(make("first")) == "first"
    assert _run_async(make("second")) == "second"


def test_to_node_maps_element_id_labels_and_properties():
    """TC-GRAPH-005 | 路由返回的 dict 被完整转换为 Neo4j Node

    输入: {"id": "4:abc:42", "labels": ["agent","asset"], "properties": {...}}
    预期输出: Node，element_id / labels / properties 与输入一致
    断言点: element_id + labels 集合 + properties 字典三项精确相等
    防回归: 若 labels 未转 frozenset、properties 被丢弃或 id 错位，断言失败
    """

    node = _to_node(NODE_PAYLOAD)

    assert isinstance(node, Node)
    assert node.element_id == "4:abc:42"
    assert set(node.labels) == {"agent", "asset"}
    assert dict(node) == {"name": "fault-agent-01", "organization": "wireless"}


def test_to_node_uses_empty_defaults_for_missing_keys():
    """TC-GRAPH-006 | 缺失字段的节点 dict 使用空默认值

    输入: {}
    预期输出: element_id == ""、无标签、无属性
    断言点: 三个默认值精确断言
    防回归: 若默认值写成 None，.element_id 访问或 set(labels) 会失败/不等
    """

    node = _to_node({})

    assert node.element_id == ""
    assert set(node.labels) == set()
    assert dict(node) == {}


def test_to_relationship_maps_type_properties_and_endpoints():
    """TC-GRAPH-007 | 关系 dict 转换为 Relationship 且保留两端节点

    输入: REL_PAYLOAD（含 startNodeId / endNodeId）
    预期输出: Relationship(type=has_role)，start/end 节点 element_id 正确
    断言点: type、properties、两端 element_id 与 properties 精确相等
    防回归: 若端点赋值被删除，_start_node/_end_node 的 element_id 断言失败
    """

    rel = _to_relationship(REL_PAYLOAD)

    assert isinstance(rel, Relationship)
    assert rel.type == "has_role"
    assert rel.element_id == "5:abc:7"
    assert dict(rel) == {"type": "has_role", "targetNode": "operator"}
    assert rel.start_node.element_id == "4:abc:42"
    assert rel.end_node.element_id == "4:abc:99"


def test_to_relationship_without_endpoint_ids_leaves_nodes_unset():
    """TC-GRAPH-008 | 缺少端点 id 时不伪造端点节点

    输入: {"type": "has_role", "properties": {}}
    预期输出: Relationship，start_node / end_node 为 None
    断言点: 两处 is None 断言
    防回归: 若把 None 判断改成无条件赋值，将得到空 element_id 的节点而非 None
    """

    rel = _to_relationship({"type": "has_role", "properties": {}})

    assert rel.type == "has_role"
    assert rel.start_node is None
    assert rel.end_node is None


def test_to_relationship_only_start_node_present():
    """TC-GRAPH-009 | 仅有 startNodeId 时只填充起点

    输入: {"type": "owns", "startNodeId": "n-1"}
    预期输出: start_node.element_id == "n-1"，end_node is None
    断言点: 起点精确值 + 终点为 None（两个分支彼此独立）
    防回归: 若两个 if 被合并成一个，终点会跟随起点被错误赋值
    """

    rel = _to_relationship({"type": "owns", "startNodeId": "n-1"})

    assert rel.start_node.element_id == "n-1"
    assert rel.end_node is None


# ---------------------------------------------------------------------------
# list_nodes
# ---------------------------------------------------------------------------

def test_list_nodes_forwards_pagination_and_label_and_converts_nodes():
    """TC-GRAPH-010 | list_nodes 透传分页/标签参数并转换返回节点

    输入: page=2, limit=5, label="agent"；路由返回 data=[NODE_PAYLOAD]
    预期输出: 单元素 Node 列表
    断言点: 路由收到的关键字参数精确匹配 + 返回列表长度与 element_id
    防回归: 参数名/顺序错位（如把 limit 传给 label）会使 await 断言失败
    """

    payload = {"success": True, "data": [NODE_PAYLOAD]}
    with _router_mock("list_nodes", return_value=payload) as router:
        nodes = list_nodes(page=2, limit=5, label="agent")

    router.assert_awaited_once_with(page=2, limit=5, label="agent")
    assert len(nodes) == 1
    assert nodes[0].element_id == "4:abc:42"


def test_list_nodes_defaults_are_forwarded():
    """TC-GRAPH-011 | list_nodes 默认参数（page=1, limit=100, label=None）透传

    输入: 无参调用
    预期输出: 空列表
    断言点: 路由收到 page=1, limit=100, label=None 的精确 kwargs
    防回归: 若默认值被改成 0/None 或标签默认值被省略，断言失败
    """

    with _router_mock("list_nodes", return_value={"data": []}) as router:
        nodes = list_nodes()

    router.assert_awaited_once_with(page=1, limit=100, label=None)
    assert nodes == []


def test_list_nodes_returns_empty_list_when_router_raises():
    """TC-GRAPH-012 | 路由异常被吞掉，返回空列表并记录一条错误日志

    输入: 路由抛 RuntimeError("db down")
    预期输出: []
    断言点: 返回值 == [] + logger.error 调用次数为 1 且消息精确匹配
    防回归: 若异常被重新抛出、或日志被删除，两条断言分别失败
    """

    with _router_mock("list_nodes", side_effect=RuntimeError("db down")), \
            patch.object(graph_module, "logger") as logger:
        nodes = list_nodes()

    assert nodes == []
    logger.error.assert_called_once_with("Error while listing nodes: db down")


def test_list_nodes_missing_data_key_returns_empty_list():
    """TC-GRAPH-013 | 路由响应缺少 data 字段时返回空列表

    输入: 路由返回 {"success": False}
    预期输出: []
    断言点: 返回值精确等于 []（未抛 KeyError/TypeError）
    防回归: 若 .get("data", []) 改为 ["data"]，本用例将因异常而失败
    """

    with _router_mock("list_nodes", return_value={"success": False}):
        assert list_nodes() == []


# ---------------------------------------------------------------------------
# create_node
# ---------------------------------------------------------------------------

def test_create_node_rejects_empty_labels_without_calling_router():
    """TC-GRAPH-014 | 空标签列表直接拒绝，不触达路由

    输入: labels=[]
    预期输出: None + 一条 "at least one label is required" 错误日志
    断言点: 返回值 is None + 日志精确消息 + 路由未被 await
    防回归: 若前置校验被删除，路由会被调用（assert_not_awaited 失败）
    """

    with _router_mock("create_node", return_value={"data": NODE_PAYLOAD}) as router, \
            patch.object(graph_module, "logger") as logger:
        node = create_node([])

    assert node is None
    logger.error.assert_called_once_with(
        "Failed to create node, at least one label is required"
    )
    router.assert_not_awaited()


def test_create_node_sends_labels_and_properties_payload():
    """TC-GRAPH-015 | create_node 组装 {labels, properties} 负载并回读节点

    输入: labels=["agent"], properties={"name": "a"}
    预期输出: Neo4j Node（element_id/labels/properties 来自路由 data）
    断言点: 路由收到的单个 dict 参数精确相等 + 返回节点三项属性
    防回归: 负载键名（labels/properties）被改动即失败
    """

    with _router_mock("create_node", return_value={"data": NODE_PAYLOAD}) as router:
        node = create_node(["agent"], {"name": "a"})

    router.assert_awaited_once_with({"labels": ["agent"], "properties": {"name": "a"}})
    assert node.element_id == "4:abc:42"
    assert set(node.labels) == {"agent", "asset"}
    assert dict(node) == {"name": "fault-agent-01", "organization": "wireless"}


def test_create_node_defaults_properties_to_empty_dict():
    """TC-GRAPH-016 | properties 为 None 时以空 dict 发送

    输入: labels=["agent"], properties=None
    预期输出: 路由收到 {"labels": [...], "properties": {}}
    断言点: 负载中 properties 精确等于 {}
    防回归: 若 "properties or {}" 退化为直接传 None，路由入参断言失败
    """

    with _router_mock("create_node", return_value={"data": NODE_PAYLOAD}) as router:
        create_node(["agent"])

    assert router.await_args.args == ({"labels": ["agent"], "properties": {}},)


def test_create_node_returns_none_when_router_raises():
    """TC-GRAPH-017 | 路由异常时 create_node 返回 None 并记录日志

    输入: 路由抛 ValueError("bad label")
    预期输出: None
    断言点: 返回值 is None + 日志消息精确匹配
    防回归: 若异常传播或日志文案变化，用例变红
    """

    with _router_mock("create_node", side_effect=ValueError("bad label")), \
            patch.object(graph_module, "logger") as logger:
        node = create_node(["agent"])

    assert node is None
    logger.error.assert_called_once_with("Error while creating node: bad label")


def test_create_node_missing_data_key_yields_empty_node():
    """TC-GRAPH-018 | 响应缺少 data 时返回空属性的 Node 而非崩溃

    输入: 路由返回 {}
    预期输出: Node，element_id == ""，无标签无属性
    断言点: 三个默认值精确断言
    防回归: 若 result.get("data") 无默认值，会抛 AttributeError 使用例失败
    """

    with _router_mock("create_node", return_value={}):
        node = create_node(["agent"])

    assert node.element_id == ""
    assert set(node.labels) == set()
    assert dict(node) == {}


# ---------------------------------------------------------------------------
# update_node
# ---------------------------------------------------------------------------

def test_update_node_rejects_empty_properties_without_calling_router():
    """TC-GRAPH-019 | 空 properties 直接拒绝，不触达路由

    输入: id="n-1", properties={}
    预期输出: None + "properties are required" 错误日志
    断言点: 返回 None + 日志精确消息 + 路由未 await
    防回归: 删除校验会让空更新打到图库，路由调用断言失败
    """

    with _router_mock("update_node", return_value={"data": NODE_PAYLOAD}) as router, \
            patch.object(graph_module, "logger") as logger:
        node = update_node("n-1", {})

    assert node is None
    logger.error.assert_called_once_with(
        "Failed to update node, properties are required"
    )
    router.assert_not_awaited()


def test_update_node_sends_id_and_wrapped_properties():
    """TC-GRAPH-020 | update_node 以 (id, {"properties": ...}) 调用路由

    输入: id="n-1", properties={"status": "published"}
    预期输出: 转换后的 Node
    断言点: 位置参数精确等于 ("n-1", {"properties": {...}}) + 节点 element_id
    防回归: 若 properties 未包一层（或 id 与 payload 顺序颠倒）即失败
    """

    with _router_mock("update_node", return_value={"data": NODE_PAYLOAD}) as router:
        node = update_node("n-1", {"status": "published"})

    assert router.await_args.args == ("n-1", {"properties": {"status": "published"}})
    assert node.element_id == "4:abc:42"


def test_update_node_returns_none_when_router_raises():
    """TC-GRAPH-021 | 路由异常时 update_node 返回 None 并记录日志

    输入: 路由抛 RuntimeError("not found")
    预期输出: None
    断言点: 返回 None + 日志消息精确匹配
    防回归: 异常透传或日志丢失都会使断言失败
    """

    with _router_mock("update_node", side_effect=RuntimeError("not found")), \
            patch.object(graph_module, "logger") as logger:
        node = update_node("n-1", {"a": 1})

    assert node is None
    logger.error.assert_called_once_with("Error while updating node: not found")


# ---------------------------------------------------------------------------
# delete_node
# ---------------------------------------------------------------------------

def test_delete_node_forwards_force_false_and_reports_success():
    """TC-GRAPH-022 | delete_node 默认 force=False 且成功返回 True

    输入: id="n-1"（不传 force）
    预期输出: True，路由收到 force=False
    断言点: 返回值 is True + 路由 await 参数 ("n-1", force=False)
    防回归: force 默认值改为 True 会造成误删，本断言失败
    """

    with _router_mock("delete_node", return_value=None) as router:
        deleted = delete_node("n-1")

    assert deleted is True
    router.assert_awaited_once_with("n-1", force=False)


def test_delete_node_forwards_force_true():
    """TC-GRAPH-023 | force=True 被透传给路由

    输入: id="n-1", force=True
    预期输出: True，路由收到 force=True
    断言点: 返回值 + 关键字参数 force=True 精确匹配
    防回归: 若 force 被硬编码，级联删除语义失效
    """

    with _router_mock("delete_node", return_value=None) as router:
        assert delete_node("n-1", force=True) is True

    router.assert_awaited_once_with("n-1", force=True)


def test_delete_node_returns_false_when_router_raises():
    """TC-GRAPH-024 | 路由异常时 delete_node 返回 False 并记录日志

    输入: 路由抛 RuntimeError("still attached")
    预期输出: False
    断言点: 返回值 is False + 日志消息精确匹配
    防回归: 若失败被当成成功返回 True，断言失败
    """

    with _router_mock("delete_node", side_effect=RuntimeError("still attached")), \
            patch.object(graph_module, "logger") as logger:
        deleted = delete_node("n-1", force=True)

    assert deleted is False
    logger.error.assert_called_once_with(
        "Error while deleting node: still attached"
    )


# ---------------------------------------------------------------------------
# create_relationship
# ---------------------------------------------------------------------------

def test_create_relationship_rejects_empty_type():
    """TC-GRAPH-025 | 关系类型为空时拒绝创建

    输入: type="", start="a", end="b"
    预期输出: None + "type is required" 日志
    断言点: 返回 None + 日志精确消息 + 路由未调用
    防回归: 删除校验会创建无名关系，路由调用断言失败
    """

    with _router_mock("create_relationship", return_value={"data": REL_PAYLOAD}) as router, \
            patch.object(graph_module, "logger") as logger:
        rel = create_relationship("", "a", "b")

    assert rel is None
    logger.error.assert_called_once_with(
        "Failed to create relationship, type is required"
    )
    router.assert_not_awaited()


@pytest.mark.parametrize(
    "start_node_id,end_node_id",
    [("", "b"), ("a", ""), ("", "")],
    ids=["missing-start", "missing-end", "missing-both"],
)
def test_create_relationship_rejects_missing_endpoints(start_node_id, end_node_id):
    """TC-GRAPH-026 | 任一端点 id 为空都拒绝创建

    输入: (start, end) ∈ {("","b"), ("a",""), ("","")}
    预期输出: None + "start and end node IDs are required" 日志
    断言点: 返回 None + 日志精确消息 + 路由未调用（三组参数均生效）
    防回归: 若 or 改为 and，任一为空仍会创建悬空关系
    """

    with _router_mock("create_relationship", return_value={"data": REL_PAYLOAD}) as router, \
            patch.object(graph_module, "logger") as logger:
        rel = create_relationship("has_role", start_node_id, end_node_id)

    assert rel is None
    logger.error.assert_called_once_with(
        "Failed to create relationship, start and end node IDs are required"
    )
    router.assert_not_awaited()


def test_create_relationship_sends_full_payload_and_maps_relationship():
    """TC-GRAPH-027 | 关系负载字段名（startNodeId/endNodeId）正确并回读关系

    输入: type="has_role", start="4:abc:42", end="4:abc:99", properties={...}
    预期输出: Relationship(has_role)，两端 element_id 正确
    断言点: 路由入参 dict 精确相等 + rel.type + 两端 element_id
    防回归: 若字段名写成 start_node_id，路由入参断言失败
    """

    payload = {
        "type": "has_role",
        "startNodeId": "4:abc:42",
        "endNodeId": "4:abc:99",
        "properties": {"targetNode": "operator"},
    }
    with _router_mock("create_relationship", return_value={"data": REL_PAYLOAD}) as router:
        rel = create_relationship(
            "has_role", "4:abc:42", "4:abc:99", {"targetNode": "operator"}
        )

    router.assert_awaited_once_with(payload)
    assert rel.type == "has_role"
    assert rel.start_node.element_id == "4:abc:42"
    assert rel.end_node.element_id == "4:abc:99"


def test_create_relationship_defaults_properties_to_empty_dict():
    """TC-GRAPH-028 | properties 省略时发送空 dict

    输入: properties=None
    预期输出: 路由负载中 properties == {}
    断言点: 负载键值精确相等
    防回归: "properties or {}" 退化为 None 会使断言失败
    """

    with _router_mock("create_relationship", return_value={"data": REL_PAYLOAD}) as router:
        create_relationship("has_role", "a", "b")

    assert router.await_args.args == ({
        "type": "has_role",
        "startNodeId": "a",
        "endNodeId": "b",
        "properties": {},
    },)


def test_create_relationship_returns_none_when_router_raises():
    """TC-GRAPH-029 | 路由异常时 create_relationship 返回 None 并记录日志

    输入: 路由抛 RuntimeError("node missing")
    预期输出: None
    断言点: 返回 None + 日志消息精确匹配
    防回归: 异常透传或日志丢失都会变红
    """

    with _router_mock("create_relationship", side_effect=RuntimeError("node missing")), \
            patch.object(graph_module, "logger") as logger:
        rel = create_relationship("has_role", "a", "b")

    assert rel is None
    logger.error.assert_called_once_with(
        "Error while creating relationship: node missing"
    )


# ---------------------------------------------------------------------------
# delete_relationship
# ---------------------------------------------------------------------------

def test_delete_relationship_rejects_empty_id():
    """TC-GRAPH-030 | 关系 id 为空时拒绝删除

    输入: id=""
    预期输出: False + "id is required" 日志
    断言点: 返回值 is False + 日志精确消息 + 路由未调用
    防回归: 删除校验会让空 id 打到图库，路由调用断言失败
    """

    with _router_mock("delete_relationship", return_value=None) as router, \
            patch.object(graph_module, "logger") as logger:
        deleted = delete_relationship("")

    assert deleted is False
    logger.error.assert_called_once_with(
        "Failed to delete relationship, id is required"
    )
    router.assert_not_awaited()


def test_delete_relationship_forwards_id_and_reports_success():
    """TC-GRAPH-031 | delete_relationship 透传 id 并返回 True

    输入: id="5:abc:7"
    预期输出: True，路由收到该 id
    断言点: 返回值 is True + 路由 await 参数精确相等
    防回归: id 传错（如传成集合/字典）会被断言拦下
    """

    with _router_mock("delete_relationship", return_value=None) as router:
        deleted = delete_relationship("5:abc:7")

    assert deleted is True
    router.assert_awaited_once_with("5:abc:7")


def test_delete_relationship_returns_false_when_router_raises():
    """TC-GRAPH-032 | 路由异常时 delete_relationship 返回 False 并记录日志

    输入: 路由抛 RuntimeError("locked")
    预期输出: False
    断言点: 返回值 is False + 日志消息精确匹配
    防回归: 若失败被吞成 True，断言失败
    """

    with _router_mock("delete_relationship", side_effect=RuntimeError("locked")), \
            patch.object(graph_module, "logger") as logger:
        deleted = delete_relationship("5:abc:7")

    assert deleted is False
    logger.error.assert_called_once_with(
        "Error while deleting relationship: locked"
    )


# ---------------------------------------------------------------------------
# list_relationships
# ---------------------------------------------------------------------------

def test_list_relationships_forwards_filters_and_converts_items():
    """TC-GRAPH-033 | list_relationships 透传 page/limit/type 并转换关系

    输入: page=3, limit=10, type="has_role"；data=[REL_PAYLOAD, REL_PAYLOAD]
    预期输出: 两个 Relationship 对象
    断言点: 路由 kwargs 精确相等 + 列表长度 + 每个元素 type 与端点 id
    防回归: 若 type 参数名写错或被丢弃，kwargs 断言失败
    """

    payload = {"data": [REL_PAYLOAD, REL_PAYLOAD]}
    with _router_mock("list_relationships", return_value=payload) as router:
        rels = list_relationships(page=3, limit=10, type="has_role")

    router.assert_awaited_once_with(page=3, limit=10, type="has_role")
    assert len(rels) == 2
    assert [rel.type for rel in rels] == ["has_role", "has_role"]
    assert [rel.start_node.element_id for rel in rels] == ["4:abc:42", "4:abc:42"]


def test_list_relationships_defaults_are_forwarded():
    """TC-GRAPH-034 | list_relationships 默认参数透传

    输入: 无参调用
    预期输出: 空列表
    断言点: 路由收到 page=1, limit=100, type=None
    防回归: 默认值被改动即失败
    """

    with _router_mock("list_relationships", return_value={"data": []}) as router:
        rels = list_relationships()

    router.assert_awaited_once_with(page=1, limit=100, type=None)
    assert rels == []


def test_list_relationships_returns_empty_list_when_router_raises():
    """TC-GRAPH-035 | 路由异常时 list_relationships 返回空列表并记录日志

    输入: 路由抛 RuntimeError("timeout")
    预期输出: []
    断言点: 返回值 == [] + 日志消息精确匹配
    防回归: 异常透传会让调用方 500，本用例变红
    """

    with _router_mock("list_relationships", side_effect=RuntimeError("timeout")), \
            patch.object(graph_module, "logger") as logger:
        rels = list_relationships()

    assert rels == []
    logger.error.assert_called_once_with(
        "Error while listing relationships: timeout"
    )
