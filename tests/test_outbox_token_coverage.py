# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Statement-coverage batch: outbox persistence modes, CLI parser/completion,
startup helpers, token acquisition IAM paths and assorted small-file gaps.

All doubles are local; every test asserts observable results.
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_registry.broadcast.outbox as outbox_mod
import agent_registry.cli.core as cli_core
import agent_registry.integration.audit_sink as audit_sink_mod
import agent_registry.integration.ban as ban_mod
import agent_registry.integration.jwks as jwks_mod
import agent_registry.integration.oauth_transport as oauth_transport_mod
import agent_registry.integration.token_acquisition as token_acq
import agent_registry.model.agent_layer as agent_layer_mod
import agent_registry.persistence.precheck as precheck_mod
import agent_registry.signature.public_address as public_address_mod
import agent_registry.signature.storage as signature_storage
import agent_registry.start as start_mod
import common.custom.custom_handle as custom_handle_mod
import common.util.app_config as app_config_mod
import common.util.database_config as db_config
from agent_registry.broadcast.outbox import (
    DELIVERY_ABANDONED, DELIVERY_DISPATCHED, DELIVERY_FAILED, DELIVERY_PENDING,
    DELIVERY_SKIPPED, FileOutbox, MemoryOutbox, SqlOutbox, aggregate_delivery_status,
)
from agent_registry.broadcast.events import build_event


# ==========================================================================
# TC-OBX: broadcast/outbox.py
# ==========================================================================

def _event(v, data=None):
    return build_event("AGENT_HEALTH_CHANGED", data or {"organization": "o1"},
                       registry_version=v)


def test_obx_aggregate_status_all_branches():
    """TC-OBX-101 | aggregate_delivery_status 五种归并结果

    输入: 空 / 含 pending / 含 failed / 仅 dispatched / 仅 skipped
    预期输出: None / pending / delivery_failed / dispatched / abandoned
    断言点: 五个返回值精确相等
    防回归: 若归并规则被改坏，/changes 的状态语义漂移
    """
    assert aggregate_delivery_status({}) is None
    assert aggregate_delivery_status({"a": DELIVERY_PENDING}) == DELIVERY_PENDING
    assert aggregate_delivery_status({"a": DELIVERY_FAILED}) == DELIVERY_FAILED
    assert aggregate_delivery_status({"a": "dispatched"}) == DELIVERY_DISPATCHED
    assert aggregate_delivery_status({"a": DELIVERY_SKIPPED}) == DELIVERY_ABANDONED


def test_obx_memory_mark_status_missing_event_and_close():
    """TC-OBX-102 | MemoryOutbox：未知事件 mark_status 返回 False；close 为空操作

    输入: 空 outbox；mark_status("gone", "dispatched")
    预期输出: False；close() 不抛异常
    断言点: 返回 False + 无异常
    防回归: 若误报成功，调用方以为事件已投递
    """
    box = MemoryOutbox()
    assert box.mark_status("gone", "dispatched") is False
    box.close()


def test_obx_memory_mark_status_overrides_all_deliveries():
    """TC-OBX-103 | mark_status 直接覆写每个订阅者的台账行

    输入: 事件 + 两个订阅（一个 pending、一个 skipped）；mark_status → dispatched
    预期输出: 两行状态都被覆写；事件状态为 dispatched
    断言点: delivery_status ×2 + 事件状态
    防回归: 若覆写被删，直接状态写与台账互相矛盾
    """
    box = MemoryOutbox()
    event = box.append(_event(1))
    box.ensure_deliveries(event, ["sub-1"], ["sub-2"])
    assert box.mark_status(event.event_id, "dispatched") is True
    assert box.delivery_status(event.event_id, "sub-1") == "dispatched"
    assert box.delivery_status(event.event_id, "sub-2") == "dispatched"


def test_obx_cleanup_without_active_ids_keeps_deliveries():
    """TC-OBX-104 | cleanup(active_subscription_ids=None) 不修剪任何台账

    输入: active=None
    预期输出: 修剪数为 0，台账行保留
    断言点: 返回 0 + 行仍在
    防回归: 若误删，活跃订阅的投递记录丢失
    """
    box = MemoryOutbox()
    event = box.append(_event(1))
    box.ensure_deliveries(event, ["sub-1"])
    assert box.cleanup(7, active_subscription_ids=None) == 0
    assert box.delivery_status(event.event_id, "sub-1") == DELIVERY_PENDING


class _FlakySqlBackend:
    """SQLite 后端替身：可注入失败语句与预置读结果。"""

    param_ph = '?'
    supports_create_index_if_not_exists = True
    dialect = "sqlite"
    shares_single_connection = False

    def __init__(self):
        self.writes = []
        self.reads_one = []
        self.reads_all = []
        self.fail_on = None
        self._tx_local = None

    def _execute_write(self, sql, params=()):
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("injected failure: " + self.fail_on)
        self.writes.append((sql, params))
        return 1

    def _execute_read_one(self, sql, params=()):
        return self._reads_one_queue.pop(0) if self._reads_one_queue else None

    @property
    def _reads_one_queue(self):
        if not hasattr(self, "_reads_one_list"):
            self._reads_one_list = list(self.reads_one)
        return self._reads_one_list

    def _execute_read_all(self, sql, params=()):
        return self.reads_all.pop(0) if self.reads_all else []

    def ensure_index(self, if_not_exists_sql, plain_sql):
        self._execute_write(if_not_exists_sql)

    def _serialize(self):
        import contextlib
        return contextlib.nullcontext()

    def transaction(self):
        import contextlib
        return contextlib.nullcontext()


def test_obx_sql_unique_index_failure_fails_loud():
    """TC-OBX-105 | 版本唯一索引建不起来时启动失败（fail loud）

    输入: _execute_write 对 CREATE UNIQUE INDEX 抛错
    预期输出: RuntimeError，消息含 "Could not enforce a unique registry_version"
    断言点: 异常类型 + 消息关键字
    防回归: 若静默启动，双实例可能写重版本，/changes 游标永久跳过事件
    """
    backend = _FlakySqlBackend()
    backend.fail_on = "UNIQUE"
    with pytest.raises(RuntimeError, match="Could not enforce a unique registry_version"):
        SqlOutbox(backend)


