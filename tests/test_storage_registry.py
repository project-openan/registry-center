# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
StorageRegistry factory unit tests.

Verifies the factory dispatches to the correct backend for each mode
and rejects unknown modes. Uses unittest.mock to avoid real DB connections.
"""

import pytest
from unittest.mock import patch, MagicMock

from agent_registry.persistence import StorageRegistry


class TestStorageRegistryFactory:
    """Test StorageRegistry.get_backend dispatch logic."""

    @patch("agent_registry.persistence.FileStorage.init")
    def test_file_mode_dispatches_to_file_storage(self, mock_init):
        mock_init.return_value = MagicMock()
        StorageRegistry.get_backend("file", {"file.path": "/tmp/x.json"})
        mock_init.assert_called_once_with({"file.path": "/tmp/x.json"})

    @patch("agent_registry.persistence.postgresql_storage.PostgreSQLStorage.init")
    def test_postgresql_mode_dispatches_to_postgresql(self, mock_init):
        mock_init.return_value = MagicMock()
        config = {"postgresql.host": "localhost"}
        StorageRegistry.get_backend("postgresql", config)
        mock_init.assert_called_once_with(config)

    @patch("agent_registry.persistence.sqlite_storage.SQLiteStorage.init")
    def test_sqlite_mode_dispatches_to_sqlite(self, mock_init):
        mock_init.return_value = MagicMock()
        config = {"sqlite.path": "/tmp/agents.db"}
        StorageRegistry.get_backend("sqlite", config)
        mock_init.assert_called_once_with(config)

    @patch("agent_registry.persistence.gaussdb_storage.GaussDBStorage.init")
    def test_gauss_mode_dispatches_to_gaussdb(self, mock_init):
        mock_init.return_value = MagicMock()
        config = {"gauss.host": "localhost"}
        StorageRegistry.get_backend("gauss", config)
        mock_init.assert_called_once_with(config)

    @pytest.mark.parametrize("mode", ["", "mysql", "redis", "mongo", "FILE", "PostgreSQL"])
    def test_unknown_mode_raises_value_error(self, mode):
        with pytest.raises(ValueError, match="Unknown storage mode"):
            StorageRegistry.get_backend(mode, {})

    def test_unknown_mode_error_includes_mode_name(self):
        try:
            StorageRegistry.get_backend("weird-db", {})
            assert False, "should have raised"
        except ValueError as e:
            assert "weird-db" in str(e)
