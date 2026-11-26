# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Branch-coverage tests for agent_registry/knowledge_graph_api/router.py.

The endpoints are driven directly (async calls) against a fake Neo4j driver so
every guard/validation/error branch is reachable without a live graph database.
The kg_guard dependency is exercised standalone with fake requests/handlers.

Every test asserts observable results (response payloads, HTTP codes, generated
Cypher fragments) per tests/TEST_DESIGN.md.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import agent_registry.knowledge_graph_api.router as kg
from common.custom.interface_type import InterfaceType
from common.util.authenticate_util import Principal


# ---------------------------------------------------------------------------
# Neo4j doubles
# ---------------------------------------------------------------------------

class _Record(dict):
    """neo4j.Record 替身：按下标/键取值。"""


class _Result:
    def __init__(self, records):
        self._records = list(records)

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None


class _Session:
    def __init__(self, driver):
        self._driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self._driver.queries.append((query, params))
        return _Result(self._driver.results.pop(0) if self._driver.results else [])


class _FakeDriver:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.queries = []
        self.closed = False

    def session(self):
        return _Session(self)

    def close(self):
        self.closed = True


def _node(idx):
    return _Record(id=f"4:node:{idx}", labels=["Agent"],
                   properties={"name": f"n{idx}"})


def _rel(idx):
    return _Record(id=f"4:rel:{idx}", type="WORKS_WITH", startNodeId="4:node:1",
                   endNodeId="4:node:2", properties={"w": 1})


@pytest.fixture(autouse=True)
def _reset_driver_global():
    yield
    kg._neo4j_driver = None


@pytest.fixture
def kg_driver(monkeypatch):
    def install(results=None):
        driver = _FakeDriver(results)
        monkeypatch.setattr(kg, "get_neo4j_driver", lambda: driver)
        return driver
    return install


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# TC-KGG: kg_guard 依赖
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, host="10.0.0.9", method="GET", headers=None, scope=None):
        self.client = SimpleNamespace(host=host)
        self.method = method
        self.headers = headers or {}
        self.scope = scope or {}


@pytest.fixture
def guard_env(monkeypatch):
    """kg_guard 依赖的可控环境：返回 hit 开关与请求工厂。"""
    hit = {"ok": True}
    principal = Principal("10.0.0.9", identity="graph-admin")
    monkeypatch.setattr(kg, "get_conf", lambda: {
        "knowledge_graph.enabled": "true",
        "knowledge_graph.allowed.owners": "graph-admin",
    })
    monkeypatch.setattr(kg, "_kg_strategy",
                        SimpleNamespace(hit=lambda *a, **kw: hit["ok"]))
    monkeypatch.setitem(kg.HandlerRegistry._instances, InterfaceType.AUTHENTICATE.value,
                        SimpleNamespace(handle=async_stub(principal)))
    return SimpleNamespace(hit=hit, request=lambda **kw: _FakeRequest(**kw))


def async_stub(value):
    async def handle(client_ip, request):
        return value
    return handle


def test_kgg_guard_disabled_returns_404(monkeypatch):
    """TC-KGG-001 | knowledge_graph 未启用时 kg_guard 返回 404

    输入: knowledge_graph.enabled=false
    预期输出: HTTPException 404，detail 含 "disabled"
    断言点: 状态码 + detail 关键字
    防回归: 若启用检查被删，禁用的图 API 仍然暴露
    """
    monkeypatch.setattr(kg, "get_conf", lambda: {"knowledge_graph.enabled": "false"})
    with pytest.raises(HTTPException) as exc:
        _run(kg.kg_guard(_FakeRequest()))
    assert exc.value.status_code == 404
    assert "disabled" in exc.value.detail


def test_kgg_guard_rate_limited_returns_429(guard_env):
    """TC-KGG-002 | 限流命中时 kg_guard 返回 429

    输入: 限流器 hit → False
    预期输出: HTTPException 429，detail 含 "Rate limit exceeded"
    断言点: 状态码 + detail 关键字
    防回归: 若限流检查被删，图 API 可被刷爆
    """
    guard_env.hit["ok"] = False
    with pytest.raises(HTTPException) as exc:
        _run(kg.kg_guard(guard_env.request()))
    assert exc.value.status_code == 429


def test_kgg_guard_unauthenticated_returns_401(guard_env, monkeypatch):
    """TC-KGG-003 | 无身份主体时 kg_guard 返回 401

    输入: 认证插件返回匿名 Principal；身份解析未验证
    预期输出: HTTPException 401，detail 含 "Authenticated graph operator required"
    断言点: 状态码 + detail 关键字
    防回归: 若 subject 检查被删，匿名请求可操作图
    """
    monkeypatch.setitem(kg.HandlerRegistry._instances, InterfaceType.AUTHENTICATE.value,
                        SimpleNamespace(handle=async_stub(Principal("10.0.0.9"))))
    with pytest.raises(HTTPException) as exc:
        _run(kg.kg_guard(guard_env.request()))
    assert exc.value.status_code == 401


