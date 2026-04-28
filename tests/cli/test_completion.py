"""
CLI framework Tab completion tests

Tests the interactive CLI auto-completion functionality.
"""

import pytest
from argparse import Namespace

from agent_registry.cli.core import CLI, InteractiveCLI
from agent_registry.cli.base import BaseCommand
from agent_registry.cli.registry import CommandRegistry


class MockCommand(BaseCommand):
    """Mock command"""
    
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
    """Mock command with subcommands"""
    
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
    """Command completion tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_complete_command_names(self):
        """complete top-level command names"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # Test completing "m"
        completions = cli.completenames("m", "", 0, 1)
        assert "mock" in completions
    
    def test_complete_empty_returns_all(self):
        """empty input returns all commands"""
        CLI.register(MockCommand)
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli.completenames("", "", 0, 0)
        assert "mock" in completions
        assert "parent" in completions
    
    def test_complete_internal_commands(self):
        """internal command completion"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        completions = cli.completenames("e", "", 0, 1)
        assert "exit" in completions
        
        completions = cli.completenames("c", "", 0, 1)
        assert "cmds" in completions
        assert "commands" in completions
    
    def test_get_names_includes_registered(self):
        """get_names includes registered commands"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        names = cli.get_names()
        assert "mock" in names
        assert "exit" in names
        assert "cmds" in names


class TestSubcommandCompletion:
    """Subcommand completion tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_complete_subcommands(self):
        """complete subcommands"""
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # Complete parent's subcommands
        completions = cli._complete_command("parent", "l", "parent l", 7, 8)
        assert "list" in completions
        
        completions = cli._complete_command("parent", "g", "parent g", 7, 8)
        assert "get" in completions
    
    def test_complete_all_subcommands(self):
        """complete all subcommands"""
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_command("parent", "", "parent ", 7, 7)
        assert "list" in completions
        assert "get" in completions
        assert "delete" in completions
    
    def test_subcommands_not_in_root_completions(self):
        """subcommands not in top-level completions"""
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # "list" should not be completed as top-level command
        completions = cli.completenames("l", "", 0, 1)
        assert "list" not in completions


class TestArgumentCompletion:
    """Argument completion tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_complete_long_option(self):
        """complete long options"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # Complete mock command arguments
        completions = cli._complete_arguments(MockCommand(), "--opt", ["mock"])
        assert "--option-a" in completions
        assert "--option-b" in completions
    
    def test_complete_short_option(self):
        """complete short options"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_arguments(MockCommand(), "-", ["mock"])
        assert "-a" in completions
        assert "-b" in completions
    
    def test_complete_partial_option(self):
        """complete partial option names"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_arguments(MockCommand(), "--opt", ["mock"])
        assert "--option-a" in completions
        assert "--option-b" in completions
    
    def test_complete_after_subcommand(self):
        """complete arguments after subcommand"""
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        # parent list --opt
        completions = cli._complete_command("parent", "--opt", "parent list --opt", 12, 17)
        assert "--option-a" in completions
        assert "--option-b" in completions


class TestGeneratedMethods:
    """Dynamically generated method tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_do_method_generated(self):
        """do_ method generated"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert hasattr(cli, "do_mock")
        assert callable(cli.do_mock)
    
    def test_complete_method_generated(self):
        """complete_ method generated"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert hasattr(cli, "complete_mock")
        assert callable(cli.complete_mock)
    
    def test_do_method_docstring(self):
        """do_ method has docstring"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert cli.do_mock.__doc__ == "Mock command"
    
    def test_multiple_commands_methods(self):
        """multi-command method generation"""
        CLI.register(MockCommand)
        CLI.register(MockCommandWithSub)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert hasattr(cli, "do_mock")
        assert hasattr(cli, "do_parent")
        assert hasattr(cli, "complete_mock")
        assert hasattr(cli, "complete_parent")


class TestInternalCommands:
    """Internal command tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_do_exit(self, capsys):
        """exit command"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_exit("")
        assert result == True  # cmd.Cmd uses True to exit
        captured = capsys.readouterr()
        assert "Goodbye" in captured.out
    
    def test_do_quit_alias(self):
        """quit alias"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_quit("")
        assert result == True
    
    def test_do_q_alias(self):
        """q alias"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_q("")
        assert result == True
    
    def test_do_cmds(self, capsys):
        """cmds command"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli.do_cmds("")
        captured = capsys.readouterr()
        assert "Available commands" in captured.out
        assert "mock" in captured.out
    
    def test_do_commands_alias(self, capsys):
        """commands alias"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli.do_commands("")
        captured = capsys.readouterr()
        assert "Available commands" in captured.out


class TestEmptyLine:
    """Empty line tests"""
    
    def test_emptyline_returns_none(self):
        """empty line does nothing"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.emptyline()
        assert result is None


class TestDefaultHandler:
    """Default handler tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_default_empty(self):
        """empty input"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        cli.default("")
        # No output, no error
    
    def test_default_unknown_command(self, capsys):
        """unknown command"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        cli.default("unknown")
        captured = capsys.readouterr()
        # argparse errors go to stderr
        assert "error" in captured.err or "invalid" in captured.err


class TestCommandExecution:
    """Command execution tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_execute_registered_command(self, capsys):
        """execute registered command"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli._execute_command("mock")
        # Successful execution
    
    def test_execute_with_arguments(self, capsys):
        """execute with arguments"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli._execute_command("mock --option-a value")
    
    def test_execute_version(self, capsys):
        """-v shows version"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli._execute_command("-v")
        captured = capsys.readouterr()
        assert "agent-registry" in captured.out
        assert "v1.0.0" in captured.out


class TestCLI:
    """CLI facade class tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_singleton(self):
        """singleton"""
        cli1 = CLI()
        cli2 = CLI()
        assert cli1 is cli2
    
    def test_register(self):
        """register command"""
        CLI.register(MockCommand)
        assert CLI.get_registry().has("mock")
    
    def test_run_exits(self):
        """run method"""
        CLI.register(MockCommand)
        cli = CLI()
        
        # Simulate user immediately exits
        import unittest.mock
        with unittest.mock.patch('sys.stdin', unittest.mock.MagicMock()):
            # Simple test that run method exists
            assert hasattr(cli, 'run')
            assert callable(cli.run)