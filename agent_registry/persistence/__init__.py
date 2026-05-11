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

import json
import os
from pathlib import Path
from typing import List, Dict, Any

from loguru import logger

from agent_registry.config import MAX_FILE_SIZE_BYTES
from .base import StorageBackend
from .file_storage import FileStorage
from .postgresql_storage import PostgreSQLStorage


def save_to_file(file_path: str, agents: List[Dict[str, Any]]) -> None:
    """Save a list of agent dictionaries to a JSON file with size limit and secure permissions."""
    try:
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        json_str = json.dumps(agents, ensure_ascii=False, indent=2)
        data_size = len(json_str.encode('utf-8'))
        if data_size > MAX_FILE_SIZE_BYTES:
            error_msg = f"Data size ({data_size} bytes) exceeds maximum allowed ({MAX_FILE_SIZE_BYTES} bytes)"
            logger.error(error_msg)
            raise ValueError(error_msg)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
        os.chmod(file_path, 0o600)
        logger.info(f"Saved {len(agents)} agents to {file_path} ({data_size} bytes)")
    except Exception as e:
        logger.error(f"Failed to save agents to {file_path}: {e}")
        raise


def load_from_file(file_path: str) -> List[Dict[str, Any]]:
    """Load agent dictionaries from a JSON file. If file not found or exceeds size limit, return empty list."""
    if not os.path.exists(file_path):
        logger.warning(f"Persistence file {file_path} not found. Starting with empty registry.")
        return []
    try:
        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            logger.error(f"File {file_path} size ({file_size} bytes) exceeds maximum allowed ({MAX_FILE_SIZE_BYTES} bytes). Cannot load.")
            return []
    except OSError as e:
        logger.error(f"Failed to check file size for {file_path}: {e}")
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.error(f"Invalid format in {file_path}: expected a list")
            return []
        logger.info(f"Loaded {len(data)} agents from {file_path} ({file_size} bytes)")
        return data
    except Exception as e:
        logger.error(f"Failed to load agents from {file_path}: {e}")
        return []


class StorageRegistry:
    _backends: Dict[str, type] = {}

    @classmethod
    def register(cls, name: str, backend_class: type):
        cls._backends[name] = backend_class

    @classmethod
    def get_backend(cls, mode: str, config: dict) -> StorageBackend:
        if mode not in cls._backends:
            raise ValueError(f"Unknown storage mode: {mode}")
        backend = cls._backends[mode]
        return backend.init(config)


StorageRegistry.register("file", FileStorage)
StorageRegistry.register("postgresql", PostgreSQLStorage)