"""
CLI framework command abstract base class tests

Tests the BaseCommand interface definition and default behavior.
"""

import pytest
from argparse import ArgumentParser, Namespace
from agent_registry.cli.base import BaseCommand


class MockCommand(BaseCommand):
    """Mock command for testing"""
    
    @property
    def name(self) -> str:
        return "mock"
    
    @property
    def help_text(self) -> str:
        return "Mock command for testing"
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommandWithAliases(BaseCommand):
    """Mock command with aliases"""
    
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
    """Mock command with subcommands"""
    
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
    """Mock command with argument validation"""
    
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
    """Mock command with error handling"""
    
    @property
    def name(self) -> str:
        return "error"
    
    @property
    def help_text(self) -> str:
        return "Command that may raise error"
    
    def execute(self, args: Namespace) -> int:
        raise ValueError("Something went wrong")


class TestBaseCommandAbstract:
    """Abstract method tests"""
    
    def test_name_abstract(self):
        """name property must be implemented"""
        with pytest.raises(TypeError):
            BaseCommand()
    
    def test_help_text_abstract(self):
        """help_text property must be implemented"""
        class IncompleteCommand(BaseCommand):
            @property
            def name(self):
                return "incomplete"
        
        with pytest.raises(TypeError):
            IncompleteCommand()
    
    def test_execute_abstract(self):
        """execute method must be implemented"""
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
    """Property tests"""
    
    def test_name_property(self):
        """name property"""
        cmd = MockCommand()
        assert cmd.name == "mock"
    
    def test_help_text_property(self):
        """help_text property"""
        cmd = MockCommand()
        assert cmd.help_text == "Mock command for testing"
    
    def test_aliases_default_empty(self):
        """aliases default to empty list"""
        cmd = MockCommand()
        assert cmd.aliases == []
    
    def test_aliases_custom(self):
        """custom aliases"""
        cmd = MockCommandWithAliases()
        assert cmd.aliases == ["run", "up"]
    
    def test_subcommands_default_empty(self):
        """subcommands default to empty dict"""
        cmd = MockCommand()
        assert cmd.subcommands == {}
    
    def test_subcommands_custom(self):
        """custom subcommands"""
        cmd = MockCommandWithSubcommands()
        assert "list" in cmd.subcommands
        assert "query" in cmd.subcommands


class TestBaseCommandMethods:
    """Method tests"""
    
    def test_add_arguments_default(self):
        """default add_arguments does nothing"""
        cmd = MockCommand()
        parser = ArgumentParser()
        cmd.add_arguments(parser)
        # No arguments added, parser should only have default arguments
        assert parser.parse_args([]) is not None
    
    def test_validate_default_returns_none(self):
        """default validate returns None"""
        cmd = MockCommand()
        args = Namespace()
        result = cmd.validate(args)
        assert result is None
    
    def test_validate_custom(self):
        """custom validate"""
        cmd = MockCommandWithValidation()
        args = Namespace(required_field=None)
        result = cmd.validate(args)
        assert result == "Missing required field"
        
        args = Namespace(required_field="value")
        result = cmd.validate(args)
        assert result is None
    
    def test_execute_returns_exit_code(self):
        """execute returns exit code"""
        cmd = MockCommand()
        args = Namespace()
        result = cmd.execute(args)
        assert result == 0
    
    def test_handle_error_returns_1(self, capsys):
        """handle_error returns 1 by default"""
        cmd = MockCommand()
        error = ValueError("test error")
        result = cmd.handle_error(error, debug=False)
        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err
    
    def test_handle_error_debug_mode(self, capsys):
        """handle_error debug mode prints stack trace"""
        cmd = MockCommand()
        error = ValueError("test error")
        result = cmd.handle_error(error, debug=True)
        assert result == 1
        captured = capsys.readouterr()
        # Debug mode outputs traceback with error message
        assert len(captured.err) > 0 or len(captured.out) > 0


class TestSubcommandMethods:
    """Subcommand method tests"""
    
    def test_has_subcommands_false(self):
        """returns False when no subcommands"""
        cmd = MockCommand()
        assert cmd.has_subcommands() == False
    
    def test_has_subcommands_true(self):
        """returns True when has subcommands"""
        cmd = MockCommandWithSubcommands()
        assert cmd.has_subcommands() == True
    
    def test_get_subcommand_exists(self):
        """get existing subcommand"""
        cmd = MockCommandWithSubcommands()
        subcmd = cmd.get_subcommand("list")
        assert subcmd is not None
        assert subcmd.name == "mock"
    
    def test_get_subcommand_not_exists(self):
        """get non-existing subcommand"""
        cmd = MockCommandWithSubcommands()
        subcmd = cmd.get_subcommand("unknown")
        assert subcmd is None


class TestFullHelp:
    """Full help text tests"""
    
    def test_full_help_basic(self):
        """basic help"""
        cmd = MockCommand()
        help_text = cmd.get_full_help()
        assert "mock" in help_text
        assert "Mock command for testing" in help_text
    
    def test_full_help_with_aliases(self):
        """help with aliases"""
        cmd = MockCommandWithAliases()
        help_text = cmd.get_full_help()
        assert "Aliases:" in help_text
        assert "run" in help_text
        assert "up" in help_text
    
    def test_full_help_with_subcommands(self):
        """help with subcommands"""
        cmd = MockCommandWithSubcommands()
        help_text = cmd.get_full_help()
        assert "Subcommands:" in help_text
        assert "list" in help_text
        assert "query" in help_text


class TestRepr:
    """String representation tests"""
    
    def test_repr(self):
        """repr format"""
        cmd = MockCommand()
        repr_str = repr(cmd)
        assert "MockCommand" in repr_str
        assert "mock" in repr_str