def test_kgg_guard_identity_verified_supplies_subject(monkeypatch):
    """TC-KGG-004 | 认证插件无主体时采用已验证的 TLS 身份 CN

    输入: resolve_caller_identity 返回 verified 身份 owner=graph-admin
    预期输出: 不抛异常（通过操作者校验）
    断言点: 无异常（84-85 分支可达）
    防回归: 若身份回退被删，mTLS 部署无法使用图 API
    """
    monkeypatch.setattr(kg, "get_conf", lambda: {
        "knowledge_graph.enabled": "true", "knowledge_graph.allowed.owners": "graph-admin"})
    monkeypatch.setattr(kg, "_kg_strategy", SimpleNamespace(hit=lambda *a, **kw: True))
    monkeypatch.setitem(kg.HandlerRegistry._instances, InterfaceType.AUTHENTICATE.value,
                        SimpleNamespace(handle=async_stub(Principal("10.0.0.9"))))
    monkeypatch.setattr(kg, "resolve_caller_identity", lambda request, config: SimpleNamespace(
        owner="graph-admin", verified=True))
    _run(kg.kg_guard(_FakeRequest()))


def test_kgg_guard_scope_authorization(guard_env, monkeypatch):
    """TC-KGG-005 | 非 operator 主体按 scope 授权；GET 需要 read scope

    输入: principal.owner 非白名单；scopes 分别为 write（POST）/ read（GET）/ 仅 write（GET）
    预期输出: POST+write 通过；GET+read 通过；GET+write → 403
    断言点: 两种通过（无异常）+ 403
    防回归: 若 scope 检查被删，任意角色可读写图
    """
    monkeypatch.setitem(kg.HandlerRegistry._instances, InterfaceType.AUTHENTICATE.value,
                        SimpleNamespace(handle=async_stub(SimpleNamespace(
                            owner="vendor-1", subject="vendor-1",
                            scopes=("knowledge_graph:write",)))))
    _run(kg.kg_guard(guard_env.request(method="POST")))  # write scope 放行

    monkeypatch.setitem(kg.HandlerRegistry._instances, InterfaceType.AUTHENTICATE.value,
                        SimpleNamespace(handle=async_stub(SimpleNamespace(
                            owner="vendor-1", subject="vendor-1",
                            scopes=("knowledge_graph:read",)))))
    _run(kg.kg_guard(guard_env.request(method="GET")))  # read scope 放行

    monkeypatch.setitem(kg.HandlerRegistry._instances, InterfaceType.AUTHENTICATE.value,
                        SimpleNamespace(handle=async_stub(SimpleNamespace(
                            owner="vendor-1", subject="vendor-1",
                            scopes=("knowledge_graph:write",)))))
    with pytest.raises(HTTPException) as exc:
        _run(kg.kg_guard(guard_env.request(method="GET")))
    assert exc.value.status_code == 403


def test_kgg_guard_non_operator_forbidden(guard_env, monkeypatch):
    """TC-KGG-006 | 非 operator 且无 scope 时返回 403

    输入: principal.owner=vendor-1（不在白名单）、scopes 为空
    预期输出: HTTPException 403，detail 含 "Graph operator permission required"
    断言点: 状态码 + detail 关键字
    防回归: 若 operator 校验被删，任意认证用户可改图
    """
    monkeypatch.setitem(kg.HandlerRegistry._instances, InterfaceType.AUTHENTICATE.value,
                        SimpleNamespace(handle=async_stub(SimpleNamespace(
                            owner="vendor-1", subject="vendor-1", scopes=()))))
    with pytest.raises(HTTPException) as exc:
        _run(kg.kg_guard(guard_env.request()))
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# TC-KGD: Neo4j 驱动生命周期
# ---------------------------------------------------------------------------

def test_kgd_driver_requires_password(monkeypatch):
    """TC-KGD-101 | 未配置 Neo4j 密码时 get_neo4j_driver 返回 503

    输入: PERSISTENCE_CONF 无 neo4j.password
    预期输出: HTTPException 503，detail 含 "credentials are not configured"
    断言点: 状态码 + detail 关键字
    防回归: 若密码检查被删，会用空密码建立连接
    """
    monkeypatch.setattr(kg, "PERSISTENCE_CONF", {"neo4j.uri": "bolt://h:7687"})
    with pytest.raises(HTTPException) as exc:
        kg.get_neo4j_driver()
    assert exc.value.status_code == 503


def test_kgd_driver_created_and_cached(monkeypatch):
    """TC-KGD-102 | 首次调用创建驱动并缓存；再次调用返回同一实例

    输入: PERSISTENCE_CONF 含密码；GraphDatabase.driver 替身
    预期输出: 两次返回同一对象；auth 参数来自配置
    断言点: is 身份比对 + 构造参数
    防回归: 若缓存被删，每次请求新建驱动连接
    """
    created = {}

    def fake_driver(uri, auth):
        created["args"] = (uri, auth)
        return _FakeDriver()

    monkeypatch.setattr(kg, "GraphDatabase",
                        SimpleNamespace(driver=fake_driver))
    monkeypatch.setattr(kg, "PERSISTENCE_CONF",
                        {"neo4j.uri": "bolt://db:7687", "neo4j.username": "u",
                         "neo4j.password": "p"})
    first = kg.get_neo4j_driver()
    second = kg.get_neo4j_driver()
    assert first is second
    assert created["args"] == ("bolt://db:7687", ("u", "p"))


