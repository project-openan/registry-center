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

# agent_registry/start.py
import asyncio
import os
import ssl
import sys

import uvicorn
from loguru import logger
from uvicorn import config

from agent_registry.cipher_converter import CipherConverter
from agent_registry.config import CONN_TIMEOUT, TLS_CIPHER, FORWARDED_ALLOW_IPS
from agent_registry.server import app
from common.cert.cert_validater import CertValidator
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import LogLevel, OperationResult, OperatorObject, OperationName
from common.util.cipher_util import DEFAULT_ENCODING
from common.util.conf_util import conf_singleton_obj, load_cert_password, set_ssl_folder_permissions
from common.util.config_util import get_conf

audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)


def get_user_info_from_env():
    """Get user information from environment variables"""
    user_info = {
        'username': os.environ.get('APP_USER', 'unknown'),
        'uid': os.environ.get('APP_UID', 'unknown'),
        'gid': os.environ.get('APP_GID', 'unknown'),
    }
    return user_info


async def record_startup_log():
    server_config = get_conf()
    await audit_handle.handle({
        "operation_name": OperationName.START_SERVICE,
        "level": LogLevel.DANGER,
        "result": OperationResult.SUCCESS,
        "object_name": OperatorObject.SERVICE,
        "details": {"ip": server_config.get("ip", ""), "port": server_config.get("port", "")},
        "user_name": get_user_info_from_env().get('username')
    })


app.add_event_handler("startup", record_startup_log)


def customized_create_ssl_context(
        certfile: str | os.PathLike[str],
        keyfile: str | os.PathLike[str] | None,
        password: str | None,
        ssl_version: int,
        cert_reqs: int,
        ca_certs: str | os.PathLike[str] | None,
        ciphers: str | None,
) -> ssl.SSLContext:
    try:
        ctx = ssl.SSLContext(ssl_version)
        get_password = (lambda: password) if password else None
        ctx.load_cert_chain(certfile, keyfile, get_password)
        ctx.verify_mode = ssl.VerifyMode(cert_reqs)
        if ca_certs:
            ctx.load_verify_locations(ca_certs)
            if len(conf_singleton_obj.get_crl_list()) > 0:
                # If CRL is configured, append CRL
                ctx.load_verify_locations(conf_singleton_obj.ssl_crl_file)
                # Enable CRL verification mode
                ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
        if ciphers:
            ctx.set_ciphers(ciphers)
        return ctx
    except BaseException as e:
        logger.error(f"customized_create_ssl_context error {e}")
        raise e


# Extend CRL support since the original config does not support loading CRLs
config.create_ssl_context = customized_create_ssl_context


class CustomUvicornServer:
    """Customized Uvicorn server, which is used to add additional security configurations."""

    def __init__(self, server_config, conf_obj):
        self.server_config = server_config
        self.conf_obj = conf_obj

    def run(self):
        os.environ.setdefault("FORWARDED_ALLOW_IPS", self.server_config.get(FORWARDED_ALLOW_IPS))
        server_config = uvicorn.Config(
            app=app,
            host=self.server_config.get("ip", "127.0.0.1"),
            port=int(self.server_config.get("port", 5000)),
            ssl_certfile=self.conf_obj.ssl_certfile,
            # Private key path
            ssl_keyfile=self.conf_obj.ssl_keyfile,
            # Private key password
            ssl_keyfile_password=load_cert_password(self.conf_obj.ssl_keyfile_password).decode(DEFAULT_ENCODING),
            # Trusted CA certificates
            ssl_ca_certs=self.conf_obj.ssl_ca_certs,
            # Whether to verify client certificates (enabling this prevents browser access without client certs)
            ssl_cert_reqs=self.conf_obj.verify_client,
            ssl_ciphers=CipherConverter.convert(self.server_config.get(TLS_CIPHER)),
            timeout_keep_alive=0,
            timeout_graceful_shutdown=int(self.server_config.get(CONN_TIMEOUT, 30)),
            log_level="info",
            proxy_headers=True
        )
        server = uvicorn.Server(server_config)
        server.run()


def main():
    server_config = get_conf()
    is_https = server_config.get("enable_https", True)
    is_enable_https = str(is_https).lower() == 'true'
    if not is_enable_https:
        uvicorn.run(app, host=server_config.get('ip', "127.0.0.1"), port=int(server_config.get('port', 5000)))
    else:
        try:
            # Validate configuration
            conf_obj = conf_singleton_obj
            result = CertValidator(conf_obj).validate()
            if not result.is_valid:
                sys.exit(result.message)
            # After validation, set etc/ssl directory permissions to 700 and file permissions to 600
            set_ssl_folder_permissions()
            # Create and start server
            server = CustomUvicornServer(server_config, conf_obj)
            server.run()
        except Exception as e:
            logger.error(f"agent_registry server start failed {e}")
            asyncio.run(audit_handle.handle({
                "object_name": OperatorObject.SERVICE,
                "operation_name": OperationName.START_SERVICE,
                "level": LogLevel.DANGER,
                "result": OperationResult.FAILURE,
                "details": {"ip": server_config.get("ip", ""), "port": server_config.get("port", "")},
                "user_name": get_user_info_from_env().get('username')
            }))
            sys.exit(f"agent_registry server start failed: {e}")


if __name__ == "__main__":
    main()