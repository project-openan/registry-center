"""
CLI framework output formatting tests

Tests Output class multiple output format functionality.
"""

import pytest
import json
import sys
from io import StringIO
from agent_registry.cli.output import Output


class TestOutput:
    """Output basic tests"""
    
    def test_default_format(self):
        """default format is text"""
        output = Output()
        assert output.format == 'text'
        assert output.get_format() == 'text'
    
    def test_set_format_json(self):
        """set json format"""
        output = Output('json')
        assert output.format == 'json'
    
    def test_set_format_table(self):
        """set table format"""
        output = Output('table')
        assert output.format == 'table'
    
    def test_set_format_invalid(self):
        """setting invalid format should raise exception"""
        with pytest.raises(ValueError):
            Output('invalid')
    
    def test_set_format_method(self):
        """set format via method"""
        output = Output()
        output.set_format('json')
        assert output.format == 'json'
    
    def test_set_format_method_invalid(self):
        """setting invalid format via method should raise exception"""
        output = Output()
        with pytest.raises(ValueError):
            output.set_format('invalid')


class TestTextOutput:
    """Text format output tests"""
    
    def test_print_dict(self, capsys):
        """output dict"""
        output = Output('text')
        output.print({'name': 'agent1', 'version': '1.0'})
        captured = capsys.readouterr()
        assert 'name: agent1' in captured.out
        assert 'version: 1.0' in captured.out
    
    def test_print_list(self, capsys):
        """output list"""
        output = Output('text')
        output.print(['item1', 'item2', 'item3'])
        captured = capsys.readouterr()
        assert 'item1' in captured.out
        assert 'item2' in captured.out
    
    def test_print_string(self, capsys):
        """output string"""
        output = Output('text')
        output.print('hello world')
        captured = capsys.readouterr()
        assert 'hello world' in captured.out
    
    def test_print_with_title(self, capsys):
        """output with title"""
        output = Output('text')
        output.print({'key': 'value'}, title='Test Output')
        captured = capsys.readouterr()
        assert 'Test Output' in captured.out
        assert '===' in captured.out


class TestJsonOutput:
    """JSON format output tests"""
    
    def test_print_dict(self, capsys):
        """output dict"""
        output = Output('json')
        output.print({'name': 'agent1', 'version': '1.0'})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data['name'] == 'agent1'
        assert data['version'] == '1.0'
    
    def test_print_list(self, capsys):
        """output list"""
        output = Output('json')
        output.print(['item1', 'item2'])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == ['item1', 'item2']
    
    def test_print_ensure_ascii_false(self, capsys):
        """non-ASCII output"""
        output = Output('json')
        output.print({'message': 'hello world'})
        captured = capsys.readouterr()
        assert 'hello world' in captured.out


class TestTableOutput:
    """Table format output tests"""
    
    def test_print_dict(self, capsys):
        """output dict (table)"""
        output = Output('table')
        output.print({'name': 'agent1', 'version': '1.0'})
        captured = capsys.readouterr()
        assert 'name' in captured.out or 'Key' in captured.out
    
    def test_print_list_of_dicts(self, capsys):
        """output list of dicts"""
        output = Output('table')
        output.print([
            {'name': 'agent1', 'org': 'org1'},
            {'name': 'agent2', 'org': 'org2'}
        ])
        captured = capsys.readouterr()
        assert 'agent1' in captured.out or 'name' in captured.out
    
    def test_print_with_title(self, capsys):
        """output with title"""
        output = Output('table')
        output.print([{'a': 1}], title='Test Table')
        captured = capsys.readouterr()
        assert 'Test Table' in captured.out


class TestMessageOutput:
    """Message output tests"""
    
    def test_success_text(self, capsys):
        """success message (text)"""
        output = Output('text')
        output.success("Operation completed")
        captured = capsys.readouterr()
        assert '[OK]' in captured.out
        assert 'Operation completed' in captured.out
    
    def test_success_json(self, capsys):
        """success message (json)"""
        output = Output('json')
        output.success("Operation completed")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data['status'] == 'success'
        assert data['message'] == 'Operation completed'
    
    def test_error_text(self, capsys):
        """error message (text)"""
        output = Output('text')
        output.error("Failed to execute")
        captured = capsys.readouterr()
        assert '[ERROR]' in captured.err
        assert 'Failed to execute' in captured.err
    
    def test_error_json(self, capsys):
        """error message (json)"""
        output = Output('json')
        output.error("Failed to execute")
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data['status'] == 'error'
        assert data['message'] == 'Failed to execute'
    
    def test_warning_text(self, capsys):
        """warning message (text)"""
        output = Output('text')
        output.warning("This is a warning")
        captured = capsys.readouterr()
        assert '[WARN]' in captured.out
        assert 'This is a warning' in captured.out
    
    def test_warning_json(self, capsys):
        """warning message (json)"""
        output = Output('json')
        output.warning("This is a warning")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data['status'] == 'warning'
    
    def test_info_text(self, capsys):
        """info message (text)"""
        output = Output('text')
        output.info("This is info")
        captured = capsys.readouterr()
        assert 'This is info' in captured.out
    
    def test_info_json(self, capsys):
        """info message (json)"""
        output = Output('json')
        output.info("This is info")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data['status'] == 'info'


class TestOutputFormatSwitch:
    """Output format switching tests"""
    
    def test_switch_format(self, capsys):
        """switch format"""
        output = Output('text')
        output.print({'key': 'value'})
        captured1 = capsys.readouterr()
        assert 'key: value' in captured1.out
        
        output.set_format('json')
        output.print({'key': 'value'})
        captured2 = capsys.readouterr()
        data = json.loads(captured2.out)
        assert data['key'] == 'value'