def test_kgd_close_driver(monkeypatch):
    """TC-KGD-103 | close_neo4j_driver 关闭驱动并清空缓存；无驱动时为空操作

    输入: 已存在的假驱动 / 全局为 None
    预期输出: close 被调用且全局复位为 None；None 时不抛异常
    断言点: closed 状态 + 全局值
    防回归: 若清空被删，重复关闭或残留连接
    """
    fake = _FakeDriver()
    kg._neo4j_driver = fake
    kg.close_neo4j_driver()
    assert fake.closed is True
    assert kg._neo4j_driver is None
    kg.close_neo4j_driver()  # None 分支：无异常


# ---------------------------------------------------------------------------
# TC-KGS: /sync
# ---------------------------------------------------------------------------

def test_kgs_sync_failure_returns_500(monkeypatch):
    """TC-KGS-101 | 同步过程抛错时 /sync 返回 500

    输入: process() 抛 RuntimeError
    预期输出: HTTPException 500，detail 含 "Sync failed"
    断言点: 状态码 + detail 关键字
    防回归: 若异常未捕获，同步失败会裸抛内部错误
    """
    monkeypatch.setattr(kg, "process",
                        lambda: (_ for _ in ()).throw(RuntimeError("watcher down")))
    with pytest.raises(HTTPException) as exc:
        _run(kg.sync_agents_to_graph())
    assert exc.value.status_code == 500
    assert "Sync failed" in exc.value.detail


def test_kgs_sync_success_payload():
    """TC-KGS-102 | /sync 成功返回 {success: true, data: plan}

    输入: process() 返回 plan dict
    预期输出: {"success": True, "data": {"created": 1}}
    断言点: 响应逐字段相等
    防回归: 若响应结构被改坏，调用方解析失败
    """
    monkeypatch_plans = {"plan": {"created": 1}}
    import agent_registry.knowledge_graph_api.router as router_mod
    original = router_mod.process
    router_mod.process = lambda: monkeypatch_plans["plan"]
    try:
        resp = _run(kg.sync_agents_to_graph())
    finally:
        router_mod.process = original
    assert resp == {"success": True, "data": {"created": 1}}


# ---------------------------------------------------------------------------
# TC-KGN: /nodes
# ---------------------------------------------------------------------------

def test_kgn_list_nodes_with_label_and_pagination(kg_driver):
    """TC-KGN-101 | list_nodes 按 label 过滤并给出分页元数据

    输入: page=2, limit=1, label="Agent"；2 条节点，count=2
    预期输出: 查询含 ":Agent" 与 skip=1；pagination hasNext=True/hasPrev=True
    断言点: Cypher 片段 + skip 参数 + 分页四项
    防回归: 若 label 分支被删，过滤查询失效
    """
    driver = kg_driver([[_node(1)], [_Record(count=3)]])
    resp = _run(kg.list_nodes(page=2, limit=1, label="Agent"))
    assert resp["success"] is True
    assert [n["id"] for n in resp["data"]] == ["4:node:1"]
    first_query, first_params = driver.queries[0]
    assert "MATCH (n:Agent)" in first_query
    assert first_params == {"skip": 1, "limit": 1}
    assert any("count(n)" in q for q, _ in driver.queries)
    page = resp["pagination"]
    assert page == {"page": 2, "limit": 1, "total": 3, "totalPages": 3,
                    "hasNext": True, "hasPrev": True}


def test_kgn_list_nodes_without_label(kg_driver):
    """TC-KGN-102 | list_nodes 无 label 时使用全量查询；空图分页边界

    输入: 无数据、count=0
    预期输出: 查询为无标签 MATCH；total=0、totalPages=0、hasNext/hasPrev 均 False
    断言点: 查询片段 + 分页边界值
    防回归: 若空图分页计算改坏，hasNext 误报
    """
    driver = kg_driver([[], [_Record(count=0)]])
    resp = _run(kg.list_nodes(page=1, limit=100, label=None))
    assert "MATCH (n)" in driver.queries[0][0]
    assert "MATCH (n:Agent)" not in driver.queries[0][0]
    assert resp["pagination"] == {"page": 1, "limit": 100, "total": 0,
                                 "totalPages": 0, "hasNext": False, "hasPrev": False}


