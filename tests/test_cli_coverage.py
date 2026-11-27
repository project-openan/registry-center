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
"""CLI coverage tests: command groups, UDS client and module entry point.

Scope: ``agent_registry/cli/commands/agent.py``, ``agent_registry/cli/commands/tag.py``,
``agent_registry/cli/uds_client.py`` and ``agent_registry/cli/__main__.py``.

Every case calls the real command implementation (argparse parsing included) and
replaces only the UDS dependency with a mock, so the assertion always covers the
observable contract: exit code, stdout/stderr text, exact client call arguments
and the response -> presentation mapping.

Design notes:
- No network, no sleeping, no reliance on execution order.
- ``os.environ`` is not touched; ``sys.modules`` manipulation is scoped with
  ``monkeypatch`` so it is undone automatically.
- The global CLI registry is snapshotted/restored around the ``__main__`` tests.
"""

import builtins
import importlib
import importlib.util
import json
import socket as socket_module
import sys
from argparse import ArgumentParser
from pathlib import Path
from unittest import mock

import pytest

from agent_registry.cli import CLI

_IS_POSIX = sys.platform != "win32"
_POSIX_ONLY = pytest.mark.skipif(
    not _IS_POSIX,
    reason="UDS(AF_UNIX)/POSIX readline only verifiable on Linux/macOS")
from agent_registry.cli import uds_client as uds_module
from agent_registry.cli.base import BaseCommand
from agent_registry.cli.commands import agent as agent_module
from agent_registry.cli.commands import tag as tag_module
from agent_registry.cli.commands.agent import (
    AgentCommand,
    ApprovalCommand,
    SetTagsCommand,
    UDSGetCommand,
    UDSListCommand,
    format_timestamp,
)
from agent_registry.cli.commands.tag import (
    TagCommand,
    TagCreateCommand,
    TagDeleteCommand,
    TagGetCommand,
    TagListCommand,
    TagUpdateCommand,
)
from agent_registry.cli.uds_client import UDSClient, get_uds_client


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _parse_args(command, argv):
    """Build a Namespace exactly the way the framework parser does."""
    parser = ArgumentParser(prog=command.name, add_help=False)
    command.add_arguments(parser)
    return parser.parse_args(argv)


def _install_client(monkeypatch, module, response=None):
    """Replace the module-level UDS client factory with a mock."""
    client = mock.Mock()
    if response is not None:
        for method_name in (
            "create_tag", "get_tag", "update_tag", "delete_tag", "list_tags",
            "approval_agent", "get_agent", "list_agents", "set_tags",
        ):
            getattr(client, method_name).return_value = response
    monkeypatch.setattr(module, "get_uds_client", lambda: client)
    return client


@pytest.fixture
def registry_snapshot():
    """Snapshot and restore the process-wide command registry."""
    saved = dict(CLI._registry._commands)
    try:
        yield saved
    finally:
        CLI._registry._commands.clear()
        CLI._registry._commands.update(saved)


# --------------------------------------------------------------------------- #
# tag command group + tag create
# --------------------------------------------------------------------------- #

def test_tag_group_exposes_exact_subcommand_set():
    """TC-CLI-001 | tag 命令组只暴露五个标签管理子命令

    输入: TagCommand() 实例
    预期输出: name == "tag"；subcommands 的键恰好为 create/get/update/delete/list；
              每个值都是 BaseCommand 子类实例且 name 与键一致；execute 返回 0
    断言点: name 字符串、子命令键集合、子命令实例类型与自身 name、execute 返回值
    防回归: 若删掉/改名任一子命令，或 execute 返回非 0，本用例失败
    """
    group = TagCommand()

    assert group.name == "tag"
    assert group.help_text == "Tag entity management via UDS interface"
    subs = group.subcommands
    assert set(subs) == {"create", "get", "update", "delete", "list"}
    for key, sub in subs.items():
        assert isinstance(sub, BaseCommand)
        assert sub.name == key
    assert group.execute(_parse_args(TagCreateCommand(), ["--name", "x"])) == 0


def test_tag_create_text_success_prints_id_and_name(monkeypatch, capsys):
    """TC-CLI-002 | tag create 成功（text）打印标签 ID 与名称

    输入: --name color；UDS 返回 {"success": True, "data": {"tag_id": "t-1", "name": "color"}}
    预期输出: 退出码 0；stdout 含 "[OK] Tag created successfully"、"Tag ID: t-1"、"Tag Name: color"
    断言点: 退出码 + stdout 关键字 + create_tag 入参精确等于 "color"
    防回归: 若成功分支不打印 ID/名称、或把 name 传错，本用例失败
    """
    client = _install_client(
        monkeypatch, tag_module,
        {"success": True, "data": {"tag_id": "t-1", "name": "color"}},
    )
    command = TagCreateCommand()
    args = _parse_args(command, ["--name", "color"])

    assert command.execute(args) == 0

    out = capsys.readouterr().out
    assert "[OK] Tag created successfully" in out
    assert "Tag ID: t-1" in out
    assert "Tag Name: color" in out
    client.create_tag.assert_called_once_with("color")


def test_tag_create_json_success_emits_parsable_json(monkeypatch, capsys):
    """TC-CLI-003 | tag create 成功（json）原样输出可解析的响应

    输入: --name color --format json；UDS 返回带 tag_id/name 的响应
    预期输出: 退出码 0；stdout 为缩进 JSON，内容与响应完全一致
    断言点: json.loads(stdout) == 响应对象
    防回归: 若 JSON 分支打印格式化文案而非原始响应，解析失败
    """
    response = {"success": True, "data": {"tag_id": "t-1", "name": "color"}}
    _install_client(monkeypatch, tag_module, response)
    command = TagCreateCommand()
    args = _parse_args(command, ["--name", "color", "--format", "json"])

    assert command.execute(args) == 0

    assert json.loads(capsys.readouterr().out) == response


def test_tag_create_text_failure_reports_error_and_message(monkeypatch, capsys):
    """TC-CLI-004 | tag create 失败（text）把 error 写 stderr、message 写 stdout

    输入: UDS 返回 {"success": False, "error": "Duplicate tag", "message": "tag exists"}
    预期输出: 退出码 1；stderr 含 "[ERROR] Duplicate tag"；stdout 含 "Message: tag exists"
    断言点: 退出码 + stderr 关键字 + stdout message 行
    防回归: 若失败分支返回 0 或丢弃 message，本用例失败
    """
    _install_client(
        monkeypatch, tag_module,
        {"success": False, "error": "Duplicate tag", "message": "tag exists"},
    )
    command = TagCreateCommand()

    assert command.execute(_parse_args(command, ["--name", "color"])) == 1

    captured = capsys.readouterr()
    assert "[ERROR] Duplicate tag" in captured.err
    assert "Message: tag exists" in captured.out


def test_tag_create_json_failure_returns_one_and_keeps_json_contract(monkeypatch, capsys):
    """TC-CLI-005 | tag create 失败（json）仍输出原始 JSON 且退出码为 1

    输入: --format json；UDS 返回 {"success": False, "error": "boom"}
    预期输出: 退出码 1；stdout 的 JSON 与响应一致；stderr 为空
    断言点: 退出码 + json 内容 + stderr 为空
    防回归: 若 json 分支忽略 success 恒返回 0，本用例失败
    """
    response = {"success": False, "error": "boom"}
    _install_client(monkeypatch, tag_module, response)
    command = TagCreateCommand()

    assert command.execute(_parse_args(command, ["--name", "color", "--format", "json"])) == 1

    captured = capsys.readouterr()
    assert json.loads(captured.out) == response
    assert captured.err == ""


