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
"""CLI coverage tests: framework dispatch, formatting, output and i18n.

Scope: ``agent_registry/cli/core.py`` (interactive dispatch, completion,
exception mapping, entry points), ``agent_registry/cli/base.py`` (formatting
helpers), ``agent_registry/cli/output.py`` and ``agent_registry/cli/i18n``.

Every case asserts observable behaviour: exit codes, stdout/stderr content,
logger call arguments and rendered text. Readline is replaced by a fake module
object, so no terminal, file or history state is touched.
"""

import argparse
import json
import sys
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from agent_registry.cli import core as core_module
from agent_registry.cli import i18n as i18n_module
from agent_registry.cli.base import BaseCommand
from agent_registry.cli.core import CLI, InteractiveCLI
from agent_registry.cli.exceptions import ServiceError
from agent_registry.cli.i18n import I18n, t, tf
from agent_registry.cli.output import Output
from agent_registry.cli.registry import CommandRegistry


# --------------------------------------------------------------------------- #
# test commands
# --------------------------------------------------------------------------- #

class EchoCommand(BaseCommand):
    """Command that echoes its --level argument."""

    @property
    def name(self):
        return "echo"

    @property
    def help_text(self):
        return "Echo command"

    def add_arguments(self, parser):
        parser.add_argument("--level", "-l", default="info")

    def execute(self, args):
        print(f"echo:{args.level}")
        return 0


class BoomCommand(BaseCommand):
    """Command raising a generic exception."""

    @property
    def name(self):
        return "boom"

    @property
    def help_text(self):
        return "Boom command"

    def execute(self, args):
        raise ValueError("boom")


class ServiceDownCommand(BaseCommand):
    """Command raising a CLIError subclass."""

    @property
    def name(self):
        return "svc"

    @property
    def help_text(self):
        return "Service command"

    def execute(self, args):
        raise ServiceError("service down")


class SubCommand(BaseCommand):
    """Subcommand with its own option (for argument completion)."""

    @property
    def name(self):
        return "sub"

    @property
    def help_text(self):
        return "Sub command"

    def add_arguments(self, parser):
        parser.add_argument("--sub-opt", "-s", help="Sub option")

    def execute(self, args):
        print("sub executed")
        return 0


class ParentCommand(BaseCommand):
    """Parent command exposing one subcommand."""

    @property
    def name(self):
        return "parent"

    @property
    def help_text(self):
        return "Parent command"

    @property
    def subcommands(self):
        return {"sub": SubCommand()}

    def execute(self, args):
        print("parent executed")
        return 0


class PlainCommand(BaseCommand):
    """Command without display_config (fallback formatting)."""

    @property
    def name(self):
        return "plain"

    @property
    def help_text(self):
        return "Plain command"

    def execute(self, args):
        return 0


class ConfiguredCommand(BaseCommand):
    """Command with full display_config (table + separate + labels)."""

    @property
    def name(self):
        return "configured"

    @property
    def help_text(self):
        return "Configured command"

    @property
    def display_config(self):
        return {
            "table_fields": ["id", "enabled", "tags"],
            "separate_fields": ["card", "nested.value", "plain", "absent"],
            "field_labels": {
                "id": "ID", "enabled": "Enabled", "tags": "Tags", "card": "Card",
            },
        }

    def execute(self, args):
        return 0


class NestedPathCommand(BaseCommand):
    """Command whose table field uses a nested path that cannot be resolved."""

    @property
    def name(self):
        return "nested"

    @property
    def help_text(self):
        return "Nested path command"

    @property
    def display_config(self):
        return {"table_fields": ["a.b.c"]}

    def execute(self, args):
        return 0


class AliasedCommand(BaseCommand):
    """Command with aliases and an over-long help text."""

    @property
    def name(self):
        return "aliased"

    @property
    def help_text(self):
        return "x" * 70

    @property
    def aliases(self):
        return ["alias1", "alias2"]

    def execute(self, args):
        return 0


class LongHelpSubCommand(BaseCommand):
    """Subcommand with an over-long help text (for truncation)."""

    @property
    def name(self):
        return "longsub"

    @property
    def help_text(self):
        return "y" * 70

    def execute(self, args):
        return 0


class ParentWithLongSubCommand(BaseCommand):
    """Parent exposing one subcommand with a long description."""

    @property
    def name(self):
        return "longparent"

    @property
    def help_text(self):
        return "Long parent"

    @property
    def subcommands(self):
        return {"longsub": LongHelpSubCommand()}

    def execute(self, args):
        return 0


def _cli_with(*command_classes):
    registry = CommandRegistry()
    for command_class in command_classes:
        registry.register(command_class)
    return InteractiveCLI(registry)


class FakeReadline:
    """Minimal stand-in for the readline module."""

    def __init__(self, buffer="", begidx=0):
        self._buffer = buffer
        self._begidx = begidx

    def get_line_buffer(self):
        return self._buffer

    def get_begidx(self):
        return self._begidx

    def get_endidx(self):
        return self._begidx

    def parse_and_bind(self, spec):
        pass

    def set_completer(self, func):
        pass

    def set_completer_delims(self, delims):
        pass

    def set_completion_display_matches_hook(self, hook):
        pass

    def read_history_file(self, path):
        raise FileNotFoundError(path)

    def write_history_file(self, path):
        pass


@pytest.fixture
def mock_logger(monkeypatch):
    """Replace every cli_logger method used by the dispatcher with a mock."""
    logger = core_module.cli_logger
    for method_name in (
        "set_level", "debug", "info", "warning", "error",
        "log_command_start", "log_command_end", "log_command_error",
    ):
        monkeypatch.setattr(logger, method_name, mock.Mock())
    return logger


