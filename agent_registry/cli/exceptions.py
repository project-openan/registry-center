"""
CLI Framework Exception Definitions

Defines exception types used in CLI framework, each carrying a specific exit code.

Exit Code Convention:
    0   - Success
    1   - General error (CLIError)
    2   - Validation error (ValidationError)
    3   - Config error (ConfigError)
    4   - Service error (ServiceError)
    5   - Permission error (PermissionError)
    127 - Command not found (CommandNotFoundError)
    130 - User interrupt (Ctrl+C)
"""

from .constants import (
    EXIT_SUCCESS,
    EXIT_GENERAL_ERROR,
    EXIT_VALIDATION_ERROR,
    EXIT_CONFIG_ERROR,
    EXIT_SERVICE_ERROR,
    EXIT_PERMISSION_ERROR,
    EXIT_COMMAND_NOT_FOUND,
)


class CLIError(Exception):
    """
    CLI Exception Base Class
    
    All CLI exceptions inherit from this class, carrying exit code.
    
    Attributes:
        message: Error message
        exit_code: Exit code
        
    Example:
        raise CLIError("Something went wrong", exit_code=EXIT_GENERAL_ERROR)
    """
    
    def __init__(self, message: str, exit_code: int = EXIT_GENERAL_ERROR):
        self.message = message
        self.exit_code = exit_code
        super().__init__(message)
    
    def __str__(self):
        return f"[ExitCode:{self.exit_code}] {self.message}"


class CommandNotFoundError(CLIError):
    """
    Command Not Found Exception
    
    Raised when user input command is not registered.
    
    Exit Code: EXIT_COMMAND_NOT_FOUND (shell convention)
    """
    
    def __init__(self, command: str):
        super().__init__(
            message=f"Command not found: '{command}'",
            exit_code=EXIT_COMMAND_NOT_FOUND
        )


class ValidationError(CLIError):
    """
    Validation Error
    
    Raised when command argument validation fails.
    
    Exit Code: EXIT_VALIDATION_ERROR
    """
    
    def __init__(self, message: str):
        super().__init__(message=message, exit_code=EXIT_VALIDATION_ERROR)


class ConfigError(CLIError):
    """
    Configuration Error
    
    Raised when config file read, parse, or validation fails.
    
    Exit Code: EXIT_CONFIG_ERROR
    """
    
    def __init__(self, message: str):
        super().__init__(message=message, exit_code=EXIT_CONFIG_ERROR)


class ServiceError(CLIError):
    """
    Service Error
    
    Raised when service call fails (connection error, service unavailable, etc).
    
    Exit Code: EXIT_SERVICE_ERROR
    """
    
    def __init__(self, message: str):
        super().__init__(message=message, exit_code=EXIT_SERVICE_ERROR)


class PermissionError(CLIError):
    """
    Permission Error
    
    Raised when permission denied (file read/write, operation permission, etc).
    
    Exit Code: EXIT_PERMISSION_ERROR
    """
    
    def __init__(self, message: str):
        super().__init__(message=message, exit_code=EXIT_PERMISSION_ERROR)


class ArgumentMissingError(CLIError):
    """
    Argument Missing Error
    
    Raised when required argument is missing.
    
    Exit Code: EXIT_VALIDATION_ERROR (validation error category)
    """
    
    def __init__(self, argument: str):
        super().__init__(
            message=f"Missing required argument: '{argument}'",
            exit_code=EXIT_VALIDATION_ERROR
        )


class SubcommandNotFoundError(CLIError):
    """
    Subcommand Not Found Exception
    
    Raised when specified subcommand not found in parent command scope.
    
    Exit Code: EXIT_COMMAND_NOT_FOUND
    """
    
    def __init__(self, parent_command: str, subcommand: str):
        super().__init__(
            message=f"Subcommand '{subcommand}' not found under '{parent_command}'",
            exit_code=EXIT_COMMAND_NOT_FOUND
        )


class CommandConflictError(CLIError):
    """
    Command Conflict Exception
    
    Raised when registering level-1 command with existing name.
    
    Exit Code: EXIT_GENERAL_ERROR
    """
    
    def __init__(self, command: str):
        super().__init__(
            message=f"Command '{command}' already registered. "
                    f"One-level commands must be globally unique.",
            exit_code=EXIT_GENERAL_ERROR
        )