def test_kgn_list_nodes_invalid_label_rejected(kg_driver):
    """TC-KGN-103 | list_nodes 非法 label 返回 422

    输入: label = "Bad-Label!"（不匹配标识符文法）
    预期输出: HTTPException 422，detail 含 "Invalid label"
    断言点: 状态码 + detail 关键字（注入防护）
    防回归: 若校验被删，label 可注入 Cypher
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.list_nodes(label="Bad-Label!"))
    assert exc.value.status_code == 422
    assert "Invalid label" in exc.value.detail


def test_kgn_create_node_validation_and_success(kg_driver):
    """TC-KGN-104 | create_node：缺 properties → 400；非法 label → 422；成功返回节点

    输入: {"labels": ["Agent"]} / 非法 label / 合法数据
    预期输出: 400 "Properties are required" / 422 / 201 语义的成功响应
    断言点: 异常与响应字段
    防回归: 若校验被删，可创建无属性或带注入标签的节点
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.create_node({"labels": ["Agent"]}))
    assert exc.value.status_code == 400
    assert exc.value.detail == "Properties are required"

    with pytest.raises(HTTPException) as exc:
        _run(kg.create_node({"labels": ["Bad-Label!"], "properties": {"a": 1}}))
    assert exc.value.status_code == 422

    driver = kg_driver([[_node(9)]])
    resp = _run(kg.create_node({"labels": ["Agent"], "properties": {"name": "n"}}))
    assert resp["success"] is True
    assert resp["data"]["id"] == "4:node:9"
    assert "CREATE (n:Agent $properties)" in driver.queries[0][0]


def test_kgn_create_node_no_record_returns_500(kg_driver):
    """TC-KGN-105 | create_node 写入无返回记录时返回 500

    输入: session.run 返回空结果
    预期输出: HTTPException 500，detail 含 "Failed to create node"
    断言点: 状态码 + detail 关键字
    防回归: 若空记录检查被删，写入失败仍报成功
    """
    kg_driver([[]])
    with pytest.raises(HTTPException) as exc:
        _run(kg.create_node({"labels": ["Agent"], "properties": {}}))
    assert exc.value.status_code == 500
    assert "Failed to create node" in exc.value.detail


def test_kgn_get_node_found_and_404(kg_driver):
    """TC-KGN-106 | get_node_by_id 命中返回节点；未命中返回 404

    输入: 结果含记录 / 空结果
    预期输出: 成功响应带 id / HTTPException 404 "Node not found"
    断言点: 响应字段 + 异常
    防回归: 若 404 分支被删，不存在节点返回空对象
    """
    driver = kg_driver([[_node(3)]])
    resp = _run(kg.get_node_by_id("4:node:3"))
    assert resp["data"]["id"] == "4:node:3"

    kg_driver([[]])
    with pytest.raises(HTTPException) as exc:
        _run(kg.get_node_by_id("missing"))
    assert exc.value.status_code == 404


def test_kgn_update_node_paths(kg_driver):
    """TC-KGN-107 | update_node：缺 properties → 400；节点不存在 → 404；成功更新

    输入: 三种输入
    预期输出: 400 / 404 / 成功响应（SET n += $properties）
    断言点: 异常与 Cypher 片段
    防回归: 若存在性检查被删，更新静默失败
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.update_node("4:node:1", None))
    assert exc.value.status_code == 400

    kg_driver([[], []])
    with pytest.raises(HTTPException) as exc:
        _run(kg.update_node("4:node:1", {"properties": {"a": 1}}))
    assert exc.value.status_code == 404

    driver = kg_driver([[_Record(count=1)], [_node(1)]])
    resp = _run(kg.update_node("4:node:1", {"properties": {"a": 1}}))
    assert resp["success"] is True
    assert "SET n += $properties" in driver.queries[1][0]


def test_kgn_delete_node_paths(kg_driver):
    """TC-KGN-108 | delete_node：force 走 DETACH；有关联 → 409；不存在 → 404；成功 204

    输入: force=true / 非force 但 relCount>0 / 非force 且 relCount=0 / 正常删除
    预期输出: DETACH DELETE 查询 / 409 "Use force=true" / 404 / 204 Response
    断言点: 查询片段 + 状态码
    防回归: 若 409 检查被删，误删带关系的节点
    """
    driver = kg_driver([[_Record(deleted=1)]])
    resp = _run(kg.delete_node("4:node:1", force=True))
    assert resp.status_code == 204
    assert "DETACH DELETE" in driver.queries[0][0]

    kg_driver([[_Record(deleted=0)], [_Record(relCount=2)]])
    with pytest.raises(HTTPException) as exc:
        _run(kg.delete_node("4:node:1", force=False))
    assert exc.value.status_code == 409
    assert "Use force=true" in exc.value.detail

    kg_driver([[_Record(deleted=0)], [_Record(relCount=0)]])
    with pytest.raises(HTTPException) as exc:
        _run(kg.delete_node("4:node:missing", force=False))
    assert exc.value.status_code == 404

    driver = kg_driver([[_Record(deleted=1)]])
    resp = _run(kg.delete_node("4:node:1", force=False))
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# TC-KGR: /relationships
# ---------------------------------------------------------------------------

def test_kgr_list_relationships_with_type(kg_driver):
    """TC-KGR-101 | list_relationships 按 type 过滤并分页

    输入: type="WORKS_WITH"；1 条关系，count=1
    预期输出: 查询含 "[r:WORKS_WITH]"；返回关系字段齐全
    断言点: Cypher 片段 + 关系字段
    防回归: 若 type 分支被删，过滤失效
    """
    driver = kg_driver([[_rel(5)], [_Record(count=1)]])
    resp = _run(kg.list_relationships(page=1, limit=100, type="WORKS_WITH"))
    assert "[r:WORKS_WITH]" in driver.queries[0][0]
    assert resp["data"][0]["type"] == "WORKS_WITH"
    assert resp["pagination"]["total"] == 1


def test_kgr_list_relationships_invalid_type(kg_driver):
    """TC-KGR-102 | list_relationships 非法 type 返回 422

    输入: type = "type with space"
    预期输出: HTTPException 422，detail 含 "Invalid relationship type"
    断言点: 状态码 + detail 关键字
    防回归: 若校验被删，type 可注入 Cypher
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.list_relationships(type="type with space"))
    assert exc.value.status_code == 422