def test_tag_create_requires_name_and_rejects_unknown_format():
    """TC-CLI-006 | tag create 参数校验：--name 必填、--format 取值受限

    输入: 空参数；以及 --name x --format yaml
    预期输出: 两种输入都由 argparse 拒绝，SystemExit 退出码为 2；不会调用 UDS
    断言点: SystemExit.code == 2（两次）+ 参数未进入 execute
    防回归: 若把 --name 改成可选或放宽 choices，本用例直接报错
    """
    command = TagCreateCommand()

    with pytest.raises(SystemExit) as missing:
        _parse_args(command, [])
    assert missing.value.code == 2

    with pytest.raises(SystemExit) as bad_format:
        _parse_args(command, ["--name", "x", "--format", "yaml"])
    assert bad_format.value.code == 2


# --------------------------------------------------------------------------- #
# tag get / update / delete / list
# --------------------------------------------------------------------------- #

def test_tag_get_without_id_or_name_short_circuits(monkeypatch, capsys):
    """TC-CLI-007 | tag get 缺少 --id/--name 时直接失败且不访问 UDS

    输入: 空参数（两个可选定位参数都缺省）
    预期输出: 退出码 1；stderr 含 "Must provide either --id or --name"；UDS 未被调用
    断言点: 退出码 + stderr 关键字 + client.get_tag.assert_not_called()
    防回归: 若删掉前置校验，代码会带 tag_id=None/name=None 调用服务端，本用例失败
    """
    client = _install_client(monkeypatch, tag_module, {"success": True, "data": {}})
    command = TagGetCommand()

    assert command.execute(_parse_args(command, [])) == 1

    assert "Must provide either --id or --name" in capsys.readouterr().err
    client.get_tag.assert_not_called()


def test_tag_get_by_id_text_success(monkeypatch, capsys):
    """TC-CLI-008 | tag get 按 ID 查询成功时打印四个字段

    输入: --id t-9；UDS 返回 tag_id/name/created_at/updated_at
    预期输出: 退出码 0；stdout 依次含 Tag ID/Name/Created/Updated 及对应值
    断言点: 退出码 + 四个关键字 + get_tag(tag_id="t-9", name=None) 精确入参
    防回归: 若把 --id 传到 name 参数或漏打印时间字段，本用例失败
    """
    client = _install_client(
        monkeypatch, tag_module,
        {"success": True, "data": {
            "tag_id": "t-9", "name": "env",
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-02T00:00:00",
        }},
    )
    command = TagGetCommand()

    assert command.execute(_parse_args(command, ["--id", "t-9"])) == 0

    out = capsys.readouterr().out
    assert "Tag ID: t-9" in out
    assert "Tag Name: env" in out
    assert "Created: 2026-01-01T00:00:00" in out
    assert "Updated: 2026-01-02T00:00:00" in out
    client.get_tag.assert_called_once_with(tag_id="t-9", name=None)


def test_tag_get_json_success_returns_payload(monkeypatch, capsys):
    """TC-CLI-009 | tag get（json）输出原始响应

    输入: --name env --format json；UDS 返回 success=True 的 data
    预期输出: 退出码 0；stdout JSON 与响应一致
    断言点: json.loads(stdout) == 响应
    防回归: 若 json 分支被改成打印文本，解析失败
    """
    response = {"success": True, "data": {"tag_id": "t-2", "name": "env"}}
    _install_client(monkeypatch, tag_module, response)
    command = TagGetCommand()

    assert command.execute(_parse_args(command, ["--name", "env", "--format", "json"])) == 0
    assert json.loads(capsys.readouterr().out) == response


def test_tag_get_text_failure_and_json_failure_exit_codes(monkeypatch, capsys):
    """TC-CLI-010 | tag get 失败分支：text 打印错误、json 返回非 0

    输入: text 模式响应 {"success": False, "error": "Not found", "message": "no tag 5"}；
          json 模式同一响应
    预期输出: text 退出码 1、stderr 含 "[ERROR] Not found"、stdout 含 "Message: no tag 5"；
              json 退出码 1 且 stdout 为原响应
    断言点: 两个退出码 + 两段输出内容
    防回归: 若失败分支被改成恒 0 或丢掉 message，本用例失败
    """
    _install_client(
        monkeypatch, tag_module,
        {"success": False, "error": "Not found", "message": "no tag 5"},
    )
    command = TagGetCommand()

    assert command.execute(_parse_args(command, ["--id", "5"])) == 1
    captured = capsys.readouterr()
    assert "[ERROR] Not found" in captured.err
    assert "Message: no tag 5" in captured.out

    assert command.execute(_parse_args(command, ["--id", "5", "--format", "json"])) == 1
    assert json.loads(capsys.readouterr().out) == {
        "success": False, "error": "Not found", "message": "no tag 5",
    }


def test_tag_update_text_success_uses_new_name(monkeypatch, capsys):
    """TC-CLI-011 | tag update 成功时按入参更新并打印新名称

    输入: --id t-3 --name newname；UDS 返回 {"tag_id": "t-3", "name": "newname"}
    预期输出: 退出码 0；stdout 含 "[OK] Tag updated successfully"、"Tag ID: t-3"、"New Name: newname"
    断言点: 退出码 + stdout 关键字 + update_tag("t-3", "newname") 精确入参
    防回归: 若 update_tag 入参顺序颠倒（id/name 互换），断言失败
    """
    client = _install_client(
        monkeypatch, tag_module,
        {"success": True, "data": {"tag_id": "t-3", "name": "newname"}},
    )
    command = TagUpdateCommand()

    assert command.execute(_parse_args(command, ["--id", "t-3", "--name", "newname"])) == 0

    out = capsys.readouterr().out
    assert "[OK] Tag updated successfully" in out
    assert "Tag ID: t-3" in out
    assert "New Name: newname" in out
    client.update_tag.assert_called_once_with("t-3", "newname")


def test_tag_update_failure_text_and_json(monkeypatch, capsys):
    """TC-CLI-012 | tag update 失败：text 报错、json 保真并返回 1

    输入: 响应 {"success": False, "error": "Conflict", "message": "name taken"}（text/json 各一次）
    预期输出: text 退出码 1 且 stderr 含 "[ERROR] Conflict"、stdout 含 message；
              json 退出码 1 且 stdout 与响应一致
    断言点: 退出码 + 输出内容 + json 解析结果
    防回归: 若失败分支被吞掉（返回 0），本用例失败
    """
    response = {"success": False, "error": "Conflict", "message": "name taken"}
    _install_client(monkeypatch, tag_module, response)
    command = TagUpdateCommand()

    assert command.execute(_parse_args(command, ["--id", "1", "--name", "x"])) == 1
    captured = capsys.readouterr()
    assert "[ERROR] Conflict" in captured.err
    assert "Message: name taken" in captured.out

    assert command.execute(
        _parse_args(command, ["--id", "1", "--name", "x", "--format", "json"])
    ) == 1
    assert json.loads(capsys.readouterr().out) == response


