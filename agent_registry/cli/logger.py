"""
CLI Framework Logging System

Integrates loguru, provides independent log file for CLI framework.
Separated from service log, convenient for troubleshooting and command auditing.
"""

import sys
import os
from pathlib import Path
from typing import Optional
from loguru import logger

from .constants import (
    LOG_FILE,
    LOG_LEVEL,
    LOG_ROTATION,
    LOG_RETENTION,
    VALID_LOG_LEVELS,
)


class CLILogger:
    """
    CLI-Specific Logging System
    
    Separated from project base logs, independently writes to log file
    
    Features:
        - Independent log file
        - Log level control: DEBUG/INFO/WARNING/ERROR
        - Command audit log: Automatically records command execution info
        - Log rotation and retention
        - Debug mode: Output to console
    
    Example:
        from agent_registry.cli.logger import cli_logger
        
        cli_logger.info("Command executed: start")
        cli_logger.error("Failed to start service")
        cli_logger.log_command_start("agent list", {"org": "MyOrg"})
    """
    
    _instance: Optional['CLILogger'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(
        self,
        log_file: str = LOG_FILE,
        level: str = LOG_LEVEL,
        rotation: str = LOG_ROTATION,
        retention: str = LOG_RETENTION
    ):
        """
        Initialize CLI logging system
        
        Args:
            log_file: Log file path
            level: Log level (DEBUG/INFO/WARNING/ERROR)
            rotation: Log rotation size
            retention: Log retention time
        """
        if self._initialized:
            return
        
        self.log_file = log_file
        self.level = level
        self.rotation = rotation
        self.retention = retention
        self._cli_handler_id: Optional[int] = None
        self._console_handler_id: Optional[int] = None
        
        self._setup_logger()
        self._initialized = True
    
    def _setup_logger(self):
        """
        Configure loguru logger
        
        Add CLI-specific handler, write to independent log file.
        Remove loguru default handler to avoid console output.
        """
        log_dir = Path(self.log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Remove loguru default handler (output to stderr)
        logger.remove()
        
        self._cli_handler_id = logger.add(
            self.log_file,
            level=self.level,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
            rotation=self.rotation,
            retention=self.retention,
            compression="zip",
            encoding="utf-8",
            filter=lambda record: record["extra"].get("cli", True)
        )
    
    def enable_console_output(self, level: str = "DEBUG"):
        """
        Enable console output
        
        Used for debug mode, output to both console and log file.
        
        Args:
            level: Console log level
        """
        if self._console_handler_id is not None:
            return
        
        self._console_handler_id = logger.add(
            sys.stderr,
            level=level,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
            colorize=True,
            filter=lambda record: record["extra"].get("cli", True)
        )
    
    def disable_console_output(self):
        """
        Disable console output
        
        Close debug mode, only output to log file.
        """
        if self._console_handler_id is not None:
            logger.remove(self._console_handler_id)
            self._console_handler_id = None
    
    def log_command_start(self, command: str, args: dict):
        """
        Log command start execution
        
        Args:
            command: Command name or path (e.g., "agent list")
            args: Command arguments dictionary
        """
        args_str = self._format_args(args)
        logger.bind(cli=True).info(
            f"COMMAND_START | {command} | args={args_str}"
        )
    
    def log_command_end(self, command: str, exit_code: int, duration: float):
        """
        Log command execution end
        
        Args:
            command: Command name or path
            exit_code: Exit code
            duration: Execution duration (seconds)
        """
        status = "SUCCESS" if exit_code == 0 else "FAILED"
        logger.bind(cli=True).info(
            f"COMMAND_END | {command} | {status} | exit_code={exit_code} | duration={duration:.3f}s"
        )
    
    def log_command_error(self, command: str, error: Exception, include_trace: bool = False):
        """
        Log command execution error
        
        Args:
            command: Command name or path
            error: Exception object
            include_trace: Whether to include stack trace
        """
        error_type = type(error).__name__
        error_msg = str(error)
        
        if include_trace:
            logger.bind(cli=True).exception(
                f"COMMAND_ERROR | {command} | {error_type}: {error_msg}"
            )
        else:
            logger.bind(cli=True).error(
                f"COMMAND_ERROR | {command} | {error_type}: {error_msg}"
            )
    
    def _format_args(self, args: dict) -> str:
        """
        Format arguments dictionary to string
        
        Args:
            args: Arguments dictionary
            
        Returns:
            Formatted string
        """
        if not args:
            return "{}"
        
        filtered_args = {
            k: v for k, v in args.items()
            if not k.startswith('_')
        }
        
        return str(filtered_args)
    
    def debug(self, message: str):
        """
        Log DEBUG level message
        
        Args:
            message: Log message
        """
        logger.bind(cli=True).debug(message)
    
    def info(self, message: str):
        """
        Log INFO level message
        
        Args:
            message: Log message
        """
        logger.bind(cli=True).info(message)
    
    def warning(self, message: str):
        """
        Log WARNING level message
        
        Args:
            message: Log message
        """
        logger.bind(cli=True).warning(message)
    
    def error(self, message: str):
        """
        Log ERROR level message
        
        Args:
            message: Log message
        """
        logger.bind(cli=True).error(message)
    
    def exception(self, message: str):
        """
        Log EXCEPTION level message (with stack trace)
        
        Args:
            message: Log message
        """
        logger.bind(cli=True).exception(message)
    
    def set_level(self, level: str):
        """
        Dynamically set log level
        
        Args:
            level: Log level (DEBUG/INFO/WARNING/ERROR)
        
        Note:
            Log level priority: DEBUG < INFO < WARNING < ERROR
            After setting to WARNING, debug() and info() logs won't be written to file.
        """
        if level.upper() not in VALID_LOG_LEVELS:
            raise ValueError(f"Invalid log level: {level}. Must be one of {VALID_LOG_LEVELS}")
        
        self.level = level.upper()
        
        if self._cli_handler_id is not None:
            logger.remove(self._cli_handler_id)
            self._cli_handler_id = None
        
        self._setup_logger()
    
    def get_log_file_path(self) -> Path:
        """
        Get log file path
        
        Returns:
            Log file Path object
        """
        return Path(self.log_file)


cli_logger = CLILogger()