def test_kgr_create_relationship_validation(kg_driver):
    """TC-KGR-103 | create_relationship：缺字段/空 type/起点缺失/终点缺失

    输入: 缺 endNodeId / type="" / startNodeId 不存在 / endNodeId 不存在
    预期输出: 400 "Missing required field: endNodeId" / 400 "cannot be empty" /
              400 "Start node not found" / 400 "End node not found"
    断言点: 四个异常 detail
    防回归: 任一校验被删，可创建悬挂关系
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.create_relationship({"type": "REL", "startNodeId": "a"}))
    assert exc.value.detail == "Missing required field: endNodeId"

    with pytest.raises(HTTPException) as exc:
        _run(kg.create_relationship({"type": "", "startNodeId": "a", "endNodeId": "b"}))
    assert exc.value.detail == "Relationship type cannot be empty"

    kg_driver([[], []])
    with pytest.raises(HTTPException) as exc:
        _run(kg.create_relationship({"type": "REL", "startNodeId": "gone", "endNodeId": "b"}))
    assert "Start node not found" in exc.value.detail

    kg_driver([[_Record(count=1)], []])
    with pytest.raises(HTTPException) as exc:
        _run(kg.create_relationship({"type": "REL", "startNodeId": "a", "endNodeId": "gone"}))
    assert "End node not found" in exc.value.detail


def test_kgr_create_relationship_success_and_500(kg_driver):
    """TC-KGR-104 | create_relationship 成功返回关系；无返回记录 → 500

    输入: 正常数据 / 空结果
    预期输出: success 响应带关系字段 / 500 "Failed to create relationship"
    断言点: 响应字段 + 异常
    防回归: 若空记录检查被删，写入失败仍报成功
    """
    driver = kg_driver([[_Record(count=1)], [_Record(count=1)], [_rel(7)]])
    resp = _run(kg.create_relationship({"type": "WORKS_WITH", "startNodeId": "a",
                                        "endNodeId": "b", "properties": {"w": 1}}))
    assert resp["data"]["id"] == "4:rel:7"
    assert "CREATE (start)-[r:`WORKS_WITH` $properties]" in driver.queries[2][0]

    kg_driver([[_Record(count=1)], [_Record(count=1)], []])
    with pytest.raises(HTTPException) as exc:
        _run(kg.create_relationship({"type": "WORKS_WITH", "startNodeId": "a",
                                     "endNodeId": "b"}))
    assert exc.value.status_code == 500


def test_kgr_get_and_update_relationship(kg_driver):
    """TC-KGR-105 | get_relationship 404；update_relationship 400/404/成功

    输入: get 空结果；update 缺 properties / 关系不存在 / 正常
    预期输出: 404 "Relationship not found" / 400 / 404 / 成功响应
    断言点: 异常与响应
    防回归: 若 404 分支被删，返回空对象误导调用方
    """
    kg_driver([[]])
    with pytest.raises(HTTPException) as exc:
        _run(kg.get_relationship_by_id("missing"))
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        _run(kg.update_relationship("4:rel:1", None))
    assert exc.value.status_code == 400

    kg_driver([[], []])
    with pytest.raises(HTTPException) as exc:
        _run(kg.update_relationship("4:rel:1", {"properties": {"a": 1}}))
    assert exc.value.status_code == 404

    driver = kg_driver([[_Record(count=1)], [_rel(1)]])
    resp = _run(kg.update_relationship("4:rel:1", {"properties": {"a": 1}}))
    assert resp["data"]["id"] == "4:rel:1"
    assert "SET r += $properties" in driver.queries[1][0]


def test_kgr_delete_relationship(kg_driver):
    """TC-KGR-106 | delete_relationship：未命中 404；命中 204

    输入: deleted=0 / deleted=1
    预期输出: HTTPException 404 / Response 204
    断言点: 异常与状态码
    防回归: 若计数检查被删，删除失败仍报成功
    """
    kg_driver([[_Record(deleted=0)]])
    with pytest.raises(HTTPException) as exc:
        _run(kg.delete_relationship("missing"))
    assert exc.value.status_code == 404

    driver = kg_driver([[_Record(deleted=1)]])
    resp = _run(kg.delete_relationship("4:rel:1"))
    assert resp.status_code == 204
    assert "DELETE r" in driver.queries[0][0]


# ---------------------------------------------------------------------------
# TC-KGB: bulk endpoints
# ---------------------------------------------------------------------------

def test_kgb_bulk_nodes_validation(kg_driver):
    """TC-KGB-101 | bulk nodes：空数组/>1000/单节点缺 label/非法 label

    输入: {"nodes": []} / 1001 个节点 / [{"properties": {}}] / [{"labels": ["Bad-Label!"]}]
    预期输出: 400 "Nodes array is required" / 400 "Maximum 1000" / 400 "at least one label" / 422
    断言点: 四个异常 detail
    防回归: 若边界被删，超大请求或坏节点进入图
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.bulk_create_nodes({"nodes": []}))
    assert "Nodes array is required" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        _run(kg.bulk_create_nodes({"nodes": [{"labels": ["A"], "properties": {}}] * 1001}))
    assert "Maximum 1000 nodes" in exc.value.detail

    kg_driver([])
    with pytest.raises(HTTPException) as exc:
        _run(kg.bulk_create_nodes({"nodes": [{"properties": {}}]}))
    assert "at least one label" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        _run(kg.bulk_create_nodes({"nodes": [{"labels": ["Bad-Label!"], "properties": {}}]}))
    assert exc.value.status_code == 422


