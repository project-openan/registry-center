"""
CLI Framework Command Registry

Manages all registered level-1 commands with level isolation design.
"""

from typing import Dict, Type, Optional
from .base import BaseCommand
from .exceptions import CommandConflictError


class CommandRegistry:
    """
    Command Registry
    
    Level isolation design:
    - Level-1 commands: Globally unique, conflict checked on registration
    - Subcommands: Defined in parent command's subcommands attribute, only valid within parent scope
    
    Example:
        registry = CommandRegistry()
        
        @CLI.register  # calls registry.register
        class StartCommand(BaseCommand):
            name = "start"
            ...
        
        # agent.list and cert.list are different commands
        # because they are in different parent command scopes
    
    Attributes:
        _commands: Level-1 commands dictionary
    """
    
    def __init__(self):
        self._commands: Dict[str, Type[BaseCommand]] = {}
    
    def register(self, command_class: Type[BaseCommand]) -> None:
        """
        Register level-1 command
        
        Args:
            command_class: Command class
            
        Raises:
            CommandConflictError: Level-1 command name already exists
        """
        instance = command_class()
        name = instance.name
        
        if name in self._commands:
            raise CommandConflictError(name)
        
        self._commands[name] = command_class
    
    def get(self, name: str) -> Optional[Type[BaseCommand]]:
        """
        Get level-1 command class
        
        Args:
            name: Command name
            
        Returns:
            Command class or None
        """
        return self._commands.get(name)
    
    def get_all(self) -> Dict[str, Type[BaseCommand]]:
        """
        Get all level-1 commands
        
        Returns:
            Level-1 commands dictionary (copy)
        """
        return self._commands.copy()
    
    def has(self, name: str) -> bool:
        """
        Check if level-1 command exists
        
        Args:
            name: Command name
            
        Returns:
            bool: Whether exists
        """
        return name in self._commands
    
    def count(self) -> int:
        """
        Get level-1 command count
        
        Returns:
            int: Command count
        """
        return len(self._commands)
    
    def clear(self) -> None:
        """
        Clear registry
        
        Used for testing scenarios
        """
        self._commands.clear()
    
    def get_command_names(self) -> list:
        """
        Get all level-1 command names
        
        Returns:
            List[str]: Command name list
        """
        return list(self._commands.keys())


class SubcommandResolver:
    """
    Subcommand Resolver
    
    Resolves subcommands within parent command scope, implementing level isolation.
    
    Example:
        parent = AgentCommand()
        subcmd = SubcommandResolver.resolve(parent, "list")
        # Only searches "list" in agent's subcommands
    """
    
    @staticmethod
    def resolve(parent: BaseCommand, subcommand_name: str) -> Optional[BaseCommand]:
        """
        Resolve subcommand within parent command scope
        
        Args:
            parent: Parent command instance
            subcommand_name: Subcommand name
            
        Returns:
            Subcommand instance or None
        """
        return parent.subcommands.get(subcommand_name)
    
    @staticmethod
    def has_subcommand(parent: BaseCommand, name: str) -> bool:
        """
        Check if parent command has specified subcommand
        
        Args:
            parent: Parent command instance
            name: Subcommand name
            
        Returns:
            bool: Whether exists
        """
        return name in parent.subcommands
    
    @staticmethod
    def get_subcommand_names(parent: BaseCommand) -> list:
        """
        Get all subcommand names of parent command
        
        Args:
            parent: Parent command instance
            
        Returns:
            List[str]: Subcommand name list
        """
        return list(parent.subcommands.keys())