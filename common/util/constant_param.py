import os

from common.util.config_util import get_root_path

ROOT_PATH = get_root_path()
SSL_PATH = os.path.join(ROOT_PATH, "etc", "ssl")
CONFIG_FILE_PATH = os.path.join(ROOT_PATH, "etc", "conf", "server.conf")

