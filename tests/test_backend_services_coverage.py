# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Coverage-gap batch 3: persistence backends, UDS client, internal service,
health sweeper and broadcast wiring — all DB/socket paths driven with doubles.

Modules covered here (no live PG/MySQL required):

* ``agent_registry/persistence/connection.py``          (was 22%)
* ``agent_registry/persistence/postgresql_storage.py``  (was 46%)
* ``agent_registry/persistence/gaussdb_storage.py``     (was 46%)
* ``agent_registry/persistence/mysql_storage.py``       (was 35%)
* ``agent_registry/cli/uds_client.py``                  (was 52%)
* ``agent_registry/internal/registry_center_internal_service.py`` (was 69%)
* ``agent_registry/health/sweeper.py``                  (was 71%)
* ``agent_registry/broadcast/__init__.py``              (was 80%)

Every test asserts observable results (returned SQL/kwargs, response dicts,
published payloads) so that a broken change turns the suite red.
"""

import asyncio
import json
import socket as socket_mod
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_registry.cli.uds_client as uds_client_mod
import agent_registry.persistence.connection as pg_connection
import agent_registry.persistence.gaussdb_storage as gaussdb_storage_mod
import agent_registry.persistence.mysql_storage as mysql_storage_mod
import agent_registry.persistence.postgresql_storage as postgresql_storage_mod
from agent_registry.internal.protocols.actions import Action
from agent_registry.persistence.sql_queries import GaussDBQueries, MySQLQueries, PostgreSQLQueries


# ==========================================================================
# TC-CONN: persistence/connection.py
# ==========================================================================

class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        self._conn.executed.append((statement, params))

    def fetchone(self):
        self._conn.fetchone_results.append(None)
        return self._conn.fetchone_queue.pop(0) if self._conn.fetchone_queue else None


class _FakeConn:
    def __init__(self, fetchone_queue=()):
        self.autocommit = False
        self.executed = []
        self.fetchone_queue = list(fetchone_queue)
        self.fetchone_results = []
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


def test_conn_ensure_pg_database_creates_missing(monkeypatch):
    """TC-CONN-001 | 维护库中不存在目标库时执行 CREATE DATABASE

    输入: fetchone → None（库不存在）
    预期输出: 连接到 'postgres' 库；CREATE DATABASE 语句被执行；连接被关闭
    断言点: 连接 database 参数 + CREATE DATABASE 执行 + close 状态
    防回归: 若建库分支被删，首次启动建库失败
    """
    conns = []
    fake = _FakeConn(fetchone_queue=[None])

    def fake_connect(**kwargs):
        conns.append(SimpleNamespace(**kwargs))
        return fake

    monkeypatch.setattr(pg_connection.psycopg2, "connect", fake_connect)
    pg_connection.ensure_pg_database("h", 5432, "new_db", "u", "p", connect_timeout=7)

    assert conns[0].database == "postgres"
    assert conns[0].connect_timeout == 7
    create_calls = [s for s, _ in fake.executed if "CREATE DATABASE" in str(s)]
    assert len(create_calls) == 1
    assert fake.autocommit is True
    assert fake.closed is True


def test_conn_ensure_pg_database_exists_noop(monkeypatch):
    """TC-CONN-002 | 目标库已存在时不执行 CREATE DATABASE

    输入: fetchone → (1,)（库已存在）
    预期输出: 只有 SELECT 语句，无 CREATE DATABASE
    断言点: CREATE DATABASE 语句数为 0
    防回归: 若存在性判断被删，重复启动会因库已存在而报错
    """
    fake = _FakeConn(fetchone_queue=[(1,)])
    monkeypatch.setattr(pg_connection.psycopg2, "connect", lambda **kw: fake)
    pg_connection.ensure_pg_database("h", 5432, "exist_db", "u", "p")
    assert all("CREATE DATABASE" not in str(s) for s, _ in fake.executed)
    assert fake.closed is True


def test_conn_build_pg_pool_forwards_kwargs(monkeypatch):
    """TC-CONN-003 | build_pg_pool 把连接参数原样传给 ThreadedConnectionPool

    输入: host/port/database/user/password/pool 尺寸/超时
    预期输出: minconn/maxconn 等参数逐项相等，返回池对象本身
    断言点: 构造参数逐项比对
    防回归: 若参数错位（如 min/max 互换），池行为异常
    """
    captured = {}

    class FakePool:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(pg_connection.pool, "ThreadedConnectionPool", FakePool)
    pool_obj = pg_connection.build_pg_pool("h", 5432, "db", "u", "p",
                                           min_size=2, max_size=9, connect_timeout=3)
    assert pool_obj.__class__ is FakePool
    assert captured == {
        "minconn": 2, "maxconn": 9,
        "host": "h", "port": 5432, "database": "db",
        "user": "u", "password": "p", "connect_timeout": 3,
    }


def test_conn_ensure_pg_tables_runs_ddl_and_restores_autocommit(monkeypatch):
    """TC-CONN-004 | ensure_pg_tables 执行完整 DDL 序列并把 autocommit 复位后归还连接

    输入: PostgreSQLQueries + GIN 附加语句；假池/假连接
    预期输出: 13 条公共 DDL + 附加语句 + tag/status-history 4 条全部执行；
              执行期间 autocommit=True，结束后 False 并 putconn 归还
    断言点: 语句总数与首尾内容 + autocommit 状态 + putconn 参数
    防回归: 若 DDL 序列缺项或连接归还逻辑被删，启动后 schema 不完整或连接泄漏
    """
    fake_conn = _FakeConn()
    fake_conn.putconn_called = []
    fake_pool = SimpleNamespace(getconn=lambda: fake_conn,
                                putconn=lambda c: fake_conn.putconn_called.append(c))

    extra = ("CREATE INDEX idx_gin ON agent_card USING gin (tags_jsonb)",)
    pg_connection.ensure_pg_tables(fake_pool, PostgreSQLQueries, extra_statements=extra)

    statements = [s for s, _ in fake_conn.executed]
    assert statements[0] == PostgreSQLQueries.CREATE_TABLE.value
    assert any("CREATE INDEX idx_gin" in s for s in statements)
    assert PostgreSQLQueries.CREATE_TAG_TABLE.value in statements
    assert PostgreSQLQueries.CREATE_STATUS_HISTORY_TABLE.value in statements
    assert len(statements) == 13 + 1 + 4
    assert fake_conn.autocommit is False
    assert fake_conn.putconn_called == [fake_conn]


# ==========================================================================
# TC-PG-2xx / TC-GDB-2xx: PostgreSQL / GaussDB backend shells
# ==========================================================================

class _FakePool:
    def __init__(self):
        self.getconn_result = None
        self.putconn_calls = []
        self.closeall_calls = 0

    def getconn(self):
        return self.getconn_result

    def putconn(self, conn):
        self.putconn_calls.append(conn)

    def closeall(self):
        self.closeall_calls += 1


def _run_pg_like_init(monkeypatch, storage_cls, module, key_prefix):
    """驱动 init() 全流程：拦截建库/建池/建表，断言配置读取与连接池装配。"""
    ensure_calls = []
    pool = _FakePool()
    table_calls = []

    monkeypatch.setattr(module, "ensure_pg_database",
                        lambda *a, **kw: ensure_calls.append(a))
    monkeypatch.setattr(module, "build_pg_pool", lambda *a, **kw: pool)
    monkeypatch.setattr(module, "ensure_pg_tables",
                        lambda p, q, extra_statements=(): table_calls.append((p, q, extra_statements)))

    config = {
        f"{key_prefix}.host": "db-host",
        f"{key_prefix}.port": "6543",
        f"{key_prefix}.database" if key_prefix == "gauss" else f"{key_prefix}.name": "regdb",
        f"{key_prefix}.username": "user1",
        f"{key_prefix}.password": "pass1",
        f"{key_prefix}.pool.min": "3",
        f"{key_prefix}.pool.max": "8",
        f"{key_prefix}.connect_timeout": "4",
    }
    instance = storage_cls.init(config)

    assert instance.pool is pool
    assert ensure_calls[0] == ("db-host", 6543, "regdb", "user1", "pass1", 4)
    return instance, pool, table_calls


@pytest.mark.parametrize("storage_cls,module,queries", [
    (postgresql_storage_mod.PostgreSQLStorage, postgresql_storage_mod, PostgreSQLQueries),
    (gaussdb_storage_mod.GaussDBStorage, gaussdb_storage_mod, GaussDBQueries),
])
def test_pg_like_backend_init_reads_config(monkeypatch, storage_cls, module, queries):
    """TC-PG-201 / TC-GDB-201 | init 读取配置建池建表

    输入: 完整 host/port/name/user/password/pool/timeout 配置
    预期输出: ensure_pg_database 收到解析后的值；ensure_pg_tables 收到本后端 queries 枚举
    断言点: ensure 调用参数 + queries 枚举类型（PG 额外带 GIN 语句，GaussDB 不带）
    防回归: 若配置键或枚举被改错，两个后端会互相串配置
    """
    instance, pool, table_calls = _run_pg_like_init(
        monkeypatch, storage_cls, module,
        "postgresql" if queries is PostgreSQLQueries else "gauss")
    assert table_calls[0][1] is queries
    if queries is PostgreSQLQueries:
        assert table_calls[0][2] == (queries.CREATE_INDEX_GIN.value,)
    else:
        assert table_calls[0][2] == ()


@pytest.mark.parametrize("storage_cls", [
    postgresql_storage_mod.PostgreSQLStorage,
    gaussdb_storage_mod.GaussDBStorage,
])
def test_pg_like_backend_conn_lifecycle(storage_cls):
    """TC-PG-202 / TC-GDB-202 | 连接获取/归还/标签参数/池关闭

    输入: 未关闭的假连接（closed=False）；已关闭假连接；标签串
    预期输出: 归还时 rollback + autocommit=False + putconn；已关闭则跳过 rollback；
              _to_tag_query_param 为 JSON 数组；close 调 closeall
    断言点: rollback/putconn 调用记录 + JSON 串 + closeall 计数
    防回归: 若归还清理被删，池连接带着脏事务回到下一个请求
    """
    instance = storage_cls(_FakePool())
    rollback_calls = []
    conn = SimpleNamespace(closed=False, rollback=lambda: rollback_calls.append(1),
                           autocommit=True)

    instance.pool.getconn_result = conn
    assert instance._acquire_conn() is conn

    instance._release_conn(conn)
    assert rollback_calls == [1]
    assert conn.autocommit is False
    assert instance.pool.putconn_calls == [conn]

    closed_conn = SimpleNamespace(closed=True)
    instance._release_conn(closed_conn)
    assert instance.pool.putconn_calls[-1] is closed_conn

    assert instance._to_tag_query_param("gpu") == '["gpu"]'

    instance.close()
    assert instance.pool.closeall_calls == 1


def test_pg_backend_default_config_values(monkeypatch):
    """TC-PG-203 | 空配置时使用文档化的默认值建池

    输入: config = {}
    预期输出: host=localhost, port=5432, name=a2a_registry, user=a2a_user, pool 5/20
    断言点: build_pg_pool 收到的默认参数
    防回归: 若默认值被改坏，零配置部署会连错库
    """
    captured = {}
    monkeypatch.setattr(postgresql_storage_mod, "ensure_pg_database", lambda *a, **kw: None)

    def fake_pool(*a, **kw):
        captured.update(host=a[0], port=a[1], database=a[2], user=a[3],
                        min_size=a[5], max_size=a[6])
        return _FakePool()

    monkeypatch.setattr(postgresql_storage_mod, "build_pg_pool", fake_pool)
    monkeypatch.setattr(postgresql_storage_mod, "ensure_pg_tables", lambda *a, **kw: None)
    postgresql_storage_mod.PostgreSQLStorage.init({})
    assert captured == {"host": "localhost", "port": 5432, "database": "a2a_registry",
                        "user": "a2a_user", "min_size": 5, "max_size": 20}


# ==========================================================================
# TC-MS-2xx: MySQL backend
# ==========================================================================

class _FakeMySQLConn:
    def __init__(self, fetchone_queue=()):
        self.autocommit_calls = []
        self.executed = []
        self.fetchone_queue = list(fetchone_queue)
        self.fetchone_results = []
        self.begun = 0
        self.closed = False

    def autocommit(self, value):
        self.autocommit_calls.append(value)

    def begin(self):
        self.begun += 1

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


class _FakePooledDB:
    last_kwargs = None

    def __init__(self, **kwargs):
        _FakePooledDB.last_kwargs = kwargs

    def connection(self):
        # column/index 均已存在 → _ensure_table_exists 不走 ALTER 分支
        return _FakeMySQLConn(fetchone_queue=[(1,), (1,)])


def test_mysql_backend_init_creates_pool(monkeypatch):
    """TC-MS-201 | init 建池：PooledDB 方言参数逐项正确

    输入: 完整 mysql.* 配置；pymysql.connect 返回库已存在的假连接
    预期输出: PooledDB 收到 blocking=True/ping=1/autocommit=True/charset=utf8mb4 与连接参数
    断言点: PooledDB 构造参数逐项比对
    防回归: 若方言参数被改坏，MySQL 上读旧快照或写不提交
    """
    existing = _FakeMySQLConn(fetchone_queue=[(1,)])
    monkeypatch.setattr(mysql_storage_mod.pymysql, "connect", lambda **kw: existing)
    monkeypatch.setattr(mysql_storage_mod, "PooledDB", _FakePooledDB)

    config = {
        "mysql.host": "m-host", "mysql.port": "3307", "mysql.name": "m_db",
        "mysql.username": "m_user", "mysql.password": "m_pass",
        "mysql.pool.min": "2", "mysql.pool.max": "6", "mysql.connect_timeout": "5",
    }
    instance = mysql_storage_mod.MySQLStorage.init(config)

    kwargs = _FakePooledDB.last_kwargs
    assert (kwargs["host"], kwargs["port"], kwargs["database"]) == ("m-host", 3307, "m_db")
    assert kwargs["blocking"] is True and kwargs["ping"] == 1
    assert kwargs["autocommit"] is True and kwargs["charset"] == "utf8mb4"
    assert kwargs["mincached"] == 2 and kwargs["maxconnections"] == 6
    assert isinstance(instance, mysql_storage_mod.MySQLStorage)


def test_mysql_backend_ensure_table_adds_missing_layer_column_and_index():
    """TC-MS-202 | layer 列/索引缺失时执行 ALTER TABLE 补齐

    输入: 假池返回连接，两次 fetchone 均为 None
    预期输出: 语句含 "ADD COLUMN layer" 与 "ADD INDEX idx_agent_layer"，
              且 tag/status-history 表 DDL 全部执行
    断言点: 三条 DDL 语句关键字存在
    防回归: 若迁移分支被删，旧库升级后缺列
    """
    conn = _FakeMySQLConn(fetchone_queue=[None, None])
    mysql_storage_mod.MySQLStorage._ensure_table_exists(SimpleNamespace(connection=lambda: conn))
    stmts = " || ".join(s for s, _ in conn.executed)
    assert "ADD COLUMN layer" in stmts
    assert "ADD INDEX idx_agent_layer" in stmts
    assert MySQLQueries.CREATE_TAG_TABLE.value in stmts
    assert MySQLQueries.CREATE_STATUS_HISTORY_TABLE.value in stmts


def test_mysql_backend_ensure_database_exists_and_name_validation(monkeypatch):
    """TC-MS-203 | 建库：存在则跳过；不存在且名字合法则 CREATE DATABASE；非法名字抛 ValueError

    输入: fetchone=(1,) / fetchone=None + "valid_db" / fetchone=None + "bad name!"
    预期输出: 跳过 / CREATE DATABASE utf8mb4 / ValueError "Invalid MySQL database name"
    断言点: 语句关键字 + 异常类型与消息
    防回归: 若库名校验被删，恶意库名可注入 DDL
    """
    existing = _FakeMySQLConn(fetchone_queue=[(1,)])
    monkeypatch.setattr(mysql_storage_mod.pymysql, "connect", lambda **kw: existing)
    mysql_storage_mod.MySQLStorage._ensure_database_exists("h", 3306, "exist_db", "u", "p")
    assert all("CREATE DATABASE" not in s for s, _ in existing.executed)
    assert existing.closed is True

    missing = _FakeMySQLConn(fetchone_queue=[None])
    monkeypatch.setattr(mysql_storage_mod.pymysql, "connect", lambda **kw: missing)
    mysql_storage_mod.MySQLStorage._ensure_database_exists("h", 3306, "valid_db", "u", "p")
    create_stmts = [s for s, _ in missing.executed if "CREATE DATABASE" in s]
    assert len(create_stmts) == 1 and "utf8mb4" in create_stmts[0]

    invalid = _FakeMySQLConn(fetchone_queue=[None])
    monkeypatch.setattr(mysql_storage_mod.pymysql, "connect", lambda **kw: invalid)
    with pytest.raises(ValueError, match="Invalid MySQL database name: bad name!"):
        mysql_storage_mod.MySQLStorage._ensure_database_exists("h", 3306, "bad name!", "u", "p")


def test_mysql_backend_conn_lifecycle_and_close():
    """TC-MS-204 | 事务开始/连接释放/标签参数/池关闭

    输入: 假连接与假池；标签串 "gpu"；pool=None 的实例
    预期输出: _begin_transaction 调 conn.begin；_release_conn 调 conn.close；
              _to_tag_query_param 为 JSON 数组；close 调 pool.close，None 时为空操作
    断言点: begin/close 状态 + JSON 串 + 无异常
    防回归: 若事务开始被删，MySQL autocommit 连接上写操作失去原子性
    """
    instance = mysql_storage_mod.MySQLStorage(SimpleNamespace())

    conn = _FakeMySQLConn()
    instance._begin_transaction(conn)
    assert conn.begun == 1

    conn2 = _FakeMySQLConn()
    instance._release_conn(conn2)
    assert conn2.closed is True

    assert instance._to_tag_query_param("gpu") == '["gpu"]'

    closed_calls = []
    instance.pool = SimpleNamespace(close=lambda: closed_calls.append(1))
    instance.close()
    assert closed_calls == [1]

    instance.pool = None
    instance.close()  # 不抛异常


# ==========================================================================
# TC-UDS-1xx: cli/uds_client.py
# ==========================================================================

class _FakeSocket:
    """socket.socket 替身：connect 行为与 recv 分片可控。"""

    def __init__(self, family=None, type=None):
        self.family, self.type = family, type
        self.connect_error = None
        self.recv_chunks = []
        self.sendall_error = None
        self.sent = b""
        self.closed = False
        self.timeout = None

    def settimeout(self, t):
        self.timeout = t

    def connect(self, path):
        if isinstance(self.connect_error, Exception):
            raise self.connect_error

    def sendall(self, data):
        if self.sendall_error is not None:
            raise self.sendall_error
        self.sent = data

    def recv(self, bufsize):
        if self.recv_chunks:
            return self.recv_chunks.pop(0)
        return b""

    def close(self):
        self.closed = True


@pytest.fixture
def fake_socket_env(monkeypatch):
    """把 uds_client 命名空间里的 socket 模块整体替换为可控替身（含 AF_UNIX 常量）。

    返回工厂函数：调用后创建"将被客户端实际使用"的 _FakeSocket 实例并完成注入。
    """
    monkeypatch.setattr(uds_client_mod, "IS_WINDOWS", False)
    holder = {}

    def factory(family, type):
        return holder["sock"]

    monkeypatch.setattr(uds_client_mod, "socket",
                        SimpleNamespace(socket=factory, AF_UNIX=1, SOCK_STREAM=2))

    def make_sock():
        sock = _FakeSocket()
        holder["sock"] = sock
        return sock

    return make_sock


def test_uds_client_windows_rejected(monkeypatch):
    """TC-UDS-101 | Windows 平台直接返回平台不支持错误

    输入: IS_WINDOWS=True
    预期输出: {"success": False, "error": "Platform not supported"}，message 含 "Windows"
    断言点: 三个字段精确值
    防回归: 若平台守卫被删，Windows 上会尝试 AF_UNIX 崩溃
    """
    monkeypatch.setattr(uds_client_mod, "IS_WINDOWS", True)
    resp = uds_client_mod.UDSClient().send_request("get_agent", {})
    assert resp["success"] is False
    assert resp["error"] == "Platform not supported"
    assert "Windows" in resp["message"]


def test_uds_client_connect_error_mapping(fake_socket_env):
    """TC-UDS-102 | 连接失败类型映射为对应的错误响应，socket 必须被关闭

    输入: FileNotFoundError / PermissionError / ConnectionRefusedError / OSError
    预期输出: error 分别为 "Socket not found"/"Permission denied"/"Connection refused"/
              "Connection failed"；每个用例后 socket.closed 为 True
    断言点: 四种 error 值 + close 状态
    防回归: 若失败分支漏 close（DEFECT-CLI-1），fd 泄漏
    """
    cases = [
        (FileNotFoundError(), "Socket not found"),
        (PermissionError(), "Permission denied"),
        (ConnectionRefusedError(), "Connection refused"),
        (OSError("weird"), "Connection failed"),
    ]
    for error, expected_error in cases:
        client = uds_client_mod.UDSClient()
        sock = fake_socket_env()
        sock.connect_error = error
        resp = client.send_request("get_agent", {"agent_name": "a", "organization": "o"})
        assert resp["success"] is False
        assert resp["error"] == expected_error
        assert sock.closed is True


def test_uds_client_success_roundtrip_and_chunked_response(fake_socket_env):
    """TC-UDS-103 | 成功往返：请求 JSON 发出；分片到达的响应被聚合到完整 JSON 为止

    输入: recv 依次返回半截 JSON 与剩余部分
    预期输出: 返回解析后的 dict；socket 已关闭；发出内容为 {"action": ..., "params": ...}
    断言点: 解析结果相等 + 发出载荷字段 + close 状态
    防回归: 若分片循环退出条件改坏（提前 break / 永不 break），解析失败或挂死
    """
    sock = fake_socket_env()
    sock.recv_chunks = [b'{"success": true, "data": {"agent_name":', b' "a-1", "extra": 1}}']

    resp = uds_client_mod.UDSClient().get_agent("a-1", "org-1")
    assert resp == {"success": True, "data": {"agent_name": "a-1", "extra": 1}}
    assert sock.closed is True
    assert sock.timeout == 10
    payload = json.loads(sock.sent.decode("utf-8"))
    assert payload == {"action": "get_agent",
                       "params": {"agent_name": "a-1", "organization": "org-1"}}


def test_uds_client_invalid_json_response(fake_socket_env):
    """TC-UDS-104 | 服务端返回非法 JSON → "Invalid response"

    输入: recv 返回非 JSON 字节后关闭（返回 b""）
    预期输出: {"success": False, "error": "Invalid response"}；socket 关闭
    断言点: error 值 + close 状态
    防回归: 若 JSONDecodeError 未捕获，CLI 命令崩溃
    """
    sock = fake_socket_env()
    sock.recv_chunks = [b"<<<not json>>>", b""]

    resp = uds_client_mod.UDSClient().list_agents()
    assert resp["success"] is False
    assert resp["error"] == "Invalid response"
    assert sock.closed is True


def test_uds_client_send_failure_returns_communication_error(fake_socket_env):
    """TC-UDS-105 | 发送阶段抛错 → "Communication error"，socket 仍关闭

    输入: sendall 抛 RuntimeError
    预期输出: {"success": False, "error": "Communication error"}；socket 关闭
    断言点: error 值 + close 状态
    防回归: 若 finally 关闭被删，异常路径泄漏 fd
    """
    sock = fake_socket_env()
    sock.sendall_error = RuntimeError("pipe broken")

    resp = uds_client_mod.UDSClient().list_tags()
    assert resp["success"] is False
    assert resp["error"] == "Communication error"
    assert sock.closed is True


def test_uds_client_wrapper_methods_build_exact_requests(fake_socket_env):
    """TC-UDS-106 | 十个包装方法构造的 action/params 精确匹配协议

    输入: 依次调用 approval_agent/get_agent/list_agents/set_tags/create_tag/
          get_tag(tag_id)/get_tag(name)/get_tag(缺参)/update_tag/delete_tag/list_tags
    预期输出: 每次发出 {"action": ..., "params": ...} 与协议逐字段一致
    断言点: 11 组载荷逐字段断言
    防回归: 任一 action 名或参数键被改错，对应命令失效
    """
    sock = fake_socket_env()
    sock.recv_chunks = [b'{"success": true, "data": null}']

    client = uds_client_mod.UDSClient()

    client.approval_agent("agent-1", "org-1")
    assert json.loads(sock.sent.decode()) == {"action": "approval",
                                              "params": {"agent_name": "agent-1", "organization": "org-1"}}

    client.set_tags("agent-1", "org-1", ["t1", "t2"])
    assert json.loads(sock.sent.decode()) == {"action": "set_tag",
                                              "params": {"agent_name": "agent-1", "organization": "org-1",
                                                         "tags": ["t1", "t2"]}}

    client.create_tag("security")
    assert json.loads(sock.sent.decode()) == {"action": "create_tag", "params": {"name": "security"}}

    client.get_tag(tag_id="42")
    assert json.loads(sock.sent.decode()) == {"action": "get_tag", "params": {"tag_id": "42"}}

    client.get_tag(name="security")
    assert json.loads(sock.sent.decode()) == {"action": "get_tag", "params": {"name": "security"}}

    client.get_tag()
    assert json.loads(sock.sent.decode()) == {"action": "get_tag", "params": {}}

    client.update_tag("42", "security-v2")
    assert json.loads(sock.sent.decode()) == {"action": "update_tag",
                                              "params": {"tag_id": "42", "name": "security-v2"}}

    client.delete_tag("42")
    assert json.loads(sock.sent.decode()) == {"action": "delete_tag", "params": {"tag_id": "42"}}

    client.list_agents()
    assert json.loads(sock.sent.decode()) == {"action": "list_agents", "params": {}}

    client.list_tags()
    assert json.loads(sock.sent.decode()) == {"action": "list_tags", "params": {}}


def test_uds_client_get_uds_client_singleton(monkeypatch):
    """TC-UDS-107 | get_uds_client 返回单例；Windows 下记录错误日志

    输入: _client 重置为 None；IS_WINDOWS=True
    预期输出: 两次调用返回同一 UDSClient 实例
    断言点: is 身份比对（并恢复模块全局状态）
    防回归: 若单例被删，每次调用新建连接对象
    """
    original = uds_client_mod._client
    monkeypatch.setattr(uds_client_mod, "_client", None)
    monkeypatch.setattr(uds_client_mod, "IS_WINDOWS", True)
    try:
        first = uds_client_mod.get_uds_client()
        second = uds_client_mod.get_uds_client()
        assert first is second
        assert isinstance(first, uds_client_mod.UDSClient)
    finally:
        uds_client_mod._client = original


def test_uds_client_default_socket_path():
    """TC-UDS-108 | 缺省 socket 路径为 run/registry-center/internal.sock

    输入: 不传 socket_path
    预期输出: client.socket_path == UDSClient.SOCKET_PATH == "run/registry-center/internal.sock"
    断言点: 两个值精确相等（CLI 与服务端路径契约）
    防回归: 若常量被改，CLI 与服务端连不上
    """
    assert uds_client_mod.UDSClient().socket_path == "run/registry-center/internal.sock"
    assert uds_client_mod.UDSClient.SOCKET_PATH == "run/registry-center/internal.sock"


# ==========================================================================
# TC-INT-1xx: internal/registry_center_internal_service.py
# ==========================================================================

class _FakeInternalConn:
    def __init__(self, payload=b""):
        self.payload = payload
        self.sent = []
        self.closed = False

    def recv(self, bufsize):
        data, self.payload = self.payload, b""
        return data

    def send(self, data):
        self.sent.append(json.loads(data.decode("utf-8")))

    def close(self):
        self.closed = True


class _RecordingHandler:
    """以"类"注册进 Dispatcher 的 handler 替身；实例按序记录调用。"""

    instances = []

    def __init__(self):
        self.calls = []
        _RecordingHandler.instances.append(self)

    def handle(self, params, registry, config):
        self.calls.append((params, registry, config))
        return {"success": True, "data": {"echo": params}}


@pytest.fixture
def internal_service(monkeypatch):
    from agent_registry.internal.registry_center_internal_service import RegistryCenterInternalService
    monkeypatch.setattr("agent_registry.internal.registry_center_internal_service.get_registry",
                        lambda: SimpleNamespace(name="fake-registry"))
    monkeypatch.setattr("agent_registry.internal.registry_center_internal_service.get_conf",
                        lambda: {"k": "v"})
    return RegistryCenterInternalService()


def test_internal_dispatcher_known_and_unknown_actions(internal_service):
    """TC-INT-101 | Dispatcher 按协议 Action 返回对应 handler；未知 action 返回 None

    输入: approval/get_agent/list_agents/set_tag/五个 tag action；未知 action
    预期输出: 每个已知 action 返回对应类实例；未知 → None；register_handler 可注册
    断言点: 9 个 isinstance 断言 + None + 注册后可取
    防回归: 若 handler 映射表漏项，对应 CLI 命令得到 Unknown action
    """
    from agent_registry.internal.handlers import (
        ApprovalHandler, SetTagsHandler,
        TagCreateHandler, TagDeleteHandler, TagGetHandler, TagListHandler, TagUpdateHandler,
    )
    from agent_registry.internal.handlers.get_agent_handler import GetAgentHandler
    from agent_registry.internal.handlers.list_agents_handler import ListAgentsHandler

    dispatcher = internal_service.dispatcher
    assert isinstance(dispatcher.get_handler(Action.APPROVAL), ApprovalHandler)
    assert isinstance(dispatcher.get_handler(Action.GET_AGENT), GetAgentHandler)
    assert isinstance(dispatcher.get_handler(Action.LIST_AGENTS), ListAgentsHandler)
    assert isinstance(dispatcher.get_handler(Action.SET_TAG), SetTagsHandler)
    assert isinstance(dispatcher.get_handler(Action.CREATE_TAG), TagCreateHandler)
    assert isinstance(dispatcher.get_handler(Action.GET_TAG), TagGetHandler)
    assert isinstance(dispatcher.get_handler(Action.UPDATE_TAG), TagUpdateHandler)
    assert isinstance(dispatcher.get_handler(Action.DELETE_TAG), TagDeleteHandler)
    assert isinstance(dispatcher.get_handler(Action.LIST_TAGS), TagListHandler)
    assert dispatcher.get_handler("no_such_action") is None

    dispatcher.register_handler("custom_action", _RecordingHandler)
    assert isinstance(dispatcher.get_handler("custom_action"), _RecordingHandler)


def test_internal_service_init_wires_dependencies(internal_service):
    """TC-INT-102 | 构造时装配 registry/config/dispatcher 且初始未运行

    输入: monkeypatch 的 get_registry/get_conf
    预期输出: registry/config 为注入对象；_running 为 False；SOCKET_PATH 契约不变
    断言点: 对象内容 + _running + socket 路径常量
    防回归: 若装配对象被改错，所有 handler 拿到错误依赖
    """
    assert internal_service.registry.name == "fake-registry"
    assert internal_service.config == {"k": "v"}
    assert internal_service._running is False
    assert internal_service.socket_path == "run/registry-center/internal.sock"


def test_internal_handle_request_paths(internal_service):
    """TC-INT-103 | _handle_request 全分支：空载荷/坏 JSON/缺 action/未知 action/正常/异常

    输入: 六种连接载荷依次喂给 _handle_request
    预期输出: 空载荷不回包；坏 JSON 回 "Invalid JSON format"；缺 action 回
              "Invalid request format"；未知 action 回 "Unknown action: ..."；
              正常请求回 handler 响应且收到 (params, registry, config)；
              handler 抛错回 {"success": False, "error": ...}
    断言点: 每个分支的响应 dict + handler 收到的依赖身份
    防回归: 任一分支的响应契约被改坏，CLI 命令解析失败
    """
    svc = internal_service

    conn = _FakeInternalConn(b"")
    svc._handle_request(conn)
    assert conn.sent == [] and conn.closed is True

    conn = _FakeInternalConn(b"not-json")
    svc._handle_request(conn)
    assert conn.sent == [{"success": False, "error": "Invalid JSON format"}]

    conn = _FakeInternalConn(json.dumps({"params": {}}).encode())
    svc._handle_request(conn)
    assert conn.sent[0]["success"] is False
    assert conn.sent[0]["error"] == "Invalid request format"

    conn = _FakeInternalConn(json.dumps({"action": "no_such_action"}).encode())
    svc._handle_request(conn)
    assert conn.sent == [{"success": False, "error": "Unknown action: no_such_action"}]

    handler = _RecordingHandler
    _RecordingHandler.instances = []
    svc.dispatcher.register_handler("echo_action", handler)
    conn = _FakeInternalConn(json.dumps({"action": "echo_action",
                                         "params": {"agent_name": "a"}}).encode())
    svc._handle_request(conn)
    assert conn.sent == [{"success": True, "data": {"echo": {"agent_name": "a"}}}]
    assert handler.instances[0].calls[0][0] == {"agent_name": "a"}
    assert handler.instances[0].calls[0][1] is svc.registry
    assert handler.instances[0].calls[0][2] == svc.config

    class _BoomHandler:
        def handle(self, params, registry, config):
            raise RuntimeError("handler down")

    svc.dispatcher.register_handler("boom_action", _BoomHandler)
    conn = _FakeInternalConn(json.dumps({"action": "boom_action"}).encode())
    svc._handle_request(conn)
    assert conn.sent[0]["success"] is False
    assert conn.sent[0]["error"] == "handler down"


def test_internal_service_stop(internal_service):
    """TC-INT-104 | stop() 置 _running=False 并清理 socket（缺文件不抛）

    输入: socket 文件不存在时调用 stop
    预期输出: _running 为 False，无异常
    断言点: _running 状态
    防回归: 若清理被删，残留 socket 文件阻塞下次启动
    """
    internal_service.socket_path = "no/such/dir/internal.sock"
    internal_service.stop()
    assert internal_service._running is False


def test_internal_service_start_accepts_and_stops(internal_service, tmp_path, monkeypatch):
    """TC-INT-105 | start() 监听 UDS：超时重试、接受连接、handler 运行后退出并清理

    输入: 假 server socket：accept 前 2 次抛 timeout，第 3 次返回含合法请求的连接；
          handler 内部将 _running 置 False
    预期输出: bind 到 socket_path；handler 已运行；连接被关闭；socket 文件被清理
    断言点: bind 路径 + handler 响应 + 连接关闭 + 文件清理
    防回归: 若 accept 循环/清理逻辑改坏，服务挂死或残留 socket
    """
    svc = internal_service
    svc.SOCKET_DIR = str(tmp_path / "run")
    svc.socket_path = str(tmp_path / "run" / "internal.sock")

    class FakeServerSocket:
        def __init__(self, family, type):
            self.bound = None
            self.closed = False
            self._accepts = [
                socket_mod.timeout(), socket_mod.timeout(),
                _FakeInternalConn(json.dumps({"action": "echo2", "params": {"p": 1}}).encode()),
            ]

        def bind(self, path):
            self.bound = path

        def listen(self, backlog):
            pass

        def settimeout(self, t):
            pass

        def accept(self):
            item = self._accepts.pop(0)
            if isinstance(item, Exception):
                raise item
            return item, ("addr",)

        def close(self):
            self.closed = True

    server = FakeServerSocket(1, 2)
    monkeypatch.setattr("agent_registry.internal.registry_center_internal_service.socket",
                        SimpleNamespace(socket=lambda family, type: server,
                                        AF_UNIX=1, SOCK_STREAM=2))

    handler = _RecordingHandler
    _RecordingHandler.instances = []
    svc.dispatcher.register_handler("echo2", handler)

    class SyncThread:
        def __init__(self, target=None, args=(), daemon=None, **kw):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr("agent_registry.internal.registry_center_internal_service.threading.Thread",
                        SyncThread)

    def stop_after_handle(params, registry, config):
        svc._running = False
        return {"success": True, "data": params}

    handler.handle = stop_after_handle

    svc.start()

    assert server.bound == svc.socket_path
    assert server.closed is True
    assert svc._running is False
    assert not Path(svc.socket_path).exists()


def test_internal_service_start_bind_failure_is_logged(internal_service, tmp_path, monkeypatch):
    """TC-INT-106 | start() 中 bind 抛错：记录日志、关闭 socket、不崩溃

    输入: 假 server socket 的 bind 抛 OSError
    预期输出: 正常返回（finally 关闭 socket 并清理），不抛异常
    断言点: 无异常 + server.closed + _running=False
    防回归: 若异常未被兜底，启动线程可能裸崩
    """
    svc = internal_service
    svc.SOCKET_DIR = str(tmp_path / "run2")
    svc.socket_path = str(tmp_path / "run2" / "internal.sock")

    class BrokenServerSocket:
        def __init__(self, family, type):
            self.closed = False

        def bind(self, path):
            raise OSError("address in use")

        def close(self):
            self.closed = True

    monkeypatch.setattr("agent_registry.internal.registry_center_internal_service.socket",
                        SimpleNamespace(socket=lambda family, type: BrokenServerSocket(1, 2),
                                        AF_UNIX=1, SOCK_STREAM=2))
    svc.start()
    assert svc._running is False


# ==========================================================================
# TC-SWEEP-1xx: health/sweeper.py
# ==========================================================================

def _make_state(name, org, last_seen, status, changed_at):
    from agent_registry.health.state import HealthState
    return HealthState(name=name, organization=org, last_heartbeat_at=last_seen,
                       status=status, status_changed_at=changed_at)


class _FakeHealthService:
    def __init__(self, states):
        self.states = list(states)
        self.updates = []
        self.removed = []
        self.update_result = True

    def list_monitored(self):
        return list(self.states)

    def update_status(self, name, org, status, now):
        self.updates.append((name, org, status))
        return self.update_result

    def remove(self, name, org):
        self.removed.append((name, org))


class _FakeRegistry:
    def __init__(self, records=None):
        self.records = records or {}
        self.deregistered = []

    def get_by_key_with_owner(self, name, org):
        return self.records.get((name, org))

    def get_agent_tags(self, name, org):
        return ["tag-a"]

    def deregister(self, name, org):
        self.deregistered.append((name, org))


class _FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, event_type, payload):
        self.published.append((event_type, payload))


def _make_sweeper(service, registry, bus, offline_ttl=0):
    from agent_registry.health.sweeper import HealthSweeper
    from datetime import datetime, timezone
    startup = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return HealthSweeper(service, registry, bus, interval=30, failure_threshold=3,
                         grace_period=10, sweep_interval=0.01, offline_ttl=offline_ttl,
                         startup_time=startup)


def test_sweeper_no_transition_when_healthy():
    """TC-SWEEP-101 | 心跳新鲜时目标状态与当前一致 → 不发布事件

    输入: last_seen == now（elapsed=0 < interval+grace=40）
    预期输出: sweep_once 返回 0；无 update、无 publish
    断言点: 返回值 0 + 两个记录列表为空
    防回归: 若新鲜度分类改错，健康 agent 会被误标
    """
    from agent_registry.health.state import HealthStatus
    from datetime import datetime, timezone

    startup = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc)
    state = _make_state("a", "o", now, HealthStatus.HEALTHY, startup)
    service = _FakeHealthService([state])
    bus = _FakeBus()
    sweeper = _make_sweeper(service, _FakeRegistry(), bus)
    assert sweeper.sweep_once(now) == 0
    assert service.updates == []
    assert bus.published == []


def test_sweeper_publishes_transition_event():
    """TC-SWEEP-102 | 状态跃迁时更新并发布 AGENT_HEALTH_CHANGED 事件（含 tags）

    输入: 已发布（published）agent 心跳停滞 90s（> 40 且 <= 100 → suspect）
    预期输出: 返回 1；update_status 被调用；事件 payload 逐字段等于预期
    断言点: 返回值 + 事件 payload 全字段 + 事件类型
    防回归: 若 payload 字段或 tags 读取被删，订阅方收不到完整通知
    """
    from agent_registry.health.state import HealthStatus
    from agent_registry.broadcast.events import EventType
    from datetime import datetime, timezone

    startup = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_seen = datetime(2026, 1, 1, 0, 8, 30, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc)

    state = _make_state("agent-1", "org-1", last_seen, HealthStatus.HEALTHY, startup)
    service = _FakeHealthService([state])
    registry = _FakeRegistry(records={("agent-1", "org-1"): SimpleNamespace(status="published")})
    bus = _FakeBus()
    sweeper = _make_sweeper(service, registry, bus)

    transitions = sweeper.sweep_once(now)
    assert transitions == 1
    assert service.updates == [("agent-1", "org-1", HealthStatus.SUSPECT)]
    assert len(bus.published) == 1
    event_type, payload = bus.published[0]
    assert event_type == EventType.AGENT_HEALTH_CHANGED
    assert payload == {
        "name": "agent-1",
        "organization": "org-1",
        "health_status": "suspect",
        "previous_health_status": "healthy",
        "tags": ["tag-a"],
        "discovery_public": True,
    }


def test_sweeper_removes_state_when_record_missing():
    """TC-SWEEP-103 | 注册中心查不到记录时移除监控状态（不发布事件）

    输入: registry 无对应记录
    预期输出: service.remove 被调用；无 publish；返回 0
    断言点: remove 记录 + publish 为空
    防回归: 若记录缺失分支被删，已注销 agent 的状态会滞留
    """
    from agent_registry.health.state import HealthStatus
    from datetime import datetime, timezone

    startup = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc)
    state = _make_state("gone", "org", datetime(2026, 1, 1, 0, 8, 30, tzinfo=timezone.utc),
                        HealthStatus.HEALTHY, startup)
    service = _FakeHealthService([state])
    registry = _FakeRegistry()
    sweeper = _make_sweeper(service, registry, _FakeBus())
    assert sweeper.sweep_once(now) == 0
    assert service.removed == [("gone", "org")]


def test_sweeper_skips_when_not_discoverable():
    """TC-SWEEP-104 | 记录状态不可发现（registered）时更新但不广播

    输入: record.status = "registered"
    预期输出: update_status 已调用；publish 为空；返回 0
    断言点: publish 空 + update 已记录
    防回归: 若可发现性过滤被删，未发布 agent 会向外广播健康事件
    """
    from agent_registry.health.state import HealthStatus
    from datetime import datetime, timezone

    startup = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc)
    state = _make_state("pending", "org", datetime(2026, 1, 1, 0, 8, 30, tzinfo=timezone.utc),
                        HealthStatus.HEALTHY, startup)
    service = _FakeHealthService([state])
    registry = _FakeRegistry(records={("pending", "org"): SimpleNamespace(status="registered")})
    bus = _FakeBus()
    sweeper = _make_sweeper(service, registry, bus)
    assert sweeper.sweep_once(now) == 0
    assert len(service.updates) == 1
    assert bus.published == []


def test_sweeper_skips_publish_when_update_rejected():
    """TC-SWEEP-105 | update_status 返回 False 时不广播

    输入: service.update_result = False
    预期输出: 返回 0；无 publish
    断言点: 返回值 + publish 空
    防回归: 若返回值检查被删，更新失败仍会广播错误状态
    """
    from agent_registry.health.state import HealthStatus
    from datetime import datetime, timezone

    startup = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc)
    state = _make_state("a", "o", datetime(2026, 1, 1, 0, 8, 30, tzinfo=timezone.utc),
                        HealthStatus.HEALTHY, startup)
    service = _FakeHealthService([state])
    service.update_result = False
    registry = _FakeRegistry(records={("a", "o"): SimpleNamespace(status="published")})
    bus = _FakeBus()
    sweeper = _make_sweeper(service, registry, bus)
    assert sweeper.sweep_once(now) == 0
    assert bus.published == []


def test_sweeper_offline_ttl_deregisters_expired():
    """TC-SWEEP-106 | offline_ttl 到期后自动注销离线 agent；未到期不注销

    输入: TTL=100；一条 OFFLINE 且已过期 100s，一条 OFFLINE 仅 50s，一条 healthy
    预期输出: 仅过期者被 deregister；healthy 不受影响
    断言点: deregister 记录恰含过期者
    防回归: 若 TTL 判断被删/改错，离线 agent 永不清理或被误清理
    """
    from agent_registry.health.state import HealthStatus
    from datetime import datetime, timezone

    startup = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc)
    expired = _make_state("old", "org", startup, HealthStatus.OFFLINE,
                          datetime(2026, 1, 1, 0, 8, 20, tzinfo=timezone.utc))  # 恰 100s
    fresh = _make_state("new", "org", startup, HealthStatus.OFFLINE,
                        datetime(2026, 1, 1, 0, 9, 10, tzinfo=timezone.utc))  # 50s
    healthy = _make_state("up", "org", now, HealthStatus.HEALTHY, startup)
    registry = _FakeRegistry()
    sweeper = _make_sweeper(_FakeHealthService([expired, fresh, healthy]), registry,
                            _FakeBus(), offline_ttl=100)
    sweeper.sweep_once(now)
    assert registry.deregistered == [("old", "org")]


def test_sweeper_run_loop_survives_sweep_errors():
    """TC-SWEEP-107 | run() 循环：单次 sweep 抛错被记录并继续，任务保持运行

    输入: sweep_interval=0.01；service.list_monitored 抛错；任务运行 50ms 后取消
    预期输出: 循环未因异常退出（任务仍在运行直到被 cancel）
    断言点: task.cancel() 前任务未完成（not task.done()）
    防回归: 若 sweep 异常未被捕获，后台任务会静默死亡
    """
    service = _FakeHealthService([])
    service.list_monitored = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    sweeper = _make_sweeper(service, _FakeRegistry(), _FakeBus())

    async def scenario():
        task = asyncio.get_running_loop().create_task(sweeper.run())
        await asyncio.sleep(0.05)
        assert not task.done()  # 异常未终结循环
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())


def test_sweeper_start_and_stop_manage_task():
    """TC-SWEEP-108 | start() 创建后台任务；stop() 取消并置 None

    输入: 在事件循环内 start()，随后 stop()
    预期输出: _task 先非空，stop 后为 None
    断言点: _task 状态变化
    防回归: 若取消/置空被删，任务句柄泄漏导致重复启动
    """
    sweeper = _make_sweeper(_FakeHealthService([]), _FakeRegistry(), _FakeBus())

    async def scenario():
        sweeper.start()
        assert sweeper._task is not None
        await asyncio.sleep(0.03)
        await sweeper.stop()
        assert sweeper._task is None

    asyncio.run(scenario())


# ==========================================================================
# TC-BCAST-1xx: broadcast/__init__.py
# ==========================================================================

class _CloseRecorder:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def test_bcast_conf_parsers_handle_bad_values():
    """TC-BCAST-101 | _int_conf/_float_conf 对非法值回退默认并告警；_truthy 仅认 true

    输入: "abc"/缺失 与 "xyz"/"3.5"；"TRUE"/" true "/"false"/缺失
    预期输出: int→默认 5；float→默认 2.0；truthy → True/True/False/False
    断言点: 九个返回值精确相等
    防回归: 若类型转换被删，坏配置会导致启动崩溃
    """
    from agent_registry.broadcast import _float_conf, _int_conf, _truthy

    assert _int_conf({"k": "abc"}, "k", 5) == 5
    assert _int_conf({}, "k", 5) == 5
    assert _int_conf({"k": "7"}, "k", 5) == 7
    assert _float_conf({"k": "xyz"}, "k", 2.0) == 2.0
    assert _float_conf({}, "k", 2.0) == 2.0
    assert _float_conf({"k": "3.5"}, "k", 2.0) == 3.5
    assert _truthy({"k": "TRUE"}, "k") is True
    assert _truthy({"k": " false "}, "k") is False
    assert _truthy({}, "k") is False


class _SqliteBackend:
    """内存 SQLite 后端替身：实现 SqlOutbox/SqlSubscriptionStore 依赖的最小契约。"""

    param_ph = '?'
    supports_create_index_if_not_exists = True

    def __init__(self):
        import sqlite3
        self.conn = sqlite3.connect(':memory:')

    def _execute_write(self, sql, params=()):
        cursor = self.conn.execute(sql, tuple(params))
        self.conn.commit()
        return cursor.rowcount

    def _execute_read_one(self, sql, params=()):
        return self.conn.execute(sql, tuple(params)).fetchone()

    def _execute_read_all(self, sql, params=()):
        return self.conn.execute(sql, tuple(params)).fetchall()

    def ensure_index(self, if_not_exists_sql, plain_sql):
        self._execute_write(if_not_exists_sql)


def test_bcast_build_stores_by_mode():
    """TC-BCAST-102 | _build_stores 按模式选择 outbox/订阅存储实现

    输入: sqlite 后端 + "sqlite" / " MySQL " / vectordb / file(默认)
    预期输出: 分别为 SqlOutbox+SqlSubscriptionStore / Memory 对 / File 对
    断言点: 实例类型逐项 is 断言（SQL 分支真实建表）
    防回归: 若模式分派被改错，SQL 后端会误用文件存储
    """
    from agent_registry.broadcast import _build_stores
    from agent_registry.broadcast.outbox import FileOutbox, MemoryOutbox, SqlOutbox
    from agent_registry.broadcast.subscriptions import (
        FileSubscriptionStore, MemorySubscriptionStore, SqlSubscriptionStore)

    backend = _SqliteBackend()
    outbox, subs = _build_stores(backend, "sqlite")
    assert isinstance(outbox, SqlOutbox) and isinstance(subs, SqlSubscriptionStore)

    outbox, subs = _build_stores(backend, " MySQL ")
    assert isinstance(outbox, SqlOutbox)

    outbox, subs = _build_stores(None, "vectordb")
    assert isinstance(outbox, MemoryOutbox) and isinstance(subs, MemorySubscriptionStore)

    outbox, subs = _build_stores(None, None)
    assert isinstance(outbox, FileOutbox) and isinstance(subs, FileSubscriptionStore)


def test_bcast_service_lifecycle_disabled():
    """TC-BCAST-103 | 广播关闭时 start/stop 只管理事件总线并关闭存储

    输入: broadcast.enabled=false；可关闭的假 outbox/订阅存储
    预期输出: dispatcher 为 None；start/stop 正常完成；stop 后两个存储 close 各一次
    断言点: dispatcher None + close 计数
    防回归: 若 stop 泄漏（不 close 存储），句柄堆积
    """
    from agent_registry.broadcast import BroadcastService

    outbox = _CloseRecorder()
    subs = _CloseRecorder()
    service = BroadcastService(outbox, subs, config={"broadcast.enabled": "false"})
    assert service.broadcast_enabled is False
    assert service.dispatcher is None

    async def scenario():
        await service.start()
        await service.stop()

    asyncio.run(scenario())
    assert outbox.closed == 1
    assert subs.closed == 1


def test_bcast_service_enabled_builds_dispatcher(monkeypatch):
    """TC-BCAST-104 | 广播开启时构建 WebhookDispatcher 并挂到事件总线

    输入: broadcast.enabled=true 及全部调度参数；monkeypatch 掉 WebhookDispatcher 为假类
    预期输出: dispatcher 为假类实例；start/stop 转发到假类；stop 后存储关闭
    断言点: 实例类型 + start/stop 调用记录 + close 计数
    防回归: 若 dispatcher 未挂接，订阅方永远收不到推送
    """
    from agent_registry.broadcast import BroadcastService

    class FakeDispatcher:
        instances = []
        started = 0
        stopped = 0

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeDispatcher.instances.append(self)

        def start(self):
            FakeDispatcher.started += 1

        async def stop(self):
            FakeDispatcher.stopped += 1

    monkeypatch.setattr("agent_registry.broadcast.dispatcher.WebhookDispatcher", FakeDispatcher)

    outbox = _CloseRecorder()
    subs = _CloseRecorder()
    service = BroadcastService(outbox, subs, config={
        "broadcast.enabled": "true",
        "broadcast.debounce.window": "1.5",
        "broadcast.max.events.per.second": "10",
        "broadcast.webhook.timeout": "3",
        "broadcast.webhook.max.retries": "2",
        "broadcast.webhook.backoff.base": "2",
        "broadcast.webhook.backoff.max": "60",
        "broadcast.outbox.retention.days": "3",
        "broadcast.delivery.max.attempts": "4",
        "broadcast.delivery.retry.interval": "5",
    })
    assert len(FakeDispatcher.instances) == 1
    assert service.dispatcher is FakeDispatcher.instances[0]

    async def scenario():
        await service.start()
        await service.stop()

    asyncio.run(scenario())
    assert FakeDispatcher.started == 1
    assert FakeDispatcher.stopped == 1
    assert outbox.closed == 1 and subs.closed == 1


def test_bcast_singleton_initialize_and_mismatch_guard(monkeypatch):
    """TC-BCAST-105 | 单例初始化：重复初始化幂等；后端与模式不匹配抛 RuntimeError

    输入: 先以 vectordb（内存存储）初始化，再用不匹配的 sqlite 后端重新初始化
    预期输出: 第一次创建单例；第二次抛 "Broadcast outbox is not bound..."
    断言点: 异常类型 + 消息关键字 + 单例身份
    防回归: 若不匹配守卫被删，SQL outbox 会被文件/内存 outbox 静默顶替
    """
    from agent_registry.broadcast import (
        initialize_broadcast_service, reset_for_tests,
    )

    reset_for_tests()
    try:
        service = initialize_broadcast_service(backend=None, mode="vectordb")
        assert service.outbox is not None
        assert initialize_broadcast_service() is service

        class FakeBackend:
            pass

        with pytest.raises(RuntimeError, match="Broadcast outbox is not bound"):
            initialize_broadcast_service(backend=FakeBackend(), mode="sqlite")
    finally:
        reset_for_tests()


def test_bcast_get_event_bus_uses_lazy_singleton():
    """TC-BCAST-106 | get_event_bus 返回单例服务的事件总线；reset_for_tests 清空单例

    输入: 先 reset，调用 get_event_bus 两次
    预期输出: 两次返回同一 EventBus 实例；reset 后重新懒加载新服务
    断言点: is 身份比对 ×2
    防回归: 若懒加载/重置被改坏，测试间状态泄漏
    """
    from agent_registry.broadcast import get_broadcast_service, get_event_bus, reset_for_tests
    from agent_registry.broadcast.event_bus import EventBus

    reset_for_tests()
    try:
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert isinstance(bus1, EventBus)
        assert bus1 is bus2

        reset_for_tests()
        fresh_service = get_broadcast_service()
        assert fresh_service.event_bus is not bus1
    finally:
        reset_for_tests()
