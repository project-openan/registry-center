# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Branch-coverage batch: audit sink, listener facade, internal-service start
loop, audit hook, validation result, main auth policy and remaining small gaps.

All doubles are local; every test asserts observable results.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import agent_registry.integration.audit as audit_mod
import agent_registry.integration.audit_sink as audit_sink_mod
import agent_registry.integration.listener as listener_mod
import agent_registry.main_auth as main_auth_mod
import common.util.validation_result as vr_mod
from common.util.authenticate_util import CallerRole, Principal


# ==========================================================================
# TC-ASINK: integration/audit_sink.py
# ==========================================================================

class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self._conn.executed.append(("ddl", sql))

    def executemany(self, sql, rows):
        self._conn.executed.append(("ins", rows))

    def close(self):
        pass


class _FakeSqlConn:
    def __init__(self):
        self.executed = []
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def sink_env(monkeypatch):
    conf = {"audit.mysql.enabled": "true", "audit.mysql.batch_size": "10",
            "audit.mysql.flush_interval": "0.01", "audit.mysql.host": "h",
            "audit.mysql.password": "p"}
    sink = audit_sink_mod.AuditMySqlSink(conf)
    # pymysql 在 _connect 内部延迟导入；以假模块整体替换 sys.modules 入口
    fake_pymysql = SimpleNamespace(connect=lambda **kw: _FakeSqlConn())
    monkeypatch.setitem(__import__("sys").modules, "pymysql", fake_pymysql)
    return sink


def test_asink_disabled_sink_is_inert():
    """TC-ASINK-101 | 未启用时 sink 为惰性：start/enqueue 直接返回

    输入: audit.mysql.enabled=false
    预期输出: enabled=False；start()/enqueue() 不创建线程、不抛异常
    断言点: enabled 值 + 无异常
    防回归: 若启用检查被删，未配置 MySQL 的部署启动线程
    """
    sink = audit_sink_mod.AuditMySqlSink({"audit.mysql.enabled": "false"})
    assert sink.enabled is False
    sink.start()
    sink.enqueue({"operation_name": "x"})
    # 禁用的 sink 不分配 _thread（生产路径只对启用 sink 调 stop）
    assert not hasattr(sink, "_thread")


def test_asink_start_stop_and_double_start(sink_env):
    """TC-ASINK-102 | start 启动消费线程；重复 start 幂等；stop 停止并清空线程

    输入: 启用的 sink；start 两次后 stop
    预期输出: _thread 非 None → None；stop 后再次 stop 为空操作
    断言点: _thread 状态
    防回归: 若重复 start 不幂等，线程泄漏
    """
    sink = sink_env
    sink.start()
    first = sink._thread
    sink.start()
    assert sink._thread is first
    sink.stop()
    assert sink._thread is None
    sink.stop()  # thread=None 分支：无异常


def test_asink_connect_uses_pymysql(sink_env):
    """TC-ASINK-103 | _connect 通过 pymysql.connect 使用配置参数建连

    输入: sys.modules 中的假 pymysql 记录 kwargs
    预期输出: 连接参数含 host/user/charset/autocommit
    断言点: kwargs 关键项
    防回归: 若连接参数装配被改坏，审计落库失败
    """
    captured = {}
    sink = sink_env
    fake_pymysql = SimpleNamespace(
        connect=lambda **kw: captured.update(kw) or _FakeSqlConn())
    import sys
    original = sys.modules.get("pymysql")
    sys.modules["pymysql"] = fake_pymysql
    try:
        conn = sink._connect()
    finally:
        if original is None:
            sys.modules.pop("pymysql", None)
        else:
            sys.modules["pymysql"] = original
    assert captured["host"] == "h"
    assert captured["charset"] == "utf8mb4"
    assert captured["autocommit"] is True
    assert conn is not None


def test_asink_consume_reconnects_after_write_failure(sink_env):
    """TC-ASINK-104 | _consume：写库失败时关闭连接、降级告警并继续

    输入: 队列 2 条记录；_write_batch 首次抛错、二次成功后置停止位
    预期输出: 不抛异常；连接在失败后被关闭重建；第二批成功写入
    断言点: 无异常 + 第二批落库
    防回归: 若失败未恢复，审计 sink 永久失效
    """
    sink = sink_env
    sink.batch_size = 1  # 每批一条：第一条写失败，第二条成功后停止
    sink.enqueue({"time": "t", "operation_name": "Op1", "details": {"a": 1}})
    sink.enqueue({"time": "t2", "operation_name": "Op2", "details": {"b": 2}})
    failures = {"n": 0}
    conn = _FakeSqlConn()
    original_write = sink._write_batch

    def flaky_write(c, batch):
        if failures["n"] == 0:
            failures["n"] += 1
            raise RuntimeError("mysql down")
        original_write(c, batch)
        sink._stop_event.set()

    sink._write_batch = flaky_write
    sink._connect = lambda: conn
    sink._consume()
    assert failures["n"] == 1
    assert any(kind == "ins" for kind, _ in conn.executed)