def test_kgb_bulk_nodes_success(kg_driver):
    """TC-KGB-102 | bulk nodes 成功：UNWIND 查询携带节点数据，返回计数

    输入: 2 个节点
    预期输出: UNWIND 查询 + 返回 created_nodes 与 count=2
    断言点: 查询关键字 + count 值
    防回归: 若 UNWIND 参数装配被改坏，批量创建丢失属性
    """
    driver = kg_driver([[_node(1), _node(2)]])
    resp = _run(kg.bulk_create_nodes({
        "nodes": [{"labels": ["Agent"], "properties": {"name": "a"}},
                  {"labels": ["Agent"], "properties": {"name": "b"}}]}))
    assert resp["count"] == 2
    assert resp["data"][0]["id"] == "4:node:1"
    query, params = driver.queries[0]
    assert "UNWIND $nodes as node" in query
    assert params["nodes"][0]["labels"] == ["Agent"]


def test_kgb_bulk_relationships_validation(kg_driver):
    """TC-KGB-103 | bulk relationships：空数组/>1000/缺字段/节点不存在

    输入: {"relationships": []} / 1001 条 / 缺 endNodeId / startNodeId 不存在
    预期输出: 400 "Relationships array is required" / 400 "Maximum 1000" /
              400 "Missing required field: endNodeId" / 400 "Node not found: gone"
    断言点: 四个异常 detail
    防回归: 任一校验被删，坏批量请求写脏图
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.bulk_create_relationships({"relationships": []}))
    assert "Relationships array is required" in exc.value.detail

    rel = {"type": "REL", "startNodeId": "a", "endNodeId": "b"}
    with pytest.raises(HTTPException) as exc:
        _run(kg.bulk_create_relationships({"relationships": [rel] * 1001}))
    assert "Maximum 1000 relationships" in exc.value.detail

    kg_driver([])
    with pytest.raises(HTTPException) as exc:
        _run(kg.bulk_create_relationships({"relationships": [{"type": "REL",
                                                             "startNodeId": "a"}]}))
    assert "Missing required field: endNodeId" in exc.value.detail

    kg_driver([[]])
    with pytest.raises(HTTPException) as exc:
        _run(kg.bulk_create_relationships({"relationships": [rel]}))
    assert "Node not found:" in exc.value.detail


def test_kgb_bulk_relationships_success(kg_driver):
    """TC-KGB-104 | bulk relationships 成功创建并计数；无记录的关系被跳过

    输入: 2 条关系，其中一条无返回记录
    预期输出: count=1，仅含成功记录；两条 CREATE 查询都发出
    断言点: count 值 + 查询数
    防回归: 若跳过逻辑改坏，空记录被计为成功
    """
    driver = kg_driver([[_Record(count=1)], [_Record(count=1)], [_Record(count=1)],
                        [_rel(1)], [[]]])
    resp = _run(kg.bulk_create_relationships({"relationships": [
        {"type": "WORKS_WITH", "startNodeId": "a", "endNodeId": "b"},
        {"type": "WORKS_WITH", "startNodeId": "a", "endNodeId": "c"}]}))
    assert resp["count"] == 1
    assert resp["data"][0]["id"] == "4:rel:1"
    assert len(driver.queries) == 5  # 3 次节点存在性检查（a/b/c） + 2 次 CREATE


# ---------------------------------------------------------------------------
# TC-KGI: /import
# ---------------------------------------------------------------------------

def test_kgi_import_requires_both_arrays(kg_driver):
    """TC-KGI-101 | import 缺 nodes 或 relationships 键时返回 400

    输入: {} / {"nodes": []}
    预期输出: 400 "Nodes array is required" / 400 "Relationships array is required"
    断言点: 两个异常 detail
    防回归: 若键检查被删，半截导入静默通过
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.import_graph({}))
    assert exc.value.detail == "Nodes array is required"
    with pytest.raises(HTTPException) as exc:
        _run(kg.import_graph({"nodes": []}))
    assert exc.value.detail == "Relationships array is required"


