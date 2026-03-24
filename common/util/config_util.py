# config_util.py
from typing import Dict, Any

import os
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
    Returns:
        A dictionary containing all configurations.
    """
    config = {}
    root_path = get_root_path()
    base_config_path = os.path.join(root_path, "etc", "conf", "server.conf")
    safe_config_path = os.path.join(root_path, "etc", "conf", "server.properties")
    load_configs(base_config_path, config)
    load_configs(safe_config_path, config)
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