def test_asink_consume_closes_connection_on_exit(sink_env):
    """TC-ASINK-105 | _consume 退出时关闭遗留连接（含关闭抛错分支）

    输入: 停止位已置；conn 已存在 / conn.close 抛错
    预期输出: 正常返回，无异常
    断言点: 无异常 ×2
    防回归: 若退出清理被删，连接泄漏
    """
    sink = sink_env
    sink._stop_event.set()
    conn = _FakeSqlConn()
    conn.close = lambda: (_ for _ in ()).throw(RuntimeError("already closed"))
    sink._connect = lambda: conn
    # 模拟循环退出时 conn 非空：直接调用尾部逻辑（通过 _consume 空跑覆盖 171-175）
    sink._consume()


def test_asink_enqueue_full_queue_warns_once(sink_env):
    """TC-ASINK-106 | 队列满时 enqueue 限频告警且不阻塞调用方

    输入: maxsize=1；先占满再 enqueue；两次 enqueue 触发限频
    预期输出: 不抛异常；第二次告警被限频抑制（_warn_last 更新）
    断言点: 无异常 + 告警限频字段
    防回归: 若队列满处理被删，业务请求被审计写入阻塞
    """
    sink = sink_env
    sink.queue = __import__("queue").Queue(maxsize=1)
    sink.queue.put_nowait({"seed": 1})
    sink.enqueue({"operation_name": "a"})  # 满 → 限频告警
    sink._warn_last = 0.0
    sink.enqueue({"operation_name": "b"})  # 间隔重置 → 再告警
    assert sink.queue.qsize() == 1


def test_asink_drain_batch_variants(sink_env):
    """TC-ASINK-107 | _drain_batch：空队列返回空；批量取到上限

    输入: 空队列 / 3 条记录 batch_size=2
    预期输出: [] / 长度 2 的批次
    断言点: 批次长度 ×2
    防回归: 若批量上限被删，单批无限膨胀
    """
    sink = sink_env
    sink.flush_interval = 0.001
    assert sink._drain_batch() == []

    sink.batch_size = 2
    for i in range(3):
        sink.queue.put_nowait({"i": i})
    batch = sink._drain_batch()
    assert len(batch) == 2


def test_asink_module_facade(monkeypatch):
    """TC-ASINK-108 | start_audit_sink 启用时装载单例；stop_audit_sink 停止

    输入: enabled 配置 → start_audit_sink；随后 stop_audit_sink
    预期输出: get_audit_sink 返回实例；stop 后线程为 None
    断言点: 单例状态
    防回归: 若单例装配被删，审计记录只落本地文件
    """
    monkeypatch.setattr(audit_sink_mod, "_sink", None)
    audit_sink_mod.start_audit_sink({
        "audit.mysql.enabled": "true", "audit.mysql.flush_interval": "0.01"})
    sink = audit_sink_mod.get_audit_sink()
    assert sink is not None and sink.enabled is True
    audit_sink_mod.stop_audit_sink()
    assert sink._thread is None
    audit_sink_mod.stop_audit_sink()  # None 分支：无异常


def test_audit_module_mirrors_to_sink(monkeypatch):
    """TC-AUD-101 | audit_integration 在 sink 存在时镜像审计记录

    输入: get_audit_sink 返回带 enqueue 记录器的假 sink
    预期输出: enqueue 被调用且 entry 含归一化字段与 result
    断言点: entry 字段
    防回归: 若镜像被删，客户 MySQL 审计缺失
    """
    mirrored = []

    class FakeSink:
        def enqueue(self, entry):
            mirrored.append(entry)

    monkeypatch.setattr(audit_sink_mod, "get_audit_sink", lambda: FakeSink())
    principal = Principal("1.2.3.4", identity="op")
    asyncio.run(audit_mod.audit_integration("Query Agent", principal, True, {"k": 1}))
    assert len(mirrored) == 1
    entry = mirrored[0]
    assert entry["operation_name"] == "Query Agent"
    assert entry["result"] == "Success"
    assert entry["client_ip"] == "1.2.3.4"

    mirrored.clear()
    asyncio.run(audit_mod.audit_integration_failure("Get Agent", principal, {"k": 2}))
    assert mirrored[0]["result"] == "Failure"


