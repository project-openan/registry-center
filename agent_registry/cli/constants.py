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
CLI Framework Constants

Centralized constants management for better maintainability.
All CLI-related constants should be defined here.
"""

# ========== CLI Version ==========

CLI_VERSION = "1.0.2"


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

# ========== I18n Configuration ==========

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ["en", "zh"]


# ========== SSL/HTTPS Configuration ==========

SSL_VERIFY_MODE_NONE = "none"
SSL_VERIFY_MODE_REQUIRED = "required"