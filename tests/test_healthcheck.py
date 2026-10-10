# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock

import pytest

from agent_registry import healthcheck


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(healthcheck, 'get_conf', lambda: {'port': '5000', 'enable_https': 'false'})
    for name in ('PORT', 'REGISTRY_HEALTHCHECK_HOST', 'REGISTRY_HEALTHCHECK_CLIENT_CERT', 'REGISTRY_HEALTHCHECK_CLIENT_KEY'):
        monkeypatch.delenv(name, raising=False)
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.status = 200
    monkeypatch.setattr(healthcheck, 'build_opener', lambda *handlers: opener)
    return opener, response


def test_http_probe_matches_configuration(setup):
    opener, response = setup
    healthcheck.probe()
    opener.open.assert_called_once_with(
        'http://127.0.0.1:5000/health', timeout=5)
    response.read.assert_not_called()


def test_platform_port_overrides_config_for_separate_probe_process(setup, monkeypatch):
    opener, _ = setup
    monkeypatch.setenv('PORT', '9090')
    healthcheck.probe()
    opener.open.assert_called_once_with(
        'http://127.0.0.1:9090/health', timeout=5)


def test_empty_platform_port_uses_configured_port(setup, monkeypatch):
    opener, _ = setup
    monkeypatch.setenv('PORT', '')
    healthcheck.probe()
    opener.open.assert_called_once_with(
        'http://127.0.0.1:5000/health', timeout=5)


def test_https_uses_ca_and_client_credentials(setup, monkeypatch):
    opener, _ = setup
    monkeypatch.setattr(healthcheck, 'get_conf', lambda: {
        'port': '5000', 'enable_https': 'true', 'verify_client': 'true', 'ssl_ca_certs': 'ca.cer'})
    monkeypatch.setattr(healthcheck, 'get_root_path', lambda: 'E:/test-probe')
    monkeypatch.setenv('REGISTRY_HEALTHCHECK_CLIENT_CERT', 'client.cer')
    monkeypatch.setenv('REGISTRY_HEALTHCHECK_CLIENT_KEY', 'client.pem')
    context = MagicMock()
    create_context = MagicMock(return_value=context)
    monkeypatch.setattr(healthcheck.ssl, 'create_default_context', create_context)
    healthcheck.probe()
    assert create_context.call_args.kwargs['cafile'].endswith('ca.cer')
    context.load_cert_chain.assert_called_once()
    assert opener.open.call_args.args[0].startswith('https://')


def test_mtls_without_probe_certificate_fails(setup, monkeypatch):
    opener, _ = setup
    monkeypatch.setattr(healthcheck, 'get_conf', lambda: {'enable_https': 'true', 'verify_client': 'true'})
    monkeypatch.setattr(healthcheck.ssl, 'create_default_context', MagicMock())
    with pytest.raises(ValueError, match='mTLS probe requires'):
        healthcheck.probe()
    opener.open.assert_not_called()


def test_failed_http_status_is_not_healthy(setup):
    _, response = setup
    response.status = 503
    with pytest.raises(RuntimeError, match='503'):
        healthcheck.probe()
