"""
CLI框架命令注册表测试

测试CommandRegistry的命令注册和层级隔离功能。
"""

import pytest
from agent_registry.cli.base import BaseCommand
from agent_registry.cli.registry import CommandRegistry, SubcommandResolver
from agent_registry.cli.exceptions import CommandConflictError
from argparse import Namespace


class MockCommand1(BaseCommand):
    """测试命令1"""
    
    @property
    def name(self) -> str:
        return "start"
    
    @property
    def help_text(self) -> str:
        return "Start command"
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommand2(BaseCommand):
    """测试命令2"""
    
    @property
    def name(self) -> str:
        return "stop"
    
    @property
    def help_text(self) -> str:
        return "Stop command"
    
    def execute(self, args: Namespace) -> int:
        return 0


class MockCommandWithSub(BaseCommand):
    """带子命令的测试命令"""
    
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
    """重复命令（用于测试冲突）"""
    
    @property
    def name(self) -> str:
        return "start"  # 与MockCommand1同名
    
    @property
    def help_text(self) -> str:
        return "Duplicate start"
    
    def execute(self, args: Namespace) -> int:
        return 0


class TestCommandRegistry:
    """CommandRegistry测试"""
    
    def setup_method(self):
        """每个测试方法前清空注册表"""
        self.registry = CommandRegistry()
    
    def test_register_command(self):
        """注册命令"""
        self.registry.register(MockCommand1)
        assert self.registry.has("start")
    
    def test_register_multiple_commands(self):
        """注册多个命令"""
        self.registry.register(MockCommand1)
        self.registry.register(MockCommand2)
        assert self.registry.count() == 2
        assert self.registry.has("start")
        assert self.registry.has("stop")
    
    def test_register_duplicate_raises_error(self):
        """注册重复命令应抛异常"""
        self.registry.register(MockCommand1)
        with pytest.raises(CommandConflictError):
            self.registry.register(DuplicateCommand)
    
    def test_get_command(self):
        """获取命令"""
        self.registry.register(MockCommand1)
        cmd_class = self.registry.get("start")
        assert cmd_class == MockCommand1
    
    def test_get_command_not_exists(self):
        """获取不存在的命令"""
        cmd_class = self.registry.get("unknown")
        assert cmd_class is None
    
    def test_get_all(self):
        """获取所有命令"""
        self.registry.register(MockCommand1)
        self.registry.register(MockCommand2)
        all_cmds = self.registry.get_all()
        assert len(all_cmds) == 2
        assert "start" in all_cmds
        assert "stop" in all_cmds
    
    def test_get_all_returns_copy(self):
        """get_all返回副本"""
        self.registry.register(MockCommand1)
        all_cmds = self.registry.get_all()
        all_cmds["new"] = MockCommand2  # 修改副本
        assert not self.registry.has("new")  # 原注册表不受影响
    
    def test_has_command(self):
        """检查命令是否存在"""
        self.registry.register(MockCommand1)
        assert self.registry.has("start") == True
        assert self.registry.has("unknown") == False
    
    def test_count(self):
        """统计命令数量"""
        assert self.registry.count() == 0
        self.registry.register(MockCommand1)
        assert self.registry.count() == 1
        self.registry.register(MockCommand2)
        assert self.registry.count() == 2
    
    def test_clear(self):
        """清空注册表"""
        self.registry.register(MockCommand1)
        self.registry.register(MockCommand2)
        self.registry.clear()
        assert self.registry.count() == 0
    
    def test_get_command_names(self):
        """获取命令名称列表"""
        self.registry.register(MockCommand1)
        self.registry.register(MockCommand2)
        names = self.registry.get_command_names()
        assert "start" in names
        assert "stop" in names
        assert len(names) == 2


class TestSubcommandResolver:
    """SubcommandResolver测试"""
    
    def test_resolve_existing_subcommand(self):
        """解析存在的子命令"""
        parent = MockCommandWithSub()
        subcmd = SubcommandResolver.resolve(parent, "list")
        assert subcmd is not None
        assert subcmd.name == "start"  # MockCommand1的name
    
    def test_resolve_non_existing_subcommand(self):
        """解析不存在的子命令"""
        parent = MockCommandWithSub()
        subcmd = SubcommandResolver.resolve(parent, "unknown")
        assert subcmd is None
    
    def test_has_subcommand_true(self):
        """检查存在的子命令"""
        parent = MockCommandWithSub()
        assert SubcommandResolver.has_subcommand(parent, "list") == True
    
    def test_has_subcommand_false(self):
        """检查不存在的子命令"""
        parent = MockCommandWithSub()
        assert SubcommandResolver.has_subcommand(parent, "unknown") == False
    
    def test_has_subcommand_parent_without_subs(self):
        """父命令无子命令时"""
        parent = MockCommand1()
        assert SubcommandResolver.has_subcommand(parent, "list") == False
    
    def test_get_subcommand_names(self):
        """获取子命令名称列表"""
        parent = MockCommandWithSub()
        names = SubcommandResolver.get_subcommand_names(parent)
        assert "list" in names
        assert "query" in names
        assert len(names) == 2
    
    def test_get_subcommand_names_empty(self):
        """无子命令时返回空列表"""
        parent = MockCommand1()
        names = SubcommandResolver.get_subcommand_names(parent)
        assert names == []


class TestLevelIsolation:
    """层级隔离测试"""
    
    def setup_method(self):
        self.registry = CommandRegistry()
    
    def test_one_level_commands_unique(self):
        """一级命令全局唯一"""
        self.registry.register(MockCommand1)
        
        # 再次注册同名命令应抛异常
        with pytest.raises(CommandConflictError):
            self.registry.register(DuplicateCommand)
    
    def test_subcommands_in_parent_scope(self):
        """子命令在父命令作用域内"""
        parent = MockCommandWithSub()
        
        # agent命令有list子命令
        assert SubcommandResolver.has_subcommand(parent, "list")
    
    def test_different_parents_can_have_same_subcommand_name(self):
        """不同父命令可以有同名子命令"""
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
                return {"list": MockCommand2()}  # 同名"list"，但不同命令
            
            def execute(self, args):
                return 0
        
        # agent和cert都有"list"子命令，但它们是不同的
        agent = AgentCommand()
        cert = CertCommand()
        
        agent_list = SubcommandResolver.resolve(agent, "list")
        cert_list = SubcommandResolver.resolve(cert, "list")
        
        assert agent_list is not None
        assert cert_list is not None
        assert agent_list.name == "start"  # MockCommand1
        assert cert_list.name == "stop"    # MockCommand2
        # agent.list 和 cert.list 是不同的命令
    
    def test_subcommand_not_global(self):
        """子命令不是全局命令"""
        self.registry.register(MockCommandWithSub)
        
        # "list"是agent的子命令，不是一级命令
        assert not self.registry.has("list")
        assert self.registry.count() == 1  # 只有agent