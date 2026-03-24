import configparser
import os
import platform
import stat

from common.util import cipher_util
from common.util.conf_obj import ConfObj
from common.util.constant_param import CONFIG_FILE_PATH, SSL_PATH


def load_conf_as_dict(conf_file: str) -> dict:
    config = configparser.ConfigParser()
    try:
        with open(conf_file, 'r', encoding='utf-8') as f:
            # 读取文件内容
            config.read_string('[DEFAULT]\n' + f.read())
            return dict(config['DEFAULT'])
    except Exception as e:
        return {}


def load_conf_obj(conf_file: str) -> ConfObj:
    config_dict = load_conf_as_dict(conf_file)
    return ConfObj.as_object(config_dict)


def load_cert_password(password_path: str) -> bytes:
    if not os.path.exists(password_path):
        return b""
    # read password file and decrypt content
    with open(password_path, 'r', encoding='utf-8') as f:
        str_content = f.read()
        return cipher_util.decrypt(str_content)


def set_ssl_folder_permissions():
    if platform.system().lower() != "linux":
        # Unsupported system type!
        return
    # 设置目录权限为700
    os.chmod(SSL_PATH, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    # 遍历目录中的所有文件，权限设置为600，不会有递归的情况
    for root, dirs, files in os.walk(SSL_PATH):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            # 设置文件权限600
            os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)

# 单例对象
conf_singleton_obj = load_conf_obj(CONFIG_FILE_PATH)
