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

"""TLS mounts must work without chmod when the controller owns permissions."""
import errno
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from common.util import ssl_config


@pytest.mark.parametrize('mode', [0o600, 0o700])
def test_secure_mount_needs_no_write(monkeypatch, mode):
    monkeypatch.setattr(ssl_config, 'os', SimpleNamespace(
        stat=lambda _: SimpleNamespace(st_mode=mode), chmod=Mock()))
    chmod = Mock(side_effect=OSError(errno.EROFS, 'read-only'))
    monkeypatch.setattr(ssl_config.os, 'chmod', chmod)
    ssl_config._restrict_ssl_permissions('/mounted/secret', mode)
    chmod.assert_not_called()


@pytest.mark.parametrize('error', [errno.EROFS, errno.EPERM, errno.EACCES])
@pytest.mark.parametrize('mode', [0o400, 0o440, 0o750])
def test_secure_controller_permissions_retained(monkeypatch, error, mode):
    monkeypatch.setattr(ssl_config, 'os', SimpleNamespace(
        stat=lambda _: SimpleNamespace(st_mode=mode), chmod=Mock()))
    monkeypatch.setattr(ssl_config.os, 'chmod', Mock(side_effect=OSError(error, 'managed mount')))
    ssl_config._restrict_ssl_permissions('/mounted/secret', 0o600)


@pytest.mark.parametrize('mode', [0o644, 0o666, 0o777, 0o660])
def test_insecure_unmodifiable_mount_fails(monkeypatch, mode):
    monkeypatch.setattr(ssl_config, 'os', SimpleNamespace(
        stat=lambda _: SimpleNamespace(st_mode=mode), chmod=Mock()))
    monkeypatch.setattr(ssl_config.os, 'chmod', Mock(side_effect=OSError(errno.EROFS, 'read-only')))
    with pytest.raises(PermissionError, match='Unsafe permissions'):
        ssl_config._restrict_ssl_permissions('/mounted/secret', 0o600)


def test_other_io_failure_not_swallowed(monkeypatch):
    monkeypatch.setattr(ssl_config, 'os', SimpleNamespace(
        stat=lambda _: SimpleNamespace(st_mode=0o400), chmod=Mock()))
    monkeypatch.setattr(ssl_config.os, 'chmod', Mock(side_effect=OSError(errno.EIO, 'io error')))
    with pytest.raises(OSError) as exc:
        ssl_config._restrict_ssl_permissions('/mounted/secret', 0o600)
    assert exc.value.errno == errno.EIO
