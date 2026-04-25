"""
CLI Framework Public Interface

Exports all framework components for developer use.
"""

from .core import CLI, main
from .base import BaseCommand
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
from .client import RegistryClient, get_client
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
    'RegistryClient',
    'get_client',
    'I18n',
    't',
    'tf',
]


__version__ = '1.0.0'