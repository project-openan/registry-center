"""
CLI Framework Runtime Context

Stores CLI runtime global state such as debug mode, config path, etc.
"""

from .constants import VALID_OUTPUT_FORMATS, DEFAULT_OUTPUT_FORMAT


class Context:
    """
    CLI Runtime Context
    
    Stores global state: debug mode, config path, output format, etc.
    
    Attributes:
        debug: Debug mode flag
        config_file: Config file path
        output_format: Output format (text/json/table)
        command_path: Current command path
    
    Example:
        context = Context()
        context.debug = True
        
        # Or create from args
        context = Context.from_args(args)
    """
    
    def __init__(self):
        self.debug: bool = False
        self.config_file: str = None
        self.output_format: str = DEFAULT_OUTPUT_FORMAT
        self.command_path: str = ''
    
    @classmethod
    def from_args(cls, args) -> 'Context':
        """
        Create context from parsed arguments
        
        Args:
            args: argparse.Namespace object
            
        Returns:
            Context instance
        """
        ctx = cls()
        ctx.debug = getattr(args, 'debug', False)
        ctx.config_file = getattr(args, 'config_file', None)
        ctx.output_format = getattr(args, 'output', DEFAULT_OUTPUT_FORMAT)
        ctx.command_path = getattr(args, 'command_path', '')
        return ctx
    
    def set_debug(self, enabled: bool):
        """
        Set debug mode
        
        Args:
            enabled: Enable debug flag
        """
        self.debug = enabled
    
    def set_config_file(self, path: str):
        """
        Set config file path
        
        Args:
            path: Config file path
        """
        self.config_file = path
    
    def set_output_format(self, format: str):
        """
        Set output format
        
        Args:
            format: Output format (text/json/table)
        """
        if format not in VALID_OUTPUT_FORMATS:
            raise ValueError(f"Invalid format: {format}. Must be one of {VALID_OUTPUT_FORMATS}")
        self.output_format = format
    
    def is_debug(self) -> bool:
        """
        Check if debug mode
        
        Returns:
            bool
        """
        return self.debug
    
    def get_config_file(self) -> str:
        """
        Get config file path
        
        Returns:
            Config file path or None
        """
        return self.config_file
    
    def get_output_format(self) -> str:
        """
        Get output format
        
        Returns:
            Output format
        """
        return self.output_format
    
    def __repr__(self):
        return f"Context(debug={self.debug}, config={self.config_file}, output={self.output_format})"