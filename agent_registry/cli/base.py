"""
CLI Framework Command Abstract Base Class

Defines the standard interface for CLI commands. All concrete commands must inherit from this class.
"""

import sys
import json
from abc import ABC, abstractmethod
from argparse import ArgumentParser, Namespace
from typing import List, Dict, Optional, Any


class BaseCommand(ABC):
    """
    CLI Command Abstract Base Class
    
    All CLI commands must inherit from this class. The framework automatically generates help info for each command.
    
    Level Isolation Design:
    - Level-1 commands: Globally unique, registered via @CLI.register decorator
    - Subcommands: Defined in parent command's subcommands attribute, only valid within parent scope
    
    Example:
        @CLI.register
        class StartCommand(BaseCommand):
            name = "start"
            help_text = "Start the service"
            
            def execute(self, args):
                print("Starting...")
                return 0
    
    Attributes:
        name: Command name (must implement)
        help_text: Command help description (must implement)
        aliases: Command aliases (optional)
        subcommands: Subcommands dictionary (optional)
        display_config: Output display configuration (optional)
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        Command name
        
        Used for command-line invocation, e.g., "start" in `agent-registry start`
        
        Returns:
            str: Command name
        """
        pass
    
    @property
    @abstractmethod
    def help_text(self) -> str:
        """
        Command help description
        
        Displayed in -h help information
        
        Returns:
            str: Help description
        """
        pass
    
    @property
    def aliases(self) -> List[str]:
        """
        Command aliases
        
        E.g., ["run"] makes `agent-registry run` equivalent to `agent-registry start`
        
        Returns:
            List[str]: Alias list
        """
        return []
    
    @property
    def subcommands(self) -> Dict[str, 'BaseCommand']:
        """
        Subcommands dictionary (level isolation)
        
        Subcommands are only valid within current command scope. Different parent commands can have same-named subcommands.
        
        Example:
            class AgentCommand(BaseCommand):
                name = "agent"
                subcommands = {
                    "list": AgentListCommand(),
                    "query": AgentQueryCommand(),
                }
            
            # agent.list is only valid under agent
        
        Returns:
            Dict[str, BaseCommand]: Subcommands dictionary, key is subcommand name, value is command instance
        """
        return {}
    
    @property
    def display_config(self) -> Dict:
        """
        Output display configuration
        
        Defines which fields to display in table format and which to display separately.
        Used by format_output() to generate structured table output.
        
        Structure:
            {
                'table_fields': ['field1', 'field2', ...],  # Fields displayed in table row
                'separate_fields': ['long_field1', ...],     # Fields displayed separately (e.g., JSON)
                'field_labels': {                            # Optional: custom field labels
                    'field1': 'Display Name',
                    'field2': 'Another Name',
                },
            }
        
        Example:
            {
                'table_fields': ['name', 'organization', 'status', 'tags'],
                'separate_fields': ['agentcard', 'agent_card_json'],
                'field_labels': {
                    'name': 'Agent Name',
                    'organization': 'Organization',
                    'status': 'Status',
                    'tags': 'Tags',
                    'agentcard': 'Agent Card',
                }
            }
        
        Returns:
            Dict: Display configuration
        """
        return {}
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        """
        Add command-specific arguments
        
        Subclasses can override this method to add command-specific arguments.
        
        Args:
            parser: argparse ArgumentParser
        """
        pass
    
    def validate(self, args: Namespace) -> Optional[str]:
        """
        Argument validation
        
        Called before execute, for complex argument validation.
        
        Args:
            args: Parsed arguments
            
        Returns:
            str: Error message, None means validation passed
        """
        return None
    
    @abstractmethod
    def execute(self, args: Namespace) -> int:
        """
        Execute command logic
        
        Args:
            args: Parsed argument object
            
        Returns:
            int: Exit code, 0=success, non-0=failure
        """
        pass
    
    def handle_error(self, error: Exception, debug: bool = False) -> int:
        """
        Error handling
        
        Called when execute throws exception.
        
        Args:
            error: Exception object
            debug: Debug mode flag
            
        Returns:
            int: Exit code
        """
        if debug:
            import traceback
            traceback.print_exc()
        else:
            print(f"Error: {error}", file=sys.stderr)
        return 1
    
    def has_subcommands(self) -> bool:
        """
        Check if has subcommands
        
        Returns:
            bool: Whether has subcommands
        """
        return len(self.subcommands) > 0
    
    def get_subcommand(self, name: str) -> Optional['BaseCommand']:
        """
        Get subcommand
        
        Args:
            name: Subcommand name
            
        Returns:
            BaseCommand: Subcommand instance, None if not exists
        """
        return self.subcommands.get(name)
    
    def get_full_help(self) -> str:
        """
        Get full help information
        
        Returns:
            str: Full help including command name, help text, aliases, subcommands
        """
        lines = []
        
        # Command header
        lines.append(f"Command: {self.name}")
        lines.append("=" * 50)
        lines.append(f"Description: {self.help_text}")
        
        # Aliases
        if self.aliases:
            lines.append(f"Aliases:     {', '.join(self.aliases)}")
        
        # Subcommands
        if self.subcommands:
            lines.append("")
            lines.append("Subcommands:")
            lines.append("-" * 50)
            subcmd_data = []
            for name, cmd in self.subcommands.items():
                subcmd_data.append({
                    'name': name,
                    'description': cmd.help_text[:60] + '...' if len(cmd.help_text) > 60 else cmd.help_text,
                    'aliases': ', '.join(cmd.aliases) if cmd.aliases else ''
                })
            lines.append(self._format_table(subcmd_data, ['name', 'description', 'aliases'], 
                                            {'name': 'Name', 'description': 'Description', 'aliases': 'Aliases'}))
        
        return '\n'.join(lines)
    
    def format_output(self, data: Dict, title: Optional[str] = None) -> str:
        """
        Format output data based on display_config
        
        Generates table-formatted output with:
        - Table row for fields in 'table_fields'
        - Separate sections for fields in 'separate_fields'
        
        Args:
            data: Data dictionary to format
            title: Optional title for output
            
        Returns:
            str: Formatted output string
        """
        config = self.display_config
        if not config:
            return self._format_simple(data, title)
        
        table_fields = config.get('table_fields', [])
        separate_fields = config.get('separate_fields', [])
        field_labels = config.get('field_labels', {})
        
        lines = []
        
        if title:
            lines.append(title)
            lines.append("=" * 50)
        
        if table_fields:
            lines.append("")
            table_data = []
            for field in table_fields:
                label = field_labels.get(field, field)
                value = self._get_field_value(data, field)
                table_data.append({
                    'property': label,
                    'value': self._format_value_for_table(value)
                })
            lines.append(self._format_table(table_data, ['property', 'value'],
                                            {'property': 'Property', 'value': 'Value'}))
        
        for field in separate_fields:
            if field in data or self._nested_field_exists(data, field):
                label = field_labels.get(field, field)
                value = self._get_field_value(data, field)
                lines.append("")
                lines.append(f"{label}:")
                lines.append("-" * 50)
                if isinstance(value, (dict, list)):
                    lines.append(json.dumps(value, indent=2, ensure_ascii=False))
                else:
                    lines.append(str(value))
        
        return '\n'.join(lines)
    
    def format_list_output(self, items: List[Dict], title: Optional[str] = None) -> str:
        """
        Format list output as table
        
        Args:
            items: List of data items
            title: Optional title
            
        Returns:
            str: Formatted output string
        """
        config = self.display_config
        table_fields = config.get('table_fields', [])
        field_labels = config.get('field_labels', {})
        
        lines = []
        
        if title:
            lines.append(title)
            lines.append("=" * 50)
        
        if not items:
            lines.append("")
            lines.append("No items found")
            return '\n'.join(lines)
        
        if table_fields:
            lines.append("")
            formatted_items = []
            for item in items:
                formatted_item = {}
                for field in table_fields:
                    value = self._get_field_value(item, field)
                    formatted_item[field] = self._format_value_for_table(value)
                formatted_items.append(formatted_item)
            
            headers = [field_labels.get(f, f) for f in table_fields]
            lines.append(self._format_table(formatted_items, table_fields, dict(zip(table_fields, headers))))
        else:
            for item in items:
                lines.append(self._format_simple(item))
        
        return '\n'.join(lines)
    
    def _format_table(self, rows: List[Dict], columns: List[str], headers: Dict[str, str]) -> str:
        """
        Format data as aligned table (no vertical bars)
        
        Args:
            rows: List of row dictionaries
            columns: Column keys to display
            headers: Header labels
            
        Returns:
            str: Formatted table
        """
        # Calculate column widths
        col_widths = {}
        for col in columns:
            header = headers.get(col, col)
            max_width = len(header)
            for row in rows:
                value = str(row.get(col, ''))
                max_width = max(max_width, len(value))
            col_widths[col] = max_width
        
        # Build table lines
        lines = []
        
        # Header row
        header_parts = []
        for col in columns:
            width = col_widths[col]
            header_parts.append(headers.get(col, col).ljust(width))
        lines.append('  '.join(header_parts))
        
        # Separator line
        sep_parts = []
        for col in columns:
            width = col_widths[col]
            sep_parts.append('-' * width)
        lines.append('  '.join(sep_parts))
        
        # Data rows
        for row in rows:
            row_parts = []
            for col in columns:
                width = col_widths[col]
                value = str(row.get(col, ''))
                row_parts.append(value.ljust(width))
            lines.append('  '.join(row_parts))
        
        return '\n'.join(lines)
    
    def _format_simple(self, data: Dict, title: Optional[str] = None) -> str:
        """Simple text format fallback"""
        lines = []
        if title:
            lines.append(title)
            lines.append("=" * 50)
        for k, v in data.items():
            lines.append(f"{k}: {v}")
        return '\n'.join(lines)
    
    def _format_value_for_table(self, value: Any, max_len: int = 100) -> str:
        """
        Format value for table display
        
        Args:
            value: Value to format
            max_len: Maximum length
            
        Returns:
            str: Formatted value
        """
        if isinstance(value, (dict, list)):
            formatted = json.dumps(value, ensure_ascii=False)
            if len(formatted) > max_len:
                return formatted[:max_len - 3] + '...'
            return formatted
        if isinstance(value, bool):
            return 'Yes' if value else 'No'
        if value is None:
            return ''
        result = str(value)
        if len(result) > max_len:
            return result[:max_len - 3] + '...'
        return result
    
    def _get_field_value(self, data: Dict, field: str) -> Any:
        """
        Get field value from data, supporting nested paths
        
        Args:
            data: Data dictionary
            field: Field name (supports dot notation like 'agentcard.name')
            
        Returns:
            Any: Field value
        """
        if '.' in field:
            parts = field.split('.')
            value = data
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, '')
                else:
                    return ''
            return value
        return data.get(field, '')
    
    def _nested_field_exists(self, data: Dict, field: str) -> bool:
        """Check if nested field exists"""
        if '.' in field:
            parts = field.split('.')
            value = data
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return False
            return True
        return field in data
    
    def __repr__(self):
        return f"<{self.__class__.__name__}: name='{self.name}'>"