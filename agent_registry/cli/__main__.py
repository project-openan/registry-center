"""
CLI Framework Entry Point

python -m agent_registry.cli
"""

import sys
import platform

# Fix Python 3.14 cmd.py readline.backend issue
# Must be executed before importing other modules
if platform.system() == 'Windows':
    try:
        import pyreadline3.readline as readline_module
        if not hasattr(readline_module, 'backend'):
            readline_module.backend = 'pyreadline3'
        # Also fix standard readline name (cmd.py uses import readline)
        import sys
        sys.modules['readline'] = readline_module
    except ImportError:
        # If pyreadline3 not available, create a fake readline module
        class FakeReadline:
            backend = 'none'
            def get_completer(self):
                return None
            def set_completer(self, func):
                pass
            def parse_and_bind(self, s):
                pass
            def get_line_buffer(self):
                return ''
            def get_begidx(self):
                return 0
            def get_endidx(self):
                return 0
        sys.modules['readline'] = FakeReadline()
else:
    try:
        import readline as readline_module
        if not hasattr(readline_module, 'backend'):
            readline_module.backend = 'readline'
    except ImportError:
        class FakeReadline:
            backend = 'none'
            def get_completer(self):
                return None
            def set_completer(self, func):
                pass
            def parse_and_bind(self, s):
                pass
            def get_line_buffer(self):
                return ''
            def get_begidx(self):
                return 0
            def get_endidx(self):
                return 0
        sys.modules['readline'] = FakeReadline()

from .core import CLI, main


def _auto_discover_commands():
    """
    Auto-discover and import command modules
    
    Scans cli/commands/ directory for .py files,
    auto-registers command classes using @CLI.register decorator.
    """
    from pathlib import Path
    
    commands_dir = Path(__file__).parent / 'commands'
    if commands_dir.exists():
        for file in commands_dir.glob('*.py'):
            if file.name.startswith('_'):
                continue
            module_name = file.stem
            try:
                __import__(f'{__package__}.commands.{module_name}')
            except ImportError as e:
                pass


_auto_discover_commands()


if __name__ == '__main__':
    main()