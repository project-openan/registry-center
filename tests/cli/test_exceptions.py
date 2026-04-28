"""
CLI framework exception tests

Tests all exception types' exit codes and message formats.
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
    """CLIError base class tests"""
    
    def test_default_exit_code(self):
        """default exit code should be 1"""
        error = CLIError("test error")
        assert error.exit_code == 1
        assert error.message == "test error"
    
    def test_custom_exit_code(self):
        """custom exit code"""
        error = CLIError("test error", exit_code=99)
        assert error.exit_code == 99
    
    def test_str_representation(self):
        """string representation should include exit code"""
        error = CLIError("test error", exit_code=1)
        assert str(error) == "[ExitCode:1] test error"
    
    def test_inherits_from_exception(self):
        """should inherit from Exception"""
        error = CLIError("test")
        assert isinstance(error, Exception)
    
    def test_can_be_raised_and_caught(self):
        """can be raised and caught"""
        with pytest.raises(CLIError) as exc_info:
            raise CLIError("test error")
        assert exc_info.value.exit_code == 1


class TestCommandNotFoundError:
    """CommandNotFoundError tests"""
    
    def test_exit_code_127(self):
        """exit code should be 127"""
        error = CommandNotFoundError("unknown")
        assert error.exit_code == 127
    
    def test_message_format(self):
        """message format should include command name"""
        error = CommandNotFoundError("unknown")
        assert "Command not found" in error.message
        assert "'unknown'" in error.message
    
    def test_inherits_cli_error(self):
        """should inherit CLIError"""
        error = CommandNotFoundError("test")
        assert isinstance(error, CLIError)


class TestValidationError:
    """ValidationError tests"""
    
    def test_exit_code_2(self):
        """exit code should be 2"""
        error = ValidationError("invalid argument")
        assert error.exit_code == 2
    
    def test_message_preserved(self):
        """message should be preserved"""
        error = ValidationError("invalid argument")
        assert error.message == "invalid argument"
    
    def test_inherits_cli_error(self):
        """should inherit CLIError"""
        error = ValidationError("test")
        assert isinstance(error, CLIError)


class TestConfigError:
    """ConfigError tests"""
    
    def test_exit_code_3(self):
        """exit code should be 3"""
        error = ConfigError("config file not found")
        assert error.exit_code == 3
    
    def test_inherits_cli_error(self):
        """should inherit CLIError"""
        error = ConfigError("test")
        assert isinstance(error, CLIError)


class TestServiceError:
    """ServiceError tests"""
    
    def test_exit_code_4(self):
        """exit code should be 4"""
        error = ServiceError("service unavailable")
        assert error.exit_code == 4
    
    def test_inherits_cli_error(self):
        """should inherit CLIError"""
        error = ServiceError("test")
        assert isinstance(error, CLIError)


class TestPermissionError:
    """PermissionError tests"""
    
    def test_exit_code_5(self):
        """exit code should be 5"""
        error = PermissionError("access denied")
        assert error.exit_code == 5
    
    def test_inherits_cli_error(self):
        """should inherit CLIError"""
        error = PermissionError("test")
        assert isinstance(error, CLIError)
    
    def test_not_builtins_permission_error(self):
        """not builtins PermissionError"""
        error = PermissionError("test")
        assert not isinstance(error, builtins.PermissionError)


class TestArgumentMissingError:
    """ArgumentMissingError tests"""
    
    def test_exit_code_2(self):
        """exit code should be 2 (validation error)"""
        error = ArgumentMissingError("name")
        assert error.exit_code == 2
    
    def test_message_format(self):
        """message format should include argument name"""
        error = ArgumentMissingError("name")
        assert "Missing required argument" in error.message
        assert "'name'" in error.message
    
    def test_inherits_cli_error(self):
        """should inherit CLIError"""
        error = ArgumentMissingError("test")
        assert isinstance(error, CLIError)


class TestSubcommandNotFoundError:
    """SubcommandNotFoundError tests"""
    
    def test_exit_code_127(self):
        """exit code should be 127"""
        error = SubcommandNotFoundError("agent", "unknown")
        assert error.exit_code == 127
    
    def test_message_format(self):
        """message format should include parent and subcommand names"""
        error = SubcommandNotFoundError("agent", "unknown")
        assert "'unknown'" in error.message
        assert "'agent'" in error.message
        assert "Subcommand" in error.message
    
    def test_inherits_cli_error(self):
        """should inherit CLIError"""
        error = SubcommandNotFoundError("parent", "child")
        assert isinstance(error, CLIError)


class TestCommandConflictError:
    """CommandConflictError tests"""
    
    def test_exit_code_1(self):
        """exit code should be 1"""
        error = CommandConflictError("start")
        assert error.exit_code == 1
    
    def test_message_format(self):
        """message format should include command name"""
        error = CommandConflictError("start")
        assert "'start'" in error.message
        assert "already registered" in error.message
    
    def test_inherits_cli_error(self):
        """should inherit CLIError"""
        error = CommandConflictError("test")
        assert isinstance(error, CLIError)


class TestExitCodeSummary:
    """Exit code summary tests"""
    
    def test_all_exit_codes_different(self):
        """different exception types should have distinct exit codes"""
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
        """ValidationError and ArgumentMissingError should use same exit code"""
        assert ValidationError("test").exit_code == ArgumentMissingError("test").exit_code
    
    def test_command_not_found_and_subcommand_not_found_same_code(self):
        """CommandNotFoundError and SubcommandNotFoundError should use same exit code"""
        assert CommandNotFoundError("test").exit_code == SubcommandNotFoundError("a", "b").exit_code