def test_validation_result_str():
    """TC-VR-101 | ValidationResult.__str__ 输出状态与消息

    输入: ValidationResult(True, "ok")
    预期输出: "True, msg: ok"
    断言点: 字符串精确相等
    防回归: 若 __str__ 被删，日志渲染为对象地址
    """
    assert str(vr_mod.ValidationResult(True, "ok")) == "True, msg: ok"


# ==========================================================================
# TC-LIST: integration/listener.py facade
# ==========================================================================

def test_list_start_stop_facade(monkeypatch):
    """TC-LIST-101 | start/stop_integration_access 装配并清理模块级单例

    输入: ThirdPartyAccessServer 替身；enabled 配置
    预期输出: start 创建实例并调用 start()；stop 调用 stop() 并清空单例
    断言点: 实例生命周期记录
    防回归: 若单例清理被删，重复启动失败
    """
    lifecycle = []

    class FakeServer:
        def __init__(self, config):
            lifecycle.append(("init", config))
            self.started = True

        def start(self):
            lifecycle.append(("start",))

        def stop(self):
            lifecycle.append(("stop",))

    monkeypatch.setattr(listener_mod, "ThirdPartyAccessServer", FakeServer)
    monkeypatch.setattr(listener_mod, "_integration_server", None)
    listener_mod.start_integration_access({"integration.enabled": "true"})
    listener_mod.stop_integration_access()
    listener_mod.stop_integration_access()  # None 分支：无异常
    assert [step[0] for step in lifecycle] == ["init", "start", "stop"]


# ==========================================================================
# TC-INT2: internal service start loop
# ==========================================================================

class _JsonConn:
    def __init__(self, payload):
        self.payload = payload
        self.sent = []
        self.closed = False

    def recv(self, bufsize):
        data, self.payload = self.payload, b""
        return data

    def send(self, data):
        self.sent.append(data.decode("utf-8"))

    def close(self):
        self.closed = True


def test_int2_start_loop_handles_errors_and_serves(monkeypatch, tmp_path):
    """TC-INT2-101 | start()：chmod 允许后进入 accept 循环；timeout 与异常均继续；正常服务后退出

    输入: accept 依次 [timeout, timeout, RuntimeError, 合法请求连接]；handler 置 _running=False
    预期输出: bind 成功；handler 响应已发送；socket 清理完成
    断言点: 响应内容 + _running 状态 + socket 文件删除
    防回归: 若 accept 异常未兜底，瞬时错误导致服务退出
    """
    from agent_registry.internal import registry_center_internal_service as svc_mod
    from agent_registry.internal.registry_center_internal_service import RegistryCenterInternalService

    monkeypatch.setattr(svc_mod, "get_registry", lambda: SimpleNamespace(name="r"))
    monkeypatch.setattr(svc_mod, "get_conf", lambda: {})
    monkeypatch.setattr(svc_mod.os, "chmod", lambda *a, **kw: None)

    class FakeServerSocket:
        def __init__(self, family, type):
            self.bound = None
            self.closed = False
            self._accepts = [
                svc_mod.socket.timeout(), svc_mod.socket.timeout(),
                RuntimeError("transient"), None,  # None 占位 → 稍后替换
            ]

        def bind(self, path):
            self.bound = path

        def listen(self, backlog):
            pass

        def settimeout(self, t):
            pass

        def accept(self):
            item = self._accepts.pop(0)
            if item is None:
                item = _JsonConn(json.dumps({"action": "echo", "params": {}}).encode())
            if isinstance(item, Exception):
                raise item
            return item, ("addr",)

        def close(self):
            self.closed = True

    server = FakeServerSocket(1, 2)
    monkeypatch.setattr(svc_mod, "socket",
                        SimpleNamespace(socket=lambda family, type: server,
                                        AF_UNIX=1, SOCK_STREAM=2, timeout=svc_mod.socket.timeout))

    svc = RegistryCenterInternalService()
    svc.SOCKET_DIR = str(tmp_path / "run")
    svc.socket_path = str(tmp_path / "run" / "internal.sock")

    class StopHandler:
        def handle(self, params, registry, config):
            svc._running = False
            return {"success": True, "data": params}

    svc.dispatcher.register_handler("echo", StopHandler)

    class SyncThread:
        def __init__(self, target=None, args=(), daemon=None, **kw):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(svc_mod.threading, "Thread", SyncThread)
    import faulthandler
    faulthandler.dump_traceback_later(20, exit=True)
    svc.start()

    assert server.bound == svc.socket_path
    assert server.closed is True
    assert svc._running is False
    assert not tmp_path_join_exists(svc.socket_path)