def test_tag_delete_success_and_failure_paths(monkeypatch, capsys):
    """TC-CLI-013 | tag delete 成功/失败与 json 分支

    输入: 第一次成功响应 {"success": True}；第二次失败响应带 error/message；第三次 json 失败
    预期输出: 成功退出码 0 且 stdout 含 "[OK] Tag deleted successfully"；
              失败退出码 1 且 stderr 含 "[ERROR] Delete failed"、stdout 含 "Message: in use"
    断言点: 三个退出码 + 输出关键字 + delete_tag 入参精确为 "t-4"
    防回归: 若删除失败被当成成功，或 delete_tag 参数错位，本用例失败
    """
    client = _install_client(monkeypatch, tag_module, {"success": True})
    command = TagDeleteCommand()

    assert command.execute(_parse_args(command, ["--id", "t-4"])) == 0
    assert "[OK] Tag deleted successfully" in capsys.readouterr().out
    client.delete_tag.assert_called_once_with("t-4")

    client.delete_tag.return_value = {
        "success": False, "error": "Delete failed", "message": "in use",
    }
    assert command.execute(_parse_args(command, ["--id", "t-4"])) == 1
    captured = capsys.readouterr()
    assert "[ERROR] Delete failed" in captured.err
    assert "Message: in use" in captured.out

    assert command.execute(_parse_args(command, ["--id", "t-4", "--format", "json"])) == 1
    assert json.loads(capsys.readouterr().out) == {
        "success": False, "error": "Delete failed", "message": "in use",
    }


def test_tag_list_text_truncates_timestamp_and_prints_count(monkeypatch, capsys):
    """TC-CLI-014 | tag list 列表：数量、ID/名称、时间截断到 19 字符

    输入: UDS 返回 count=2，两条标签，其中一条 created_at 带微秒，另一条 created_at 为空
    预期输出: 退出码 0；stdout 含 "Found 2 tags:"、"t-1: env (created: 2026-05-07T08:11:36)"，
              空时间显示 "(created: unknown)"
    断言点: 退出码 + 行内容（含精确截断结果）+ list_tags 调用一次
    防回归: 若时间未截断（带 .193309）或空值分支丢失，本用例失败
    """
    client = _install_client(monkeypatch, tag_module, {
        "success": True,
        "data": {
            "count": 2,
            "tags": [
                {"tag_id": "t-1", "name": "env", "created_at": "2026-05-07T08:11:36.193309"},
                {"tag_id": "t-2", "name": "team", "created_at": ""},
            ],
        },
    })
    command = TagListCommand()

    assert command.execute(_parse_args(command, [])) == 0

    out = capsys.readouterr().out
    assert "Found 2 tags:" in out
    assert "  t-1: env (created: 2026-05-07T08:11:36)" in out
    assert "  t-2: team (created: unknown)" in out
    client.list_tags.assert_called_once_with()


def test_tag_list_empty_and_json_and_failure(monkeypatch, capsys):
    """TC-CLI-015 | tag list 空列表 / json / 失败三分支

    输入: 空 tags；json 模式空 tags；失败响应
    预期输出: 空列表 stdout 含 "No tags found" 且退出码 0；
              json 退出码 0 且 stdout 与响应一致；失败退出码 1 且 stderr 含 "[ERROR] List failed"
    断言点: 三个退出码 + 三类输出内容
    防回归: 若空列表被当成错误退出 1，或失败分支返回 0，本用例失败
    """
    client = _install_client(monkeypatch, tag_module, {
        "success": True, "data": {"count": 0, "tags": []},
    })
    command = TagListCommand()

    assert command.execute(_parse_args(command, [])) == 0
    assert "No tags found" in capsys.readouterr().out

    assert command.execute(_parse_args(command, ["--format", "json"])) == 0
    assert json.loads(capsys.readouterr().out) == {
        "success": True, "data": {"count": 0, "tags": []},
    }

    client.list_tags.return_value = {"success": False, "error": "List failed", "message": "db down"}
    assert command.execute(_parse_args(command, [])) == 1
    captured = capsys.readouterr()
    assert "[ERROR] List failed" in captured.err
    assert "Message: db down" in captured.out


# --------------------------------------------------------------------------- #
# agent command group
# --------------------------------------------------------------------------- #

def test_agent_group_exposes_exact_subcommand_set():
    """TC-CLI-016 | agent 命令组暴露 approval/list/get/set-tags 四个子命令

    输入: AgentCommand() 实例
    预期输出: name == "agent"；子命令键集合精确匹配；execute 返回 0
    断言点: name + 键集合 + 每个子命令 name + execute 返回值
    防回归: 若子命令被改名/删除（例如 set-tags -> set_tags），本用例失败
    """
    group = AgentCommand()

    assert group.name == "agent"
    assert group.help_text == "Agent management commands via internal UDS service"
    subs = group.subcommands
    assert set(subs) == {"approval", "list", "get", "set-tags"}
    for key, sub in subs.items():
        assert sub.name == key
    assert group.execute(None) == 0


@pytest.mark.parametrize("raw, expected", [
    ("", "N/A"),
    ("N/A", "N/A"),
    ("2026-05-07T08:11:36.193309", "2026-05-07T08:11:36"),
    ("2026-05-07T08:11:36Z", "2026-05-07T08:11:36"),
    ("2026-05-07T08:11:36", "2026-05-07T08:11:36"),
])
def test_format_timestamp_normalises_values(raw, expected):
    """TC-CLI-017 | format_timestamp 归一化：空值、微秒、尾部 Z

    输入: ""、"N/A"、带微秒、带尾部 Z、标准格式共五种
    预期输出: 空值/N/A 返回 "N/A"；带微秒截到秒；尾部 Z 被去掉；标准格式原样返回
    断言点: 每个输入的精确返回值
    防回归: 若去掉微秒截断或把 N/A 变成 "N/A.N/A"，用例失败
    """
    assert format_timestamp(raw) == expected


def test_agent_get_text_success_flattens_and_renders_agentcard(monkeypatch, capsys):
    """TC-CLI-018 | agent get（text）展平字段并以独立段落渲染 agentcard

    输入: --agent-name agent1 --org org1；UDS data 含 status/tag/created_at 与 agentcard
    预期输出: 退出码 0；stdout 含 "Agent Name"、"agent1"、"Tags" 行的 "blue, green"、
              "Agent Card:" 段落以及 agentcard 的 JSON（"name": "agent1"），
              updated_at 缺省显示 "N/A"
    断言点: 退出码 + 各字段文本 + agentcard JSON 片段 + get_agent 精确入参
    防回归: 若 tags 未用 ", " 连接、agentcard 被塞进表格截断、或时间未格式化，本用例失败
    """
    client = _install_client(monkeypatch, agent_module, {
        "success": True,
        "data": {
            "status": "published",
            "tag": ["blue", "green"],
            "created_at": "2026-05-07T08:11:36.193309",
            "agentcard": {"name": "agent1", "skills": []},
        },
    })
    command = UDSGetCommand()

    assert command.execute(
        _parse_args(command, ["--agent-name", "agent1", "--org", "org1"])
    ) == 0

    out = capsys.readouterr().out
    assert "Agent Name" in out
    assert "agent1" in out
    assert "blue, green" in out
    assert "2026-05-07T08:11:36" in out
    assert "N/A" in out
    assert "Agent Card:" in out
    assert '"name": "agent1"' in out
    client.get_agent.assert_called_once_with("agent1", "org1")