# --------------------------------------------------------------------------- #
# base.py formatting
# --------------------------------------------------------------------------- #

def test_base_default_display_config_uses_simple_format():
    """TC-CLI-101 | 未覆写 display_config 时输出退化为 key: value 文本

    输入: 不覆写 display_config 的命令，数据 {"a": 1}，分别带/不带标题
    预期输出: display_config 为 {}；带标题时首两行为 "T" 与 50 个 "="，
              随后一行 "a: 1"；不带标题时只有 "a: 1"
    断言点: 返回的配置字典为空 + 精确文本行
    防回归: 若默认配置返回非空（导致走表格分支）或改掉分隔线长度，本用例失败
    """
    command = PlainCommand()

    assert command.display_config == {}
    assert command.format_output({"a": 1}) == "a: 1"
    assert command.format_output({"a": 1}, "T") == "T\n" + "=" * 50 + "\na: 1"


def test_base_format_output_renders_table_separate_and_labels():
    """TC-CLI-102 | format_output 渲染表格字段、独立字段、自定义标签与嵌套路径

    输入: 数据 id=a1（enabled=True、tags 列表、card 字典、nested.value 深层值、plain 字符串），
          separate_fields 中还包含不存在的 absent
    预期输出: 表格含 ID/Enabled/Tags 标签行，布尔显示 Yes，列表显示 JSON，字典字段
              以 "Card:" 段落输出缩进 JSON，嵌套值单独成段，plain 原样输出，
              absent 整段不出现
    断言点: 各标签与值文本 + "absent:" 不存在
    防回归: 若省略 separate_fields 段落、把 bool 渲染成 True、或对缺失字段仍输出空段，本用例失败
    """
    rendered = ConfiguredCommand().format_output({
        "id": "a1",
        "enabled": True,
        "tags": ["x", "y"],
        "card": {"k": "v"},
        "nested": {"value": "deep"},
        "plain": "raw text",
    })

    assert "ID" in rendered and "a1" in rendered
    assert "Enabled" in rendered and "Yes" in rendered
    assert "Tags" in rendered and '["x", "y"]' in rendered
    assert "Card:" in rendered and '"k": "v"' in rendered
    assert "nested.value:" in rendered and "deep" in rendered
    assert "plain:" in rendered and "raw text" in rendered
    assert "absent:" not in rendered


def test_base_format_output_truncates_long_values_and_bool_false():
    """TC-CLI-103 | 表格值超过 100 字符被截断，False 渲染为 No

    输入: id 为 150 个 "x"，enabled=False
    预期输出: 表格中 id 值为 97 个 x 加 "...",共 100 字符；Enabled 行为 "No"
    断言点: 精确截断串存在、98 个 x 不存在、"No" 出现
    防回归: 若去掉截断（超长值原样打印）或 bool 映射反转，本用例失败
    """
    rendered = ConfiguredCommand().format_output({"id": "x" * 150, "enabled": False})

    assert "x" * 97 + "..." in rendered
    assert "x" * 98 not in rendered
    assert "No" in rendered


def test_base_format_list_output_table_and_empty():
    """TC-CLI-104 | format_list_output 渲染标题/表头/行，并在空列表时提示

    输入: 两条记录（第二条缺 enabled）与空列表
    预期输出: 标题 "List (2)"、表头 ID/Enabled/Tags、两行数据（缺失值渲染为空串）；
              空列表时输出 "No items found"
    断言点: 标题 + 表头 + 数据 + 空列表提示（以及 "No items found" 只出现一次）
    防回归: 若空列表不提示、或表头取错字段，本用例失败
    """
    command = ConfiguredCommand()

    rendered = command.format_list_output(
        [{"id": "a1", "enabled": True, "tags": []}, {"id": "a2"}], title="List (2)"
    )
    assert "List (2)" in rendered
    assert "ID" in rendered and "Enabled" in rendered and "Tags" in rendered
    assert "a1" in rendered and "a2" in rendered
    assert "Yes" in rendered

    empty = command.format_list_output([], title="List (0)")
    assert "List (0)" in empty
    assert empty.count("No items found") == 1


def test_base_format_list_output_without_config_uses_simple_lines():
    """TC-CLI-105 | 无 display_config 时列表按 key: value 逐行输出

    输入: PlainCommand().format_list_output([{"a": 1}, {"b": 2}])
    预期输出: "a: 1\nb: 2"
    断言点: 精确字符串相等
    防回归: 若回退分支改成表格或丢行，本用例失败
    """
    assert PlainCommand().format_list_output([{"a": 1}, {"b": 2}]) == "a: 1\nb: 2"


def test_base_unresolvable_nested_table_field_renders_empty():
    """TC-CLI-106 | 嵌套路径中途不是字典时表格值渲染为空

    输入: 数据 {"a": {"b": "x"}}，table_fields 为 ["a.b.c"]
    预期输出: 表格中出现标签 a.b.c，其值为空字符串（不抛异常、不输出 None）
    断言点: 输出含 "a.b.c"、不含 "None"、且以该标签开头的行末尾为空
    防回归: 若 _get_field_value 在非字典中间节点抛 AttributeError，本用例失败
    """
    rendered = NestedPathCommand().format_output({"a": {"b": "x"}})

    assert "a.b.c" in rendered
    assert "None" not in rendered
    row = [line for line in rendered.splitlines() if line.startswith("a.b.c")][0]
    assert row.strip() == "a.b.c"


