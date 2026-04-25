"""
CLI框架命令抽象基类测试

测试BaseCommand的接口定义和默认行为。
"""

import pytest
from argparse import ArgumentParser, Namespace
from agent_registry.cli.base import BaseCommand


class MockCommand(BaseCommand):
    """测试用的Mock命令"""
    
    @property
    def name(self) -> str:
        return "mock"
    
    @property
    def help_text(self) -> str:
        return "Mock command for testing"
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommandWithAliases(BaseCommand):
    """带别名的Mock命令"""
    
    @property
    def name(self) -> str:
        return "start"
    
    @property
    def help_text(self) -> str:
        return "Start the service"
    
    @property
    def aliases(self) -> list:
        return ["run", "up"]
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommandWithSubcommands(BaseCommand):
    """带子命令的Mock命令"""
    
    @property
    def name(self) -> str:
        return "agent"
    
    @property
    def help_text(self) -> str:
        return "Agent management"
    
    @property
    def subcommands(self) -> dict:
        return {
            "list": MockCommand(),
            "query": MockCommand(),
        }
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommandWithValidation(BaseCommand):
    """带参数校验的Mock命令"""
    
    @property
    def name(self) -> str:
        return "validate"
    
    @property
    def help_text(self) -> str:
        return "Command with validation"
    
    def validate(self, args: Namespace) -> str:
        if not args.required_field:
            return "Missing required field"
        return None
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommandWithErrorHandling(BaseCommand):
    """带错误处理的Mock命令"""
    
    @property
    def name(self) -> str:
        return "error"
    
    @property
    def help_text(self) -> str:
        return "Command that may raise error"
    
    def execute(self, args: Namespace) -> int:
        raise ValueError("Something went wrong")


class TestBaseCommandAbstract:
    """抽象方法测试"""
    
    def test_name_abstract(self):
        """name必须实现"""
        with pytest.raises(TypeError):
            BaseCommand()
    
    def test_help_text_abstract(self):
        """help_text必须实现"""
        class IncompleteCommand(BaseCommand):
            @property
            def name(self):
                return "incomplete"
        
        with pytest.raises(TypeError):
            IncompleteCommand()
    
    def test_execute_abstract(self):
        """execute必须实现"""
        class IncompleteCommand(BaseCommand):
            @property
            def name(self):
                return "incomplete"
            
            @property
            def help_text(self):
                return "Incomplete"
        
        with pytest.raises(TypeError):
            IncompleteCommand()


class TestBaseCommandProperties:
    """属性测试"""
    
    def test_name_property(self):
        """name属性"""
        cmd = MockCommand()
        assert cmd.name == "mock"
    
    def test_help_text_property(self):
        """help_text属性"""
        cmd = MockCommand()
        assert cmd.help_text == "Mock command for testing"
    
    def test_aliases_default_empty(self):
        """aliases默认为空"""
        cmd = MockCommand()
        assert cmd.aliases == []
    
    def test_aliases_custom(self):
        """自定义aliases"""
        cmd = MockCommandWithAliases()
        assert cmd.aliases == ["run", "up"]
    
    def test_subcommands_default_empty(self):
        """subcommands默认为空"""
        cmd = MockCommand()
        assert cmd.subcommands == {}
    
    def test_subcommands_custom(self):
        """自定义subcommands"""
        cmd = MockCommandWithSubcommands()
        assert "list" in cmd.subcommands
        assert "query" in cmd.subcommands


class TestBaseCommandMethods:
    """方法测试"""
    
    def test_add_arguments_default(self):
        """默认add_arguments不做任何事"""
        cmd = MockCommand()
        parser = ArgumentParser()
        cmd.add_arguments(parser)
        # 无参数添加，parser应该只有默认参数
        assert parser.parse_args([]) is not None
    
    def test_validate_default_returns_none(self):
        """默认validate返回None"""
        cmd = MockCommand()
        args = Namespace()
        result = cmd.validate(args)
        assert result is None
    
    def test_validate_custom(self):
        """自定义validate"""
        cmd = MockCommandWithValidation()
        args = Namespace(required_field=None)
        result = cmd.validate(args)
        assert result == "Missing required field"
        
        args = Namespace(required_field="value")
        result = cmd.validate(args)
        assert result is None
    
    def test_execute_returns_exit_code(self):
        """execute返回退出码"""
        cmd = MockCommand()
        args = Namespace()
        result = cmd.execute(args)
        assert result == 0
    
    def test_handle_error_returns_1(self, capsys):
        """handle_error默认返回1"""
        cmd = MockCommand()
        error = ValueError("test error")
        result = cmd.handle_error(error, debug=False)
        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err
    
    def test_handle_error_debug_mode(self, capsys):
        """handle_error调试模式打印堆栈"""
        cmd = MockCommand()
        error = ValueError("test error")
        result = cmd.handle_error(error, debug=True)
        assert result == 1
        captured = capsys.readouterr()
        # 调试模式下会输出traceback，包含错误信息
        assert len(captured.err) > 0 or len(captured.out) > 0


class TestSubcommandMethods:
    """子命令相关方法测试"""
    
    def test_has_subcommands_false(self):
        """无子命令时返回False"""
        cmd = MockCommand()
        assert cmd.has_subcommands() == False
    
    def test_has_subcommands_true(self):
        """有子命令时返回True"""
        cmd = MockCommandWithSubcommands()
        assert cmd.has_subcommands() == True
    
    def test_get_subcommand_exists(self):
        """获取存在的子命令"""
        cmd = MockCommandWithSubcommands()
        subcmd = cmd.get_subcommand("list")
        assert subcmd is not None
        assert subcmd.name == "mock"
    
    def test_get_subcommand_not_exists(self):
        """获取不存在的子命令"""
        cmd = MockCommandWithSubcommands()
        subcmd = cmd.get_subcommand("unknown")
        assert subcmd is None


class TestFullHelp:
    """完整帮助测试"""
    
    def test_full_help_basic(self):
        """基本帮助"""
        cmd = MockCommand()
        help_text = cmd.get_full_help()
        assert "mock" in help_text
        assert "Mock command for testing" in help_text
    
    def test_full_help_with_aliases(self):
        """带别名的帮助"""
        cmd = MockCommandWithAliases()
        help_text = cmd.get_full_help()
        assert "Aliases:" in help_text
        assert "run" in help_text
        assert "up" in help_text
    
    def test_full_help_with_subcommands(self):
        """带子命令的帮助"""
        cmd = MockCommandWithSubcommands()
        help_text = cmd.get_full_help()
        assert "Subcommands:" in help_text
        assert "list" in help_text
        assert "query" in help_text


class TestRepr:
    """字符串表示测试"""
    
    def test_repr(self):
        """repr格式"""
        cmd = MockCommand()
        repr_str = repr(cmd)
        assert "MockCommand" in repr_str
        assert "mock" in repr_str