def test_agent_get_text_failure_and_json_modes(monkeypatch, capsys):
    """TC-CLI-019 | agent get 失败分支与 json 分支

    输入: text 模式响应 {"success": False, "error": "Agent not found", "message": "42"}；
          json 模式同一响应
    预期输出: text 退出码 1、stderr 含 "[ERROR] Agent not found"、stdout 含 "Message: 42"；
              json 退出码 1 且 stdout JSON 与响应一致
    断言点: 退出码 + 文本关键字 + json 解析结果
    防回归: 若失败被当成功（退出 0）或 message 丢失，本用例失败
    """
    response = {"success": False, "error": "Agent not found", "message": "42"}
    _install_client(monkeypatch, agent_module, response)
    command = UDSGetCommand()

    args = _parse_args(command, ["-n", "missing", "-o", "org1"])
    assert command.execute(args) == 1
    captured = capsys.readouterr()
    assert "[ERROR] Agent not found" in captured.err
    assert "Message: 42" in captured.out

    args = _parse_args(command, ["-n", "missing", "-o", "org1", "-f", "json"])
    assert command.execute(args) == 1
    assert json.loads(capsys.readouterr().out) == response


def test_agent_get_defaults_status_and_empty_tags(monkeypatch, capsys):
    """TC-CLI-020 | agent get 对缺失字段使用默认值

    输入: UDS 成功但 data 为空字典
    预期输出: 退出码 0；stdout 状态显示 "published"；Tags 行为空；时间显示 "N/A"
    断言点: 退出码 + "published" + 不含 "None" + 出现两个 "N/A"
    防回归: 若默认状态被改成空字符串或 None 泄漏到输出，本用例失败
    """
    _install_client(monkeypatch, agent_module, {"success": True, "data": {}})
    command = UDSGetCommand()

    assert command.execute(_parse_args(command, ["-n", "a", "-o", "o"])) == 0

    out = capsys.readouterr().out
    assert "published" in out
    assert "None" not in out
    assert out.count("N/A") == 2


def test_agent_list_text_renders_title_rows_and_unknown_defaults(monkeypatch, capsys):
    """TC-CLI-021 | agent list（text）输出标题、行数并回退 unknown

    输入: UDS 返回两个 agent，第二个缺少 organization/tag/时间
    预期输出: 退出码 0；stdout 含 "Agents List (2 total)"、两个 agent 名、"unknown" 回退值
    断言点: 退出码 + 标题（含数量）+ 行内容 + list_agents 调用一次
    防回归: 若标题数量算错（例如用 data 长度）或默认值分支丢失，本用例失败
    """
    client = _install_client(monkeypatch, agent_module, {
        "success": True,
        "data": {"agents": [
            {"agent_name": "a1", "organization": "org1", "status": "published",
             "tag": ["x"], "created_at": "2026-01-01T00:00:00.5"},
            {"agent_name": "a2"},
        ]},
    })
    command = UDSListCommand()

    assert command.execute(_parse_args(command, [])) == 0

    out = capsys.readouterr().out
    assert "Agents List (2 total)" in out
    assert "a1" in out
    assert "a2" in out
    assert "unknown" in out
    client.list_agents.assert_called_once_with()


def test_agent_list_empty_and_failure_paths(monkeypatch, capsys):
    """TC-CLI-022 | agent list 空列表与失败分支

    输入: data.agents 为空；随后失败响应 {"success": False, "error": "Query failed"}
    预期输出: 空列表 stdout 含 "No agents found" 且退出码 0；
              失败退出码 1 且 stderr 含 "[ERROR] Query failed"（无 message 时不打印 Message 行）
    断言点: 两个退出码 + 输出内容 + stdout 不含 "Message:"
    防回归: 若空列表走失败退出码、或失败时仍打印 "Message: None"，本用例失败
    """
    _install_client(monkeypatch, agent_module, {"success": True, "data": {"agents": []}})
    command = UDSListCommand()

    assert command.execute(_parse_args(command, [])) == 0
    assert "No agents found" in capsys.readouterr().out

    _install_client(monkeypatch, agent_module, {"success": False, "error": "Query failed"})
    assert command.execute(_parse_args(command, [])) == 1
    captured = capsys.readouterr()
    assert "[ERROR] Query failed" in captured.err
    assert "Message:" not in captured.out


def test_agent_list_json_failure_returns_one(monkeypatch, capsys):
    """TC-CLI-023 | agent list（json）失败时输出原始响应并退出 1

    输入: --format json；响应 {"success": False, "error": "down"}
    预期输出: 退出码 1；stdout JSON 与响应一致
    断言点: 退出码 + json 内容
    防回归: 若 json 分支忽略 success，退出码会变成 0，本用例失败
    """
    response = {"success": False, "error": "down"}
    _install_client(monkeypatch, agent_module, response)
    command = UDSListCommand()

    assert command.execute(_parse_args(command, ["--format", "json"])) == 1
    assert json.loads(capsys.readouterr().out) == response


def test_agent_approval_success_title_and_status(monkeypatch, capsys):
    """TC-CLI-024 | agent approval 成功打印 Approval Result 与 approved=Yes

    输入: --agent-name a1 --org org1；UDS data 含 status="approved"
    预期输出: 退出码 0；stdout 含 "Approval Result"、"a1"、"approved"、"Yes"
    断言点: 退出码 + 关键字 + approval_agent("a1", "org1") 精确入参
    防回归: 若 approved 标记或状态来源被改错（例如恒 published），本用例失败
    """
    client = _install_client(monkeypatch, agent_module, {
        "success": True, "data": {"status": "approved"},
    })
    command = ApprovalCommand()

    assert command.execute(_parse_args(command, ["-n", "a1", "-o", "org1"])) == 0

    out = capsys.readouterr().out
    assert "Approval Result" in out
    assert "a1" in out
    assert "approved" in out
    assert "Yes" in out
    client.approval_agent.assert_called_once_with("a1", "org1")


def test_agent_approval_failure_text_and_json(monkeypatch, capsys):
    """TC-CLI-025 | agent approval 失败分支（text/json）

    输入: 响应 {"success": False, "error": "Approval failed", "message": "disabled"}
    预期输出: text 退出码 1、stderr 含 "[ERROR] Approval failed"、stdout 含 "Message: disabled"；
              json 退出码 1 且 stdout 与响应一致
    断言点: 退出码 + 两段输出内容
    防回归: 若失败分支被简化成恒 0 或丢 message，本用例失败
    """
    response = {"success": False, "error": "Approval failed", "message": "disabled"}
    _install_client(monkeypatch, agent_module, response)
    command = ApprovalCommand()

    assert command.execute(_parse_args(command, ["-n", "a", "-o", "o"])) == 1
    captured = capsys.readouterr()
    assert "[ERROR] Approval failed" in captured.err
    assert "Message: disabled" in captured.out

    assert command.execute(_parse_args(command, ["-n", "a", "-o", "o", "-f", "json"])) == 1
    assert json.loads(capsys.readouterr().out) == response


# --------------------------------------------------------------------------- #
# set-tags
# --------------------------------------------------------------------------- #

def test_agent_set_tags_strips_and_replaces(monkeypatch, capsys):
    """TC-CLI-026 | set-tags 清洗空白后按全量替换提交

    输入: --tags " a , b ,, c "
    预期输出: 退出码 0；stdout 含 "Tags set successfully" 与 "a, b, c"；
              调用 set_tags("a1","org1",["a","b","c"])
    断言点: 退出码 + 输出 + 精确入参（顺序与去空项）
    防回归: 若未 strip/未过滤空项（会传 [" a "," b ",""," c "]），本用例失败
    """
    client = _install_client(monkeypatch, agent_module, {"success": True})
    command = SetTagsCommand()

    assert command.execute(_parse_args(command, ["-n", "a1", "-o", "org1", "-t", " a , b ,, c "])) == 0

    out = capsys.readouterr().out
    assert "Tags set successfully" in out
    assert "a, b, c" in out
    client.set_tags.assert_called_once_with("a1", "org1", ["a", "b", "c"])


