"""
CLI Framework Output Formatter

Supports multiple output formats: text/json/table
"""

import json
import sys
from typing import Any, List, Dict, Optional

from .constants import VALID_OUTPUT_FORMATS, DEFAULT_OUTPUT_FORMAT


class Output:
    """
    Output Formatter
    
    Supports multiple output formats: text/json/table
    
    Example:
        output = Output('json')
        output.print({'name': 'agent1'})
        
        output.success("Operation completed")
        output.error("Failed to execute")
    """
    
    def __init__(self, format: str = DEFAULT_OUTPUT_FORMAT):
        """
        Initialize output formatter
        
        Args:
            format: Output format (text/json/table)
        """
        if format not in VALID_OUTPUT_FORMATS:
            raise ValueError(f"Invalid format: {format}. Must be one of {VALID_OUTPUT_FORMATS}")
        self.format = format
    
    def print(self, data: Any, title: Optional[str] = None):
        """
        Format and output data
        
        Args:
            data: Data to output
            title: Title (optional)
        """
        if self.format == 'json':
            self._print_json(data)
        elif self.format == 'table':
            self._print_table(data, title)
        else:
            self._print_text(data, title)
    
    def print_table(self, rows: List[Dict], columns: List[str], headers: Dict[str, str], 
                    title: Optional[str] = None):
        """
        Print data as aligned table (no vertical bars)
        
        Args:
            rows: List of row dictionaries
            columns: Column keys to display
            headers: Header labels mapping
            title: Optional title
        """
        if self.format == 'json':
            data = [dict(zip(columns, [row.get(c, '') for c in columns])) for row in rows]
            self._print_json(data)
            return
        
        lines = []
        
        if title:
            lines.append(title)
            lines.append("=" * 50)
        
        if not rows:
            lines.append("")
            lines.append("No items found")
            print('\n'.join(lines))
            return
        
        # Calculate column widths based on actual content
        col_widths = {}
        for col in columns:
            header = headers.get(col, col)
            max_width = len(header)
            for row in rows:
                value = self._format_value(str(row.get(col, '')))
                max_width = max(max_width, len(value))
            col_widths[col] = max_width
        
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
                value = self._format_value(str(row.get(col, '')))
                row_parts.append(value.ljust(width))
            lines.append('  '.join(row_parts))
        
        print('\n'.join(lines))
    
    def print_dict_table(self, data: Dict, field_order: Optional[List[str]] = None, 
                         labels: Optional[Dict[str, str]] = None, title: Optional[str] = None):
        """
        Print dictionary as property table
        
        Args:
            data: Dictionary data
            field_order: Optional field order
            labels: Optional field label mapping
            title: Optional title
        """
        if self.format == 'json':
            self._print_json(data)
            return
        
        if field_order:
            keys = field_order
        else:
            keys = list(data.keys())
        
        rows = []
        for k in keys:
            rows.append({
                'property': labels.get(k, k) if labels else k,
                'value': self._format_value(str(data.get(k, '')))
            })
        
        self.print_table(rows, ['property', 'value'], 
                        {'property': 'Property', 'value': 'Value'}, title)
    
    def print_separate(self, label: str, data: Any):
        """
        Print large data separately
        
        Args:
            label: Label for the data
            data: Data to print
        """
        if self.format == 'json':
            return
        
        print()
        print(f"{label}:")
        print("-" * 50)
        
        if isinstance(data, (dict, list)):
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(str(data))
    
    def _format_value(self, value: str, max_len: int = 100) -> str:
        """Format value for display"""
        if len(value) > max_len:
            return value[:max_len - 3] + '...'
        return value
    
    def _print_json(self, data: Any):
        """
        JSON format output
        
        Args:
            data: Data
        """
        print(json.dumps(data, indent=2, ensure_ascii=False))
    
    def _print_table(self, data: Any, title: Optional[str] = None):
        """
        Table format output
        
        Args:
            data: Data
            title: Title
        """
        if isinstance(data, list) and data and isinstance(data[0], dict):
            keys = list(data[0].keys())
            rows = data
            headers = dict(zip(keys, keys))
            self.print_table(rows, keys, headers, title)
        elif isinstance(data, dict):
            self.print_dict_table(data, title=title)
        else:
            if title:
                print(f"\n{title}")
                print("=" * 50)
            print(data)
    
    def _print_text(self, data: Any, title: Optional[str] = None):
        """
        Text format output
        
        Args:
            data: Data
            title: Title
        """
        lines = []
        
        if title:
            lines.append(title)
            lines.append("=" * 50)
        
        if isinstance(data, dict):
            for k, v in data.items():
                lines.append(f"{k}: {v}")
        elif isinstance(data, list):
            for item in data:
                lines.append(str(item))
        else:
            lines.append(str(data))
        
        print('\n'.join(lines))
    
    def success(self, msg: str):
        """
        Output success message
        
        Args:
            msg: Message content
        """
        if self.format == 'json':
            print(json.dumps({"status": "success", "message": msg}, ensure_ascii=False))
        else:
            lines = []
            lines.append("")
            lines.append("=" * 50)
            lines.append("[OK] " + msg)
            lines.append("=" * 50)
            print('\n'.join(lines))
    
    def error(self, msg: str):
        """
        Output error message
        
        Args:
            msg: Message content
        """
        if self.format == 'json':
            print(json.dumps({"status": "error", "message": msg}, ensure_ascii=False), file=sys.stderr)
        else:
            lines = []
            lines.append("")
            lines.append("=" * 50)
            lines.append("[ERROR] " + msg)
            lines.append("=" * 50)
            print('\n'.join(lines), file=sys.stderr)
    
    def warning(self, msg: str):
        """
        Output warning message
        
        Args:
            msg: Message content
        """
        if self.format == 'json':
            print(json.dumps({"status": "warning", "message": msg}, ensure_ascii=False))
        else:
            print("[WARN] " + msg)
    
    def info(self, msg: str):
        """
        Output info message
        
        Args:
            msg: Message content
        """
        if self.format == 'json':
            print(json.dumps({"status": "info", "message": msg}, ensure_ascii=False))
        else:
            print(msg)
    
    def set_format(self, format: str):
        """
        Set output format
        
        Args:
            format: Output format
        """
        if format not in VALID_OUTPUT_FORMATS:
            raise ValueError(f"Invalid format: {format}. Must be one of {VALID_OUTPUT_FORMATS}")
        self.format = format
    
    def get_format(self) -> str:
        """
        Get current output format
        
        Returns:
            Output format
        """
        return self.format