def test_base_get_full_help_lists_aliases_and_description():
    """TC-CLI-107 | get_full_help 展示命令名、别名与完整描述

    输入: AliasedCommand（help_text 70 字符、两个别名）
    预期输出: 含 "Command: aliased"、"Aliases:     alias1, alias2"，
              以及完整的 70 字符描述（命令自身描述不做截断）
    断言点: 三处文本精确匹配
    防回归: 若丢失别名行，或把命令描述误用子命令的截断规则，本用例失败
    """
    help_text = AliasedCommand().get_full_help()

    assert "Command: aliased" in help_text
    assert "Aliases:     alias1, alias2" in help_text
    assert "Description: " + "x" * 70 in help_text


def test_base_get_full_help_truncates_long_subcommand_description():
    """TC-CLI-148 | get_full_help 把超过 60 字符的子命令描述截断

    输入: 含 help_text 为 70 个 "y" 的子命令的父命令
    预期输出: 输出 "Subcommands:" 表，子命令描述为 60 个 "y" 加 "..."，
              不出现 61 个连续的 "y"
    断言点: 截断串存在 + 未截断串不存在 + 表头存在
    防回归: 若去掉 :60 + '...' 的截断，长描述会把表格撑坏，本用例失败
    """
    help_text = ParentWithLongSubCommand().get_full_help()

    assert "Subcommands:" in help_text
    assert "y" * 60 + "..." in help_text
    assert "y" * 61 not in help_text


def test_base_handle_error_debug_and_quiet(capsys):
    """TC-CLI-108 | handle_error 在 debug 下打印栈、否则只打印 "Error: ..."

    输入: 同一个 RuntimeError("bad")，debug=False 与 debug=True 各调用一次
    预期输出: 两次都返回 1；非 debug 时 stderr 只含 "Error: bad"（无栈）；
              debug 时 stderr 含 "Traceback" 与 "RuntimeError: bad"
    断言点: 返回码 + 两种 stderr 内容差异
    防回归: 若 debug 分支不再打印栈，或非 debug 泄露栈，本用例失败
    """
    command = PlainCommand()

    assert command.handle_error(RuntimeError("bad"), debug=False) == 1
    quiet = capsys.readouterr().err
    assert quiet.strip() == "Error: bad"
    assert "Traceback" not in quiet

    try:
        raise RuntimeError("bad")
    except RuntimeError as error:
        assert command.handle_error(error, debug=True) == 1
    verbose = capsys.readouterr().err
    assert "Traceback" in verbose
    assert "RuntimeError: bad" in verbose


# --------------------------------------------------------------------------- #
# core.py dispatch
# --------------------------------------------------------------------------- #

def test_core_get_command_path_builds_nested_path():
    """TC-CLI-109 | _get_command_path 拼出一级命令与各级子命令路径

    输入: Namespace(_command_name="agent", _subcommand_0="get")；空 Namespace
    预期输出: "agent get"；"unknown"
    断言点: 两个返回值精确相等
    防回归: 若丢失子命令层级或以空串代替 "unknown"，审计日志路径会错，本用例失败
    """
    cli = _cli_with(EchoCommand)

    assert cli._get_command_path(Namespace(_command_name="agent", _subcommand_0="get")) == "agent get"
    assert cli._get_command_path(Namespace()) == "unknown"


def test_core_execute_success_logs_start_and_end(mock_logger, capsys):
    """TC-CLI-110 | 命令成功执行返回 0 并记录开始/结束审计日志

    输入: echo --level warn
    预期输出: 退出码 0；stdout "echo:warn"；log_command_start("echo", 含 level=warn)；
              log_command_end("echo", 0, duration>=0)
    断言点: 退出码 + 输出 + 两个日志调用的精确参数 + 无错误日志
    防回归: 若审计日志被删、路径/退出码记录错误，本用例失败
    """
    cli = _cli_with(EchoCommand)

    assert cli._execute_command("echo --level warn") == 0

    assert "echo:warn" in capsys.readouterr().out
    start_args = mock_logger.log_command_start.call_args.args
    assert start_args[0] == "echo"
    assert start_args[1]["level"] == "warn"
    path, exit_code, duration = mock_logger.log_command_end.call_args.args
    assert (path, exit_code) == ("echo", 0)
    assert isinstance(duration, float) and duration >= 0.0
    mock_logger.log_command_error.assert_not_called()


def test_core_execute_unknown_command_prints_guidance(mock_logger, capsys):
    """TC-CLI-111 | 解析结果没有 _command 时提示未知命令并返回 1

    输入: 桩掉 _build_parser，使其返回一个只接受位置参数的解析器
    预期输出: 退出码 1；stdout 含 "Unknown command. Type 'cmds' for available commands."
    断言点: 退出码 + 提示文本 + 未调用 execute（无 echo 输出）
    防回归: 若缺少 _command 时抛 AttributeError 或静默返回 0，本用例失败
    """
    cli = _cli_with(EchoCommand)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("word", nargs="?")
    monkeypatch_parser = mock.Mock(return_value=parser)
    cli._build_parser = monkeypatch_parser

    assert cli._execute_command("whatever") == 1

    out = capsys.readouterr().out
    assert "Unknown command. Type 'cmds' for available commands." in out
    assert "echo:" not in out


def test_core_execute_syntax_error_from_shlex(mock_logger, capsys):
    """TC-CLI-112 | 引号不闭合时提示语法错误并返回 1，不进入命令执行

    输入: echo "unterminated
    预期输出: 退出码 1；stdout 含 "Syntax error: No closing quotation"
    断言点: 退出码 + 精确语法错误前缀 + 无命令输出
    防回归: 若 shlex 异常未被捕获，命令栈会崩溃，本用例失败
    """
    cli = _cli_with(EchoCommand)

    assert cli._execute_command('echo "unterminated') == 1

    out = capsys.readouterr().out
    assert "Syntax error: No closing quotation" in out
    assert "echo:" not in out