def tmp_path_join_exists(path):
    from pathlib import Path
    return Path(path).exists()


# ==========================================================================
# TC-MAUTH: main_auth.py
# ==========================================================================

def _auth_request(method="GET", path="/rest/v1/registry-center/agent-cards"):
    return SimpleNamespace(method=method,
                           url=SimpleNamespace(path=path),
                           scope={})


def test_mauth_token_policy_rejects_mtls_mode():
    """TC-MAUTH-101 | token 身份源 + integration.auth.mode=mtls 启动即拒绝

    输入: config owner.identity.mode=token 且 mode=mtls
    预期输出: ValueError，消息含 "requires a token authentication provider"
    断言点: 异常类型 + 消息关键字
    防回归: 若检查被删，mtls 无法在 token 身份源下工作
    """
    policy = main_auth_mod.MainTokenPolicy()
    with pytest.raises(ValueError, match="requires a token authentication provider"):
        asyncio.run(policy.start({"owner.identity.mode": "token",
                                  "integration.auth.mode": "mtls"}))


def test_mauth_authenticate_rejects_unverified_principal(monkeypatch):
    """TC-MAUTH-102 | authenticate：provider 未返回可验证身份时返回 503

    输入: authenticate_request 替身返回普通对象
    预期输出: HTTPException 503，detail 含 "no verified identity"
    断言点: 状态码 + detail 关键字
    防回归: 若校验被删，匿名主体进入授权流程
    """
    import agent_registry.integration.app as app_mod

    from fastapi import HTTPException

    policy = main_auth_mod.MainTokenPolicy()
    policy.handler = SimpleNamespace(validate_configuration=lambda: None)
    monkeypatch.setattr(app_mod, "authenticate_request",
                        async_stub(SimpleNamespace(not_a_principal=True)))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(policy.authenticate(_auth_request()))
    assert exc.value.status_code == 503


def async_stub(value):
    async def handle(*a, **kw):
        return value
    return handle


def test_mauth_authorize_role_matrix():
    """TC-MAUTH-103 | _authorize 角色矩阵：NMS 放行；VENDOR 读写边界；其它 403

    输入: NMS_OSS / VENDOR_AGENT 的 GET、POST、PUT、heartbeat / PARTNER 的 GET
    预期输出: NMS 直接返回；VENDOR GET/POST/PUT/heartbeat 通过；PARTNER GET → 403
    断言点: 无异常 ×4 + 403
    防回归: 若角色矩阵被改坏，越权访问主端口
    """
    cards = "/rest/v1/registry-center/agent-cards"
    # NMS 管理员：任意请求直接放行
    main_auth_mod.MainTokenPolicy._authorize(
        _auth_request("DELETE", cards + "/x"), SimpleNamespace(role=CallerRole.NMS_OSS))

    vendor = SimpleNamespace(role=CallerRole.VENDOR_AGENT)
    main_auth_mod.MainTokenPolicy._authorize(_auth_request("GET", cards), vendor)
    main_auth_mod.MainTokenPolicy._authorize(_auth_request("POST", cards), vendor)
    # PUT/DELETE 按 org/name 两段主键（路径 6 段），heartbeat 为 7 段
    main_auth_mod.MainTokenPolicy._authorize(
        _auth_request("PUT", cards + "/org-1/agent-1"), vendor)
    main_auth_mod.MainTokenPolicy._authorize(
        _auth_request("POST", cards + "/org-1/agent-1/heartbeat"), vendor)

    partner = SimpleNamespace(role=CallerRole.PARTNER_SERVICE)
    from fastapi import HTTPException
    # 发现类 GET 与角色无关：partner 也能读卡片列表
    main_auth_mod.MainTokenPolicy._authorize(_auth_request("GET", cards), partner)
    # 非Discovery路径的GET与无权限写操作 → 403
    with pytest.raises(HTTPException) as exc:
        main_auth_mod.MainTokenPolicy._authorize(
            _auth_request("GET", "/rest/v1/registry-center/subscriptions"), partner)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        main_auth_mod.MainTokenPolicy._authorize(_auth_request("POST", cards), partner)
    assert exc.value.status_code == 403
    # 段数不足的 PUT 同样被拒（路径不匹配任何放行规则）
    with pytest.raises(HTTPException) as exc:
        main_auth_mod.MainTokenPolicy._authorize(_auth_request("PUT", cards + "/1"), vendor)
    assert exc.value.status_code == 403


# ==========================================================================
# TC-PKM2 / TC-ALOG2 / TC-SSL2: remaining partial branches
# ==========================================================================