def test_agent_set_tags_rejects_empty_list_without_calling_service(monkeypatch, capsys):
    """TC-CLI-027 | set-tags 全空输入被拒绝且不调用服务端

    输入: --tags " , , "
    预期输出: 退出码 1；stderr 含 "No valid tags provided"；UDS 未被调用
    断言点: 退出码 + stderr 关键字 + set_tags.assert_not_called()
    防回归: 若校验被删，会以空列表调用服务端并可能清空标签，本用例失败
    """
    client = _install_client(monkeypatch, agent_module, {"success": True})
    command = SetTagsCommand()

    assert command.execute(_parse_args(command, ["-n", "a", "-o", "o", "-t", " , , "])) == 1

    assert "No valid tags provided" in capsys.readouterr().err
    client.set_tags.assert_not_called()


def test_agent_set_tags_rejects_more_than_ten(monkeypatch, capsys):
    """TC-CLI-028 | set-tags 超过 10 个标签被拒绝且不调用服务端

    输入: 11 个逗号分隔标签
    预期输出: 退出码 1；stderr 含 "Tag limit exceeded: maximum 10 tags allowed, got 11"；
              UDS 未被调用
    断言点: 退出码 + 精确报错文本（含实际数量）+ 未调用
    防回归: 若上限被放宽到 >10 或改用 >=10 判断（10 个也拒绝），本用例失败
    """
    client = _install_client(monkeypatch, agent_module, {"success": True})
    tags = ",".join("t%d" % index for index in range(1, 12))

    assert SetTagsCommand().execute(
        _parse_args(SetTagsCommand(), ["-n", "a", "-o", "o", "-t", tags])
    ) == 1

    assert "Tag limit exceeded: maximum 10 tags allowed, got 11" in capsys.readouterr().err
    client.set_tags.assert_not_called()


def test_agent_set_tags_accepts_exactly_ten(monkeypatch):
    """TC-CLI-029 | set-tags 恰好 10 个标签属于合法边界

    输入: 10 个逗号分隔标签
    预期输出: 退出码 0；set_tags 收到 10 个标签
    断言点: 退出码 + 入参列表长度与内容
    防回归: 若边界写成 >=10 或 >9，本用例失败
    """
    client = _install_client(monkeypatch, agent_module, {"success": True})
    tags = ",".join("t%d" % index for index in range(1, 11))

    assert SetTagsCommand().execute(
        _parse_args(SetTagsCommand(), ["-n", "a", "-o", "o", "-t", tags])
    ) == 0

    expected = ["t%d" % index for index in range(1, 11)]
    client.set_tags.assert_called_once_with("a", "o", expected)


def test_agent_set_tags_json_and_failure_paths(monkeypatch, capsys):
    """TC-CLI-030 | set-tags 的 json 成功/失败与文本失败分支

    输入: json 成功响应；json 失败响应；文本失败响应带 message
    预期输出: json 成功退出码 0 且 stdout 与响应一致；json 失败退出码 1；
              text 失败退出码 1、stderr 含 "[ERROR] Set tags failed"、stdout 含 "Message: denied"
    断言点: 三个退出码 + json 内容 + 文本输出
    防回归: 若 json 分支不看 success、或文本失败丢失 message，本用例失败
    """
    client = _install_client(monkeypatch, agent_module, {"success": True, "data": {}})
    command = SetTagsCommand()
    argv = ["-n", "a", "-o", "o", "-t", "x", "-f", "json"]

    assert command.execute(_parse_args(command, argv)) == 0
    assert json.loads(capsys.readouterr().out) == {"success": True, "data": {}}

    client.set_tags.return_value = {"success": False, "error": "Set tags failed", "message": "denied"}
    assert command.execute(_parse_args(command, argv)) == 1
    assert json.loads(capsys.readouterr().out) == {
        "success": False, "error": "Set tags failed", "message": "denied",
    }

    assert command.execute(_parse_args(command, ["-n", "a", "-o", "o", "-t", "x"])) == 1
    captured = capsys.readouterr()
    assert "[ERROR] Set tags failed" in captured.err
    assert "Message: denied" in captured.out


# --------------------------------------------------------------------------- #
# UDSClient
# --------------------------------------------------------------------------- #

def _socket_factory(monkeypatch, recv_chunks=None, connect_error=None, send_error=None):
    """Install a fake socket module factory and return (factory, socket_instance)."""
    sock = mock.Mock()
    sock.recv.side_effect = list(recv_chunks or [])
    if connect_error is not None:
        sock.connect.side_effect = connect_error
    if send_error is not None:
        sock.sendall.side_effect = send_error
    factory = mock.Mock(return_value=sock)
    monkeypatch.setattr(uds_module.socket, "socket", factory)
    return factory, sock