def test_core_execute_blank_input_returns_zero(mock_logger, capsys):
    """TC-CLI-113 | 纯空白输入视为空命令并返回 0，无输出

    输入: "   "
    预期输出: 退出码 0；stdout/stderr 均为空
    断言点: 退出码 + 两个输出流为空
    防回归: 若空白输入触发 argparse 报错（返回 1 并打印 usage），本用例失败
    """
    cli = _cli_with(EchoCommand)

    assert cli._execute_command("   ") == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_core_execute_debug_mode_enables_debug_logging(mock_logger, capsys):
    """TC-CLI-114 | -x 打开 debug：设置日志级别并记录命令原文

    输入: -x echo
    预期输出: 退出码 0；set_level("DEBUG")；debug 收到 "Executing: -x echo"；
              context.debug 变为 True
    断言点: 两个日志调用精确参数 + context.debug 值
    防回归: 若 -x 不再传递到 logger 或 context，debug 排查能力丢失，本用例失败
    """
    cli = _cli_with(EchoCommand)

    assert cli._execute_command("-x echo") == 0

    mock_logger.set_level.assert_called_once_with("DEBUG")
    mock_logger.debug.assert_called_once_with("Executing: -x echo")
    assert cli._context.debug is True


def test_core_execute_help_exits_zero(mock_logger, capsys):
    """TC-CLI-115 | -h 触发 argparse help（SystemExit 0）时返回 0

    输入: -h
    预期输出: 退出码 0；stdout 含 "usage: agent-registry"
    断言点: 退出码 + usage 文本
    防回归: 若把 SystemExit(0) 当成错误返回 1，`cmd -h` 会报失败，本用例失败
    """
    cli = _cli_with(EchoCommand)

    assert cli._execute_command("-h") == 0

    assert "usage: agent-registry" in capsys.readouterr().out


def test_core_execute_invalid_option_exits_one(mock_logger, capsys):
    """TC-CLI-116 | 非法选项让 argparse 以 2 退出，框架统一映射为 1

    输入: echo --nope
    预期输出: 退出码 1；stderr 含 "unrecognized arguments: --nope"
    断言点: 退出码 + stderr 文本
    防回归: 若 SystemExit 非 0 被当作 0 或不捕获，本用例失败
    """
    cli = _cli_with(EchoCommand)

    assert cli._execute_command("echo --nope") == 1

    assert "unrecognized arguments: --nope" in capsys.readouterr().err


def test_core_execute_generic_exception_prints_error(mock_logger, capsys):
    """TC-CLI-117 | 普通异常映射为退出码 1 并打印 "Error: <msg>"

    输入: boom（execute 抛 ValueError("boom")）
    预期输出: 退出码 1；stdout "Error: boom"；log_command_error 收到异常且 include_trace=False
    断言点: 退出码 + 输出 + 异常类型与 include_trace 标志
    防回归: 若异常被吞掉返回 0，或 include_trace 恒为 True，本用例失败
    """
    cli = _cli_with(BoomCommand)

    assert cli._execute_command("boom") == 1

    assert "Error: boom" in capsys.readouterr().out
    path, error, include_trace = mock_logger.log_command_error.call_args.args
    assert path == "boom"
    assert isinstance(error, ValueError) and str(error) == "boom"
    assert include_trace is False


def test_core_execute_debug_exception_prints_traceback(monkeypatch, mock_logger, capsys):
    """TC-CLI-118 | debug 模式下异常打印栈，并把 include_trace=True 传给日志

    输入: -x boom
    预期输出: 退出码 1；stderr 含 Traceback；traceback.print_exc 被调用一次；
              log_command_error 的第三个参数为 True
    断言点: 退出码 + print_exc 调用次数 + include_trace 值
    防回归: 若 debug 分支被删除，定位线上问题会失去栈信息，本用例失败
    """
    printed = mock.Mock()
    monkeypatch.setattr("traceback.print_exc", printed)
    cli = _cli_with(BoomCommand)

    assert cli._execute_command("-x boom") == 1

    assert printed.call_count == 1
    assert mock_logger.log_command_error.call_args.args[2] is True


def test_core_execute_cli_error_uses_its_exit_code(mock_logger, capsys):
    """TC-CLI-119 | CLIError 子类使用自身 exit_code 并输出 message

    输入: svc（execute 抛 ServiceError("service down")，exit_code=4）
    预期输出: 退出码 4；stdout "Error: service down"
    断言点: 退出码精确为 4 + 输出文本
    防回归: 若统一按 1 退出，脚本编排会丢失错误分类，本用例失败
    """
    cli = _cli_with(ServiceDownCommand)

    assert cli._execute_command("svc") == 4

    assert "Error: service down" in capsys.readouterr().out


def test_core_show_commands_lists_subcommands_and_internal_entries(mock_logger, capsys):
    """TC-CLI-120 | cmds 列表包含一级命令、子命令与内置项

    输入: 注册含子命令的 parent 后执行 do_cmds
    预期输出: stdout 含 "Available commands:"、"parent"、"parent sub"、
              "Subcommand"、"Internal"、"exit/quit/q"
    断言点: 六处关键字
    防回归: 若子命令不再展开或内置项丢失，帮助信息不完整，本用例失败
    """
    cli = _cli_with(ParentCommand)

    cli.do_cmds("")

    out = capsys.readouterr().out
    assert "Available commands:" in out
    assert "parent" in out
    assert "parent sub" in out
    assert "Subcommand" in out
    assert "Internal" in out
    assert "exit/quit/q" in out


