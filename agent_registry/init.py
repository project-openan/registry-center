import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from loguru import logger

from common.cert.cert_parser import parse_cer_certificate, parse_pem_files
from common.util.cipher_util import encrypt, DEFAULT_ENCODING
from common.util.config_util import get_root_path
from common.util.password_util import input_password_with_validation


class InitCommand:
    def __init__(self):
        self.root_path = get_root_path()
        self.config_file = os.path.join(self.root_path, "etc", "conf", "server.conf")
        self.persistence_config_file = os.path.join(self.root_path, "etc", "conf", "persistence.conf")
        self.existing_config = self._parse_config_file(self.config_file)
        self.existing_persistence_config = self._parse_config_file(self.persistence_config_file)

    def _parse_config_file(self, file_path: str) -> dict:
        config = {}
        if not os.path.exists(file_path):
            return config
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    key, _, value = line.partition('=')
                    config[key.strip()] = value.strip()
        return config

    def init_command(self):
        config = {}

        default_enable_https = self.existing_config.get('enable_https', 'true')
        enable_https_input = input(f"Enable HTTPS (y/n, default: {default_enable_https}): ").strip()
        if enable_https_input.lower() == 'n':
            config['enable_https'] = 'false'
        elif enable_https_input.lower() == 'y':
            config['enable_https'] = 'true'
        else:
            config['enable_https'] = default_enable_https

        if config['enable_https'] == 'true':
            print("\nConfigure server TLS certificate (RSA only):")
            tls_config = self.config_tls_cert()
            config.update(tls_config)

        default_sign_enabled = self.existing_config.get('registry.sign.enabled', 'true')
        sign_enabled_input = input(
            f"Enable registry signing registry.sign.enabled (y/n, default: {default_sign_enabled}): ").strip()
        if sign_enabled_input.lower() == 'n':
            config['registry.sign.enabled'] = 'false'
        elif sign_enabled_input.lower() == 'y':
            config['registry.sign.enabled'] = 'true'
        else:
            config['registry.sign.enabled'] = default_sign_enabled

        if config['registry.sign.enabled'] == 'true':
            print("\nConfigure signing certificate (RSA only):")
            sign_config = self.config_sign_cert()
            config.update(sign_config)

        default_signature = self.existing_config.get('signature_validation_enabled', 'true')
        signature_validation_input = input(
            f"Enable signature validation (y/n, default: {default_signature}): ").strip()
        if signature_validation_input.lower() == 'n':
            config['signature_validation_enabled'] = 'false'
        elif signature_validation_input.lower() == 'y':
            config['signature_validation_enabled'] = 'true'
        else:
            config['signature_validation_enabled'] = default_signature

        default_approval = self.existing_config.get('agent_approval_enabled', 'false')
        current_approval = default_approval
        approval_input = input(
            f"Enable agent approval (y/n, default: {default_approval}): "
        ).strip().lower()
        
        if approval_input == 'n':
            if current_approval == 'true':
                from agent_registry.registry_instance import get_registry
                registry = get_registry()
                registered_agents = []
                for agent in registry.find_all():
                    if hasattr(agent, 'status') and agent.status == 'registered':
                        registered_agents.append(agent)
                
                if registered_agents:
                    print("Error: Approval function is enabled, cannot disable directly!")
                    print(f"Reason: There are {len(registered_agents)} agents in 'registered' status")
                    print("Suggestions:")
                    print("  1. Publish these agents via approval interface first")
                    print("  2. Or delete these agents via deregister interface")
                    print("  3. Disable approval function after processing")
                    sys.exit(1)
                else:
                    config['agent_approval_enabled'] = 'false'
                    print("Approval function disabled")
            else:
                config['agent_approval_enabled'] = 'false'
                print("Approval function disabled")
        elif approval_input == 'y':
            config['agent_approval_enabled'] = 'true'
            print("Approval function enabled")
        else:
            config['agent_approval_enabled'] = default_approval

        self.save_config_to_file(config)

        print("\n" + "=" * 50)
        print("Persistence Storage Configuration")
        print("=" * 50)
        persistence_config = self.config_persistence()
        self.save_persistence_config_to_file(persistence_config)

        print(f"\nConfiguration complete, saved to {self.config_file}")
        print("You can use './start.sh' to start the service")

    def config_tls_cert(self) -> dict:
        config = {}

        default_ssl_certfile = self.existing_config.get('ssl_certfile', '')
        config['ssl_certfile'] = self.input_path(
            "Enter server certificate path ssl_certfile",
            default_ssl_certfile,
            ".cer"
        )

        default_ssl_keyfile = self.existing_config.get('ssl_keyfile', '')
        ssl_keyfile, keyfile_changed = self.input_path(
            "Enter server private key path ssl_keyfile",
            default_ssl_keyfile,
            ".pem",
            track_change=True
        )
        config['ssl_keyfile'] = ssl_keyfile

        default_ssl_ca_certs = self.existing_config.get('ssl_ca_certs', '')
        config['ssl_ca_certs'] = self.input_path(
            "Enter server trust certificate path ssl_ca_certs",
            default_ssl_ca_certs,
            ".cer"
        )

        default_ssl_cert_certs = self.existing_config.get('ssl_cert_certs', '')
        config['ssl_cert_certs'] = self.input_path(
            "Enter server CRL file path ssl_cert_certs",
            default_ssl_cert_certs,
            ".crl",
            required=False
        )

        if keyfile_changed:
            password = self.input_password("Enter server private key password")
            config['ssl_keyfile_password'] = self.save_password_file(password, ssl_keyfile)
        else:
            config['ssl_keyfile_password'] = self.existing_config.get('ssl_keyfile_password', '')

        default_verify_client = self.existing_config.get('ssl_verify_client', 'true')
        verify_client = input(f"Enable client certificate verification verify_client (y/n, default: {default_verify_client}): ").strip()
        if verify_client.lower() == 'n':
            config['ssl_verify_client'] = 'false'
        elif verify_client.lower() == 'y':
            config['ssl_verify_client'] = 'true'
        else:
            config['ssl_verify_client'] = default_verify_client

        return config

    def config_sign_cert(self) -> dict:
        config = {}

        default_sign_certfile = self.existing_config.get('sign_certfile', '')
        config['sign_certfile'] = self.input_path(
            "Enter signing certificate path sign_certfile",
            default_sign_certfile,
            ".cer"
        )

        default_sign_keyfile = self.existing_config.get('sign_keyfile', '')
        sign_keyfile, keyfile_changed = self.input_path(
            "Enter signing private key path sign_keyfile",
            default_sign_keyfile,
            ".pem",
            track_change=True
        )
        config['sign_keyfile'] = sign_keyfile

        if keyfile_changed:
            password = self.input_password("Enter signing private key password")
            config['sign_keyfile_password'] = self.save_password_file(password, sign_keyfile)
        else:
            config['sign_keyfile_password'] = self.existing_config.get('sign_keyfile_password', '')

        return config

    def input_path(self, prompt: str, default: str, suffix: str, required: bool = True, track_change: bool = False):
        while True:
            prompt_text = f"{prompt}: (current: {default}): " if default else f"{prompt}: "
            path = input(prompt_text).strip()

            changed = False
            if not path:
                if default:
                    path = default
                elif not required:
                    if track_change:
                        return "", False
                    return ""
                else:
                    print("Error: path cannot be empty")
                    continue
            else:
                changed = (path != default)

            result, error = self.validate_cert_path(path, suffix, required if not default else False)
            if not result:
                print(f"Error: {error}")
                continue

            result, error = self.validate_file_permissions(path)
            if not result:
                print(f"Warning: {error}")
                confirm = input("Continue using this file? (y/n): ").strip().lower()
                if confirm != 'y':
                    continue

            if track_change:
                return path, changed
            return path

    def input_password(self, prompt: str) -> str:
        return input_password_with_validation(prompt)

    def validate_cert_path(self, path: str, suffix: str, required: bool = True) -> tuple[bool, str]:
        if not path:
            if not required:
                return True, ""
            return False, "Path cannot be empty"

        path_obj = Path(path)
        if not path_obj.exists():
            return False, f"File does not exist: {path}"

        if not path_obj.is_file():
            return False, f"Not a valid file: {path}"

        if suffix and path_obj.suffix.lower() != suffix.lower():
            return False, f"Incorrect file extension, expected {suffix}"

        return True, ""

    def validate_file_permissions(self, path: str) -> tuple[bool, str]:
        try:
            if os.name == 'nt':
                return True, ""

            stat_info = os.stat(path)
            mode = stat_info.st_mode
            file_perms = oct(mode & 0o777)

            if file_perms != '0o600':
                return False, f"File {path} has overly permissive permissions (current: {file_perms[2:]}), security risk"

            return True, ""
        except Exception as e:
            return False, f"Cannot read file permissions: {e}"

    def validate_certificate(self, cert_path: str, key_path: str, password: str) -> tuple[bool, str]:
        try:
            cert_obj = parse_cer_certificate(cert_path)
            if len(cert_obj.cert_list) == 0:
                return False, "Certificate file is empty"

            cert = cert_obj.cert_list[0]

            if not isinstance(cert.public_key(), x509.RSAPublicKey):
                return False, "Unsupported certificate algorithm, RSA only"

            private_key = parse_pem_files(key_path, password.encode(DEFAULT_ENCODING))

            if private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
            ) != cert.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ):
                return False, "Private key does not match certificate"

            return True, ""
        except Exception as e:
            return False, f"Certificate validation failed: {e}"

    def save_password_file(self, password: str, key_path: str) -> str:
        encrypted_password = encrypt(password)
        key_path_obj = Path(key_path)
        password_file_path = key_path_obj.parent / f"{key_path_obj.stem}_pwd"

        with open(password_file_path, 'w', encoding='utf-8') as f:
            f.write(encrypted_password)

        os.chmod(password_file_path, 0o600)

        return str(password_file_path)

    def save_config_to_file(self, config: dict):
        config_dir = os.path.dirname(self.config_file)
        os.makedirs(config_dir, exist_ok=True)

        existing_config = {}
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and '=' in line:
                        key, _, value = line.partition('=')
                        existing_config[key.strip()] = value.strip()

        existing_config.update(config)

        with open(self.config_file, 'w', encoding='utf-8') as f:
            for key, value in existing_config.items():
                f.write(f"{key}={value}\n")

        os.chmod(self.config_file, 0o600)

    def config_persistence(self) -> dict:
        config = {}

        default_mode = self.existing_persistence_config.get('persistence.mode', 'file')
        mode_input = input(
            f"\nSelect storage mode persistence.mode (file/postgresql, default: {default_mode}): "
        ).strip()
        config['persistence.mode'] = mode_input or default_mode

        if config['persistence.mode'] == 'postgresql':
            print("\nConfigure PostgreSQL database connection:")
            default_host = self.existing_persistence_config.get('postgresql.host', 'localhost')
            host_input = input(f"Enter database host postgresql.host (default: {default_host}): ").strip()
            config['postgresql.host'] = host_input or default_host

            default_port = self.existing_persistence_config.get('postgresql.port', '5432')
            port_input = input(f"Enter database port postgresql.port (default: {default_port}): ").strip()
            config['postgresql.port'] = port_input or default_port

            default_name = self.existing_persistence_config.get('postgresql.name', 'a2a_registry')
            name_input = input(f"Enter database name postgresql.name (default: {default_name}): ").strip()
            config['postgresql.name'] = name_input or default_name

            default_username = self.existing_persistence_config.get('postgresql.username', 'a2a_user')
            username_input = input(f"Enter database user postgresql.username (default: {default_username}): ").strip()
            config['postgresql.username'] = username_input or default_username

            password_input = input(f"Enter database password postgresql.password: ").strip()
            if password_input:
                config['postgresql.password'] = encrypt(password_input)
            else:
                config['postgresql.password'] = self.existing_persistence_config.get('postgresql.password', '')

        return config

    def _get_persistence_config_header(self) -> str:
        return """# Copyright (c) 2026 Huawei Technologies Co., Ltd.
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

# Persistence mode: file / postgresql / sqlite / gauss
"""

    def save_persistence_config_to_file(self, config: dict):
        config_dir = os.path.dirname(self.persistence_config_file)
        os.makedirs(config_dir, exist_ok=True)

        existing_config = self._parse_config_file(self.persistence_config_file)
        existing_config.update(config)

        with open(self.persistence_config_file, 'w', encoding='utf-8') as f:
            f.write(self._get_persistence_config_header())
            for key, value in existing_config.items():
                f.write(f"{key}={value}\n")

        os.chmod(self.persistence_config_file, 0o600)


def main():
    init_cmd = InitCommand()
    init_cmd.init_command()


if __name__ == "__main__":
    main()