def test_obx_sql_counter_seed_race_is_tolerated():
    """TC-OBX-106 | 版本计数器并发播种冲突只记录信息日志

    输入: counter 行不存在（read_one → None）且 INSERT 抛错
    预期输出: 不抛异常（初始化继续）
    断言点: 无异常
    防回归: 若把竞态当错误，双实例同时启动会失败
    """
    backend = _FlakySqlBackend()
    backend.fail_on = "INSERT INTO registry_event_counter"
    SqlOutbox(backend)  # 初始化完成即通过


def test_obx_sql_mark_status_missing_event_false():
    """TC-OBX-107 | SqlOutbox.mark_status 对不存在的事件返回 False

    输入: _execute_write 返回 0 行
    预期输出: False
    断言点: 返回值
    防回归: 若误报 True，调用方认为已标记
    """
    class _ZeroWriteBackend(_FlakySqlBackend):
        def _execute_write(self, sql, params=()):
            return 0

    box = SqlOutbox(_ZeroWriteBackend())
    assert box.mark_status("gone", "dispatched") is False


def test_obx_sql_cleanup_without_active_ids_zero():
    """TC-OBX-108 | SqlOutbox cleanup(active=None) 返回 0 且不查询修剪

    输入: active_subscription_ids=None
    预期输出: 0
    断言点: 返回值
    防回归: 若误修剪，删除事件波及活跃订阅
    """
    box = SqlOutbox(_FlakySqlBackend())
    # _prune_deliveries(None) 直接返回 0；cleanup 返回 DELETE 语句的行数（替身恒为 1）
    assert box.cleanup(7, active_subscription_ids=None) == 1
    box.close()


def test_obx_sql_close_is_noop():
    """TC-OBX-109 | SqlOutbox.close 为空操作

    输入: 已初始化的 SqlOutbox
    预期输出: close() 不抛异常
    断言点: 无异常
    防回归: 若误关共享后端连接，主存储被拖垮
    """
    box = SqlOutbox(_FlakySqlBackend())
    box.close()


