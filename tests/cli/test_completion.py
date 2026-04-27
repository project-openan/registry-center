"""
CLI 框架 Tab 补齐测试

测试交互式 CLI 的自动补齐功能。
"""

import pytest
from argparse import Namespace

from agent_registry.cli.core import CLI, InteractiveCLI
from agent_registry.cli.base import BaseCommand
from agent_registry.cli.registry import CommandRegistry


class MockCommand(BaseCommand):
    """Mock 命令"""
    
    @property
    def name(self) -> str:
        return "mock"
    
    @property
    def help_text(self) -> str:
        return "Mock command"
    
    def add_arguments(self, parser):
        parser.add_argument("--option-a", "-a", help="Option A")
        parser.add_argument("--option-b", "-b", help="Option B")
        parser.add_argument("positional", nargs="?", help="Positional arg")
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommandWithSub(BaseCommand):
    """带子命令的 Mock 命令"""
    
    @property
    def name(self) -> str:
        return "parent"
    
    @property
    def help_text(self) -> str:
        return "Parent command"
    
    @property
    def subcommands(self) -> dict:
        return {
            "list": MockCommand(),
            "get": MockCommand(),
            "delete": MockCommand(),
        }
    
    def execute(self, args: Namespace) -> int:
        return 0


class TestCommandCompletion:
    """命令补齐测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_complete_command_names(self):
        """补齐一级命令名"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # 测试补齐 "m"
        completions = cli.completenames("m", "", 0, 1)
        assert "mock" in completions
    
    def test_complete_empty_returns_all(self):
        """空输入返回所有命令"""
        CLI.register(MockCommand)
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli.completenames("", "", 0, 0)
        assert "mock" in completions
        assert "parent" in completions
    
    def test_complete_internal_commands(self):
        """内部命令补齐"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        completions = cli.completenames("e", "", 0, 1)
        assert "exit" in completions
        
        completions = cli.completenames("c", "", 0, 1)
        assert "cmds" in completions
        assert "commands" in completions
    
    def test_get_names_includes_registered(self):
        """get_names 包含注册命令"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        names = cli.get_names()
        assert "mock" in names
        assert "exit" in names
        assert "cmds" in names


class TestSubcommandCompletion:
    """子命令补齐测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_complete_subcommands(self):
        """补齐子命令"""
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # 补齐 parent 的子命令
        completions = cli._complete_command("parent", "l", "parent l", 7, 8)
        assert "list" in completions
        
        completions = cli._complete_command("parent", "g", "parent g", 7, 8)
        assert "get" in completions
    
    def test_complete_all_subcommands(self):
        """补齐所有子命令"""
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_command("parent", "", "parent ", 7, 7)
        assert "list" in completions
        assert "get" in completions
        assert "delete" in completions
    
    def test_subcommands_not_in_root_completions(self):
        """子命令不在一级补齐中"""
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # "list" 不应该作为一级命令补齐
        completions = cli.completenames("l", "", 0, 1)
        assert "list" not in completions


class TestArgumentCompletion:
    """参数补齐测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_complete_long_option(self):
        """补齐长选项"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # 补齐 mock 命令的参数
        completions = cli._complete_arguments(MockCommand(), "--opt", ["mock"])
        assert "--option-a" in completions
        assert "--option-b" in completions
    
    def test_complete_short_option(self):
        """补齐短选项"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_arguments(MockCommand(), "-", ["mock"])
        assert "-a" in completions
        assert "-b" in completions
    
    def test_complete_partial_option(self):
        """补齐部分选项名"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_arguments(MockCommand(), "--opt", ["mock"])
        assert "--option-a" in completions
        assert "--option-b" in completions
    
    def test_complete_after_subcommand(self):
        """子命令后补齐参数"""
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # parent list --opt
        completions = cli._complete_command("parent", "--opt", "parent list --opt", 12, 17)
        assert "--option-a" in completions
        assert "--option-b" in completions


class TestGeneratedMethods:
    """动态生成方法测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_do_method_generated(self):
        """do_方法已生成"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert hasattr(cli, "do_mock")
        assert callable(cli.do_mock)
    
    def test_complete_method_generated(self):
        """complete_方法已生成"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert hasattr(cli, "complete_mock")
        assert callable(cli.complete_mock)
    
    def test_do_method_docstring(self):
        """do_方法有文档"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert cli.do_mock.__doc__ == "Mock command"
    
    def test_multiple_commands_methods(self):
        """多命令方法生成"""
        CLI.register(MockCommand)
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert hasattr(cli, "do_mock")
        assert hasattr(cli, "do_parent")
        assert hasattr(cli, "complete_mock")
        assert hasattr(cli, "complete_parent")


class TestInternalCommands:
    """内部命令测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_do_exit(self, capsys):
        """exit 命令"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_exit("")
        assert result == True  # cmd.Cmd 用 True 表示退出
        captured = capsys.readouterr()
        assert "Goodbye" in captured.out
    
    def test_do_quit_alias(self):
        """quit 别名"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_quit("")
        assert result == True
    
    def test_do_q_alias(self):
        """q 别名"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_q("")
        assert result == True
    
    def test_do_cmds(self, capsys):
        """cmds 命令"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli.do_cmds("")
        captured = capsys.readouterr()
        assert "Available commands" in captured.out
        assert "mock" in captured.out
    
    def test_do_commands_alias(self, capsys):
        """commands 别名"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli.do_commands("")
        captured = capsys.readouterr()
        assert "Available commands" in captured.out


class TestEmptyLine:
    """空行测试"""
    
    def test_emptyline_returns_none(self):
        """空行不执行"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.emptyline()
        assert result is None


class TestDefaultHandler:
    """默认处理器测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_default_empty(self):
        """空输入"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        cli.default("")
        # 无输出，无错误
    
    def test_default_unknown_command(self, capsys):
        """未知命令"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        cli.default("unknown")
        captured = capsys.readouterr()
        # argparse 错误输出到 stderr
        assert "error" in captured.err or "invalid" in captured.err


class TestCommandExecution:
    """命令执行测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_execute_registered_command(self, capsys):
        """执行注册命令"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli._execute_command("mock")
        # 成功执行
    
    def test_execute_with_arguments(self, capsys):
        """带参数执行"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli._execute_command("mock --option-a value")
    
    def test_execute_version(self, capsys):
        """-v 显示版本"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli._execute_command("-v")
        captured = capsys.readouterr()
        assert "agent-registry" in captured.out
        assert "v1.0.0" in captured.out


class TestCLI:
    """CLI 门面类测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_singleton(self):
        """单例"""
        cli1 = CLI()
        cli2 = CLI()
        assert cli1 is cli2
    
    def test_register(self):
        """注册命令"""
        CLI.register(MockCommand)
        assert CLI.get_registry().has("mock")
    
    def test_run_exits(self):
        """run 方法"""
        CLI.register(MockCommand)
        cli = CLI()
        
        # 模拟用户立即退出
        import unittest.mock
        with unittest.mock.patch('sys.stdin', unittest.mock.MagicMock()):
            # 简单测试 run 方法存在
            assert hasattr(cli, 'run')
            assert callable(cli.run)