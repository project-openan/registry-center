"""
CLI Framework Constants

Centralized constants management for better maintainability.
All CLI-related constants should be defined here.
"""

# ========== CLI Version ==========

CLI_VERSION = "1.0.0"


# ========== Exit Codes ==========

EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_VALIDATION_ERROR = 2
EXIT_CONFIG_ERROR = 3
EXIT_SERVICE_ERROR = 4
EXIT_PERMISSION_ERROR = 5
EXIT_COMMAND_NOT_FOUND = 127
EXIT_USER_INTERRUPT = 130


# ========== Display Configuration ==========

# Command display width
CMD_DISPLAY_WIDTH = 15
SUBCMD_DISPLAY_WIDTH = 20

# Tab completion display width
COMPLETION_COL_WIDTH = 15
TERMINAL_WIDTH = 80


# ========== History File ==========

HISTORY_FILE = ".agent_registry_history"


# ========== Log Configuration ==========

LOG_FILE = "log/cli.log"
LOG_LEVEL = "INFO"
LOG_ROTATION = "10 MB"
LOG_RETENTION = "7 days"

VALID_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


# ========== Output Configuration ==========

VALID_OUTPUT_FORMATS = ["text", "json", "table"]
DEFAULT_OUTPUT_FORMAT = "text"


# ========== HTTP Client Configuration ==========

DEFAULT_TIMEOUT = 30

# API Endpoints
API_AGENTS_QUERY = "/rest/a2a-t/v1/agents/query"
API_AGENTS_REGISTER = "/rest/a2a-t/v1/agents/register"
API_AGENTS_GET = "/rest/a2a-t/v1/agents/{name}"
API_AGENTS_UPDATE = "/rest/a2a-t/v1/update_agent/{name}"
API_AGENTS_DEREGISTER = "/rest/a2a-t/v1/deregister_agent/{name}"
API_AGENTS_RETRIEVE = "/rest/a2a-t/v1/agents/retrieve"


# ========== I18n Configuration ==========

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ["en", "zh"]


# ========== SSL/HTTPS Configuration ==========

SSL_VERIFY_MODE_NONE = "none"
SSL_VERIFY_MODE_REQUIRED = "required"