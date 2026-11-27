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

"""Execute the real Bash entrypoint and Python config/init consumers.

Serve is intercepted to observe configuration without binding ports. A separate
Linux container smoke job exercises the real image and service listeners.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def bash():
    if os.name == 'nt':
        git = shutil.which('git')
        candidates = [Path(git).resolve().parents[1] / 'bin/bash.exe'] if git else []
        executable = next((str(p) for p in candidates if p.is_file()), None)
    else:
        executable = shutil.which('bash')
    if not executable:
        pytest.skip('Bash required for container entrypoint contract tests')
    return executable


def shell_path(bash, path):
    if os.name != 'nt':
        return str(path)
    return subprocess.check_output([bash, '-c', 'cygpath -u "$1"', 'probe', str(path)], text=True).strip()


@pytest.fixture
def run_entry(tmp_path, bash):
    conf = tmp_path / 'etc/conf'
    conf.mkdir(parents=True)
    for name in ('server.conf', 'persistence.conf'):
        shutil.copyfile(REPO / 'etc/conf' / (name + '.example'), conf / name)
    shutil.copyfile(REPO / 'etc/conf/server.properties', conf / 'server.properties')
    shim = tmp_path / 'shim'
    shim.mkdir()
    probe = tmp_path / 'probe.py'
    probe.write_text('''import json, os, sys
from common.util import app_config
app_config.get_root_path = lambda: os.environ['APP_HOME']
if sys.argv[2] == 'agent_registry.init':
    from agent_registry.init import main
    main(sys.argv[3:])
else:
    conf = app_config.get_conf()
    persistence = app_config.get_persistence_conf()
    print(json.dumps({'port': conf['port'],
                      'owner_mode': conf['owner.validation.mode'],
                      'https': conf['enable_https'],
                      'owner_isolation': conf['owner.isolation.enabled'],
                      'heartbeat_interval': conf['heartbeat.interval'],
                      'jwk_ratelimit': conf['flowcontrol.ratelimit.jwk'],
                      'mode': persistence['persistence.mode'],
                      'password_matches': persistence.get('mysql.password') == 'fixture#&\\\\value'}))
''', encoding='utf-8')
    (shim / 'python').write_text('#!/bin/bash\nexec "$REAL_PYTHON" "$PROBE_SCRIPT" "$@"\n', encoding='utf-8', newline='\n')
    (shim / 'python3').write_text('#!/bin/bash\nexec "$REAL_PYTHON" "$@"\n', encoding='utf-8', newline='\n')
    for path in shim.iterdir():
        path.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('REGISTRY_', 'DB_', 'LLM_', 'GAUSS_', 'MYSQL_'))}
    for key in ('PORT', 'PERSISTENCE_MODE'):
        env.pop(key, None)
    # Match the image defaults, including absence of a baked owner mode.
    env.update(APP_HOME=str(tmp_path), PYTHONPATH=str(REPO),
               REAL_PYTHON=shell_path(bash, sys.executable), PROBE_SCRIPT=shell_path(bash, probe),
               PROBE_BIN=shell_path(bash, shim), REGISTRY_IP='0.0.0.0', REGISTRY_PORT='8080',
               REGISTRY_ENABLE_HTTPS='true', REGISTRY_VERIFY_CLIENT='true',
               REGISTRY_OWNER_ISOLATION_ENABLED='true', REGISTRY_STARTUP_STRICT_IDENTITY='true')

    def run(changes=None, args=('serve',)):
        result = subprocess.run(
            [bash, '-c', 'export PATH="$PROBE_BIN:/usr/bin:/bin:$PATH"; exec bash "$1" "${@:2}"',
             'probe', shell_path(bash, REPO / 'bin/entrypoint.sh'), *args],
            env=dict(env, **(changes or {})), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=30)
        return result
    return run


def effective(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_platform_port_wins_in_actual_python_consumer(run_entry):
    assert effective(run_entry({'PORT': '9090'}))['port'] == '9090'


def test_image_default_and_empty_argv(run_entry):
    assert effective(run_entry(args=()))['port'] == '8080'


def test_explicit_registry_port(run_entry):
    assert effective(run_entry({'REGISTRY_PORT': '5001'}))['port'] == '5001'


def test_policy_environment_overrides_reach_python_consumer(run_entry, tmp_path):
    conf = effective(run_entry({'REGISTRY_HEARTBEAT_INTERVAL': '45',
                                'REGISTRY_FLOWCONTROL_RATELIMIT_JWK': '25'}))
    assert conf['heartbeat_interval'] == '45'
    assert conf['jwk_ratelimit'] == '25'
    deployment = (tmp_path / 'etc/conf/server.conf').read_text(encoding='utf-8')
    assert 'heartbeat.interval=' not in deployment
    assert 'flowcontrol.ratelimit.jwk=' not in deployment


@pytest.mark.parametrize('port', ['0', '65536', '-1', 'word', '999999999999999',
                                  pytest.param('1\nIP=evil',
                                               marks=pytest.mark.skipif(
                                                   sys.platform == 'win32',
                                                   reason='Windows 环境变量值不允许包含换行符'))])
def test_invalid_platform_port_rejected(run_entry, port):
    result = run_entry({'PORT': port})
    assert result.returncode == 2
    assert 'between 1 and 65535' in result.stderr


def test_legacy_strict_is_not_hidden_by_image_default(run_entry):
    assert effective(run_entry({'REGISTRY_OWNER__VALIDATION__MODE': 'strict'}))['owner_mode'] == 'strict'


def test_canonical_owner_mode_wins_when_both_are_explicit(run_entry):
    result = run_entry({'REGISTRY_OWNER__VALIDATION__MODE': 'strict', 'REGISTRY_OWNER_VALIDATION_MODE': 'relaxed'})
    assert effective(result)['owner_mode'] == 'relaxed'
    assert 'deprecated' in result.stderr


def test_serve_flags_are_not_silently_ignored(run_entry):
    result = run_entry(args=('serve', '--port', '9090'))
    assert result.returncode == 2
    assert 'accepts no arguments' in result.stderr


def test_http_never_implicitly_disables_ownership(run_entry):
    conf = effective(run_entry({'REGISTRY_ENABLE_HTTPS': 'false'}))
    assert conf['https'] == 'false'
    assert conf['owner_isolation'] == 'true'


def test_noninteractive_init_no_stdin(run_entry):
    result = run_entry({'REGISTRY_ENABLE_HTTPS': 'false', 'REGISTRY_OWNER_ISOLATION_ENABLED': 'false'}, ('init',))
    assert result.returncode == 0, result.stderr
    assert 'validation passed' in result.stdout
    assert 'Enter server' not in result.stdout
    assert 'EOFError' not in result.stderr


def test_noninteractive_init_rejects_unusable_identity(run_entry):
    result = run_entry({'REGISTRY_ENABLE_HTTPS': 'false'}, ('init',))
    assert result.returncode == 1
    assert 'enable_https=false' in result.stderr


def test_noninteractive_init_requires_real_tls_material(run_entry):
    result = run_entry(args=('init',))
    assert result.returncode == 1
    assert 'validation failed' in result.stderr
    assert 'EOFError' not in result.stderr


def test_init_rejects_unknown_flags(run_entry):
    result = run_entry(args=('init', '--unknown'))
    assert result.returncode == 2
    assert 'unrecognized arguments' in result.stderr


def test_database_override_preserves_metacharacters(run_entry):
    conf = effective(run_entry({'PERSISTENCE_MODE': 'mysql', 'DB_PASSWORD': 'fixture#&\\value'}))
    assert conf['mode'] == 'mysql'
    assert conf['password_matches']


def test_model_generation_does_not_persist_api_secret(run_entry, tmp_path):
    result = run_entry({'LLM_CHAT_MODEL': 'fixture', 'LLM_CHAT_URL': 'http://localhost:9/v1', 'LLM_CHAT_API_KEY': 'fixture-secret'})
    effective(result)
    text = (tmp_path / 'etc/config/models.yaml').read_text(encoding='utf-8')
    assert 'api_key_env: LLM_CHAT_API_KEY' in text
    assert 'fixture-secret' not in text


def test_incomplete_model_config_fails(run_entry):
    result = run_entry({'LLM_CHAT_MODEL': 'fixture'})
    assert result.returncode == 1
    assert 'Incomplete chat model' in result.stderr


def test_docker_copy_allowlist_and_exclusions():
    dockerfile = (REPO / 'Dockerfile').read_text(encoding='utf-8')
    assert 'COPY . ' not in dockerfile
    assert 'COPY etc/conf/server.conf.example ' in dockerfile
    assert 'COPY etc/conf/persistence.conf.example ' in dockerfile
    assert 'REGISTRY_OWNER_VALIDATION_MODE=relaxed' not in dockerfile
    patterns = (REPO / '.dockerignore').read_text(encoding='utf-8').splitlines()
    for path in ('etc/ssl/', 'etc/sign_cert/', 'etc/sign_verify/', 'etc/conf/server.conf',
                 'etc/conf/persistence.conf', 'etc/conf/integration_credentials.conf',
                 '**/cipher.key', '.env', 'etc/config/models.yaml', 'registry-center-web/', 'reviews/'):
        assert path in patterns


def test_shell_is_lf_and_portable_across_windows_checkout():
    assert b'\r\n' not in (REPO / 'bin/entrypoint.sh').read_bytes()
    assert '*.sh text eol=lf' in (REPO / '.gitattributes').read_text()
    assert "sed -i 's/\\r$//'" in (REPO / 'Dockerfile').read_text()


def test_cloud_upload_secrets_excluded():
    patterns = (REPO / '.gcloudignore').read_text().splitlines()
    for path in ('etc/ssl/', 'etc/sign_cert/', 'etc/conf/server.conf',
                 'etc/conf/persistence.conf', 'etc/config/models.yaml', '**/cipher.key'):
        assert path in patterns


def test_cloud_run_default_refuses_before_cloud_operations():
    powershell = shutil.which('pwsh') or shutil.which('powershell')
    if not powershell:
        pytest.skip('PowerShell required to exercise Cloud Run preflight')
    # 用 -Command + ErrorActionPreference=Stop 捕获原始异常消息：Write-Error 走
    # 控制台错误渲染时会被按宽度省略截断（'...'），消息体无法完整到达 stderr
    command = ("$ErrorActionPreference='Stop'\n"
               "try {{ & '{script}' }} catch {{ $_.Exception.Message; exit 1 }}\n"
               ).format(script=str(REPO / 'deploy-all.ps1'))
    result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', command],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert 'cannot provide verified owner identities' in result.stdout
    assert '[1/5]' not in result.stdout
    script = (REPO / 'deploy-all.ps1').read_text(encoding='utf-8')
    assert '--no-allow-unauthenticated' in script
    assert '--set-secrets="DB_PASSWORD=${SECRET_ID}:latest"' in script
    assert '$envVars += ",DB_PASSWORD=' not in script