@_POSIX_ONLY
def test_uds_send_request_wire_protocol(monkeypatch):
    """TC-CLI-031 | UDS 请求的建连参数、超时、线格式与返回解析

    输入: action="get_agent"，params={"agent_name": "a1"}；服务端一次返回完整 JSON
    预期输出: socket(AF_UNIX, SOCK_STREAM)、settimeout(10)、connect(默认 socket 路径)、
              sendall 内容为 {"action":..., "params":...} 的 UTF-8 JSON；
              返回值等于响应字典；socket 被关闭
    断言点: 五处调用参数 + 发送字节精确内容 + 返回值 + close 调用一次
    防回归: 若改协议字段名（action/params）、改超时、或忘关 socket，本用例失败
    """
    response = {"success": True, "data": {"status": "published"}}
    factory, sock = _socket_factory(monkeypatch, recv_chunks=[json.dumps(response).encode()])
    client = UDSClient()

    result = client.send_request("get_agent", {"agent_name": "a1"})

    factory.assert_called_once_with(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    sock.settimeout.assert_called_once_with(10)
    sock.connect.assert_called_once_with("run/registry-center/internal.sock")
    payload = sock.sendall.call_args.args[0]
    assert json.loads(payload.decode("utf-8")) == {
        "action": "get_agent", "params": {"agent_name": "a1"},
    }
    assert result == response
    assert sock.close.call_count == 1


@_POSIX_ONLY
def test_uds_send_request_custom_socket_path(monkeypatch):
    """TC-CLI-032 | 构造参数可覆盖默认 socket 路径并用于 connect

    输入: UDSClient(socket_path="/tmp/x.sock")，connect 抛 FileNotFoundError
    预期输出: 返回 {"success": False, "error": "Socket not found"}，
              message 含 "/tmp/x.sock"
    断言点: connect 调用路径 + 错误码 + message 中的路径
    防回归: 若忽略构造参数总是用默认路径，本用例失败
    """
    _, sock = _socket_factory(monkeypatch, connect_error=FileNotFoundError())

    result = UDSClient("/tmp/x.sock").send_request("list_agents", {})

    sock.connect.assert_called_once_with("/tmp/x.sock")
    assert result["success"] is False
    assert result["error"] == "Socket not found"
    assert "/tmp/x.sock" in result["message"]


@_POSIX_ONLY
def test_uds_connect_error_mapping(monkeypatch):
    """TC-CLI-033 | connect 异常到错误码/文案的映射

    输入: PermissionError、ConnectionRefusedError 两种 connect 异常
    预期输出: 分别返回 {"error": "Permission denied"} 与 {"error": "Connection refused"}，
              message 与产品文案完全一致
    断言点: success 为 False + error 精确值 + message 精确值
    防回归: 若两种异常被合并成同一文案，或错误码拼写改变，本用例失败
    """
    _socket_factory(monkeypatch, connect_error=PermissionError())
    denied = UDSClient().send_request("x", {})
    assert denied == {
        "success": False,
        "error": "Permission denied",
        "message": "You don't have permission to access registry center",
    }

    _socket_factory(monkeypatch, connect_error=ConnectionRefusedError())
    refused = UDSClient().send_request("x", {})
    assert refused == {
        "success": False,
        "error": "Connection refused",
        "message": "Internal service is not accepting connections",
    }


@_POSIX_ONLY
def test_uds_invalid_response_is_reported_with_reason(monkeypatch):
    """TC-CLI-034 | 非 JSON 响应返回 Invalid response 且携带解析器消息

    输入: recv 返回 b'not-json' 后返回 b''（连接关闭）
    预期输出: {"success": False, "error": "Invalid response"}，message 以 "Expecting value" 开头
    断言点: error 精确值 + message 前缀 + socket 已关闭
    防回归: 若解析失败被静默吞掉返回 success=True，本用例失败
    """
    _, sock = _socket_factory(monkeypatch, recv_chunks=[b"not-json", b""])

    result = UDSClient().send_request("x", {})

    assert result["success"] is False
    assert result["error"] == "Invalid response"
    assert result["message"].startswith("Expecting value")
    assert sock.close.call_count == 1


@_POSIX_ONLY
def test_uds_empty_response_is_invalid(monkeypatch):
    """TC-CLI-035 | 服务端立即关闭（空响应）被判为 Invalid response

    输入: recv 第一次就返回 b''
    预期输出: error == "Invalid response"；success 为 False
    断言点: error 值 + success 值
    防回归: 若空响应被当作成功（返回 {}），本用例失败
    """
    _socket_factory(monkeypatch, recv_chunks=[b""])

    result = UDSClient().send_request("x", {})

    assert result["success"] is False
    assert result["error"] == "Invalid response"


@_POSIX_ONLY
def test_uds_accumulates_chunks_until_json_complete(monkeypatch):
    """TC-CLI-036 | 分片响应被拼接后才解析

    输入: 两个分片 b'{"success": tr' 与 b'ue, "data": {"x": 1}}'
    预期输出: 返回 {"success": True, "data": {"x": 1}}
    断言点: 返回值精确相等（证明跨分片拼接生效）
    防回归: 若只解析首个分片就 break，会返回 Invalid response，本用例失败
    """
    _socket_factory(
        monkeypatch,
        recv_chunks=[b'{"success": tr', b'ue, "data": {"x": 1}}'],
    )

    assert UDSClient().send_request("x", {}) == {"success": True, "data": {"x": 1}}


@_POSIX_ONLY
def test_uds_send_failure_maps_to_communication_error(monkeypatch):
    """TC-CLI-037 | 发送阶段异常映射为 Communication error 并关闭 socket

    输入: sendall 抛 OSError("send failed")
    预期输出: {"success": False, "error": "Communication error", "message": "send failed"}
    断言点: 三个字段精确值 + close 调用一次
    防回归: 若异常未捕获导致命令栈崩溃，或 socket 未关闭，本用例失败
    """
    _, sock = _socket_factory(monkeypatch, send_error=OSError("send failed"))

    result = UDSClient().send_request("x", {})

    assert result == {
        "success": False,
        "error": "Communication error",
        "message": "send failed",
    }
    assert sock.close.call_count == 1


def test_uds_windows_platform_returns_error_without_touching_socket(monkeypatch):
    """TC-CLI-038 | Windows 平台直接返回 Platform not supported，不触碰 socket

    输入: client.is_windows = True（模拟 IS_WINDOWS 平台判定）
    预期输出: {"success": False, "error": "Platform not supported"}，
              message 含 "Windows environment is not supported"
    断言点: 错误码 + message 关键字 + socket 工厂未被调用
    防回归: 若去掉平台护栏，Windows 上会尝试 AF_UNIX 并抛异常，本用例失败
    """
    factory = mock.Mock()
    monkeypatch.setattr(uds_module.socket, "socket", factory)
    client = UDSClient()
    client.is_windows = True

    result = client.send_request("list_agents", {})

    assert result["success"] is False
    assert result["error"] == "Platform not supported"
    assert "Windows environment is not supported" in result["message"]
    factory.assert_not_called()


def test_get_uds_client_is_cached_with_default_path(monkeypatch):
    """TC-CLI-039 | get_uds_client 返回同一单例并使用默认 socket 路径

    输入: 首次调用两次 get_uds_client()
    预期输出: 两次返回同一对象；socket_path 为 run/registry-center/internal.sock；is_windows 与平台一致
    断言点: 对象身份同一 + 路径字符串 + is_windows 与 uds_module.IS_WINDOWS 相等
    防回归: 若每次新建实例（缓存失效）或默认路径改变，本用例失败
    """
    monkeypatch.setattr(uds_module, "_client", None)

    first = get_uds_client()
    second = get_uds_client()

    assert first is second
    assert first.socket_path == "run/registry-center/internal.sock"
    assert first.is_windows == uds_module.IS_WINDOWS


def test_get_uds_client_windows_branch_sets_flag(monkeypatch):
    """TC-CLI-040 | IS_WINDOWS 为真时单例标记 is_windows 并记录错误日志

    输入: monkeypatch uds_module.IS_WINDOWS = True，缓存清空后取客户端
    预期输出: 新实例 is_windows 为 True；logger.error 被调用一次且文案含 Windows
    断言点: is_windows 值 + 日志调用次数 + 日志文案关键字
    防回归: 若平台标志未从 IS_WINDOWS 读取，Windows 会误走 AF_UNIX 分支，本用例失败
    """
    monkeypatch.setattr(uds_module, "_client", None)
    monkeypatch.setattr(uds_module, "IS_WINDOWS", True)
    error_log = mock.Mock()
    monkeypatch.setattr(uds_module.logger, "error", error_log)

    client = get_uds_client()

    assert client.is_windows is True
    error_log.assert_called_once()
    assert "Windows environment is not supported" in error_log.call_args.args[0]


@pytest.mark.parametrize("method, call_args, expected_action, expected_params", [
    ("approval_agent", ("a1", "org1"), "approval",
     {"agent_name": "a1", "organization": "org1"}),
    ("get_agent", ("a1", "org1"), "get_agent",
     {"agent_name": "a1", "organization": "org1"}),
    ("list_agents", (), "list_agents", {}),
    ("set_tags", ("a1", "org1", ["x"]), "set_tag",
     {"agent_name": "a1", "organization": "org1", "tags": ["x"]}),
    ("create_tag", ("env",), "create_tag", {"name": "env"}),
    ("update_tag", ("t-1", "new"), "update_tag", {"tag_id": "t-1", "name": "new"}),
    ("delete_tag", ("t-1",), "delete_tag", {"tag_id": "t-1"}),
    ("list_tags", (), "list_tags", {}),
])
def test_uds_convenience_methods_map_to_wire_actions(
    monkeypatch, method, call_args, expected_action, expected_params
):
    """TC-CLI-041 | UDSClient 便捷方法到 action/params 的映射

    输入: 依次调用 approval_agent/get_agent/list_agents/set_tags/create_tag/update_tag/
          delete_tag/list_tags
    预期输出: 每个方法调用 send_request(预期 action, 预期 params)，并原样返回其返回值
    断言点: send_request 的入参精确值 + 方法返回值是 send_request 的返回值
    防回归: 若任一 action 名称或参数键改动（例如 set_tag -> set_tags），对应用例失败
    """
    client = UDSClient()
    sentinel = {"success": True, "data": expected_action}
    monkeypatch.setattr(client, "send_request", mock.Mock(return_value=sentinel))

    result = getattr(client, method)(*call_args)

    client.send_request.assert_called_once_with(expected_action, expected_params)
    assert result is sentinel


@pytest.mark.parametrize("kwargs, expected_params", [
    ({"tag_id": "t-1"}, {"tag_id": "t-1"}),
    ({"name": "env"}, {"name": "env"}),
    ({"tag_id": "t-1", "name": "env"}, {"tag_id": "t-1"}),
    ({}, {}),
])
def test_uds_get_tag_parameter_precedence(monkeypatch, kwargs, expected_params):
    """TC-CLI-042 | get_tag 的参数优先级：tag_id 优先于 name，可都为空

    输入: 四种组合（仅 id / 仅 name / 同时给 / 都不给）
    预期输出: params 分别为 {"tag_id"}、{"name"}、{"tag_id"}（id 优先）、{}
    断言点: send_request("get_tag", 精确 params)
    防回归: 若把 elif 改成 if（两者都传）或调换优先级，对应用例失败
    """
    client = UDSClient()
    monkeypatch.setattr(client, "send_request", mock.Mock(return_value={"success": True}))

    client.get_tag(**kwargs)

    client.send_request.assert_called_once_with("get_tag", expected_params)


@_POSIX_ONLY
def test_uds_socket_is_closed_when_connect_fails(monkeypatch):
    """TC-CLI-043 | connect 失败时必须关闭 socket（不泄漏 fd）

    输入: connect 抛 FileNotFoundError
    预期输出: 返回错误字典的同时调用 client_socket.close() 恰好一次
    断言点: 返回值 + close 调用次数 == 1
    防回归: 若失败分支又改成直接 return，close 次数变 0，本用例失败
    历史: 修复前 socket 只在第二个 try/finally 里关闭，connect 失败会泄漏 fd
    """
    _, sock = _socket_factory(monkeypatch, connect_error=FileNotFoundError())

    UDSClient().send_request("x", {})

    assert sock.close.call_count == 1


@_POSIX_ONLY
def test_uds_unexpected_connect_os_error_is_reported_and_closed(monkeypatch):
    """TC-CLI-053 | connect 抛其他 OSError 时同样返回错误字典并关闭 socket

    输入: connect 抛 OSError("network down")
    预期输出: {"success": False, "error": "Connection failed", "message": "network down"}
    断言点: 返回字典三个字段精确值 + close 调用一次
    防回归: 若缺少兜底 OSError 分支，异常会冒给调用方且 fd 泄漏
    """
    _, sock = _socket_factory(monkeypatch, connect_error=OSError("network down"))

    result = UDSClient().send_request("x", {})

    assert result == {
        "success": False,
        "error": "Connection failed",
        "message": "network down",
    }
    assert sock.close.call_count == 1


# --------------------------------------------------------------------------- #
# __main__ module
# --------------------------------------------------------------------------- #

MAIN_MODULE_PATH = Path(agent_module.__file__).parent.parent / "__main__.py"


def _load_main_probe(monkeypatch, module_name, platform_name):
    """Execute cli/__main__.py under a throwaway name and a forced platform."""
    import platform as platform_module

    monkeypatch.setattr(platform_module, "system", lambda: platform_name)
    spec = importlib.util.spec_from_file_location(module_name, MAIN_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_auto_discovery_imports_all_command_modules(monkeypatch, registry_snapshot):
    """TC-CLI-044 | __main__ 自动发现会导入 commands 下全部非下划线模块并注册命令

    输入: 清空全局注册表并从 sys.modules 移除 agent/tag 命令模块后调用
          _auto_discover_commands()
    预期输出: 重新导入 agent_registry.cli.commands.agent 与 .tag，
              全局注册表出现 "agent" 与 "tag" 两个一级命令
    断言点: sys.modules 中含两个命令模块 + registry.has("agent")/has("tag") 为真
    防回归: 若发现逻辑过滤掉模块（例如只扫 __init__）或漏掉注册，本用例失败
    """
    main_module = importlib.import_module("agent_registry.cli.__main__")
    monkeypatch.delitem(sys.modules, "agent_registry.cli.commands.agent", raising=False)
    monkeypatch.delitem(sys.modules, "agent_registry.cli.commands.tag", raising=False)
    CLI._registry.clear()

    main_module._auto_discover_commands()

    assert "agent_registry.cli.commands.agent" in sys.modules
    assert "agent_registry.cli.commands.tag" in sys.modules
    assert CLI.get_registry().has("agent") is True
    assert CLI.get_registry().has("tag") is True
    assert CLI.get_registry().get_command_names().count("agent") == 1


def test_main_auto_discovery_skips_dunder_files_and_swallows_import_error(
    monkeypatch, registry_snapshot
):
    """TC-CLI-045 | 自动发现跳过 _ 开头文件，单个模块 ImportError 不中断整体

    输入: 用假 __import__ 记录被导入的模块名，并对 commands.tag 抛 ImportError
    预期输出: 记录中不含 "__init__"；包含 agent 与 tag；调用不抛异常
    断言点: 导入名列表内容（无 __init__）+ 无异常传播 + tag 被尝试过
    防回归: 若去掉 startswith('_') 过滤或去掉 try/except，本用例失败
    """
    main_module = importlib.import_module("agent_registry.cli.__main__")
    monkeypatch.delitem(sys.modules, "agent_registry.cli.commands.agent", raising=False)
    monkeypatch.delitem(sys.modules, "agent_registry.cli.commands.tag", raising=False)
    CLI._registry.clear()
    real_import = builtins.__import__
    attempted = []

    def fake_import(name, *args, **kwargs):
        attempted.append(name)
        if name.endswith(".commands.tag"):
            raise ImportError("simulated import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    main_module._auto_discover_commands()

    assert "agent_registry.cli.commands.agent" in attempted
    assert "agent_registry.cli.commands.tag" in attempted
    assert not any("__init__" in name for name in attempted)
    # agent 模块被重新导入并注册；tag 导入失败被吞掉，因此没有注册
    assert CLI.get_registry().has("agent") is True
    assert CLI.get_registry().has("tag") is False


def test_main_windows_without_pyreadline_installs_fake_readline(monkeypatch):
    """TC-CLI-046 | Windows 且无 pyreadline3 时安装 FakeReadline 占位模块

    输入: platform.system() 返回 "Windows"；sys.modules["pyreadline3"] 置 None 强制 ImportError
    预期输出: sys.modules["readline"] 为 FakeReadline 实例，backend == "none"，
              且 get_completer/get_line_buffer/get_begidx/get_endidx 返回约定默认值
    断言点: 模块替换 + backend 值 + 四个方法返回值
    防回归: 若回退分支不再注入 readline，Windows 上导入 cmd 相关代码会崩溃，本用例失败
    """
    monkeypatch.setitem(sys.modules, "pyreadline3", None)
    saved_readline = sys.modules.get("readline")
    try:
        _load_main_probe(monkeypatch, "agent_registry.cli._main_probe_win", "Windows")

        fake = sys.modules["readline"]
        assert type(fake).__name__ == "FakeReadline"
        assert fake.backend == "none"
        assert fake.get_completer() is None
        assert fake.get_line_buffer() == ""
        assert fake.get_begidx() == 0
        assert fake.get_endidx() == 0
        assert fake.set_completer(None) is None
        assert fake.parse_and_bind("tab: complete") is None
        # History/completion helpers that cmd.Cmd and InteractiveCLI call.
        assert fake.get_completer_delims() == " \t\n"
        assert fake.set_completer_delims(" \t\n") is None
        assert fake.read_history_file("/nonexistent") is None
        assert fake.write_history_file("/nonexistent") is None
        assert fake.add_history("ls") is None
        assert fake.get_current_history_length() == 0
    finally:
        if saved_readline is None:
            sys.modules.pop("readline", None)
        else:
            sys.modules["readline"] = saved_readline


def test_main_windows_with_pyreadline3_marks_backend(monkeypatch):
    """TC-CLI-047 | Windows 且有 pyreadline3 时补 backend 并注册为 readline 模块

    输入: sys.modules 注入伪造的 pyreadline3.readline（没有 backend 属性）
    预期输出: 伪造模块被写入 backend == "pyreadline3"，且 sys.modules["readline"] 指向它
    断言点: backend 属性值 + sys.modules 身份同一
    防回归: 若补丁逻辑被删除，Python 3.14 下 cmd.py 会因缺少 backend 报错，本用例失败
    """
    import types

    fake_readline = types.ModuleType("pyreadline3.readline")
    fake_package = types.ModuleType("pyreadline3")
    fake_package.readline = fake_readline
    monkeypatch.setitem(sys.modules, "pyreadline3", fake_package)
    monkeypatch.setitem(sys.modules, "pyreadline3.readline", fake_readline)
    saved_readline = sys.modules.get("readline")
    try:
        _load_main_probe(monkeypatch, "agent_registry.cli._main_probe_pre", "Windows")

        assert fake_readline.backend == "pyreadline3"
        assert sys.modules["readline"] is fake_readline
    finally:
        if saved_readline is None:
            sys.modules.pop("readline", None)
        else:
            sys.modules["readline"] = saved_readline


@_POSIX_ONLY
def test_main_posix_marks_stdlib_readline_backend(monkeypatch):
    """TC-CLI-048 | POSIX 分支导入标准库 readline 并补 backend == "readline"

    输入: platform.system() 返回 "Linux"
    预期输出: sys.modules["readline"] 可导入且有 backend 属性，值为 "readline"
    断言点: backend 精确值 + 模块确实可 import
    防回归: 若 POSIX 分支被删除或 backend 值写错，本用例失败
    """
    import readline as real_readline

    had_backend = hasattr(real_readline, "backend")
    saved_value = getattr(real_readline, "backend", None)
    try:
        _load_main_probe(monkeypatch, "agent_registry.cli._main_probe_posix", "Linux")

        assert sys.modules["readline"] is real_readline
        assert real_readline.backend == "readline"
    finally:
        if had_backend:
            real_readline.backend = saved_value
        else:
            del real_readline.backend


def test_main_posix_without_readline_installs_fake_readline(monkeypatch):
    """TC-CLI-049 | POSIX 且标准库 readline 不可用时同样安装 FakeReadline

    输入: sys.modules["readline"] = None 使 import readline 抛 ImportError
    预期输出: sys.modules["readline"] 为 FakeReadline 实例且 backend == "none"，
              占位方法返回约定默认值
    断言点: 类型名 + backend + 六个占位方法的返回值
    防回归: 若 POSIX 的 ImportError 分支被删，缺少 readline 的精简镜像上 CLI 无法启动
    """
    monkeypatch.setitem(sys.modules, "readline", None)
    saved_readline = sys.modules.get("readline")
    try:
        _load_main_probe(monkeypatch, "agent_registry.cli._main_probe_norl", "Linux")

        fake = sys.modules["readline"]
        assert type(fake).__name__ == "FakeReadline"
        assert fake.backend == "none"
        assert fake.get_completer() is None
        assert fake.get_line_buffer() == ""
        assert fake.get_begidx() == 0
        assert fake.get_endidx() == 0
        assert fake.set_completer(None) is None
        assert fake.parse_and_bind("tab: complete") is None
        # History/completion helpers that cmd.Cmd and InteractiveCLI call.
        assert fake.get_completer_delims() == " \t\n"
        assert fake.set_completer_delims(" \t\n") is None
        assert fake.read_history_file("/nonexistent") is None
        assert fake.write_history_file("/nonexistent") is None
        assert fake.add_history("ls") is None
        assert fake.get_current_history_length() == 0
    finally:
        if saved_readline is None:
            sys.modules.pop("readline", None)
        else:
            sys.modules["readline"] = saved_readline


def test_main_guard_runs_cli_and_exits_with_its_code(monkeypatch):
    """TC-CLI-050 | 以 __main__ 运行时调用 main() 并以 CLI.run() 的返回值退出

    输入: runpy 以 __main__ 身份执行 agent_registry.cli，桩掉 CLI.run 返回 7
    预期输出: 抛出 SystemExit，code == 7；CLI.run 被调用一次
    断言点: SystemExit.code == 7 + run 调用次数
    防回归: 若入口守卫丢失或 sys.exit 用了固定 0，本用例失败
    """
    import runpy

    run_mock = mock.Mock(return_value=7)
    monkeypatch.setattr(CLI, "run", run_mock)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("agent_registry.cli", run_name="__main__")

    assert excinfo.value.code == 7
    assert run_mock.call_count == 1


def test_interactive_cli_starts_with_windows_fake_readline(monkeypatch):
    """TC-CLI-051 | Windows 回退 FakeReadline 足以启动 InteractiveCLI

    输入: 先按 __main__ 的 Windows 分支安装 FakeReadline，再把 core.readline 指向它
    预期输出: InteractiveCLI(registry) 构造成功，prompt 为 "agent-registry> "
    断言点: 构造不抛异常 + prompt 精确值
    防回归: 若回退桩又缺 set_completer_delims/read_history_file，
            core.__init__ 会抛 AttributeError，本用例失败
    历史: 修复前桩只实现了 6 个方法，缺 set_completer_delims 与 read_history_file
    """
    from agent_registry.cli import core as core_module
    from agent_registry.cli.registry import CommandRegistry

    monkeypatch.setitem(sys.modules, "pyreadline3", None)
    saved_readline = sys.modules.get("readline")
    try:
        _load_main_probe(monkeypatch, "agent_registry.cli._main_probe_xfail", "Windows")
        fake = sys.modules["readline"]
        monkeypatch.setattr(core_module, "readline", fake)
        monkeypatch.setattr(core_module, "HAS_READLINE", True)

        cli = core_module.InteractiveCLI(CommandRegistry())

        assert cli.prompt == "agent-registry> "
    finally:
        if saved_readline is None:
            sys.modules.pop("readline", None)
        else:
            sys.modules["readline"] = saved_readline