def test_core_complete_cmds_returns_nothing():
    """TC-CLI-121 | cmds 命令不做补全

    输入: complete_cmds("c", "cmds c", 5, 6)
    预期输出: 空列表
    断言点: 返回值精确等于 []
    防回归: 若误返回命令名列表，Tab 补全会插入非法参数，本用例失败
    """
    assert _cli_with(EchoCommand).complete_cmds("c", "cmds c", 5, 6) == []


def test_core_generated_do_and_complete_methods(mock_logger, capsys):
    """TC-CLI-122 | 动态生成的 do_*/complete_* 方法按子命令与参数补全

    输入: 注册 parent 后，分别调用 do_parent("")、complete_parent 三种上下文
    预期输出: do_parent 执行父命令（输出 "parent executed"）；
              "parent " 补全返回 ["sub"]；"parent sub --" 补全返回
              ["--help", "--sub-opt"]（argparse 自带 --help）；未知子命令前缀返回 []
    断言点: 执行输出 + 三种补全结果 + do_parent.__doc__ 等于 help_text
    防回归: 若补全闭包把 cmd_name/子命令取错，或文档串丢失，本用例失败
    """
    cli = _cli_with(ParentCommand)

    assert cli.do_parent.__doc__ == "Parent command"
    cli.do_parent("")
    assert "parent executed" in capsys.readouterr().out

    assert cli.complete_parent("", "parent ", 7, 7) == ["sub"]
    assert cli.complete_parent("--", "parent sub --", 13, 13) == ["--help", "--sub-opt"]
    assert cli.complete_parent("zz", "parent zz", 9, 9) == []


def test_core_complete_resolves_commands_subcommands_and_arguments(monkeypatch):
    """TC-CLI-123 | complete() 根据输入上下文补全命令/子命令/参数

    输入: 伪造 readline 依次给出 ""、"parent "、"parent sub --" 的缓冲区
    预期输出: 空缓冲区返回内置或已注册命令名（按 state 取）；"parent " 返回 "sub"；
              "parent sub --" 依次返回 "--help"、"--sub-opt"，越界 state 返回 None
    断言点: 多个返回值 + 越界 None
    防回归: 若上下文判断错位（把参数当子命令），补全内容会错，本用例失败
    """
    cli = _cli_with(ParentCommand)
    fake = FakeReadline(buffer="", begidx=0)
    monkeypatch.setattr(core_module, "readline", fake)
    monkeypatch.setattr(core_module, "HAS_READLINE", True)

    names = cli.get_names()
    assert cli.complete("", names.index("parent")) == "parent"
    assert cli.complete("", len(names) + 10) is None

    fake._buffer, fake._begidx = "parent ", 7
    assert cli.complete("", 0) == "sub"

    fake._buffer, fake._begidx = "parent sub --", 13
    assert cli.complete("--", 0) == "--help"
    assert cli.complete("--", 1) == "--sub-opt"
    assert cli.complete("--", 2) is None


def test_core_complete_handles_unbalanced_quote_and_unknown_command(monkeypatch, capsys):
    """TC-CLI-124 | complete() 遇到 shlex 解析失败时回退到空白切分

    输入: readline 缓冲区 "parent 'sub"（引号不闭合）与 "nope "
    预期输出: 两种输入都返回 None 且不抛异常、不打印错误
    断言点: 返回值 + 无输出
    防回归: 若移除 ValueError 回退，按 Tab 会抛异常中断交互，本用例失败
    """
    cli = _cli_with(ParentCommand)
    fake = FakeReadline(buffer="parent 'sub", begidx=11)
    monkeypatch.setattr(core_module, "readline", fake)
    monkeypatch.setattr(core_module, "HAS_READLINE", True)

    assert cli.complete("", 0) is None
    fake._buffer, fake._begidx = "nope ", 5
    assert cli.complete("", 0) is None
    assert capsys.readouterr().out == ""


def test_core_complete_returns_none_without_readline(monkeypatch):
    """TC-CLI-125 | 没有 readline 时 complete() 直接返回 None

    输入: monkeypatch HAS_READLINE=False
    预期输出: complete("a", 0) 返回 None
    断言点: 返回值
    防回归: 若缺少该守卫，精简环境会因 AttributeError 崩溃，本用例失败
    """
    cli = _cli_with(ParentCommand)
    monkeypatch.setattr(core_module, "HAS_READLINE", False)

    assert cli.complete("a", 0) is None


def test_core_preloop_configures_completion_and_display_hook(monkeypatch):
    """TC-CLI-126 | preloop 绑定补全函数并在 POSIX 下安装显示钩子

    输入: 伪造 readline，sys.platform 为 linux
    预期输出: set_completer(cli.complete)、parse_and_bind("tab: complete") 各一次，
              _setup_display_hook 被调用一次
    断言点: 两处 readline 调用参数 + 钩子调用次数
    防回归: 若 preloop 不再绑定补全，Tab 键失效，本用例失败
    """
    cli = _cli_with(EchoCommand)
    fake = FakeReadline()
    fake.set_completer = mock.Mock()
    fake.parse_and_bind = mock.Mock()
    hook = mock.Mock()
    monkeypatch.setattr(core_module, "readline", fake)
    monkeypatch.setattr(core_module, "HAS_READLINE", True)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(cli, "_setup_display_hook", hook)

    cli.preloop()

    fake.set_completer.assert_called_once_with(cli.complete)
    fake.parse_and_bind.assert_called_once_with("tab: complete")
    assert hook.call_count == 1


