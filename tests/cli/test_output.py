"""
CLI框架输出格式化测试

测试Output类的多种输出格式功能。
"""

import pytest
import json
import sys
from io import StringIO
from agent_registry.cli.output import Output


class TestOutput:
    """Output基础测试"""
    
    def test_default_format(self):
        """默认格式为text"""
        output = Output()
        assert output.format == 'text'
        assert output.get_format() == 'text'
    
    def test_set_format_json(self):
        """设置json格式"""
        output = Output('json')
        assert output.format == 'json'
    
    def test_set_format_table(self):
        """设置table格式"""
        output = Output('table')
        assert output.format == 'table'
    
    def test_set_format_invalid(self):
        """设置无效格式应抛异常"""
        with pytest.raises(ValueError):
            Output('invalid')
    
    def test_set_format_method(self):
        """通过方法设置格式"""
        output = Output()
        output.set_format('json')
        assert output.format == 'json'
    
    def test_set_format_method_invalid(self):
        """通过方法设置无效格式应抛异常"""
        output = Output()
        with pytest.raises(ValueError):
            output.set_format('invalid')


class TestTextOutput:
    """文本格式输出测试"""
    
    def test_print_dict(self, capsys):
        """输出字典"""
        output = Output('text')
        output.print({'name': 'agent1', 'version': '1.0'})
        captured = capsys.readouterr()
        assert 'name: agent1' in captured.out
        assert 'version: 1.0' in captured.out
    
    def test_print_list(self, capsys):
        """输出列表"""
        output = Output('text')
        output.print(['item1', 'item2', 'item3'])
        captured = capsys.readouterr()
        assert 'item1' in captured.out
        assert 'item2' in captured.out
    
    def test_print_string(self, capsys):
        """输出字符串"""
        output = Output('text')
        output.print('hello world')
        captured = capsys.readouterr()
        assert 'hello world' in captured.out
    
    def test_print_with_title(self, capsys):
        """带标题输出"""
        output = Output('text')
        output.print({'key': 'value'}, title='Test Output')
        captured = capsys.readouterr()
        assert 'Test Output' in captured.out
        assert '===' in captured.out


class TestJsonOutput:
    """JSON格式输出测试"""
    
    def test_print_dict(self, capsys):
        """输出字典"""
        output = Output('json')
        output.print({'name': 'agent1', 'version': '1.0'})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data['name'] == 'agent1'
        assert data['version'] == '1.0'
    
    def test_print_list(self, capsys):
        """输出列表"""
        output = Output('json')
        output.print(['item1', 'item2'])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == ['item1', 'item2']
    
    def test_print_ensure_ascii_false(self, capsys):
        """中文输出"""
        output = Output('json')
        output.print({'message': '你好世界'})
        captured = capsys.readouterr()
        assert '你好世界' in captured.out


class TestTableOutput:
    """表格格式输出测试"""
    
    def test_print_dict(self, capsys):
        """输出字典（表格）"""
        output = Output('table')
        output.print({'name': 'agent1', 'version': '1.0'})
        captured = capsys.readouterr()
        assert 'name' in captured.out or 'Key' in captured.out
    
    def test_print_list_of_dicts(self, capsys):
        """输出字典列表"""
        output = Output('table')
        output.print([
            {'name': 'agent1', 'org': 'org1'},
            {'name': 'agent2', 'org': 'org2'}
        ])
        captured = capsys.readouterr()
        assert 'agent1' in captured.out or 'name' in captured.out
    
    def test_print_with_title(self, capsys):
        """带标题输出"""
        output = Output('table')
        output.print([{'a': 1}], title='Test Table')
        captured = capsys.readouterr()
        assert 'Test Table' in captured.out


class TestMessageOutput:
    """消息输出测试"""
    
    def test_success_text(self, capsys):
        """成功消息（text）"""
        output = Output('text')
        output.success("Operation completed")
        captured = capsys.readouterr()
        assert '[OK]' in captured.out
        assert 'Operation completed' in captured.out
    
    def test_success_json(self, capsys):
        """成功消息（json）"""
        output = Output('json')
        output.success("Operation completed")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data['status'] == 'success'
        assert data['message'] == 'Operation completed'
    
    def test_error_text(self, capsys):
        """错误消息（text）"""
        output = Output('text')
        output.error("Failed to execute")
        captured = capsys.readouterr()
        assert '[ERROR]' in captured.err
        assert 'Failed to execute' in captured.err
    
    def test_error_json(self, capsys):
        """错误消息（json）"""
        output = Output('json')
        output.error("Failed to execute")
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data['status'] == 'error'
        assert data['message'] == 'Failed to execute'
    
    def test_warning_text(self, capsys):
        """警告消息（text）"""
        output = Output('text')
        output.warning("This is a warning")
        captured = capsys.readouterr()
        assert '[WARN]' in captured.out
        assert 'This is a warning' in captured.out
    
    def test_warning_json(self, capsys):
        """警告消息（json）"""
        output = Output('json')
        output.warning("This is a warning")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data['status'] == 'warning'
    
    def test_info_text(self, capsys):
        """信息消息（text）"""
        output = Output('text')
        output.info("This is info")
        captured = capsys.readouterr()
        assert 'This is info' in captured.out
    
    def test_info_json(self, capsys):
        """信息消息（json）"""
        output = Output('json')
        output.info("This is info")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data['status'] == 'info'


class TestOutputFormatSwitch:
    """输出格式切换测试"""
    
    def test_switch_format(self, capsys):
        """切换格式"""
        output = Output('text')
        output.print({'key': 'value'})
        captured1 = capsys.readouterr()
        assert 'key: value' in captured1.out
        
        output.set_format('json')
        output.print({'key': 'value'})
        captured2 = capsys.readouterr()
        data = json.loads(captured2.out)
        assert data['key'] == 'value'