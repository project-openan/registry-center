"""
CLI框架核心引擎测试

测试基于 cmd.Cmd 的交互式 CLI。
"""

import pytest
import unittest.mock
from argparse import Namespace

from agent_registry.cli.core import CLI, InteractiveCLI
from agent_registry.cli.base import BaseCommand
from agent_registry.cli.exceptions import CLIError, ValidationError
from agent_registry.cli.registry import CommandRegistry


class MockCommand(BaseCommand):
    """Mock 命令"""
    
    @property
    def name(self) -> str:
        return "mock"
    
    @property
    def help_text(self) -> str:
        return "Mock command for testing"
    
    def execute(self, args: Namespace) -> int:
        print("Mock executed")
        return 0


class MockFailCommand(BaseCommand):
    """失败的命令"""
    
    @property
    def name(self) -> str:
        return "fail"
    
    @property
    def help_text(self) -> str:
        return "Fail command"
    
    def execute(self, args: Namespace) -> int:
        return 1


class MockErrorCommand(BaseCommand):
    """错误命令"""
    
    @property
    def name(self) -> str:
        return "error"
    
    @property
    def help_text(self) -> str:
        return "Error command"
    
    def execute(self, args: Namespace) -> int:
        raise CLIError("Test error", exit_code=4)


class MockValidateCommand(BaseCommand):
    """带校验的命令"""
    
    @property
    def name(self) -> str:
        return "validate"
    
    @property
    def help_text(self) -> str:
        return "Validate command"
    
    def validate(self, args):
        if not args.required:
            return "Missing required"
        return None
    
    def add_arguments(self, parser):
        parser.add_argument("--required")
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockSubCommand(BaseCommand):
    """子命令"""
    
    @property
    def name(self) -> str:
        return "sub"
    
    @property
    def help_text(self) -> str:
        return "Sub command"
    
    def execute(self, args: Namespace) -> int:
        print("Sub executed")
        return 0


class MockParentCommand(BaseCommand):
    """父命令"""
    
    @property
    def name(self) -> str:
        return "parent"
    
    @property
    def help_text(self) -> str:
        return "Parent command"
    
    @property
    def subcommands(self):
        return {"sub": MockSubCommand()}
    
    def execute(self, args: Namespace) -> int:
        return 0


class TestCLI:
    """CLI 门面类测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_singleton(self):
        """单例模式"""
        cli1 = CLI()
        cli2 = CLI()
        assert cli1 is cli2
    
    def test_register_decorator(self):
        """装饰器注册"""
        CLI._registry.clear()
        
        @CLI.register
        class TestCmd(BaseCommand):
            @property
            def name(self):
                return "test"
            
            @property
            def help_text(self):
                return "Test"
            
            def execute(self, args):
                return 0
        
        assert CLI.get_registry().has("test")
    
    def test_get_registry(self):
        """获取注册表"""
        registry = CLI.get_registry()
        assert isinstance(registry, CommandRegistry)


class TestInteractiveCLI:
    """InteractiveCLI 测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_intro(self):
        """intro 属性"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        assert "agent-registry" in cli.intro
        assert "cmds" in cli.intro
    
    def test_prompt(self):
        """prompt 属性"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        assert cli.prompt == "agent-registry> "
    
    def test_init_generates_methods(self):
        """初始化生成方法"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert hasattr(cli, "do_mock")
        assert hasattr(cli, "complete_mock")
    
    def test_emptyline(self):
        """空行处理"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.emptyline()
        assert result is None
    
    def test_do_exit(self, capsys):
        """exit 命令"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_exit("")
        assert result == True
        captured = capsys.readouterr()
        assert "Goodbye" in captured.out
    
    def test_do_quit(self):
        """quit 别名"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_quit("")
        assert result == True
    
    def test_do_q(self):
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


class TestCommandExecution:
    """命令执行测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_execute_success(self, capsys):
        """成功执行"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli._execute_command("mock")
        captured = capsys.readouterr()
        assert "Mock executed" in captured.out
    
    def test_execute_fail(self):
        """失败执行"""
        CLI.register(MockFailCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("fail")
        assert result == 1
    
    def test_execute_error(self, capsys):
        """错误执行"""
        CLI.register(MockErrorCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("error")
        assert result == 4
        captured = capsys.readouterr()
        assert "Error:" in captured.out
    
    def test_execute_version(self, capsys):
        """-v 版本"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("-v")
        assert result == 0
        captured = capsys.readouterr()
        assert "v1.0.0" in captured.out
    
    def test_execute_validation_fail(self, capsys):
        """校验失败"""
        CLI.register(MockValidateCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("validate")
        assert result == 2
    
    def test_execute_validation_pass(self, capsys):
        """校验通过"""
        CLI.register(MockValidateCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("validate --required value")
        assert result == 0
    
    def test_execute_subcommand(self, capsys):
        """子命令执行"""
        CLI.register(MockParentCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("parent sub")
        assert result == 0
        captured = capsys.readouterr()
        assert "Sub executed" in captured.out


class TestCompletion:
    """补齐测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_completenames(self):
        """命令名补齐"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli.completenames("m", "", 0, 1)
        assert "mock" in completions
    
    def test_complete_command(self):
        """命令补齐方法"""
        CLI.register(MockParentCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_command("parent", "su", "parent su", 7, 9)
        assert "sub" in completions
    
    def test_complete_arguments(self):
        """参数补齐"""
        CLI.register(MockValidateCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_arguments(MockValidateCommand(), "--", ["validate"])
        assert "--required" in completions
    
    def test_get_names(self):
        """获取命令名列表"""
        CLI.register(MockCommand)
        CLI.register(MockParentCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        names = cli.get_names()
        assert "mock" in names
        assert "parent" in names
        assert "exit" in names
        assert "cmds" in names


class TestGlobalOptions:
    """全局选项测试"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_parse_version(self):
        """解析 -v"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        argv, opts = cli._parse_global_options(["-v", "mock"])
        assert opts.get("version") == True
        assert "mock" in argv
    
    def test_parse_debug(self):
        """解析 -x"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        argv, opts = cli._parse_global_options(["-x", "mock"])
        assert opts.get("debug") == True
        assert "mock" in argv
    
    def test_parse_both(self):
        """解析 -v -x"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        argv, opts = cli._parse_global_options(["-v", "-x", "mock"])
        assert opts.get("version") == True
        assert opts.get("debug") == True