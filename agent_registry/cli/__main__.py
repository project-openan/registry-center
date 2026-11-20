# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
CLI Framework Entry Point

python -m agent_registry.cli
"""

import sys
import platform


class FakeReadline:
    """Minimal stand-in for the ``readline`` module.

    Used when neither pyreadline3 (Windows) nor readline (POSIX) is installed.
    ``cmd.Cmd`` and ``InteractiveCLI`` call several module-level helpers, so the
    stub exposes all of them as no-ops rather than raising AttributeError.
    """

    backend = 'none'

    def get_completer(self):
        return None

    def set_completer(self, func):
        pass

    def set_completer_delims(self, delims):
        pass

    def get_completer_delims(self):
        return ' \t\n'

    def parse_and_bind(self, s):
        pass

    def get_line_buffer(self):
        return ''

    def get_begidx(self):
        return 0

    def get_endidx(self):
        return 0

    def read_history_file(self, path):
        pass

    def write_history_file(self, path):
        pass

    def add_history(self, line):
        pass

    def get_current_history_length(self):
        return 0


# Fix Python 3.14 cmd.py readline.backend issue.
# Must be executed before importing other modules.
if platform.system() == 'Windows':
    try:
        import pyreadline3.readline as readline_module
        if not hasattr(readline_module, 'backend'):
            readline_module.backend = 'pyreadline3'
        # cmd.py uses ``import readline``, so register the module under both names.
        sys.modules['readline'] = readline_module
    except ImportError:
        sys.modules['readline'] = FakeReadline()
else:
    try:
        import readline as readline_module
        if not hasattr(readline_module, 'backend'):
            readline_module.backend = 'readline'
    except ImportError:
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