def test_core_preloop_skips_hook_on_windows_and_swallows_platform_errors(monkeypatch):
    """TC-CLI-127 | preloop 在 Windows 跳过显示钩子，且平台探测异常被忽略

    输入: sys.platform = "win32"；以及 startswith 抛 RuntimeError 的假平台对象
    预期输出: 两次都正常返回；钩子调用 0 次；不抛异常
    断言点: 钩子调用次数 + 无异常
    防回归: 若去掉平台判断（Windows 上调用不存在的钩子 API）或去掉 try/except，本用例失败
    """
    cli = _cli_with(EchoCommand)
    fake = FakeReadline()
    fake.set_completer = mock.Mock()
    fake.parse_and_bind = mock.Mock()
    hook = mock.Mock()
    monkeypatch.setattr(core_module, "readline", fake)
    monkeypatch.setattr(core_module, "HAS_READLINE", True)
    monkeypatch.setattr(cli, "_setup_display_hook", hook)

    monkeypatch.setattr(sys, "platform", "win32")
    cli.preloop()
    assert hook.call_count == 0

    broken_platform = mock.Mock()
    broken_platform.startswith.side_effect = RuntimeError("broken platform")
    monkeypatch.setattr(sys, "platform", broken_platform)
    cli.preloop()
    assert hook.call_count == 0


def test_core_display_hook_prints_matches_in_columns(monkeypatch, capsys):
    """TC-CLI-128 | 补全显示钩子按列打印候选并回显提示符与缓冲区

    输入: 四个候选 ["parent", "pager", "patch", "pause"]，缓冲区 "par"
    预期输出: 输出四个候选（排序后）、提示符 "agent-registry> " 与回显 "par"
    断言点: 四个候选均在输出 + 提示符 + 缓冲区内容
    防回归: 若钩子不打印候选或丢失提示符回显，交互体验退化，本用例失败
    """
    cli = _cli_with(EchoCommand)
    fake = FakeReadline(buffer="par")
    fake.set_completion_display_matches_hook = mock.Mock()
    monkeypatch.setattr(core_module, "readline", fake)

    cli._setup_display_hook()

    hook = fake.set_completion_display_matches_hook.call_args.args[0]
    hook("par", ["parent", "pager", "patch", "pause"], 2)
    out = capsys.readouterr().out
    for match in ("pager", "parent", "patch", "pause"):
        assert match in out
    assert "agent-registry> " in out
    assert "par" in out


def test_core_display_hook_ignores_empty_match_list(monkeypatch, capsys):
    """TC-CLI-129 | 候选为空时显示钩子不产生任何输出

    输入: matches = []
    预期输出: 无输出
    断言点: capsys 捕获的 stdout 为空字符串
    防回归: 若空候选仍打印提示符，会破坏命令行重绘，本用例失败
    """
    cli = _cli_with(EchoCommand)
    fake = FakeReadline(buffer="")
    fake.set_completion_display_matches_hook = mock.Mock()
    monkeypatch.setattr(core_module, "readline", fake)

    cli._setup_display_hook()
    hook = fake.set_completion_display_matches_hook.call_args.args[0]
    hook("", [], 0)

    assert capsys.readouterr().out == ""


def test_core_postloop_swallows_history_write_failure(monkeypatch):
    """TC-CLI-130 | postloop 写历史失败被吞掉，不向交互循环抛异常

    输入: 伪造 readline，write_history_file 抛 OSError
    预期输出: postloop 正常返回；write_history_file 被调用一次（参数为历史文件路径）
    断言点: 无异常 + 调用次数 + 调用参数
    防回归: 若去掉 try/except，退出 CLI 时可能崩溃并丢历史，本用例失败
    """
    cli = _cli_with(EchoCommand)
    fake = FakeReadline()
    fake.write_history_file = mock.Mock(side_effect=OSError("read-only fs"))
    monkeypatch.setattr(core_module, "readline", fake)
    monkeypatch.setattr(core_module, "HAS_READLINE", True)

    cli.postloop()

    assert fake.write_history_file.call_count == 1
    assert fake.write_history_file.call_args.args[0] == ".agent_registry_history"


def test_core_default_handles_blank_eof_and_command(mock_logger, capsys):
    """TC-CLI-131 | default() 区分空行、EOF 与普通命令

    输入: "   "、"EOF"、"echo --level x" 三种输入
    预期输出: 空行返回 None 且无输出；EOF 返回 True 并打印 "Goodbye!"；
              命令返回 None 且执行（输出 echo:x）
    断言点: 三个返回值 + 两类输出
    防回归: 若 EOF 不再退出或空行被当成命令，交互循环行为异常，本用例失败
    """
    cli = _cli_with(EchoCommand)

    assert cli.default("   ") is None
    assert capsys.readouterr().out == ""

    assert cli.default("EOF") is True
    assert "Goodbye!" in capsys.readouterr().out

    assert cli.default("echo --level x") is None
    assert "echo:x" in capsys.readouterr().out


def test_core_cli_run_delegates_to_cmdloop(monkeypatch):
    """TC-CLI-132 | CLI.run 创建一个交互实例并进入 cmdloop

    输入: 桩 InteractiveCLI.cmdloop
    预期输出: 返回 0；cmdloop 调用一次
    断言点: 返回值 + 调用次数
    防回归: 若 run 不再进入交互循环（例如直接返回），CLI 无法使用，本用例失败
    """
    loop = mock.Mock()
    monkeypatch.setattr(core_module.InteractiveCLI, "cmdloop", loop)

    assert CLI().run() == 0
    assert loop.call_count == 1


def test_core_main_exits_with_run_result(monkeypatch):
    """TC-CLI-133 | main() 以 CLI.run() 的结果调用 sys.exit

    输入: CLI.run 返回 3
    预期输出: 抛出 SystemExit，code == 3
    断言点: SystemExit.code
    防回归: 若 main 固定 sys.exit(0)，脚本编排无法感知失败，本用例失败
    """
    monkeypatch.setattr(core_module.CLI, "run", mock.Mock(return_value=3))

    with pytest.raises(SystemExit) as excinfo:
        core_module.main()

    assert excinfo.value.code == 3


