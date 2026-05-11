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

import asyncio
import configparser
import os
import platform
import re
import stat

from loguru import logger

from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.util import cipher_util
from common.util.conf_obj import ConfObj
from common.util.config_util import get_root_path
from common.util.constant_param import CONFIG_FILE_PATH, SSL_PATH

decrypt_handle = HandlerRegistry.get_handler(InterfaceType.DECRYPT)

def load_conf_as_dict(conf_file: str) -> dict:
    config = configparser.ConfigParser()
    try:
        with open(conf_file, 'r', encoding='utf-8') as f:
            # Read file content
            config.read_string('[DEFAULT]\n' + f.read())
            return dict(config['DEFAULT'])
    except Exception as e:
        logger.error(f"load config failed, {e}")
        return {}


def load_conf_obj(conf_file: str) -> ConfObj:
    config_dict = load_conf_as_dict(conf_file)
    return ConfObj.as_object(config_dict)


def load_cert_password(password_path: str) -> bytes:
    if not os.path.exists(password_path):
        return b""
    # read password file and decrypt content
    with open(password_path, 'r', encoding='utf-8') as f:
        # File may contain newline characters
        str_content = f.read().strip()
        return asyncio.run(decrypt_handle.handle(str_content))


def set_ssl_folder_permissions():
    if platform.system().lower() != "linux":
        logger.info(f"current system type is: {platform.system().lower()}")
        return
    # Set directory permissions to 700
    os.chmod(SSL_PATH, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    # Traverse all files in the directory, set permissions to 600 (non-recursive)
    for root, _, files in os.walk(SSL_PATH):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            # Set file permissions to 600
            os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)


def get_persistence_conf() -> dict:
    """
    Read persistence configuration file with environment variable substitution.
    Decrypt database password if present.
    """
    root_path = get_root_path()
    persistence_conf_path = os.path.join(root_path, "etc", "conf", "persistence.conf")
    conf = load_conf_as_dict(persistence_conf_path)
    conf = _resolve_env_vars(conf)
    if 'postgresql.password' in conf and conf['postgresql.password']:
        from common.util.cipher_util import decrypt
        decrypted = decrypt(conf['postgresql.password'])
        conf['postgresql.password'] = decrypted.decode('utf-8') if isinstance(decrypted, bytes) else decrypted
    return conf


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


# Singleton instance
conf_singleton_obj = load_conf_obj(CONFIG_FILE_PATH)
