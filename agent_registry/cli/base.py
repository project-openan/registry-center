"""
CLI Framework Command Abstract Base Class

Defines the standard interface for CLI commands. All concrete commands must inherit from this class.
"""

import sys
from abc import ABC, abstractmethod
from argparse import ArgumentParser, Namespace
from typing import List, Dict, Optional


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
        help_parts = [f"{self.name}: {self.help_text}"]
        
        if self.aliases:
            help_parts.append(f"Aliases: {', '.join(self.aliases)}")
        
        if self.subcommands:
            subcmd_list = ', '.join(self.subcommands.keys())
            help_parts.append(f"Subcommands: {subcmd_list}")
        
        return '\n'.join(help_parts)
    
    def __repr__(self):
        return f"<{self.__class__.__name__}: name='{self.name}'>"