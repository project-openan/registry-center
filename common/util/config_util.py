# config_loader.py
import os
from typing import Dict, Any


def get_root_path() -> str:
    current_script_path = os.path.abspath(__file__)

    # 向上查找，直到找到项目的根目录
    project_root = current_script_path
    while True:
        project_root = os.path.dirname(project_root)
        if os.path.exists(os.path.join(project_root, "requirements.txt")):
            break
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
    if os.path.exists(conf_path):
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
    else:
        print(f"Error: The configuration file {conf_path} does not exist.")

if __name__ == '__main__':
    print(get_conf())