# --------------------------------------------------------------------------- #
# output.py
# --------------------------------------------------------------------------- #

def test_output_print_table_json_emits_projected_list(capsys):
    """TC-CLI-134 | json 模式下 print_table 只输出指定列并保持列表结构

    输入: rows=[{"a":1,"b":2},{"a":3,"b":4}]，columns=["a"]
    预期输出: stdout 为 JSON 列表 [{"a": 1}, {"a": 3}]
    断言点: json.loads(stdout) 精确相等（证明 b 列被剔除）
    防回归: 若 json 分支忽略 columns 或输出成表格文本，本用例失败
    """
    Output("json").print_table([{"a": 1, "b": 2}, {"a": 3, "b": 4}], ["a"], {"a": "A"})

    assert json.loads(capsys.readouterr().out) == [{"a": 1}, {"a": 3}]


def test_output_print_table_empty_rows(capsys):
    """TC-CLI-135 | 空行时 print_table 输出 "No items found"

    输入: rows=[]
    预期输出: stdout 含 "No items found"，且无表头
    断言点: 输出文本 + 不含表头 "A"
    防回归: 若空列表仍打印表头，或抛异常（列表下标），本用例失败
    """
    Output("text").print_table([], ["a"], {"a": "A"})

    out = capsys.readouterr().out
    assert "No items found" in out
    assert "----" not in out


def test_output_print_dict_table_json_and_ordering(capsys):
    """TC-CLI-136 | print_dict_table 支持 json、字段顺序与标签映射

    输入: data={"a":1,"b":2}；json 模式；text 模式指定 field_order=["b","a"]、labels
    预期输出: json 模式输出原始字典；text 模式标签为 "B"/"A"，且 B 行在 A 行之前
    断言点: json 内容 + 标签文本 + 行顺序（下标比较）
    防回归: 若忽略 field_order（顺序变 a、b），本用例失败
    """
    data = {"a": 1, "b": 2}

    Output("json").print_dict_table(data, field_order=["b", "a"], labels={"a": "A", "b": "B"})
    assert json.loads(capsys.readouterr().out) == data

    Output("table").print_dict_table(data, field_order=["b", "a"], labels={"a": "A", "b": "B"})
    out = capsys.readouterr().out
    assert "B" in out and "A" in out
    assert out.index("B") < out.index("A")


def test_output_print_separate_formats(capsys):
    """TC-CLI-137 | print_separate 对 json 静默，对 dict/list/str 分别渲染

    输入: json 模式一次；text 模式分别传 dict、list、str
    预期输出: json 模式无输出；text 模式含 "Card:"、缩进 JSON、列表项与原始字符串
    断言点: json 空输出 + 三段文本内容
    防回归: 若 json 模式仍打印、或非 dict 分支丢失，本用例失败
    """
    Output("json").print_separate("Card", {"k": "v"})
    assert capsys.readouterr().out == ""

    output = Output("text")
    output.print_separate("Card", {"k": "v"})
    first = capsys.readouterr().out
    assert "Card:" in first and '"k": "v"' in first

    output.print_separate("Items", ["x", "y"])
    second = capsys.readouterr().out
    assert '"x"' in second and '"y"' in second

    output.print_separate("Raw", "plain text")
    assert "plain text" in capsys.readouterr().out


def test_output_print_dispatch_variants(capsys):
    """TC-CLI-138 | Output.print 按格式与数据类型分派

    输入: table 模式下传入 dict 列表、单个字符串（带标题）；text 模式传 list
    预期输出: 表格输出含表头 a 与两行；单字符串带标题输出 "Title" 与原文；
              text 模式逐行输出列表元素
    断言点: 三种输出内容
    防回归: 若 table 模式对字符串调表格渲染（AttributeError），本用例失败
    """
    Output("table").print([{"a": 1}, {"a": 2}], title="Rows")
    table_out = capsys.readouterr().out
    assert "Rows" in table_out
    assert "a" in table_out
    assert "1" in table_out and "2" in table_out

    Output("table").print("just text", title="Title")
    scalar_out = capsys.readouterr().out
    assert "Title" in scalar_out
    assert "just text" in scalar_out

    Output("text").print(["one", "two"])
    text_out = capsys.readouterr().out
    assert text_out.strip().splitlines() == ["one", "two"]


def test_output_messages_in_both_modes(capsys):
    """TC-CLI-139 | warning/info 在 json 与 text 下的输出格式

    输入: json 模式的 warning/info；text 模式的 warning/info
    预期输出: json 输出 {"status": "warning"|"info", "message": ...}；
              text 分别带 "[WARN] " 前缀与原文
    断言点: 四个输出内容精确匹配
    防回归: 若 json 模式退回纯文本，脚本解析会失败，本用例失败
    """
    output = Output("json")

    output.warning("careful")
    assert json.loads(capsys.readouterr().out) == {"status": "warning", "message": "careful"}

    output.info("note")
    assert json.loads(capsys.readouterr().out) == {"status": "info", "message": "note"}

    text_output = Output("text")
    text_output.warning("careful")
    assert capsys.readouterr().out.strip() == "[WARN] careful"

    text_output.info("note")
    assert capsys.readouterr().out.strip() == "note"


