"""
CLI Framework Core Engine

Interactive interface based on cmd module with tab completion support.
"""

import sys
import cmd
import argparse
import shlex
import time
import platform
from typing import List, Optional, Dict, Type

try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False
    readline = None

from .base import BaseCommand
from .registry import CommandRegistry
from .exceptions import CLIError, ValidationError
from .context import Context
from .logger import cli_logger
from .i18n import t, tf
from .constants import (
    CLI_VERSION,
    HISTORY_FILE,
    CMD_DISPLAY_WIDTH,
    SUBCMD_DISPLAY_WIDTH,
    COMPLETION_COL_WIDTH,
    TERMINAL_WIDTH,
)


class InteractiveCLI(cmd.Cmd):
    """
    Interactive CLI based on cmd.Cmd
    
    Features:
        - Tab auto-completion (commands, subcommands, arguments)
        - Command history
        - Cross-platform support (Windows/Linux/Mac)
    """
    
    intro = tf('cli.intro', version=CLI_VERSION)
    prompt = t('cli.prompt')
    
    def __init__(self, registry: CommandRegistry):
        super().__init__()
        self._registry = registry
        self._context = Context()
        
        self._generate_command_methods()
        
        if HAS_READLINE:
            readline.parse_and_bind("tab: complete")
            readline.set_completer_delims(' \t\n')
            try:
                readline.read_history_file(HISTORY_FILE)
            except FileNotFoundError:
                pass
    
    def preloop(self):
        """Setup before entering command loop"""
        if HAS_READLINE:
            readline.set_completer(self.complete)
            readline.parse_and_bind("tab: complete")
            
            # Try to set custom display hook for better formatting
            # This works on Linux/Mac with standard readline, not on Windows with pyreadline3
            try:
                import sys
                if not sys.platform.startswith('win'):
                    self._setup_display_hook()
            except:
                pass
    
    def _setup_display_hook(self):
        """Setup custom completion display hook (Linux/Mac only)"""
        def display_matches(substitution, matches, longest_match_length):
            if not matches:
                return
            
            print()
            
            cols = max(1, TERMINAL_WIDTH // COMPLETION_COL_WIDTH)
            
            for i, match in enumerate(sorted(matches)):
                if (i + 1) % cols == 0 or i == len(matches) - 1:
                    print(f"{match:<{COMPLETION_COL_WIDTH}}")
                else:
                    print(f"{match:<{COMPLETION_COL_WIDTH}}", end='')
            
            print(self.prompt, end='', flush=True)
            print(readline.get_line_buffer(), end='', flush=True)
        
        readline.set_completion_display_matches_hook(display_matches)
    
    def postloop(self):
        """Cleanup after exiting command loop"""
        if HAS_READLINE:
            try:
                readline.write_history_file(HISTORY_FILE)
            except Exception:
                pass
    
    def _generate_command_methods(self):
        """
        Dynamically generate command methods
        
        cmd.Cmd recognizes commands via do_<name> methods
        and provides completion via complete_<name> methods
        """
        for cmd_name, cmd_class in self._registry.get_all().items():
            cmd = cmd_class()
            
            do_method = self._create_do_method(cmd_name, cmd)
            setattr(self.__class__, f"do_{cmd_name}", do_method)
            
            complete_method = self._create_complete_method(cmd_name, cmd)
            setattr(self.__class__, f"complete_{cmd_name}", complete_method)
    
    def _create_do_method(self, cmd_name: str, cmd: BaseCommand):
        """Create do_<name> method"""
        def do_method(self, arg_line: str):
            full_line = f"{cmd_name} {arg_line}" if arg_line else cmd_name
            self._execute_command(full_line)
        do_method.__doc__ = cmd.help_text
        return do_method
    
    def _create_complete_method(self, cmd_name: str, cmd: BaseCommand):
        """Create complete_<name> method"""
        def complete_method(self, text: str, line: str, begidx: int, endidx: int) -> List[str]:
            parts = line[:begidx].split()
            
            if len(parts) == 1:
                return [s for s in cmd.subcommands.keys() if s.startswith(text)]
            
            subcmd_name = parts[1] if len(parts) >= 2 else ""
            
            if subcmd_name in cmd.subcommands:
                subcmd = cmd.subcommands[subcmd_name]
                return self._complete_arguments(subcmd, text, parts)
            
            return [s for s in cmd.subcommands.keys() if s.startswith(subcmd_name)]
        
        return complete_method
    
    def _complete_command(self, cmd_name: str, text: str, line: str, begidx: int, endidx: int) -> List[str]:
        """Complete command (for testing and internal use)"""
        parts = line[:begidx].split()
        
        cmd_class = self._registry.get(cmd_name)
        if not cmd_class:
            return []
        
        cmd = cmd_class()
        
        if len(parts) <= 1:
            return [s for s in cmd.subcommands.keys() if s.startswith(text)]
        
        subcmd_name = parts[1] if len(parts) >= 2 else ""
        
        if subcmd_name in cmd.subcommands:
            subcmd = cmd.subcommands[subcmd_name]
            return self._complete_arguments(subcmd, text, parts)
        
        return [s for s in cmd.subcommands.keys() if s.startswith(subcmd_name)]
    
    def _complete_arguments(self, command: BaseCommand, text: str, parts: List[str]) -> List[str]:
        """Complete arguments"""
        parser = argparse.ArgumentParser()
        command.add_arguments(parser)
        
        completions = []
        for action in parser._actions:
            for opt in action.option_strings:
                if opt.startswith(text):
                    completions.append(opt)
        
        return completions
    
    def default(self, line: str):
        """Handle unknown commands or EOF"""
        if not line.strip():
            return
        
        if line.strip() == 'EOF':
            print(f"\n{t('cli.goodbye')}")
            return True
        
        self._execute_command(line)
    
    def emptyline(self):
        """Do nothing on empty line"""
        pass
    
    def do_exit(self, arg):
        """Exit CLI"""
        print(t('cli.goodbye'))
        return True
    
    def do_quit(self, arg):
        """Exit CLI (alias)"""
        return self.do_exit(arg)
    
    def do_q(self, arg):
        """Exit CLI (alias)"""
        return self.do_exit(arg)
    
    def do_cmds(self, arg):
        """Show available commands"""
        self._show_commands()
    
    def do_commands(self, arg):
        """Show available commands (alias)"""
        self._show_commands()
    
    def complete_cmds(self, text, line, begidx, endidx):
        """cmds command completion"""
        return []
    
    def _show_commands(self):
        """Show all available commands with aligned formatting"""
        print(f"\n{t('commands.header')}")
        
        commands_data = []
        
        for name, cmd_class in self._registry.get_all().items():
            cmd = cmd_class()
            commands_data.append(('cmd', name, cmd.help_text))
            
            if cmd.subcommands:
                for sub_name, sub_cmd in cmd.subcommands.items():
                    full_name = f"{name} {sub_name}"
                    commands_data.append(('subcmd', full_name, sub_cmd.help_text))
        
        commands_data.append(('cmd', 'cmds', t('commands.internal.cmds')))
        commands_data.append(('cmd', 'exit/quit/q', t('commands.internal.exit')))
        
        for item in commands_data:
            type_, name, help_text = item
            if type_ == 'cmd':
                print(f"  {name:<{CMD_DISPLAY_WIDTH}}  {help_text}")
            else:
                print(f"    {name:<{SUBCMD_DISPLAY_WIDTH}}  {help_text}")
        
        print(f"\n{t('commands.footer')}\n")
    
    def get_names(self):
        """
        Return list of completable command names
        
        cmd.Cmd uses this method to determine which commands can be tab-completed
        """
        names = []
        
        names.extend(['exit', 'quit', 'q', 'cmds', 'commands'])
        
        names.extend(self._registry.get_command_names())
        
        return names
    
    def completenames(self, text, line, begidx, endidx):
        """
        Complete first-level command names
        
        Args:
            text: Current input text
            line: Full line input
            begidx: Completion start position
            endidx: Completion end position
        
        Returns:
            List of matching command names
        """
        names = self.get_names()
        return [name for name in names if name.startswith(text)]
    
    def complete(self, text, state):
        """
        Generic completion method
        
        Complete commands, subcommands, or arguments based on current input context
        """
        if not HAS_READLINE:
            return None
        
        line = readline.get_line_buffer()
        begidx = readline.get_begidx()
        endidx = readline.get_endidx()
        
        try:
            parts = shlex.split(line[:begidx])
        except ValueError:
            parts = line[:begidx].split()
        
        if not parts:
            matches = self.completenames(text, line, begidx, endidx)
            return matches[state] if state < len(matches) else None
        
        cmd_name = parts[0]
        
        if cmd_name in self._registry.get_command_names():
            cmd_class = self._registry.get(cmd_name)
            cmd = cmd_class()
            
            if len(parts) == 1:
                subcmds = list(cmd.subcommands.keys())
                matches = [s for s in subcmds if s.startswith(text)]
                return matches[state] if state < len(matches) else None
            
            elif len(parts) >= 2:
                subcmd_name = parts[1]
                if subcmd_name in cmd.subcommands:
                    subcmd = cmd.subcommands[subcmd_name]
                    matches = self._complete_arguments(subcmd, text, parts)
                    return matches[state] if state < len(matches) else None
        
        return None
    
    def _execute_command(self, user_input: str) -> int:
        """Execute command"""
        try:
            argv = shlex.split(user_input)
        except ValueError as e:
            print(tf('errors.syntax', error=str(e)))
            return 1
        
        if not argv:
            return 0
        
        argv, global_options = self._parse_global_options(argv)
        self._context.debug = global_options.get('debug', False)
        
        if global_options.get('version'):
            print(tf('cli.intro', version='1.0.0'))
            return 0
        
        if self._context.debug:
            cli_logger.set_level("DEBUG")
            cli_logger.debug(tf('debug.command_start', command=user_input))
        
        parser = self._build_parser()
        
        try:
            args = parser.parse_args(argv)
        except SystemExit:
            return 1
        
        if not hasattr(args, '_command') or args._command is None:
            print(t('cli.unknown_command'))
            return 1
        
        command = args._command
        command_path = self._get_command_path(args)
        args_dict = {k: v for k, v in vars(args).items() if not k.startswith('_')}
        
        cli_logger.log_command_start(command_path, args_dict)
        
        start_time = time.time()
        exit_code = 0
        
        try:
            error = command.validate(args)
            if error:
                raise ValidationError(error)
            
            exit_code = command.execute(args)
        
        except CLIError as e:
            cli_logger.log_command_error(command_path, e, self._context.debug)
            print(f"Error: {e.message}")
            exit_code = e.exit_code
        
        except Exception as e:
            cli_logger.log_command_error(command_path, e, self._context.debug)
            if self._context.debug:
                import traceback
                traceback.print_exc()
            else:
                print(f"Error: {e}")
            exit_code = 1
        
        finally:
            duration = time.time() - start_time
            cli_logger.log_command_end(command_path, exit_code, duration)
        
        return exit_code
    
    def _parse_global_options(self, argv: List[str]) -> tuple:
        """Parse global options"""
        global_options = {}
        remaining = []
        
        for arg in argv:
            if arg in ('-v', '--version'):
                global_options['version'] = True
            elif arg in ('-x', '--debug'):
                global_options['debug'] = True
            else:
                remaining.append(arg)
        
        return remaining, global_options
    
    def _build_parser(self) -> argparse.ArgumentParser:
        """Build argument parser"""
        parser = argparse.ArgumentParser(
            prog="agent-registry",
            add_help=True
        )
        
        parser.add_argument('-v', '--version', action='store_true')
        parser.add_argument('-x', '--debug', action='store_true')
        
        subparsers = parser.add_subparsers(dest='_command_name')
        
        for name, cmd_class in self._registry.get_all().items():
            self._add_command(subparsers, cmd_class())
        
        return parser
    
    def _add_command(self, subparsers, command: BaseCommand, level: int = 0):
        """Recursively add command"""
        cmd_parser = subparsers.add_parser(
            command.name,
            help=command.help_text,
            aliases=command.aliases
        )
        cmd_parser.set_defaults(_command=command)
        
        command.add_arguments(cmd_parser)
        
        if command.subcommands:
            sub_subparsers = cmd_parser.add_subparsers(dest=f'_subcommand_{level}')
            for sub_name, sub_cmd in command.subcommands.items():
                self._add_command(sub_subparsers, sub_cmd, level + 1)
    
    def _get_command_path(self, args) -> str:
        """Get command path"""
        parts = []
        
        if hasattr(args, '_command_name') and args._command_name:
            parts.append(args._command_name)
        
        level = 0
        while hasattr(args, f'_subcommand_{level}'):
            subcmd = getattr(args, f'_subcommand_{level}')
            if subcmd:
                parts.append(subcmd)
            level += 1
        
        return ' '.join(parts) if parts else 'unknown'


class CLI:
    """
    CLI Framework facade class
    
    Maintains API compatibility
    """
    
    _instance: Optional['CLI'] = None
    _registry: CommandRegistry = CommandRegistry()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        self.name = "agent-registry"
        self.version = "1.0.0"
    
    @classmethod
    def register(cls, command_class: Type[BaseCommand]) -> Type[BaseCommand]:
        """Decorator: register command"""
        cls._registry.register(command_class)
        return command_class
    
    @classmethod
    def get_registry(cls) -> CommandRegistry:
        """Get registry"""
        return cls._registry
    
    def run(self) -> int:
        """Run interactive CLI"""
        interactive = InteractiveCLI(self._registry)
        interactive.cmdloop()
        return 0


def main():
    """CLI entry point"""
    cli = CLI()
    sys.exit(cli.run())