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
        if title:
            print(f"\n{title}")
            print('=' * len(title))
        
        try:
            from tabulate import tabulate
            
            if isinstance(data, list) and data and isinstance(data[0], dict):
                headers = list(data[0].keys())
                rows = [[item.get(h, '') for h in headers] for item in data]
                print(tabulate(rows, headers=headers, tablefmt='grid'))
            elif isinstance(data, dict):
                rows = [[k, v] for k, v in data.items()]
                print(tabulate(rows, headers=['Key', 'Value'], tablefmt='grid'))
            else:
                print(data)
        except ImportError:
            self._print_text(data, title)
    
    def _print_text(self, data: Any, title: Optional[str] = None):
        """
        Text format output
        
        Args:
            data: Data
            title: Title
        """
        if title:
            print(f"\n{title}")
            print('=' * len(title))
        
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"{k}: {v}")
        elif isinstance(data, list):
            for item in data:
                print(item)
        else:
            print(data)
    
    def success(self, msg: str):
        """
        Output success message
        
        Args:
            msg: Message content
        """
        if self.format == 'json':
            print(json.dumps({"status": "success", "message": msg}, ensure_ascii=False))
        else:
            print(f"[OK] {msg}")
    
    def error(self, msg: str):
        """
        Output error message
        
        Args:
            msg: Message content
        """
        if self.format == 'json':
            print(json.dumps({"status": "error", "message": msg}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"[ERROR] {msg}", file=sys.stderr)
    
    def warning(self, msg: str):
        """
        Output warning message
        
        Args:
            msg: Message content
        """
        if self.format == 'json':
            print(json.dumps({"status": "warning", "message": msg}, ensure_ascii=False))
        else:
            print(f"[WARN] {msg}")
    
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