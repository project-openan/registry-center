# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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

# audit_logger.py
import os
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any
from loguru import logger

from common.util.config_util import get_root_path, load_configs

# File permissions: 600 -> owner read/write only, others no access
FILE_PERMISSION_MODE = 0o600


class LogLevel:
    DANGER = "Critical"
    MINOR = "General"
    INFO = "Informational"


class OperationName:
    START_SERVICE = "Start Service"
    REGISTER_AGENT = "Register Agent"
    UPDATE_AGENT = "Update Agent"
    QUERY_AGENT = "Query Agent"
    RETRIEVE_AGENT = "Retrieve Agent"
    GET_AGENT = "Get Agent"
    DEREGISTER_AGENT = "Deregister Agent"
    GENERATE_CERTIFICATE = "Generate Certificate"


class OperatorObject:
    SERVICE = "Service"
    AGENT = "Agent"


class OperationResult:
    SUCCESS = "Success"
    FAILURE = "Failure"


class AuditLogger:
    """
    Security audit logger.
    Supports UTC timestamps, file rotation, log wrapping/deletion, and permission control.
    """

    def __init__(self):
        self.config = self._load_config()
        self.max_size = int(self.config.get("audit_log_max_file_size_mb", 5)) * 1024 * 1024  # Convert to bytes
        self.backup_count = int(self.config.get("audit_log_backup_count", 5)) - 1
        parent_path = os.path.join(get_root_path(), "log", "audit")
        audit_log_dir = Path(parent_path)
        audit_log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(audit_log_dir, 0o700)
        self.log_file = os.path.join(parent_path, "audit.log")
        self.lock = threading.Lock()

    @staticmethod
    def _load_config() -> Dict[str, Any]:
        """Load configuration file, create default config if it does not exist"""
        root_path = get_root_path()
        log_config = {}
        log_config_path = os.path.join(root_path, "etc", "conf", "log_config.conf")
        if os.path.exists(log_config_path):
            load_configs(log_config_path, log_config)
        return log_config

    def audit(self, log_entry: Dict[str, Any]):
        """
        :param log_entry: Audit log entry containing the following fields:
                          operation_name: Operation name
                          level: Severity level
                          result: Success / Failure
                          object_name: Target object
                          details: Supplementary information
                          client_ip: Client IP address
                          user_name: User name
        """
        log_data = {
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "clientIP": log_entry.get("client_ip", ""),
            "userName": log_entry.get("user_name", ""),
            "level": log_entry["level"],
            "operationName": log_entry["operation_name"],
            "object": log_entry["object_name"],
            "result": log_entry["result"],
            "details": log_entry.get("details", {})
        }
        self._write_log(log_data)

    def _get_file_size(self) -> int:
        """Get current log file size, returns 0 if file does not exist"""
        return os.path.getsize(self.log_file) if os.path.exists(self.log_file) else 0

    def _rotate_logs(self):
        """Safe log rotation to avoid deadlocks"""
        if self._get_file_size() < self.max_size:
            return

        # 1. Delete the oldest file first (.backup_count + 1)
        oldest = f"{self.log_file}.{self.backup_count + 1}"
        if os.path.exists(oldest):
            try:
                os.remove(oldest)
            except Exception as e:
                logger.error(f"Warning: failed to remove {oldest}: {e}")  # Do not raise, avoid blocking logs

        # 2. Rename from high to low: .4 -> .5, .3 -> .4, ..., .1 -> .2
        for i in range(self.backup_count, 0, -1):
            src = f"{self.log_file}.{i}"
            dst = f"{self.log_file}.{i + 1}"
            if os.path.exists(src):
                try:
                    os.rename(src, dst)
                except Exception as e:
                    logger.error(f"Warning: failed to rename {src} to {dst}: {e}")

        # 3. Rename current main log to .1
        if os.path.exists(self.log_file):
            try:
                os.rename(self.log_file, f"{self.log_file}.1")
            except Exception as e:
                logger.error(f"Warning: failed to rename {self.log_file} to {self.log_file}.1: {e}")
                return  # If renaming main file fails, do not continue

        # 4. Create new log file
        try:
            open(self.log_file, 'w').close()
            os.chmod(self.log_file, FILE_PERMISSION_MODE)
        except Exception as e:
            logger.error(f"Error: failed to create new log file: {e}")

    def _write_log(self, log_entry: Dict[str, Any]):
        """Write a single log entry, thread-safe"""
        with self.lock:
            self._rotate_logs()  # Check for rotation
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            # Ensure permissions (especially on newly created files)
            os.chmod(self.log_file, FILE_PERMISSION_MODE)


audit_logger = AuditLogger()
