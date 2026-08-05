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

# app_config.py — application-level configuration loading
import configparser
import os
import re
from typing import Dict, Any

from loguru import logger


def get_root_path() -> str:
    """
    get the root path of the component
    Returns:
        the root path
    """
    current_script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(current_script_path)
    project_root = os.path.dirname(os.path.dirname(script_dir))
    return project_root


def get_conf() -> Dict[str, Any]:
    """
    Load all server configurations.
    File configs are loaded first, then REGISTRY_* env vars override them.
    Returns:
        A dictionary containing all configurations.
    """
    config = {}
    root_path = get_root_path()
    base_config_path = os.path.join(root_path, "etc", "conf", "server.conf")
    safe_config_path = os.path.join(root_path, "etc", "conf", "server.properties")
    load_configs(base_config_path, config)
    load_configs(safe_config_path, config)
    apply_env_overrides(config)
    return config


def load_configs(conf_path, config):
    if not os.path.exists(conf_path):
        logger.error(f"Error: The configuration file {conf_path} does not exist.")
        return
    with open(conf_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Processing Comments
            if '#' in line:
                line = line[:line.index('#')].strip()

            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()

                config[key.lower()] = value


def load_conf_as_dict(conf_file: str) -> dict:
    config = configparser.ConfigParser()
    try:
        with open(conf_file, 'r', encoding='utf-8') as f:
            config.read_string('[DEFAULT]\n' + f.read())
            return dict(config['DEFAULT'])
    except Exception as e:
        logger.error(f"load config failed, {e}")
        return {}


def apply_env_overrides(conf: Dict[str, Any]) -> None:
    """
    Override config values with REGISTRY_* environment variables.
    Env var REGISTRY_FOO_BAR overrides config key 'foo.bar' or 'foobar'.
    """
    env_prefix = "REGISTRY_"
    for env_key, env_value in os.environ.items():
        if not env_key.startswith(env_prefix):
            continue
        raw_key = env_key[len(env_prefix):].lower()
        config_key = raw_key.replace("_", ".")
        if config_key in conf:
            conf[config_key] = env_value
            continue
        config_key_no_dot = raw_key.strip("_")
        if config_key_no_dot in conf:
            conf[config_key_no_dot] = env_value
            continue
        conf[raw_key] = env_value


def _resolve_env_vars(conf: dict) -> dict:
    """
    Resolve environment variables in config values.
    Format: ${ENV_VAR:default_value}
    """
    resolved = {}
    for key, value in conf.items():
        if isinstance(value, str):
            pattern = r'\$\{([^}:]+)(?:([^}]*))?\}'
            matches = re.findall(pattern, value)
            for env_var, default in matches:
                env_value = os.environ.get(env_var, default.lstrip(':') if default else '')
                value = value.replace(f'${{{env_var}{default}}}', env_value)
        resolved[key] = value
    return resolved


def get_persistence_conf() -> dict:
    """
    Read persistence configuration file with environment variable substitution.
    Decrypt database password if present.
    """
    root_path = get_root_path()
    persistence_conf_path = os.path.join(root_path, "etc", "conf", "persistence.conf")
    conf = load_conf_as_dict(persistence_conf_path)
    conf = _resolve_env_vars(conf)
    apply_env_overrides(conf)
    if 'postgresql.password' in conf and conf['postgresql.password']:
        from common.util.cipher_util import decrypt
        decrypted = decrypt(conf['postgresql.password'])
        conf['postgresql.password'] = decrypted.decode('utf-8') if isinstance(decrypted, bytes) else decrypted
    if 'gauss.password' in conf and conf['gauss.password']:
        from common.util.cipher_util import decrypt
        decrypted = decrypt(conf['gauss.password'])
        conf['gauss.password'] = decrypted.decode('utf-8') if isinstance(decrypted, bytes) else decrypted
    return conf
