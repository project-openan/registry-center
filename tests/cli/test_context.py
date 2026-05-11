"""
CLI framework context tests

Tests Context class global state management functionality.
"""

import pytest
from argparse import Namespace
from agent_registry.cli.context import Context


class TestContext:
    """Context basic tests"""
    
    def test_default_values(self):
        """default values test"""
        ctx = Context()
        assert ctx.debug == False
        assert ctx.config_file is None
        assert ctx.output_format == 'text'
        assert ctx.command_path == ''
    
    def test_set_debug(self):
        """set debug mode"""
        ctx = Context()
        ctx.set_debug(True)
        assert ctx.debug == True
        assert ctx.is_debug() == True
    
    def test_set_config_file(self):
        """set config file"""
        ctx = Context()
        ctx.set_config_file("etc/conf/server.conf")
        assert ctx.config_file == "etc/conf/server.conf"
        assert ctx.get_config_file() == "etc/conf/server.conf"
    
    def test_set_output_format(self):
        """set output format"""
        ctx = Context()
        ctx.set_output_format('json')
        assert ctx.output_format == 'json'
        assert ctx.get_output_format() == 'json'
    
    def test_set_output_format_invalid(self):
        """setting invalid output format should raise exception"""
        ctx = Context()
        with pytest.raises(ValueError):
            ctx.set_output_format('invalid')
    
    def test_repr(self):
        """string representation"""
        ctx = Context()
        ctx.debug = True
        ctx.config_file = "config.conf"
        repr_str = repr(ctx)
        assert "debug=True" in repr_str
        assert "config=config.conf" in repr_str


class TestContextFromArgs:
    """Create Context from args tests"""
    
    def test_from_args_basic(self):
        """create from basic args"""
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
        """use default values when args missing attributes"""
        args = Namespace()
        ctx = Context.from_args(args)
        assert ctx.debug == False
        assert ctx.config_file is None
        assert ctx.output_format == 'text'
    
    def test_from_args_partial_attributes(self):
        """partial attributes present"""
        args = Namespace(debug=True)
        ctx = Context.from_args(args)
        assert ctx.debug == True
        assert ctx.config_file is None
        assert ctx.output_format == 'text'


class TestContextMethods:
    """Context method tests"""
    
    def test_is_debug(self):
        """is_debug method"""
        ctx = Context()
        assert ctx.is_debug() == False
        
        ctx.set_debug(True)
        assert ctx.is_debug() == True
    
    def test_get_config_file(self):
        """get_config_file method"""
        ctx = Context()
        assert ctx.get_config_file() is None
        
        ctx.set_config_file("path/to/config")
        assert ctx.get_config_file() == "path/to/config"
    
    def test_get_output_format(self):
        """get_output_format method"""
        ctx = Context()
        assert ctx.get_output_format() == 'text'
        
        ctx.set_output_format('table')
        assert ctx.get_output_format() == 'table'
    
    def test_command_path(self):
        """command path"""
        ctx = Context()
        ctx.command_path = "agent list"
        assert ctx.command_path == "agent list"