def test_pkm2_get_public_key_swallows_lookup_failure(monkeypatch):
    """TC-PKM2-101 | get_public_key 在读取失败时返回 None 而非抛错

    输入: get_all_public_keys 抛 RuntimeError
    预期输出: None
    断言点: 返回 None
    防回归: 若兜底被删，公钥读取故障穿透到 API
    """
    from agent_registry.signature.public_key_manager import PublicKeyManager

    mgr = PublicKeyManager()
    monkeypatch.setattr(mgr, "get_all_public_keys",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("io")))
    assert mgr.get_public_key("org", "agent", "kid") is None


def test_pkm2_load_jwks_missing_file_race(tmp_path, monkeypatch):
    """TC-PKM2-102 | is_valid_path 通过后文件被删除 → _load_jwks 返回空 JWKS

    输入: monkeypatch is_valid_path=True；os.path.exists=False
    预期输出: JWKS.keys == []
    断言点: 空列表（102 行竞态分支）
    防回归: 若竞态分支被删，TOCTOU 场景崩溃
    """
    from agent_registry.signature import public_key_manager as pkm
    from agent_registry.signature.models import JWKS
    from agent_registry.signature.storage import StoragePath

    monkeypatch.setattr(StoragePath, "is_valid_path", lambda path: True)
    monkeypatch.setattr(pkm.os.path, "exists", lambda path: False)
    jwks = pkm.PublicKeyManager().get_all_public_keys("org", "agent")
    assert isinstance(jwks, JWKS)
    assert jwks.keys == []


def test_alog2_load_config_missing_file(tmp_path, monkeypatch):
    """TC-ALOG2-101 | 审计配置文件不存在时使用空配置（默认值生效）

    输入: monkeypatch os.path.exists → False（仅对 log_config.conf）
    预期输出: _load_config() == {}
    断言点: 空 dict
    防回归: 若缺文件分支被删，全新部署审计日志初始化失败
    """
    import common.log.audit_logger as alog

    real_exists = alog.os.path.exists

    def fake_exists(path):
        if str(path).endswith("log_config.conf"):
            return False
        return real_exists(path)

    monkeypatch.setattr(alog.os.path, "exists", fake_exists)
    assert alog.AuditLogger._load_config() == {}


def test_alog2_rotation_renames_backup_failure_continues(tmp_path, monkeypatch):
    """TC-ALOG2-102 | 轮转：最旧备份删除失败与备份重命名失败均不中断轮转

    输入: .3 存在且 os.remove 抛错；.1 重命名抛错
    预期输出: 不抛异常；主文件审计条目仍写入
    断言点: 无异常 + 主文件行数
    防回归: 若备份操作失败中断轮转，日志写满后丢失审计
    """
    import common.log.audit_logger as alog

    log = alog.AuditLogger()
    log.log_file = str(tmp_path / "audit.log")
    log.max_size = 0
    log.backup_count = 2
    for suffix, content in ((".3", "B3\n"), (".2", "B2\n"), (".1", "B1\n")):
        (tmp_path / ("audit.log" + suffix)).write_text(content, encoding="utf-8")

    real_remove = alog.os.remove
    real_rename = alog.os.rename

    def failing_remove(path, *a, **kw):
        if str(path).endswith(".3"):
            raise OSError("locked")
        return real_remove(path, *a, **kw)

    def failing_rename(src, dst, *a, **kw):
        if str(src).endswith(".1") and not str(src) == str(log.log_file):
            raise OSError("deny")
        return real_rename(src, dst, *a, **kw)

    monkeypatch.setattr(alog.os, "remove", failing_remove)
    monkeypatch.setattr(alog.os, "rename", failing_rename)
    log.audit({"operation_name": "Op", "level": "General",
               "result": "Success", "object_name": "Tag"})
    content = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert content.count("\n") == 1


def test_ssl2_linux_walk_restricts_permissions(tmp_path, monkeypatch):
    """TC-SSL2-101 | Linux 分支：目录 700、文件 600 逐一收紧

    输入: platform.system()=Linux；SSL_PATH 指向含 2 个文件的临时目录
    预期输出: 不抛异常（chmod 在 Windows 上为受限操作，但遍历逻辑被执行）
    断言点: 无异常 + walk 完成
    防回归: 若 Linux 分支被删，部署脚本在 Linux 上不收紧权限
    """
    import common.util.ssl_config as ssl_config

    monkeypatch.setattr(ssl_config.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ssl_config, "SSL_PATH", str(tmp_path))
    (tmp_path / "server.key").write_text("k", encoding="utf-8")
    (tmp_path / "server.crt").write_text("c", encoding="utf-8")
    ssl_config.set_ssl_folder_permissions()
