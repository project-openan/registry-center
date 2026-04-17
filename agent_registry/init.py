import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from common.cert.cert_parser import parse_cer_certificate, parse_pem_files
from common.util.cipher_util import encrypt, DEFAULT_ENCODING
from common.util.config_util import get_root_path
from common.util.password_util import input_password_with_validation


class InitCommand:
    def __init__(self):
        self.root_path = get_root_path()
        self.config_file = os.path.join(self.root_path, "etc", "conf", "server.conf")

    def init_command(self):
        print("配置服务端TLS证书：（仅支持RSA算法）")
        tls_config = self.config_tls_cert()

        print("\n配置签名证书：（仅支持RSA算法）")
        sign_config = self.config_sign_cert()

        config = {**tls_config, **sign_config}
        self.save_config_to_file(config)

        print(f"\n配置已完成，已保存在 {self.config_file}")
        print("您可以使用 './start.sh' 启动服务")

    def config_tls_cert(self) -> dict:
        config = {}

        config['ssl_certfile'] = self.input_path(
            "请输入服务端证书路径 ssl_certfile",
            "etc/ssl/service/server_rsa.cer",
            ".cer"
        )

        config['ssl_keyfile'] = self.input_path(
            "请输入服务端私钥路径 ssl_keyfile",
            "etc/ssl/service/server_key_rsa.pem",
            ".pem"
        )

        config['ssl_ca_certs'] = self.input_path(
            "请输入服务端信任证书路径 ssl_ca_certs",
            "etc/ssl/service/trust.cer",
            ".cer"
        )

        config['ssl_cert_certs'] = self.input_path(
            "请输入服务端吊销列表文件路径 ssl_cert_certs",
            "etc/ssl/service/revovationlist.crl",
            ".crl",
            required=False
        )

        password = self.input_password("请输入服务端私钥口令")
        config['ssl_keyfile_password'] = self.save_password_file(password, config['ssl_keyfile'])

        verify_client = input("是否开启客户端证书校验 verify_client (y/n, 默认: y): ").strip()
        config['ssl_verify_client'] = 'true' if verify_client.lower() != 'n' else 'false'

        return config

    def config_sign_cert(self) -> dict:
        config = {}

        config['sign_certfile'] = self.input_path(
            "请输入签名证书路径",
            "etc/sign_cert/server_rsa.cer",
            ".cer"
        )

        config['sign_keyfile'] = self.input_path(
            "请输入签名私钥路径",
            "etc/sign_cert/server_key_rsa.pem",
            ".pem"
        )

        password = self.input_password("请输入签名私钥口令")
        config['sign_keyfile_password'] = self.save_password_file(password, config['sign_keyfile'])

        return config

    def input_path(self, prompt: str, default: str, suffix: str, required: bool = True) -> str:
        while True:
            path = input(f"{prompt}: (当前配置: {default}): ").strip()
            if not path:
                if not required:
                    return ""
                path = default

            result, error = self.validate_cert_path(path, suffix, required)
            if not result:
                print(f"错误：{error}")
                continue

            result, error = self.validate_file_permissions(path)
            if not result:
                print(f"警告：{error}")
                confirm = input("是否继续使用该文件？ (y/n): ").strip().lower()
                if confirm != 'y':
                    continue

            return path

    def input_password(self, prompt: str) -> str:
        return input_password_with_validation(prompt)

    def validate_cert_path(self, path: str, suffix: str, required: bool = True) -> tuple[bool, str]:
        if not path:
            if not required:
                return True, ""
            return False, "路径不能为空"

        path_obj = Path(path)
        if not path_obj.exists():
            return False, f"文件不存在：{path}"

        if not path_obj.is_file():
            return False, f"不是有效的文件：{path}"

        if suffix and path_obj.suffix.lower() != suffix.lower():
            return False, f"文件扩展名不正确，应为 {suffix}"

        return True, ""

    def validate_file_permissions(self, path: str) -> tuple[bool, str]:
        try:
            if os.name == 'nt':
                return True, ""

            stat_info = os.stat(path)
            mode = stat_info.st_mode
            file_perms = oct(mode & 0o777)

            if file_perms != '0o600':
                return False, f"文件 {path} 权限过大（当前权限：{file_perms[2:]}），可能存在安全风险"

            return True, ""
        except Exception as e:
            return False, f"无法获取文件权限：{e}"

    def validate_certificate(self, cert_path: str, key_path: str, password: str) -> tuple[bool, str]:
        try:
            cert_obj = parse_cer_certificate(cert_path)
            if len(cert_obj.cert_list) == 0:
                return False, "证书文件为空"

            cert = cert_obj.cert_list[0]

            if not isinstance(cert.public_key(), x509.RSAPublicKey):
                return False, "证书算法不支持，仅支持RSA"

            private_key = parse_pem_files(key_path, password.encode(DEFAULT_ENCODING))

            if private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ) != cert.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ):
                return False, "私钥与证书不匹配"

            return True, ""
        except Exception as e:
            return False, f"证书验证失败：{e}"

    def save_password_file(self, password: str, key_path: str) -> str:
        encrypted_password = encrypt(password)
        key_path_obj = Path(key_path)
        password_file_path = key_path_obj.parent / f"{key_path_obj.stem}_pwd"

        with open(password_file_path, 'w') as f:
            f.write(encrypted_password)

        os.chmod(password_file_path, 0o600)

        return str(password_file_path)

    def save_config_to_file(self, config: dict):
        config_dir = os.path.dirname(self.config_file)
        os.makedirs(config_dir, exist_ok=True)

        with open(self.config_file, 'w') as f:
            f.write("[ssl]\n")
            f.write(f"ssl_certfile={config.get('ssl_certfile', '')}\n")
            f.write(f"ssl_keyfile={config.get('ssl_keyfile', '')}\n")
            f.write(f"ssl_keyfile_password={config.get('ssl_keyfile_password', '')}\n")
            f.write(f"ssl_ca_certs={config.get('ssl_ca_certs', '')}\n")
            f.write(f"ssl_cert_certs={config.get('ssl_cert_certs', '')}\n")
            f.write(f"ssl_verify_client={config.get('ssl_verify_client', 'true')}\n")
            f.write("\n[sign]\n")
            f.write(f"sign_certfile={config.get('sign_certfile', '')}\n")
            f.write(f"sign_keyfile={config.get('sign_keyfile', '')}\n")
            f.write(f"sign_keyfile_password={config.get('sign_keyfile_password', '')}\n")

        os.chmod(self.config_file, 0o600)


def main():
    init_cmd = InitCommand()
    init_cmd.init_command()


if __name__ == "__main__":
    main()