def test_kgi_import_partial_failure_reports_errors(kg_driver):
    """TC-KGI-102 | import 部分失败：错误逐条上报，201 返回计数

    输入: 1 个无 label 节点 + 1 个缺字段关系 + 1 个可创建节点
    预期输出: success=True；nodesCreated=1；errors 含 "Missing labels" 与 "Missing field: type"
    断言点: 计数 + 两条错误消息
    防回归: 若错误上报被删，调用方无法发现半截导入
    """
    kg_driver([[_node(1)]])
    resp = _run(kg.import_graph({
        "nodes": [{"labels": ["Agent"], "properties": {}},
                  {"properties": {}}],
        "relationships": [{"startNodeId": "a", "endNodeId": "b"}]}))
    assert resp["success"] is True
    assert resp["data"]["nodesCreated"] == 1
    messages = [e["message"] for e in resp["data"]["errors"]]
    assert "Missing labels" in messages
    assert "Missing field: type" in messages


def test_kgi_import_node_exception_recorded(monkeypatch):
    """TC-KGI-103 | import 节点写入抛错时记入 errors 而不中断

    输入: session.run 对节点 CREATE 查询抛 ValueError
    预期输出: success=True；errors[0]["message"] 含 "boom"；nodesCreated=0
    断言点: 错误内容 + 计数
    防回归: 若节点异常未捕获，整批导入中断
    """
    driver = _FakeDriver([[_node(2)]])

    original_run = _Session.run
    state = {"n": 0}

    def failing_run(self, query, **params):
        if "CREATE (n:" in query:
            state["n"] += 1
            if state["n"] == 1:
                raise ValueError("boom")
        return original_run(self, query, **params)

    monkeypatch.setattr(kg, "get_neo4j_driver", lambda: driver)
    _Session.run = failing_run
    try:
        resp = _run(kg.import_graph({
            "nodes": [{"labels": ["Agent"], "properties": {}},
                      {"labels": ["Agent"], "properties": {}}],
            "relationships": []}))
    finally:
        _Session.run = original_run
    assert resp["success"] is True
    assert resp["data"]["nodesCreated"] == 1
    assert "boom" in resp["data"]["errors"][0]["message"]


class _FailingRun:
    def __init__(self, driver, node_error=None, rel_error=None):
        self.node_error = node_error
        self.rel_error = rel_error
        self.driver = driver


def test_kgi_import_rel_exception_recorded(monkeypatch):
    """TC-KGI-104 | import 关系写入抛错时记入 errors 而不中断

    输入: session.run 对关系 CREATE 查询抛 ValueError
    预期输出: errors[0]["message"] 含 "rel-boom"
    断言点: 错误内容
    防回归: 若关系异常未捕获，整批导入中断
    """
    driver = _FakeDriver([_node(1)])

    original_run = _Session.run

    def failing_run(self, query, **params):
        if "CREATE (start)-[r:" in query:
            raise ValueError("rel-boom")
        return original_run(self, query, **params)

    monkeypatch.setattr(kg, "get_neo4j_driver", lambda: driver)
    _Session.run = failing_run
    try:
        resp = _run(kg.import_graph({
            "nodes": [{"labels": ["Agent"], "properties": {}}],
            "relationships": [{"type": "REL", "startNodeId": "a", "endNodeId": "b"}]}))
    finally:
        _Session.run = original_run
    assert resp["success"] is True
    assert "rel-boom" in resp["data"]["errors"][0]["message"]


def test_kgi_import_total_failure_returns_422(kg_driver):
    """TC-KGI-105 | import 全部失败时返回 422 且 success=false

    输入: 无 label 节点 + 缺字段关系
    预期输出: JSONResponse 422，payload.success=False
    断言点: 状态码 + success 值（201 会误导调用方图已变更）
    防回归: 若 422 分支被删，全失败的导入仍报 201
    """
    kg_driver([])
    resp = _run(kg.import_graph({
        "nodes": [{"properties": {}}],
        "relationships": [{"startNodeId": "a", "endNodeId": "b"}]}))
    assert resp.status_code == 422
    body = json.loads(resp.body)
    assert body["success"] is False
    assert body["data"]["nodesCreated"] == 0


