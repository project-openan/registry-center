"""
CLI框架异常测试

测试所有异常类型的退出码和消息格式。
"""

import pytest
import builtins
from agent_registry.cli.exceptions import (
    CLIError,
    CommandNotFoundError,
    ValidationError,
    ConfigError,
    ServiceError,
    PermissionError,
    ArgumentMissingError,
    SubcommandNotFoundError,
    CommandConflictError,
)


class TestCLIError:
    """CLIError基类测试"""
    
    def test_default_exit_code(self):
        """默认退出码应为1"""
        error = CLIError("test error")
        assert error.exit_code == 1
        assert error.message == "test error"
    
    def test_custom_exit_code(self):
        """可自定义退出码"""
        error = CLIError("test error", exit_code=99)
        assert error.exit_code == 99
    
    def test_str_representation(self):
        """字符串表示应包含退出码"""
        error = CLIError("test error", exit_code=1)
        assert str(error) == "[ExitCode:1] test error"
    
    def test_inherits_from_exception(self):
        """应继承自Exception"""
        error = CLIError("test")
        assert isinstance(error, Exception)
    
    def test_can_be_raised_and_caught(self):
        """可被抛出和捕获"""
        with pytest.raises(CLIError) as exc_info:
            raise CLIError("test error")
        assert exc_info.value.exit_code == 1


class TestCommandNotFoundError:
    """CommandNotFoundError测试"""
    
    def test_exit_code_127(self):
        """退出码应为127"""
        error = CommandNotFoundError("unknown")
        assert error.exit_code == 127
    
    def test_message_format(self):
        """消息格式应包含命令名"""
        error = CommandNotFoundError("unknown")
        assert "Command not found" in error.message
        assert "'unknown'" in error.message
    
    def test_inherits_cli_error(self):
        """应继承CLIError"""
        error = CommandNotFoundError("test")
        assert isinstance(error, CLIError)


class TestValidationError:
    """ValidationError测试"""
    
    def test_exit_code_2(self):
        """退出码应为2"""
        error = ValidationError("invalid argument")
        assert error.exit_code == 2
    
    def test_message_preserved(self):
        """消息应被保留"""
        error = ValidationError("invalid argument")
        assert error.message == "invalid argument"
    
    def test_inherits_cli_error(self):
        """应继承CLIError"""
        error = ValidationError("test")
        assert isinstance(error, CLIError)


class TestConfigError:
    """ConfigError测试"""
    
    def test_exit_code_3(self):
        """退出码应为3"""
        error = ConfigError("config file not found")
        assert error.exit_code == 3
    
    def test_inherits_cli_error(self):
        """应继承CLIError"""
        error = ConfigError("test")
        assert isinstance(error, CLIError)


class TestServiceError:
    """ServiceError测试"""
    
    def test_exit_code_4(self):
        """退出码应为4"""
        error = ServiceError("service unavailable")
        assert error.exit_code == 4
    
    def test_inherits_cli_error(self):
        """应继承CLIError"""
        error = ServiceError("test")
        assert isinstance(error, CLIError)


class TestPermissionError:
    """PermissionError测试"""
    
    def test_exit_code_5(self):
        """退出码应为5"""
        error = PermissionError("access denied")
        assert error.exit_code == 5
    
    def test_inherits_cli_error(self):
        """应继承CLIError"""
        error = PermissionError("test")
        assert isinstance(error, CLIError)
    
    def test_not_builtins_permission_error(self):
        """不是内置PermissionError"""
        error = PermissionError("test")
        assert not isinstance(error, builtins.PermissionError)


class TestArgumentMissingError:
    """ArgumentMissingError测试"""
    
    def test_exit_code_2(self):
        """退出码应为2（属于校验错误）"""
        error = ArgumentMissingError("name")
        assert error.exit_code == 2
    
    def test_message_format(self):
        """消息格式应包含参数名"""
        error = ArgumentMissingError("name")
        assert "Missing required argument" in error.message
        assert "'name'" in error.message
    
    def test_inherits_cli_error(self):
        """应继承CLIError"""
        error = ArgumentMissingError("test")
        assert isinstance(error, CLIError)


class TestSubcommandNotFoundError:
    """SubcommandNotFoundError测试"""
    
    def test_exit_code_127(self):
        """退出码应为127"""
        error = SubcommandNotFoundError("agent", "unknown")
        assert error.exit_code == 127
    
    def test_message_format(self):
        """消息格式应包含父命令和子命令名"""
        error = SubcommandNotFoundError("agent", "unknown")
        assert "'unknown'" in error.message
        assert "'agent'" in error.message
        assert "Subcommand" in error.message
    
    def test_inherits_cli_error(self):
        """应继承CLIError"""
        error = SubcommandNotFoundError("parent", "child")
        assert isinstance(error, CLIError)


class TestCommandConflictError:
    """CommandConflictError测试"""
    
    def test_exit_code_1(self):
        """退出码应为1"""
        error = CommandConflictError("start")
        assert error.exit_code == 1
    
    def test_message_format(self):
        """消息格式应包含命令名"""
        error = CommandConflictError("start")
        assert "'start'" in error.message
        assert "already registered" in error.message
    
    def test_inherits_cli_error(self):
        """应继承CLIError"""
        error = CommandConflictError("test")
        assert isinstance(error, CLIError)


class TestExitCodeSummary:
    """退出码汇总测试"""
    
    def test_all_exit_codes_different(self):
        """各类异常退出码应有区分"""
        exit_codes = [
            CLIError("test").exit_code,
            CommandNotFoundError("test").exit_code,
            ValidationError("test").exit_code,
            ConfigError("test").exit_code,
            ServiceError("test").exit_code,
            PermissionError("test").exit_code,
            ArgumentMissingError("test").exit_code,
            SubcommandNotFoundError("a", "b").exit_code,
            CommandConflictError("test").exit_code,
        ]
        expected_codes = [1, 127, 2, 3, 4, 5, 2, 127, 1]
        assert exit_codes == expected_codes
    
    def test_validation_and_argument_missing_same_code(self):
        """ValidationError和ArgumentMissingError应使用相同退出码"""
        assert ValidationError("test").exit_code == ArgumentMissingError("test").exit_code
    
    def test_command_not_found_and_subcommand_not_found_same_code(self):
        """CommandNotFoundError和SubcommandNotFoundError应使用相同退出码"""
        assert CommandNotFoundError("test").exit_code == SubcommandNotFoundError("a", "b").exit_code