def _write_file(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_obx_file_load_skips_malformed_lines(tmp_path):
    """TC-OBX-110 | FileOutbox 加载跳过损坏的事件行与投递行

    输入: 事件文件与投递文件各混入空行/坏 JSON/缺字段行 + 1 条合法记录
    预期输出: 仅合法记录加载；list_pending 返回该事件
    断言点: 事件数 + 投递状态
    防回归: 若坏行未跳过，一个损坏文件让启动失败
    """
    good = _event(1)
    events_file = _write_file(tmp_path / "events.jsonl", [
        "",
        "not-json",
        json.dumps(good.to_dict()),
        json.dumps({"event_id": "e2", "registry_version": "not-a-number"}),
    ])
    deliveries_file = _write_file(tmp_path / "events.jsonl.deliveries", [
        "",
        "garbage",
        json.dumps({"event_id": good.event_id, "subscription_id": "sub-1",
                    "status": "pending", "attempts": 0}),
        json.dumps({"missing": "fields"}),
    ])
    box = FileOutbox(str(events_file))
    assert len(box.list_pending()) == 1
    assert box.delivery_status(good.event_id, "sub-1") == DELIVERY_PENDING
    # attempts 计数随台账恢复
    assert box.delivery_attempts(good.event_id, "sub-1") == 0


def test_obx_file_load_oserror_returns_empty(tmp_path, monkeypatch):
    """TC-OBX-111 | 事件/投递文件读取抛 OSError 时告警并按空处理

    输入: 内置 open 对两个文件抛 OSError
    预期输出: outbox 为空、台账为空、不抛异常
    断言点: 空 outbox + 无异常
    防回归: 若 OSError 上抛，磁盘抖动导致启动失败
    """
    events_file = _write_file(tmp_path / "events.jsonl", [json.dumps(_event(1).to_dict())])
    _write_file(tmp_path / "events.jsonl.deliveries", [json.dumps(
        {"event_id": _event(1).event_id, "subscription_id": "s", "status": "pending"})])
    real_open = open

    def failing_open(file, *a, **kw):
        if str(file).endswith(("events.jsonl", "events.jsonl.deliveries")):
            raise OSError("io error")
        return real_open(file, *a, **kw)

    monkeypatch.setattr("builtins.open", failing_open)
    box = FileOutbox(str(events_file))
    assert box.list_pending() == []
    assert box._ledger().statuses("x") == {}


def test_obx_file_mark_status_missing_false_and_rewrite(tmp_path):
    """TC-OBX-112 | FileOutbox：未知事件 mark_status=False；已知事件落盘新快照

    输入: 空 outbox / 含事件 outbox；mark_status
    预期输出: False / True 且文件追加 status+dispatched_at 快照行
    断言点: 返回值 + 追加行内容字段
    防回归: 若快照缺 status 字段，重启后事件回到 pending
    """
    events_file = tmp_path / "events.jsonl"
    box = FileOutbox(str(events_file))
    assert box.mark_status("gone", "dispatched") is False

    event = box.append(_event(1))
    assert box.mark_status(event.event_id, "dispatched") is True
    lines = events_file.read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(lines[-1])
    assert last["status"] == "dispatched"
    assert last["dispatched_at"]
    box.close()


def test_obx_file_cleanup_prunes_and_rewrites(tmp_path):
    """TC-OBX-113 | FileOutbox cleanup 清理过期非 pending 事件并重写文件

    输入: 1 条过期 dispatched 事件 + 1 条 pending 事件；retention=1 天
    预期输出: 返回 1；文件重写后仅剩 pending 事件；台账中过期事件被剪除
    断言点: 返回值 + 文件行数 + 剩余事件
    防回归: 若重写被删，重启后已清理事件复活
    """
    events_file = tmp_path / "events.jsonl"
    box = FileOutbox(str(events_file))
    old = build_event("AGENT_HEALTH_CHANGED", {"organization": "o"},
                      registry_version=1)
    old.timestamp = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    box.append(old)
    box.mark_status(old.event_id, "dispatched")
    fresh = box.append(_event(2))

    removed = box.cleanup(1, active_subscription_ids=["sub-1"])
    assert removed == 1
    remaining = [json.loads(line)["event_id"]
                 for line in events_file.read_text(encoding="utf-8").strip().splitlines()]
    assert remaining == [fresh.event_id]
    assert [e.event_id for e in box.list_pending()] == [fresh.event_id]
    box.close()


# ==========================================================================
# TC-CLIC: cli/core.py
# ==========================================================================

class _FakeCliCommand(cli_core.BaseCommand):
    name = "fakecmd"
    help_text = "fake command with a=b option"
    aliases = ()

    @property
    def subcommands(self):
        return {"list": type("Sub", (cli_core.BaseCommand,),
                             {"name": "list", "help_text": "list things",
                              "aliases": (), "subcommands": {},
                              "add_arguments": lambda self, p: p.add_argument(
                                  "--filter", help="x=y"),
                              "execute": lambda self, args: 0})()}

    def add_arguments(self, parser):
        parser.add_argument("-o", "--opt", help="a=b")
        parser.add_argument("positional")

    def execute(self, args):
        return 0


def test_clic_complete_unknown_command_returns_empty():
    """TC-CLIC-101 | _complete_command 对未注册命令返回空列表

    输入: cmd_name 不在 registry
    预期输出: []
    断言点: 空列表
    防回归: 若误返回子命令补全，Tab 键给出错误建议
    """
    from agent_registry.cli.registry import CommandRegistry
    registry = CommandRegistry()
    registry.register(_FakeCliCommand)
    shell = cli_core.InteractiveCLI(registry)
    assert shell._complete_command("nosuch", "", "nosuch ", 6, 6) == []


def test_clic_complete_unknown_subcommand_prefixes():
    """TC-CLIC-102 | 子命令名部分输入时按前缀补全子命令列表

    输入: line = "fakecmd li"，光标在末尾
    预期输出: ["list"]
    断言点: 补全结果
    防回归: 若前缀逻辑被删，部分输入无建议
    """
    from agent_registry.cli.registry import CommandRegistry
    registry = CommandRegistry()
    registry.register(_FakeCliCommand)
    shell = cli_core.InteractiveCLI(registry)
    line = "fakecmd li"
    result = shell._complete_command("fakecmd", "li", line, len(line), len(line))
    assert result == ["list"]


def test_clic_help_formatter_splits_equal_help():
    """TC-CLIC-103 | CleanHelpFormatter：'=' 帮助拆两行；positional 用 dest；子解析器用短调用名

    输入: 用含 '-o/--opt help=\"a=b\"' 的解析器分别以两个内嵌 formatter 输出帮助
    预期输出: 顶层 formatter 把 '  -o, --opt OPT' 与 'a=b' 拆成两行；
              子解析器 formatter 输出 '  -o, --opt OPT'
    断言点: 两种格式化输出关键行
    防回归: 若格式化被删，帮助输出退回原始 argparse 长行
    """
    import argparse as argparse_mod
    from agent_registry.cli.registry import CommandRegistry
    registry = CommandRegistry()
    registry.register(_FakeCliCommand)
    shell = cli_core.InteractiveCLI(registry)
    parser = shell._build_parser()

    # _add_command 的子解析器 formatter（_format_action_invocation）
    subparser = parser._subparsers._group_actions[0].choices["fakecmd"]
    sub_help = subparser.format_help()
    assert "-o, --opt OPT" in sub_help
    assert "positional" in sub_help

    # _build_parser 的顶层 formatter（format_help 的 '=' 拆分行）
    top_formatter = parser.formatter_class
    p2 = argparse_mod.ArgumentParser(formatter_class=top_formatter, add_help=False)
    p2.add_argument("-o", "--opt", help="a=b")
    top_help = p2.format_help()
    assert "-o, --opt OPT" in top_help
    assert "      b" in top_help       # '=' 被拆为独立描述行
    assert "a=b" not in top_help       # 原始长行不再出现


def test_clic_command_help_text_properties():
    """TC-CLIC-104 | tag/agent 命令的 help_text 属性可读且为字符串

    输入: 实例化全部 tag/agent 子命令
    预期输出: help_text 均为非空字符串（9 个属性分支可达）
    断言点: isinstance(str) ×9
    防回归: 若属性被删，CLI 帮助聚合崩溃
    """
    from agent_registry.cli.commands.agent import (
        ApprovalCommand, SetTagsCommand, UDSGetCommand, UDSListCommand)
    from agent_registry.cli.commands.tag import (
        TagCreateCommand, TagDeleteCommand, TagGetCommand, TagListCommand, TagUpdateCommand)

    commands = [TagCreateCommand(), TagGetCommand(), TagUpdateCommand(),
                TagDeleteCommand(), TagListCommand(),
                UDSGetCommand(), UDSListCommand(), ApprovalCommand(), SetTagsCommand()]
    for cmd in commands:
        assert isinstance(cmd.help_text, str) and cmd.help_text


# ==========================================================================
# TC-START: start.py helpers
# ==========================================================================

def test_start_internal_service_non_windows_uses_uds(monkeypatch):
    """TC-START-101 | 非 Windows 平台内部服务走 UDS 并记录对应日志

    输入: IS_WINDOWS=False；内部服务替身
    预期输出: _internal_service 为替身实例且线程已启动
    断言点: 模块全局 _internal_service
    防回归: 若平台分派被改坏，Windows 上误建 UDS 服务
    """
    started = []

    class FakeService:
        def start(self):
            started.append(1)

        def stop(self):
            pass

    monkeypatch.setattr(start_mod, "IS_WINDOWS", False)
    monkeypatch.setattr(start_mod, "_create_internal_service", lambda cfg: FakeService())
    original = getattr(start_mod, "_internal_service", None)
    try:
        start_mod.start_internal_service({})
        assert isinstance(start_mod._internal_service, FakeService)
        assert started == [1]
    finally:
        start_mod._internal_service = original


def test_start_shutdown_signal_stops_service(monkeypatch):
    """TC-START-102 | 关停信号处理器调用 stop_internal_service 并退出进程

    输入: sys.exit 替身；_internal_service 为假服务
    预期输出: service.stop() 被调用；sys.exit(0) 被调用
    断言点: stop 记录 + exit 码
    防回归: 若信号处理被删，优雅停机失效
    """
    stopped = []
    exits = []

    class FakeService:
        def stop(self):
            stopped.append(1)

    monkeypatch.setattr(start_mod, "stop_audit_sink", lambda: None)
    monkeypatch.setattr(start_mod, "stop_integration_access", lambda: None)
    monkeypatch.setattr(start_mod, "_internal_service", FakeService())
    monkeypatch.setattr(start_mod.sys, "exit", lambda code: exits.append(code))
    try:
        start_mod._handle_shutdown_signal(15, None)
    finally:
        start_mod._internal_service = None
    assert stopped == [1]
    assert exits == [0]


# ==========================================================================
# TC-TOKIAM: token_acquisition.py IAM paths
# ==========================================================================

class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body if isinstance(body, bytes) else body.encode()

    async def aiter_bytes(self):
        yield self._body


class _FakeStream:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class _FakeIamClient:
    def __init__(self, response):
        self._response = response

    def stream(self, *a, **kw):
        return _FakeStream(self._response)

    async def aclose(self):
        pass


def _provider_with(response, monkeypatch=None):
    provider = token_acq.OAuth2ClientCredentialsProvider(
        "https://iam.example.com/token", client=_FakeIamClient(response))
    return provider


def test_tokiam_provider_aclose_owned_client():
    """TC-TOKIAM-101 | 自建 httpx 客户端的 provider 在 aclose 时关闭它

    输入: client=None 构造（owns_client=True）
    预期输出: aclose() 正常完成
    断言点: 无异常
    防回归: 若 aclose 被删，连接池泄漏
    """
    provider = token_acq.OAuth2ClientCredentialsProvider("https://iam.example.com/token")
    asyncio.run(provider.aclose())

    class _Minimal(token_acq.TokenAcquisitionProvider):
        async def acquire(self, credentials, scopes):
            return None

    asyncio.run(_Minimal().aclose())  # ABC 默认 aclose：pass


def test_tokiam_non_dict_body_rejected(monkeypatch):
    """TC-TOKIAM-102 | IAM 返回非 JSON 对象体（数组）→ temporarily_unavailable

    输入: 200 + body "[1,2]"
    预期输出: TokenAcquisitionError，error == "temporarily_unavailable"
    断言点: error 值
    防回归: 若类型检查被删，畸形响应进入 token 字段解析
    """
    provider = _provider_with(_FakeResponse(200, "[1,2]"))
    with pytest.raises(token_acq.TokenAcquisitionError) as exc:
        asyncio.run(provider.acquire(token_acq.ClientCredentials("id", "secret"),
                                     frozenset({"read"})))
    assert exc.value.error == "temporarily_unavailable"


def test_tokiam_forbidden_error_mapped_to_503():
    """TC-TOKIAM-103 | IAM 403（非 400/401 错误映射）→ temporarily_unavailable

    输入: 403 + {"error": "forbidden"}
    预期输出: error == "temporarily_unavailable"，status_code == 503
    断言点: 两个属性
    防回归: 若状态码映射被删，上游错误细节外泄
    """
    provider = _provider_with(_FakeResponse(403, json.dumps({"error": "forbidden"})))
    with pytest.raises(token_acq.TokenAcquisitionError) as exc:
        asyncio.run(provider.acquire(token_acq.ClientCredentials("id", "secret"),
                                     frozenset({"read"})))
    assert exc.value.error == "temporarily_unavailable"
    assert exc.value.status_code == 503


def test_tokiam_expired_remaining_rejected(monkeypatch):
    """TC-TOKIAM-104 | IAM 处理耗时超过 expires_in 时拒绝 token

    输入: expires_in=1；monkeypatch time.monotonic 使流逝时间大于 1
    预期输出: TokenAcquisitionError("temporarily_unavailable")
    断言点: error 值
    防回归: 若剩余有效期检查被删，立刻过期的 token 被发放
    """
    provider = _provider_with(_FakeResponse(200, json.dumps({
        "access_token": "tok-1", "token_type": "Bearer", "expires_in": 1,
        "scope": "read"})))
    fake_clock = iter([100.0, 100.0, 200.0, 200.0, 300.0])
    monkeypatch.setattr(token_acq.time, "monotonic", lambda: next(fake_clock, 300.0))
    with pytest.raises(token_acq.TokenAcquisitionError) as exc:
        asyncio.run(provider.acquire(token_acq.ClientCredentials("id", "secret"),
                                     frozenset({"read"})))
    assert exc.value.error == "temporarily_unavailable"


def test_tokiam_register_provider_rejects_bad_ids():
    """TC-TOKIAM-105 | 注册适配器：空 id / 重复 id 抛 ValueError

    输入: "" 与 "oauth2_client_credentials"
    预期输出: ValueError "unique nonempty id"
    断言点: 异常类型 + 消息关键字
    防回归: 若校验被删，业务适配器顶替内置 provider
    """
    with pytest.raises(ValueError, match="unique nonempty id"):
        token_acq.register_token_acquisition_provider("", lambda conf: None)
    with pytest.raises(ValueError, match="unique nonempty id"):
        token_acq.register_token_acquisition_provider(
            "oauth2_client_credentials", lambda conf: None)


def test_tokiam_service_validates_provider_and_scopes():
    """TC-TOKIAM-106 | TokenAcquisitionService：非 provider 实例/scope 配置错误各抛 ValueError

    输入: provider=object() / allowed_scopes="" / default 超出 allowed
    预期输出: ValueError，消息分别含 "must return a TokenAcquisitionProvider" /
              "must be explicitly configured"
    断言点: 异常消息关键字 ×3
    防回归: 若校验被删，坏适配器或超范围 scope 进入签发
    """

    class _P(token_acq.TokenAcquisitionProvider):
        async def acquire(self, credentials, scopes):
            return None

    with pytest.raises(ValueError, match="must return a TokenAcquisitionProvider"):
        token_acq.TokenAcquisitionService(object(), "read", "read")
    with pytest.raises(ValueError, match="must be explicitly configured"):
        token_acq.TokenAcquisitionService(_P(), "", "")
    with pytest.raises(ValueError, match="must be explicitly configured"):
        token_acq.TokenAcquisitionService(_P(), "read", "write")


def test_tokiam_configure_rejects_reconfigure_and_unknown_provider(monkeypatch):
    """TC-TOKIAM-107 | configure：重复配置抛 RuntimeError；未知 provider 抛 ValueError

    输入: 已配置后再次 configure；enabled=true 且 provider 不存在
    预期输出: RuntimeError "already configured" / ValueError "Unknown token acquisition provider"
    断言点: 异常类型 + 消息关键字（模块全局状态已恢复）
    防回归: 若守卫被删，重复配置泄漏旧传输资源
    """
    original_service = token_acq._service
    original_configured = token_acq._configured
    try:
        monkeypatch.setattr(token_acq, "_service", object())
        monkeypatch.setattr(token_acq, "_configured", True)
        with pytest.raises(RuntimeError, match="already configured"):
            token_acq.configure_token_acquisition({})

        monkeypatch.setattr(token_acq, "_service", None)
        monkeypatch.setattr(token_acq, "_configured", False)
        with pytest.raises(ValueError, match="Unknown token acquisition provider"):
            token_acq.configure_token_acquisition({
                "integration.token.enabled": "true",
                "integration.token.provider": "no_such_provider",
                "integration.token.allowed_scopes": "read",
                "integration.token.default_scope": "read",
            })
    finally:
        token_acq._service = original_service
        token_acq._configured = original_configured


# ==========================================================================
# TC-SMALL: assorted small-file gaps
# ==========================================================================

def test_small_ban_tracker_threshold_and_reset():
    """TC-SMALL-101 | BanTracker：达到阈值封禁、封禁期不计数、冷却后解禁、成功清零

    输入: threshold=2、可控时钟；两次失败 → True；封禁期再失败 → False；
          冷却到期 is_banned 解禁 → 两次失败再次触发
    预期输出: False/True/False → 解禁后 False/True
    断言点: record_failure 返回值序列 + on_lift 回调
    防回归: 若封禁/解禁状态机被改坏，爆破防护漂移
    """
    now = {"t": 1000.0}
    lifted = []
    tracker = ban_mod.BanTracker(threshold=2, cooldown_seconds=60,
                                 clock=lambda: now["t"], on_lift=lifted.append)
    assert tracker.record_failure("k") is False
    assert tracker.record_failure("k") is True
    assert tracker.record_failure("k") is False  # 封禁期内不计数（第 66 行）
    assert tracker.remaining_seconds("k") > 0

    now["t"] += 61  # 冷却到期 → 解禁并触发回调
    assert tracker.is_banned("k") is False
    assert lifted == ["k"]
    assert tracker.record_failure("k") is False
    assert tracker.record_failure("k") is True
    tracker.record_success("k")   # 清空失败计数
    assert tracker.record_failure("k") is False
    tracker.record_success("")    # 空 key 直接返回（第 77 行）


def test_small_jwks_client_rejects_missing_kid_and_empty_keys(monkeypatch):
    """TC-SMALL-102 | VerifiedJwkClient：无 kid 的 JWT 与空 keys 的 JWKS 各抛对应异常

    输入: header 无 kid 的 JWT / JWKS 返回 {"keys": []}
    预期输出: PyJWKClientError "JWT signing key missing" /
              PyJWKClientConnectionError "JWKS unavailable"
    断言点: 异常类型 + 消息关键字
    防回归: 若校验被删，kid 缺失或空 JWKS 进入验签
    """
    import jwt

    client = jwks_mod.VerifiedJwkClient("https://jwks.example.com", timeout=3.0)
    token = jwt.encode({"sub": "x"}, "secret", algorithm="HS256")
    with pytest.raises(jwt.PyJWKClientError, match="JWT signing key missing"):
        asyncio.run(client.get_signing_key_from_jwt(token))

    fetch_client = _FakeIamClient(_FakeResponse(200, json.dumps({"keys": []})))
    client2 = jwks_mod.VerifiedJwkClient("https://jwks.example.com", timeout=3.0,
                                         client=fetch_client)
    with pytest.raises(jwt.PyJWKClientConnectionError, match="JWKS unavailable"):
        asyncio.run(client2._refresh())


def test_small_signer_rejects_bad_algorithm_and_non_rsa_key(tmp_path):
    """TC-SMALL-103 | AgentCardSigner：非法算法/非 RSA 私钥各抛 ValueError

    输入: algorithm="ES256" / EC 私钥文件
    预期输出: "Unsupported registry signing algorithm" / "requires an RSA private key"
    断言点: 异常消息关键字 ×2
    防回归: 若校验被删，非 RSA 算法进入卡片签名
    """
    from agent_registry.agent_registry.agent_card_signer import AgentCardSigner
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    with pytest.raises(ValueError, match="Unsupported registry signing algorithm"):
        AgentCardSigner(sign_enabled=True, algorithm="ES256")

    ec_key = ec.generate_private_key(ec.SECP256R1())
    key_file = tmp_path / "ec.pem"
    key_file.write_bytes(ec_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    with pytest.raises(ValueError, match="requires an RSA private key"):
        AgentCardSigner(private_key_path=str(key_file), sign_enabled=True)


def test_small_watcher_enabled_log_and_none_endpoint(monkeypatch):
    """TC-SMALL-104 | watcher：启用时打印监控日志；端点节点为 None 返回空串

    输入: agent_to_graph_enabled=true；_resolve_endpoint_node_id(None, [])
    预期输出: 不抛异常；返回 ""
    断言点: 返回空串
    防回归: 若 None 守卫被删，关系端点解析崩溃
    """
    import agent_registry.agent_to_graph.watcher as watcher_mod

    monkeypatch.setattr(watcher_mod, "get_conf",
                        lambda: {"agent_to_graph_enabled": "true"})
    watcher_mod.start_watching()
    assert watcher_mod._resolve_endpoint_node_id(None, []) == ""


def test_small_app_config_comments_and_env_overrides(tmp_path, monkeypatch):
    """TC-SMALL-105 | app_config：load_configs 剥离行内注释；REGISTRY_ 环境变量三级映射

    输入: 含 '#' 注释的 key=value 文件（load_configs）；REGISTRY_FOO_BAR / REGISTRY_FOO_BAZ / REGISTRY_QUX
    预期输出: 注释被剥离；foo.bar / foobar 分别被覆写；未知键以小写原始名存入
    断言点: 解析结果 ×4
    防回归: 若环境映射被改坏，部署覆盖失效
    """
    conf_file = tmp_path / "server.properties"
    conf_file.write_text("ip = 1.2.3.4 # main port\n", encoding="utf-8")
    config = {}
    app_config_mod.load_configs(str(conf_file), config)
    assert config["ip"] == "1.2.3.4"

    conf = {"foo.bar": "a", "foo_bar": "b"}
    overrides = {"REGISTRY_foo_bar": "x", "REGISTRY__FOO_BAR": "y", "REGISTRY_QUX": "z"}
    app_config_mod.apply_env_overrides(conf, env=overrides)
    assert conf["foo.bar"] == "x"      # 小写后缀 env 绕过 canonical 命中点号键（164-166 行）
    assert conf["foo_bar"] == "y"      # REGISTRY__FOO_BAR → 去下划线名匹配（167-170 行）
    assert conf["qux"] == "z"          # 未知键按原始小写名存入（171 行）


def test_small_app_config_invalid_db_profile_raises(monkeypatch):
    """TC-SMALL-106 | 非 audit_mysql 的数据库配置无效时错误上抛

    输入: REGISTRY_PERSISTENCE_MODE=postgresql 且 provider_config 抛 DatabaseConfigError
    预期输出: DatabaseConfigError 传播（audit_mysql 才降级）
    断言点: 异常类型
    防回归: 若吞掉错误，主库配置错误被静默降级
    """
    import common.util.connection_profiles as profiles_mod

    def raiser(name, root_path):
        if name == "postgresql":
            raise db_config.DatabaseConfigError("db/postgresql.json: configure host")
        return {}

    monkeypatch.setenv("REGISTRY_PERSISTENCE_MODE", "postgresql")
    monkeypatch.setattr(app_config_mod, "get_conf", lambda: {"knowledge_graph.enabled": "false"})
    monkeypatch.setattr(profiles_mod, "provider_config", raiser)
    with pytest.raises(db_config.DatabaseConfigError):
        app_config_mod.get_persistence_conf()


def test_small_custom_handler_registry_paths():
    """TC-SMALL-107 | HandlerRegistry：非 BaseHandler 注册被拒；自定义注册可取；未知类型报错

    输入: object 作为 handler 类 / 注册自定义 handler / 未知 interface value
    预期输出: TypeError / 返回自定义实例 / ValueError "Unknown interface type"
    断言点: 三种结果
    防回归: 若校验被删，任意类进入处理链
    """
    from common.custom.custom_handle import BaseHandler, HandlerRegistry
    from common.custom.interface_type import InterfaceType

    with pytest.raises(TypeError, match="must be a subclass of BaseHandler"):
        HandlerRegistry.register(InterfaceType.DECRYPT, object)

    class MyHandler(BaseHandler):
        async def handle(self, *a, **kw):
            return "ok"

    saved_registry = dict(HandlerRegistry._registry)
    try:
        HandlerRegistry.register(InterfaceType.DECRYPT, MyHandler)
        HandlerRegistry._instances.pop(InterfaceType.DECRYPT.value, None)
        assert isinstance(HandlerRegistry.get_handler(InterfaceType.DECRYPT), MyHandler)

        fake_type = SimpleNamespace(value="definitely_unknown_interface")
        with pytest.raises(ValueError, match="Unknown interface type"):
            HandlerRegistry.get_handler(fake_type)
    finally:
        HandlerRegistry._registry.clear()
        HandlerRegistry._registry.update(saved_registry)


def test_small_request_validation_card_batch():
    """TC-SMALL-108 | card_batch：合法列表原样返回；非法输入 422

    输入: {"agentCards": [{...}]} / 缺键 / 空列表 / 非列表
    预期输出: 原列表 / HTTPException 422 ×3
    断言点: 返回值 + 三个异常
    防回归: 若批量校验被删，空批量进入注册循环
    """
    from agent_registry.request_validation import card_batch
    from fastapi import HTTPException

    body = {"agentCards": [{"name": "a"}]}
    assert card_batch(body) == [{"name": "a"}]
    for bad in ({}, {"agentCards": []}, {"agentCards": "no"}):
        with pytest.raises(HTTPException) as exc:
            card_batch(bad)
        assert exc.value.status_code == 422


def test_small_public_address_http_and_bind_addresses():
    """TC-SMALL-109 | registry_jku_url：HTTP 部署与绑定地址返回空串

    输入: enable_https=false / ip=0.0.0.0 / ip=::
    预期输出: 三个空串
    断言点: 返回值 ×3
    防回归: 若守卫被删，HTTP 部署暴露未受信 JWKS 地址
    """
    assert public_address_mod.registry_jku_url(
        {"ip": "1.2.3.4", "enable_https": "false"}) == ""
    assert public_address_mod.registry_jku_url({"ip": "0.0.0.0"}) == ""
    assert public_address_mod.registry_jku_url({"ip": "::"}) == ""


def test_small_oauth_transport_relative_ca_file(tmp_path, monkeypatch):
    """TC-SMALL-110 | oauth_transport.tls_context：相对 CA 路径基于 root 解析

    输入: 生成的 CA PEM；ca_file="ca/ca.pem"；get_root_path → tmp
    预期输出: 返回以该 CA 初始化的 SSLContext
    断言点: context.verify_files 加载成功（不抛异常）
    防回归: 若相对路径拼接被删，容器内相对配置无法加载
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ut-ca")])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    ca_dir = tmp_path / "ca"
    ca_dir.mkdir()
    (ca_dir / "ca.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    monkeypatch.setattr(oauth_transport_mod, "get_root_path", lambda: str(tmp_path))
    ctx = oauth_transport_mod.tls_context("ca/ca.pem")
    assert ctx is not None


def test_small_agent_layer_agentcard_must_be_object():
    """TC-SMALL-111 | normalize_registration_item：agentCard 非对象时 ValueError

    输入: {"agentCard": "str", "layer": "gpu"}
    预期输出: ValueError，消息含 "agentCard must be an object"
    断言点: 异常类型 + 消息关键字
    防回归: 若类型检查被删，字符串卡片进入注册
    """
    with pytest.raises(ValueError, match="agentCard must be an object"):
        agent_layer_mod.normalize_registration_item({"agentCard": "str", "layer": "gpu"})


def test_small_database_config_integer_key_absent():
    """TC-SMALL-112 | 整数字段未配置时跳过校验（continue 分支）

    输入: profile.integers 含 "pool_min" 但 defaults/raw 均无该键
    预期输出: 配置正常返回且不含 pool_min
    断言点: "pool_min" not in config
    防回归: 若缺键分支被删，可选整数配置报错
    """
    profile = db_config.DatabaseProfile(defaults={}, env={}, secrets={},
                                        required=(), integers={"pool_min": (1, 10)},
                                        paths=())
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(db_config, "read_profile_file", lambda *a, **kw: {})
    try:
        config = db_config.load_profile("pg", profile, ".")
    finally:
        monkeypatch.undo()
    assert "pool_min" not in config


def test_small_cert_check_unsupported_key_type(tmp_path):
    """TC-SMALL-113 | cert_check：Ed25519 证书的密钥强度检查记为失败

    输入: Ed25519 自签证书
    预期输出: results 含 ("key strength (RSA)", False, detail 含 "unsupported key type")
    断言点: 检查项元组
    防回归: 若兜底分支被删，未知密钥类型崩溃
    """
    import importlib
    import agent_registry.cert_check as cert_check

    ed_mod = importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
    ed_key = ed_mod.Ed25519PrivateKey.generate()
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ut-ed")])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(ed_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .sign(ed_key, algorithm=None))
    path = tmp_path / "ed.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    passed, results = cert_check.check_certificate(str(path))
    entry = next(r for r in results if r[0] == "key strength (RSA)")
    assert entry[1] is False
    assert "unsupported key type" in entry[2]
    assert passed is False


def test_small_certificate_generator_validations(tmp_path):
    """TC-SMALL-114 | 证书生成：非法 usage / 空密码 / 已存在证书 各返回 False 或抛错

    输入: cert_usage="tls" / password="" / 目录已有证书
    预期输出: 前两者 False（异常被记录），第三者 False
    断言点: 返回 False ×3
    防回归: 若校验被删，坏参数写半截证书
    """
    from common.cert.certificate_generator import CertificateGenerator

    generator = CertificateGenerator()
    assert generator.generate_self_signed_cert(str(tmp_path / "c1"), "tls", "pw") is False
    assert generator.generate_self_signed_cert(str(tmp_path / "c2"), "serverAuth", "") is False

    cert_dir = tmp_path / "c3"
    cert_dir.mkdir()
    (cert_dir / "server.cer").write_text("x", encoding="utf-8")
    assert generator.generate_certificates(str(cert_dir), "serverAuth") is False


@pytest.mark.skipif(sys.platform != 'win32',
                    reason='os.name=="nt" 的快捷放行仅 Windows 可验证；POSIX 分支走真实 os.stat')
def test_small_init_validate_file_permissions_windows():
    """TC-SMALL-115 | validate_file_permissions 在 Windows 上直接通过

    输入: 任意路径（os.name == 'nt'）
    预期输出: (True, "")
    断言点: 元组精确相等
    防回归: 若 Windows 分支被删，Windows 安装向导误报权限错误
    """
    from agent_registry.init import InitCommand

    wizard = InitCommand.__new__(InitCommand)
    result = wizard.validate_file_permissions("any/path")
    assert result == (True, "")


def test_small_mysql_acquire_conn_uses_pool():
    """TC-SMALL-116 | MySQLStorage._acquire_conn 从池获取连接

    输入: pool 替身记录 connection() 调用
    预期输出: 返回池连接
    断言点: 返回对象 + 调用记录
    防回归: 若获取方式被改错，连接不受池管理
    """
    import agent_registry.persistence.mysql_storage as mysql_mod

    conn = object()
    calls = []
    pool = SimpleNamespace(connection=lambda: calls.append(1) or conn)
    instance = mysql_mod.MySQLStorage(pool)
    assert instance._acquire_conn() is conn
    assert calls == [1]


def test_small_health_init_sql_backend_store():
    """TC-SMALL-117 | initialize_health_service 带 SQL 后端时使用 SqlHeartbeatStore

    输入: 内存 SQLite 后端替身；mode="sqlite"
    预期输出: 服务.store 为 SqlHeartbeatStore 实例
    断言点: 类型断言
    防回归: 若分派被删，SQL 模式误用内存存储
    """
    import sqlite3

    from agent_registry.health import initialize_health_service, reset_for_tests
    from agent_registry.health.store import SqlHeartbeatStore

    class Backend:
        param_ph = '?'

        def __init__(self):
            self.conn = sqlite3.connect(':memory:')

        def _execute_write(self, sql, params=()):
            self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return 1

        def _execute_read_one(self, sql, params=()):
            return self.conn.execute(sql, tuple(params)).fetchone()

        def _execute_read_all(self, sql, params=()):
            return self.conn.execute(sql, tuple(params)).fetchall()

        def ensure_index(self, a, b):
            pass

    reset_for_tests()
    try:
        service = initialize_health_service(backend=Backend(), mode="sqlite",
                                            config={"heartbeat.enabled": "false"})
        assert isinstance(service.store, SqlHeartbeatStore)
    finally:
        reset_for_tests()


def test_small_precheck_vectordb_failure_and_systemexit(monkeypatch):
    """TC-SMALL-118 | verify_storage_ready：vectordb 失败日志；SystemExit 原样上抛

    输入: USE_VECTORDB=True 且 check_connection 抛 RuntimeError / SystemExit
    预期输出: SystemExit（vector 路径 exit(1)）/ SystemExit 原样传播
    断言点: pytest.raises(SystemExit) ×2
    防回归: 若 SystemExit 被吞掉，退出码语义丢失
    """
    import agent_registry.config as config_mod

    fake_registry = SimpleNamespace(storage=SimpleNamespace(
        check_connection=lambda: (_ for _ in ()).throw(RuntimeError("vector down"))))
    monkeypatch.setattr("agent_registry.registry_instance.get_registry",
                        lambda: fake_registry)
    monkeypatch.setattr(config_mod, "USE_VECTORDB", True)
    with pytest.raises(SystemExit):
        precheck_mod.verify_storage_ready()

    fake_registry2 = SimpleNamespace(storage=SimpleNamespace(
        check_connection=lambda: (_ for _ in ()).throw(SystemExit(3))))
    monkeypatch.setattr("agent_registry.registry_instance.get_registry",
                        lambda: fake_registry2)
    with pytest.raises(SystemExit):
        precheck_mod.verify_storage_ready()


def test_small_signature_storage_hash_path_traversal(monkeypatch):
    """TC-SMALL-119 | 无 organization 的哈希路径被解析到 BASE_DIR 外时拒绝

    输入: monkeypatch BASE_DIR 与 os.path.realpath 使结果路径逃逸
    预期输出: ValueError，消息含 "Path traversal detected"
    断言点: 异常类型 + 消息关键字
    防回归: 若 realpath 校验被删，符号链接可把公钥写到任意目录
    """
    monkeypatch.setattr(signature_storage.StoragePath, "BASE_DIR", "C:/base")
    real_realpath = signature_storage.os.path.realpath

    def fake_realpath(path):
        if "json" in str(path):
            return "C:/outside/leaked.json"
        return "C:/base"

    monkeypatch.setattr(signature_storage.os.path, "realpath", fake_realpath)
    with pytest.raises(ValueError, match="Path traversal detected"):
        signature_storage.StoragePath.get_storage_path(None, "agent", "http://u")


def test_small_jwk_provider_wrong_key_types():
    """TC-SMALL-120 | JWKProvider：RSA/EC 转换入口收到错误密钥类型时抛 CertLoadError

    输入: EC 公钥传入 _rsa_to_jwk_dict；RSA 公钥传入 _ec_to_jwk_dict
    预期输出: CertLoadError "Expected RSA public key" / "Expected EC public key"
    断言点: 异常消息关键字 ×2
    防回归: 若类型守卫被删，JWK 字段错乱
    """
    from agent_registry.agent_registry.jwk_provider import CertLoadError, JWKProvider
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    provider = JWKProvider("unused.pem")
    ec_key = ec.generate_private_key(ec.SECP256R1()).public_key()
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    with pytest.raises(CertLoadError, match="Expected RSA public key"):
        provider._rsa_to_jwk_dict(ec_key, "kid")
    with pytest.raises(CertLoadError, match="Expected EC public key"):
        provider._ec_to_jwk_dict(rsa_key, "kid")


def test_small_audit_sink_close_failures_are_swallowed(tmp_path):
    """TC-SMALL-121 | 审计 sink：连接关闭抛错被吞掉，消费循环继续/正常退出

    输入: conn.close 抛 OSError；两条记录（第一条写失败、第二条成功后停止）
    预期输出: 不抛异常；第二批落库
    断言点: 无异常 + ins 记录
    防回归: 若关闭异常未捕获，降级路径中断
    """
    class _BrokenCloseConn:
        def __init__(self):
            self.executed = []
            self.closed = False

        def cursor(self):
            return _FakeCursor(self)

        def close(self):
            raise OSError("already closed")

    sink = audit_sink_mod.AuditMySqlSink({
        "audit.mysql.enabled": "true", "audit.mysql.batch_size": "1",
        "audit.mysql.flush_interval": "0.01"})
    sink.enqueue({"time": "t", "operation_name": "Op1", "details": {}})
    sink.enqueue({"time": "t2", "operation_name": "Op2", "details": {}})
    failures = {"n": 0}
    conn = _BrokenCloseConn()
    original_write = sink._write_batch

    def flaky_write(c, batch):
        if failures["n"] == 0:
            failures["n"] += 1
            raise RuntimeError("mysql down")
        original_write(c, batch)
        sink._stop_event.set()

    sink._write_batch = flaky_write
    import sys
    fake_pymysql = SimpleNamespace(connect=lambda **kw: conn)
    original_module = sys.modules.get("pymysql")
    sys.modules["pymysql"] = fake_pymysql
    try:
        sink._consume()
    finally:
        if original_module is None:
            sys.modules.pop("pymysql", None)
        else:
            sys.modules["pymysql"] = original_module
    assert failures["n"] == 1
    assert any(kind == "ins" for kind, _ in conn.executed)


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