def test_output_format_validation_and_switching():
    """TC-CLI-140 | Output 拒绝非法格式并在切换后返回新格式

    输入: Output("xml")；Output("text").set_format("xml")；set_format("json")
    预期输出: 两次 ValueError，消息含 "Invalid format: xml"；合法切换后 get_format() == "json"
    断言点: 异常类型 + 消息前缀 + 切换后的 get_format
    防回归: 若去掉格式校验，非法格式会静默退化为文本输出，本用例失败
    """
    with pytest.raises(ValueError, match="Invalid format: xml"):
        Output("xml")

    output = Output("text")
    with pytest.raises(ValueError, match="Invalid format: xml"):
        output.set_format("xml")

    output.set_format("json")
    assert output.get_format() == "json"


# --------------------------------------------------------------------------- #
# i18n
# --------------------------------------------------------------------------- #

@pytest.fixture
def i18n_state():
    """Snapshot/restore I18n class-level state (singleton, class attributes)."""
    saved_lang = I18n._current_lang
    saved_translations = {key: dict(value) for key, value in I18n._translations.items()}
    saved_loaded = I18n._loaded
    saved_dir = I18n._lang_dir
    try:
        yield
    finally:
        I18n._current_lang = saved_lang
        I18n._translations = saved_translations
        I18n._loaded = saved_loaded
        I18n._lang_dir = saved_dir


def test_i18n_switch_language_and_read_back(i18n_state):
    """TC-CLI-141 | set_language 切换语言后 get_language 与 t() 同步变化

    输入: set_language("zh")，读取 cli.goodbye
    预期输出: get_language() == "zh"；t("cli.goodbye") == "再见！"
    断言点: 语言码 + 中文文案精确值
    防回归: 若切换语言不重载文件或 get_language 未更新，本用例失败
    """
    I18n.set_language("zh")

    assert I18n.get_language() == "zh"
    assert t("cli.goodbye") == "再见！"


def test_i18n_missing_key_falls_back_to_english(i18n_state):
    """TC-CLI-142 | 当前语言缺少键时回退英文，仍缺失时返回默认值/键名

    输入: 中文下读取仅英文存在的键 "debug.request"；以及完全不存在的 "no.such.key"
    预期输出: 前者返回英文模板 "HTTP {method} {url}"；
              后者返回传入的 default；不传 default 时返回键名本身
    断言点: 三个返回值精确匹配
    防回归: 若回退逻辑被删，中文界面会出现键名，本用例失败
    """
    I18n.set_language("zh")

    assert t("debug.request") == "HTTP {method} {url}"
    assert t("no.such.key", "fallback") == "fallback"
    assert t("no.such.key") == "no.such.key"


def test_i18n_unknown_language_file_falls_back_to_english(i18n_state):
    """TC-CLI-143 | 不存在的语言文件回退到 en.yaml

    输入: set_language("de")（没有 de.yaml）
    预期输出: get_language() == "de"，但 t("cli.goodbye") 仍能取到英文 "Goodbye!"
    断言点: 语言码 + 回退文案
    防回归: 若缺少文件时直接清空翻译，界面会显示键名，本用例失败
    """
    I18n.set_language("de")

    assert I18n.get_language() == "de"
    assert t("cli.goodbye") == "Goodbye!"


def test_i18n_missing_language_directory_returns_key(i18n_state, tmp_path):
    """TC-CLI-144 | 语言目录为空（连 en.yaml 都没有）时保留已有翻译并返回键名

    输入: I18n._lang_dir 指向空目录；set_language("en") 与 set_language("de")
    预期输出: 两次都不抛异常，已加载的英文翻译未被清空，t("cli.goodbye") 仍为 "Goodbye!"
    断言点: 无异常 + 回退文案（说明缺失目录不会覆盖既有翻译）
    防回归: 若缺少 en.yaml 时把翻译表清空，界面会显示键名，本用例失败
    """
    I18n._lang_dir = Path(tmp_path)

    I18n.set_language("en")
    I18n.set_language("de")

    assert t("cli.goodbye") == "Goodbye!"


def test_i18n_without_yaml_support_keeps_existing_translations(i18n_state, monkeypatch):
    """TC-CLI-145 | 缺少 PyYAML 时不加载文件，已有翻译保持不变

    输入: HAS_YAML=False；预先写入哨兵翻译后调用 _load_language("en")
    预期输出: t("cli.goodbye") 仍为哨兵值
    断言点: 哨兵值未被覆盖
    防回归: 若 HAS_YAML 判断被删，导入会因 yaml 缺失而崩溃，本用例失败
    """
    I18n._translations["en"] = {"cli": {"goodbye": "SENTINEL"}}
    monkeypatch.setattr(i18n_module, "HAS_YAML", False)

    I18n()._load_language("en")

    assert t("cli.goodbye") == "SENTINEL"


def test_i18n_load_error_yields_empty_translation(i18n_state, monkeypatch):
    """TC-CLI-146 | YAML 解析异常被捕获，该语言翻译置空并回退键名

    输入: yaml.safe_load 抛 RuntimeError；_load_language("en")
    预期输出: 不抛异常；t("cli.goodbye") 返回键名（翻译表被置为 {}）
    断言点: 无异常 + 返回键名
    防回归: 若解析异常未捕获，CLI 启动即崩溃，本用例失败
    """
    monkeypatch.setattr(i18n_module.yaml, "safe_load", mock.Mock(side_effect=RuntimeError("bad yaml")))
    I18n._translations.pop("en", None)

    I18n()._load_language("en")

    assert t("cli.goodbye") == "cli.goodbye"


def test_i18n_format_missing_variable_returns_template(i18n_state):
    """TC-CLI-147 | format 缺少插值变量时返回未格式化的模板

    输入: tf("cli.intro")（模板需要 version）
    预期输出: 返回值含 "{version}" 占位符且不抛异常
    断言点: 占位符存在
    防回归: 若 KeyError 未捕获，帮助信息渲染会崩溃，本用例失败
    """
    assert "{version}" in tf("cli.intro")
