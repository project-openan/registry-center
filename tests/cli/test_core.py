"""
CLI framework core engine tests

Tests the interactive CLI based on cmd.Cmd.
"""

import pytest
import unittest.mock
from argparse import Namespace

from agent_registry.cli.core import CLI, InteractiveCLI
from agent_registry.cli.base import BaseCommand
from agent_registry.cli.exceptions import CLIError, ValidationError
from agent_registry.cli.registry import CommandRegistry


class MockCommand(BaseCommand):
    """Mock command"""
    
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
    """Failing command"""
    
    @property
    def name(self) -> str:
        return "fail"
    
    @property
    def help_text(self) -> str:
        return "Fail command"
    
    def execute(self, args: Namespace) -> int:
        return 1


class MockErrorCommand(BaseCommand):
    """Error command"""
    
    @property
    def name(self) -> str:
        return "error"
    
    @property
    def help_text(self) -> str:
        return "Error command"
    
    def execute(self, args: Namespace) -> int:
        raise CLIError("Test error", exit_code=4)


class MockValidateCommand(BaseCommand):
    """Command with validation"""
    
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
    """Subcommand"""
    
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
    """Parent command"""
    
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
    """CLI facade class tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_singleton(self):
        """singleton pattern"""
        cli1 = CLI()
        cli2 = CLI()
        assert cli1 is cli2
    
    def test_register_decorator(self):
        """decorator registration"""
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
        """get registry"""
        registry = CLI.get_registry()
        assert isinstance(registry, CommandRegistry)


class TestInteractiveCLI:
    """InteractiveCLI tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_intro(self):
        """intro property"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        assert "agent-registry" in cli.intro
        assert "cmds" in cli.intro
    
    def test_prompt(self):
        """prompt property"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        assert cli.prompt == "agent-registry> "
    
    def test_init_generates_methods(self):
        """init generates methods"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        assert hasattr(cli, "do_mock")
        assert hasattr(cli, "complete_mock")
    
    def test_emptyline(self):
        """empty line handling"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.emptyline()
        assert result is None
    
    def test_do_exit(self, capsys):
        """exit command"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_exit("")
        assert result == True
        captured = capsys.readouterr()
        assert "Goodbye" in captured.out
    
    def test_do_quit(self):
        """quit alias"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        result = cli.do_quit("")
        assert result == True
    
    def test_do_q(self):
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


class TestCommandExecution:
    """Command execution tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_execute_success(self, capsys):
        """successful execution"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        cli._execute_command("mock")
        captured = capsys.readouterr()
        assert "Mock executed" in captured.out
    
    def test_execute_fail(self):
        """failed execution"""
        CLI.register(MockFailCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("fail")
        assert result == 1
    
    def test_execute_error(self, capsys):
        """error execution"""
        CLI.register(MockErrorCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("error")
        assert result == 4
        captured = capsys.readouterr()
        assert "Error:" in captured.out
    
    def test_execute_version(self, capsys):
        """-v version"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("-v")
        assert result == 0
        captured = capsys.readouterr()
        assert "v1.0.0" in captured.out
    
    def test_execute_validation_fail(self, capsys):
        """validation failure"""
        CLI.register(MockValidateCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("validate")
        assert result == 2
    
    def test_execute_validation_pass(self, capsys):
        """validation passed"""
        CLI.register(MockValidateCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("validate --required value")
        assert result == 0
    
    def test_execute_subcommand(self, capsys):
        """subcommand execution"""
        CLI.register(MockParentCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        result = cli._execute_command("parent sub")
        assert result == 0
        captured = capsys.readouterr()
        assert "Sub executed" in captured.out


class TestCompletion:
    """Completion tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_completenames(self):
        """command name completion"""
        CLI.register(MockCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli.completenames("m", "", 0, 1)
        assert "mock" in completions
    
    def test_complete_command(self):
        """command completion method"""
        CLI.register(MockParentCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_command("parent", "su", "parent su", 7, 9)
        assert "sub" in completions
    
    def test_complete_arguments(self):
        """argument completion"""
        CLI.register(MockValidateCommand)
        registry = CLI.get_registry()
        cli = InteractiveCLI(registry)
        
        completions = cli._complete_arguments(MockValidateCommand(), "--", ["validate"])
        assert "--required" in completions
    
    def test_get_names(self):
        """get command names list"""
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
    """Global options tests"""
    
    def setup_method(self):
        CLI._registry.clear()
    
    def test_parse_version(self):
        """parse -v"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        argv, opts = cli._parse_global_options(["-v", "mock"])
        assert opts.get("version") == True
        assert "mock" in argv
    
    def test_parse_debug(self):
        """parse -x"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        argv, opts = cli._parse_global_options(["-x", "mock"])
        assert opts.get("debug") == True
        assert "mock" in argv
    
    def test_parse_both(self):
        """parse -v -x"""
        registry = CommandRegistry()
        cli = InteractiveCLI(registry)
        
        argv, opts = cli._parse_global_options(["-v", "-x", "mock"])
        assert opts.get("version") == True
        assert opts.get("debug") == True