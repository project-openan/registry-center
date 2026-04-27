"""
CLI框架上下文测试

测试Context类的全局状态管理功能。
"""

import pytest
from argparse import Namespace
from agent_registry.cli.context import Context


class TestContext:
    """Context基础测试"""
    
    def test_default_values(self):
        """默认值测试"""
        ctx = Context()
        assert ctx.debug == False
        assert ctx.config_file is None
        assert ctx.output_format == 'text'
        assert ctx.command_path == ''
    
    def test_set_debug(self):
        """设置调试模式"""
        ctx = Context()
        ctx.set_debug(True)
        assert ctx.debug == True
        assert ctx.is_debug() == True
    
    def test_set_config_file(self):
        """设置配置文件"""
        ctx = Context()
        ctx.set_config_file("etc/conf/server.conf")
        assert ctx.config_file == "etc/conf/server.conf"
        assert ctx.get_config_file() == "etc/conf/server.conf"
    
    def test_set_output_format(self):
        """设置输出格式"""
        ctx = Context()
        ctx.set_output_format('json')
        assert ctx.output_format == 'json'
        assert ctx.get_output_format() == 'json'
    
    def test_set_output_format_invalid(self):
        """设置无效输出格式应抛异常"""
        ctx = Context()
        with pytest.raises(ValueError):
            ctx.set_output_format('invalid')
    
    def test_repr(self):
        """字符串表示"""
        ctx = Context()
        ctx.debug = True
        ctx.config_file = "config.conf"
        repr_str = repr(ctx)
        assert "debug=True" in repr_str
        assert "config=config.conf" in repr_str


class TestContextFromArgs:
    """从参数创建Context测试"""
    
    def test_from_args_basic(self):
        """从基本参数创建"""
        args = Namespace(
            debug=True,
            config_file="test.conf",
            output='json'
        )
        ctx = Context.from_args(args)
        assert ctx.debug == True
        assert ctx.config_file == "test.conf"
        assert ctx.output_format == 'json'
    
    def test_from_args_missing_attributes(self):
        """参数缺少属性时使用默认值"""
        args = Namespace()
        ctx = Context.from_args(args)
        assert ctx.debug == False
        assert ctx.config_file is None
        assert ctx.output_format == 'text'
    
    def test_from_args_partial_attributes(self):
        """部分属性存在"""
        args = Namespace(debug=True)
        ctx = Context.from_args(args)
        assert ctx.debug == True
        assert ctx.config_file is None
        assert ctx.output_format == 'text'


class TestContextMethods:
    """Context方法测试"""
    
    def test_is_debug(self):
        """is_debug方法"""
        ctx = Context()
        assert ctx.is_debug() == False
        
        ctx.set_debug(True)
        assert ctx.is_debug() == True
    
    def test_get_config_file(self):
        """get_config_file方法"""
        ctx = Context()
        assert ctx.get_config_file() is None
        
        ctx.set_config_file("path/to/config")
        assert ctx.get_config_file() == "path/to/config"
    
    def test_get_output_format(self):
        """get_output_format方法"""
        ctx = Context()
        assert ctx.get_output_format() == 'text'
        
        ctx.set_output_format('table')
        assert ctx.get_output_format() == 'table'
    
    def test_command_path(self):
        """命令路径"""
        ctx = Context()
        ctx.command_path = "agent list"
        assert ctx.command_path == "agent list"