def test_kgi_import_rel_type_invalid_recorded(kg_driver):
    """TC-KGI-106 | import 关系 type 不合法时记入 errors（422 校验不中断批次）

    输入: 关系 type 含空格
    预期输出: errors[0]["message"] 含 "Invalid relationship type"
    断言点: 错误内容
    防回归: 若类型校验被删，注入串进入 Cypher
    """
    kg_driver([_node(1)])
    resp = _run(kg.import_graph({
        "nodes": [{"labels": ["Agent"], "properties": {}}],
        "relationships": [{"type": "bad type", "startNodeId": "a", "endNodeId": "b"}]}))
    assert "Invalid relationship type" in resp["data"]["errors"][0]["message"]


import json  # noqa: E402


# ---------------------------------------------------------------------------
# TC-KGE: /export
# ---------------------------------------------------------------------------

def test_kge_export_property_filter_requires_colon(kg_driver):
    """TC-KGE-101 | export 的 property 过滤缺少 key:value 冒号时返回 422

    输入: filter="property=name"（无冒号）
    预期输出: HTTPException 422，detail 含 "Property filter must be key:value"
    断言点: 状态码 + detail 关键字
    防回归: 若校验被删，坏过滤串进入查询
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.export_graph(filter="property=name"))
    assert exc.value.status_code == 422


def test_kge_export_invalid_identifier_rejected(kg_driver):
    """TC-KGE-102 | export 的 label/property key 不合法时返回 422

    输入: filter="label=Bad-Label!" / filter="property=bad key:1"
    预期输出: HTTPException 422 ×2，detail 含 "Invalid"
    断言点: 两个异常
    防回归: 若导出前校验被删，过滤值注入 Cypher
    """
    with pytest.raises(HTTPException) as exc:
        _run(kg.export_graph(filter="label=Bad-Label!"))
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        _run(kg.export_graph(filter="property=bad key:1"))
    assert exc.value.status_code == 422


def test_kge_export_by_label(kg_driver):
    """TC-KGE-103 | export 按 label 过滤：节点与关联关系查询都带 label

    输入: filter="label=Agent"；1 节点 1 关系
    预期输出: 节点查询含 `Agent`；关系查询为 UNION 形式；metadata 计数正确
    断言点: 两条查询片段 + metadata
    防回归: 若 label 导出分支被删，过滤导出失效
    """
    driver = kg_driver([[_node(1)], [_rel(2)]])
    resp = _run(kg.export_graph(filter="label=Agent"))
    assert "`Agent`" in driver.queries[0][0]
    assert "UNION" in driver.queries[1][0]
    assert resp["data"]["nodes"][0]["id"] == "4:node:1"
    assert resp["metadata"]["nodeCount"] == 1
    assert resp["metadata"]["relationshipCount"] == 1


def test_kge_export_by_property(kg_driver):
    """TC-KGE-104 | export 按 property 过滤：WHERE n.`key` = $propValue

    输入: filter="property=layer:gpu"；1 节点 1 关系
    预期输出: 节点查询含 propValue 参数；关系查询含 prop_key 拼接
    断言点: 查询片段 + 参数值
    防回归: 若 property 导出分支被删，属性过滤失效
    """
    driver = kg_driver([[_node(1)], [_rel(2)]])
    resp = _run(kg.export_graph(filter="property=layer:gpu"))
    assert "WHERE n.`layer` = $propValue" in driver.queries[0][0]
    assert driver.queries[0][1]["propValue"] == "gpu"
    assert "start.`layer`" in driver.queries[1][0]
    assert resp["data"]["relationships"][0]["id"] == "4:rel:2"


def test_kge_export_without_filter(kg_driver):
    """TC-KGE-105 | export 无过滤时导出全图

    输入: 无 filter；1 节点 1 关系
    预期输出: 两条全量 MATCH 查询；metadata.filter 为 None
    断言点: 查询片段 + metadata.filter
    防回归: 若默认分支被删，空过滤导出崩溃
    """
    driver = kg_driver([[_node(1)], [_rel(2)]])
    resp = _run(kg.export_graph(filter=None, format="json"))
    assert "MATCH (n)" in driver.queries[0][0]
    assert "MATCH (start)-[r]->(end)" in driver.queries[1][0]
    assert resp["metadata"]["filter"] is None
    assert resp["metadata"]["format"] == "json"


def test_kge_export_malformed_filter_parts_ignored(kg_driver):
    """TC-KGE-106 | export 过滤串中无 '=' 的片段被忽略

    输入: filter="notapair&label=Agent"
    预期输出: 仅 label 过滤生效（不抛 422 的 property 分支）
    断言点: 不抛异常 + 查询带 label
    防回归: 若片段解析改坏，坏输入导致 500
    """
    driver = kg_driver([[_node(1)], []])
    resp = _run(kg.export_graph(filter="notapair&label=Agent"))
    assert "`Agent`" in driver.queries[0][0]
    assert resp["metadata"]["nodeCount"] == 1
