"""
CLI Framework Public Interface

Exports all framework components for developer use.
"""

from .core import CLI, main
from .base import BaseCommand
from .constants import *
from .exceptions import (
    CLIError,
    CommandNotFoundError,
    ValidationError,
    ConfigError,
    ServiceError,
    PermissionError,
    ArgumentMissingError,
    SubcommandNotFoundError,
    CommandConflictError,
)
from .context import Context
from .output import Output
from .logger import cli_logger, CLILogger
from .registry import CommandRegistry, SubcommandResolver
from .i18n import I18n, t, tf


__all__ = [
    'CLI',
    'main',
    'BaseCommand',
    'CLIError',
    'CommandNotFoundError',
    'ValidationError',
    'ConfigError',
    'ServiceError',
    'PermissionError',
    'ArgumentMissingError',
    'SubcommandNotFoundError',
    'CommandConflictError',
    'Context',
    'Output',
    'cli_logger',
    'CLILogger',
    'CommandRegistry',
    'SubcommandResolver',
    'I18n',
    't',
    'tf',
    # Constants
    'CLI_VERSION',
    'EXIT_SUCCESS',
    'EXIT_GENERAL_ERROR',
    'EXIT_VALIDATION_ERROR',
    'EXIT_CONFIG_ERROR',
    'EXIT_SERVICE_ERROR',
    'EXIT_PERMISSION_ERROR',
    'EXIT_COMMAND_NOT_FOUND',
    'EXIT_USER_INTERRUPT',
    'CMD_DISPLAY_WIDTH',
    'SUBCMD_DISPLAY_WIDTH',
    'COMPLETION_COL_WIDTH',
    'TERMINAL_WIDTH',
    'HISTORY_FILE',
    'LOG_FILE',
    'LOG_LEVEL',
    'LOG_ROTATION',
    'LOG_RETENTION',
    'VALID_LOG_LEVELS',
    'VALID_OUTPUT_FORMATS',
    'DEFAULT_OUTPUT_FORMAT',
    'DEFAULT_TIMEOUT',
    'DEFAULT_LANGUAGE',
]


__version__ = CLI_VERSION