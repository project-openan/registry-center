"""
CLI framework command registry tests

Tests CommandRegistry command registration and level isolation functionality.
"""

import pytest
from agent_registry.cli.base import BaseCommand
from agent_registry.cli.registry import CommandRegistry, SubcommandResolver
from agent_registry.cli.exceptions import CommandConflictError
from argparse import Namespace


class MockCommand1(BaseCommand):
    """Test command 1"""
    
    @property
    def name(self) -> str:
        return "start"
    
    @property
    def help_text(self) -> str:
        return "Start command"
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommand2(BaseCommand):
    """Test command 2"""
    
    @property
    def name(self) -> str:
        return "stop"
    
    @property
    def help_text(self) -> str:
        return "Stop command"
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommandWithSub(BaseCommand):
    """Test command with subcommands"""
    
    @property
    def name(self) -> str:
        return "agent"
    
    @property
    def help_text(self) -> str:
        return "Agent command"
    
    @property
    def subcommands(self) -> dict:
        return {
            "list": MockCommand1(),
            "query": MockCommand2(),
        }
    
    def execute(self, args: Namespace) -> int:
        return 0


class DuplicateCommand(BaseCommand):
    """Duplicate command (for testing conflicts)"""
    
    @property
    def name(self) -> str:
        return "start"  # Same name as MockCommand1
    
    @property
    def help_text(self) -> str:
        return "Duplicate start"
    
    def execute(self, args: Namespace) -> int:
        return 0


class TestCommandRegistry:
    """CommandRegistry tests"""
    
    def setup_method(self):
        """clear registry before each test method"""
        self.registry = CommandRegistry()
    
    def test_register_command(self):
        """register command"""
        self.registry.register(MockCommand1)
        assert self.registry.has("start")
    
    def test_register_multiple_commands(self):
        """register multiple commands"""
        self.registry.register(MockCommand1)
        self.registry.register(MockCommand2)
        assert self.registry.count() == 2
        assert self.registry.has("start")
        assert self.registry.has("stop")
    
    def test_register_duplicate_raises_error(self):
        """registering duplicate command should raise exception"""
        self.registry.register(MockCommand1)
        with pytest.raises(CommandConflictError):
            self.registry.register(DuplicateCommand)
    
    def test_get_command(self):
        """get command"""
        self.registry.register(MockCommand1)
        cmd_class = self.registry.get("start")
        assert cmd_class == MockCommand1
    
    def test_get_command_not_exists(self):
        """get non-existing command"""
        cmd_class = self.registry.get("unknown")
        assert cmd_class is None
    
    def test_get_all(self):
        """get all commands"""
        self.registry.register(MockCommand1)
        self.registry.register(MockCommand2)
        all_cmds = self.registry.get_all()
        assert len(all_cmds) == 2
        assert "start" in all_cmds
        assert "stop" in all_cmds
    
    def test_get_all_returns_copy(self):
        """get_all returns copy"""
        self.registry.register(MockCommand1)
        all_cmds = self.registry.get_all()
        all_cmds["new"] = MockCommand2  # Modify copy
        assert not self.registry.has("new")  # Original registry unaffected
    
    def test_has_command(self):
        """check if command exists"""
        self.registry.register(MockCommand1)
        assert self.registry.has("start") == True
        assert self.registry.has("unknown") == False
    
    def test_count(self):
        """count commands"""
        assert self.registry.count() == 0
        self.registry.register(MockCommand1)
        assert self.registry.count() == 1
        self.registry.register(MockCommand2)
        assert self.registry.count() == 2
    
    def test_clear(self):
        """clear registry"""
        self.registry.register(MockCommand1)
        self.registry.register(MockCommand2)
        self.registry.clear()
        assert self.registry.count() == 0
    
    def test_get_command_names(self):
        """get command names list"""
        self.registry.register(MockCommand1)
        self.registry.register(MockCommand2)
        names = self.registry.get_command_names()
        assert "start" in names
        assert "stop" in names
        assert len(names) == 2


class TestSubcommandResolver:
    """SubcommandResolver tests"""
    
    def test_resolve_existing_subcommand(self):
        """resolve existing subcommand"""
        parent = MockCommandWithSub()
        subcmd = SubcommandResolver.resolve(parent, "list")
        assert subcmd is not None
        assert subcmd.name == "start"  # MockCommand1's name
    
    def test_resolve_non_existing_subcommand(self):
        """resolve non-existing subcommand"""
        parent = MockCommandWithSub()
        subcmd = SubcommandResolver.resolve(parent, "unknown")
        assert subcmd is None
    
    def test_has_subcommand_true(self):
        """check existing subcommand"""
        parent = MockCommandWithSub()
        assert SubcommandResolver.has_subcommand(parent, "list") == True
    
    def test_has_subcommand_false(self):
        """check non-existing subcommand"""
        parent = MockCommandWithSub()
        assert SubcommandResolver.has_subcommand(parent, "unknown") == False
    
    def test_has_subcommand_parent_without_subs(self):
        """parent without subcommands"""
        parent = MockCommand1()
        assert SubcommandResolver.has_subcommand(parent, "list") == False
    
    def test_get_subcommand_names(self):
        """get subcommand names list"""
        parent = MockCommandWithSub()
        names = SubcommandResolver.get_subcommand_names(parent)
        assert "list" in names
        assert "query" in names
        assert len(names) == 2
    
    def test_get_subcommand_names_empty(self):
        """return empty list when no subcommands"""
        parent = MockCommand1()
        names = SubcommandResolver.get_subcommand_names(parent)
        assert names == []


class TestLevelIsolation:
    """Level isolation tests"""
    
    def setup_method(self):
        self.registry = CommandRegistry()
    
    def test_one_level_commands_unique(self):
        """top-level commands globally unique"""
        self.registry.register(MockCommand1)
        
        # Registering same-name command again should raise exception
        with pytest.raises(CommandConflictError):
            self.registry.register(DuplicateCommand)
    
    def test_subcommands_in_parent_scope(self):
        """subcommands in parent command scope"""
        parent = MockCommandWithSub()
        
        # agent command has list subcommand
        assert SubcommandResolver.has_subcommand(parent, "list")
    
    def test_different_parents_can_have_same_subcommand_name(self):
        """different parent commands can have same-name subcommands"""
        class AgentCommand(BaseCommand):
            @property
            def name(self):
                return "agent"
            
            @property
            def help_text(self):
                return "Agent"
            
            @property
            def subcommands(self):
                return {"list": MockCommand1()}
            
            def execute(self, args):
                return 0
        
        class CertCommand(BaseCommand):
            @property
            def name(self):
                return "cert"
            
            @property
            def help_text(self):
                return "Cert"
            
            @property
            def subcommands(self):
                return {"list": MockCommand2()}  # Same "list" name, but different command
            
            def execute(self, args):
                return 0
        
        # Both agent and cert have "list" subcommand, but they are different
        agent = AgentCommand()
        cert = CertCommand()
        
        agent_list = SubcommandResolver.resolve(agent, "list")
        cert_list = SubcommandResolver.resolve(cert, "list")
        
        assert agent_list is not None
        assert cert_list is not None
        assert agent_list.name == "start"  # MockCommand1
        assert cert_list.name == "stop"    # MockCommand2
        # agent.list and cert.list are different commands
    
    def test_subcommand_not_global(self):
        """subcommands are not global commands"""
        self.registry.register(MockCommandWithSub)
        
        # "list" is agent's subcommand, not a top-level command
        assert not self.registry.has("list")
        assert self.registry.count() == 1  # Only agent