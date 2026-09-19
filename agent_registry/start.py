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

import asyncio
import os
import signal
import ssl
import sys
import threading

import uvicorn
from loguru import logger
from uvicorn import config

from agent_registry.config import CONN_TIMEOUT, TLS_CIPHER, FORWARDED_ALLOW_IPS, IS_WINDOWS
from agent_registry.cipher_converter import CipherConverter
from agent_registry.internal.registry_center_internal_service import RegistryCenterInternalService
from agent_registry.internal.tcp_internal_service import TCPInternalService
from agent_registry.persistence.precheck import verify_storage_ready
from agent_registry.server import app
from common.cert.cert_validater import CertValidator
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import LogLevel, OperationResult, OperatorObject, OperationName
from common.util.cipher_util import DEFAULT_ENCODING
from common.util.ssl_config import conf_singleton_obj, load_cert_password, set_ssl_folder_permissions
from common.util.app_config import get_conf

audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)

_internal_service = None
_internal_thread = None


def get_user_info_from_env():
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


try:
    app.add_event_handler("startup", record_startup_log)
except AttributeError:
    pass


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
                ctx.load_verify_locations(conf_singleton_obj.ssl_crl_file)
                ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
        if ciphers:
            ctx.set_ciphers(ciphers)
        return ctx
    except Exception as e:
        logger.error(f"customized_create_ssl_context error {e}")
        raise


config.create_ssl_context = customized_create_ssl_context


class CustomUvicornServer:
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
            ssl_keyfile=self.conf_obj.ssl_keyfile,
            ssl_keyfile_password=load_cert_password(self.conf_obj.ssl_keyfile_password).decode(DEFAULT_ENCODING),
            ssl_ca_certs=self.conf_obj.ssl_ca_certs,
            ssl_cert_reqs=self.conf_obj.verify_client,
            ssl_ciphers=CipherConverter.convert(self.server_config.get(TLS_CIPHER)),
            timeout_keep_alive=0,
            timeout_graceful_shutdown=int(self.server_config.get(CONN_TIMEOUT, 30)),
            log_level="info",
            proxy_headers=True
        )
        server = uvicorn.Server(server_config)
        server.run()


def _create_internal_service(server_config):
    if IS_WINDOWS:
        logger.warning(
            "Running on Windows: UDS is not supported. "
            "Internal service will use TCP on 127.0.0.1:1108 instead."
        )
        return TCPInternalService()
    else:
        return RegistryCenterInternalService()


def start_internal_service(server_config):
    global _internal_service, _internal_thread
    _internal_service = _create_internal_service(server_config)
    _internal_thread = threading.Thread(target=_internal_service.start, daemon=True)
    _internal_thread.start()

    if IS_WINDOWS:
        logger.info("Internal service started on TCP: 127.0.0.1:1108")
    else:
        logger.info("Internal service started on UDS socket: run/registry-center/internal.sock")


def stop_internal_service():
    global _internal_service
    if _internal_service:
        try:
            _internal_service.stop()
            logger.info("Internal service stopped")
        except Exception as e:
            logger.error(f"Failed to stop internal service: {e}")


def _handle_shutdown_signal(signum, frame):
    logger.info(f"Received signal {signum}, shutting down...")
    stop_internal_service()
    sys.exit(0)


def main():
    if IS_WINDOWS:
        logger.warning(
            "Registry Center is running on Windows. "
            "Windows support is provided for development and debugging purposes. "
            "For production deployment, please use a Linux environment."
        )

    server_config = get_conf()

    # Fail fast on unusable storage (wrong DB config / unreachable DB) before
    # binding any port — including the internal UDS/TCP service below.
    verify_storage_ready()

    start_internal_service(server_config)

    is_https = server_config.get("enable_https", True)
    is_enable_https = str(is_https).lower() == 'true'

    if not is_enable_https:
        try:
            signal.signal(signal.SIGINT, _handle_shutdown_signal)
            signal.signal(signal.SIGTERM, _handle_shutdown_signal)
        except Exception:
            pass
        try:
            uvicorn.run(app, host=server_config.get('ip', "127.0.0.1"), port=int(server_config.get('port', 5000)))
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received, shutting down...")
            stop_internal_service()
    else:
        try:
            conf_obj = conf_singleton_obj
            result = CertValidator(conf_obj).validate()
            if not result.is_valid:
                stop_internal_service()
                sys.exit(result.message)
            set_ssl_folder_permissions()
            try:
                signal.signal(signal.SIGINT, _handle_shutdown_signal)
                signal.signal(signal.SIGTERM, _handle_shutdown_signal)
            except Exception:
                pass
            server = CustomUvicornServer(server_config, conf_obj)
            server.run()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received, shutting down...")
            stop_internal_service()
        except Exception as e:
            logger.error(f"agent_registry server start failed {e}")
            stop_internal_service()
            try:
                asyncio.run(audit_handle.handle({
                    "object_name": OperatorObject.SERVICE,
                    "operation_name": OperationName.START_SERVICE,
                    "level": LogLevel.DANGER,
                    "result": OperationResult.FAILURE,
                    "details": {"ip": server_config.get("ip", ""), "port": server_config.get("port", "")},
                    "user_name": get_user_info_from_env().get('username')
                }))
            except RuntimeError:
                logger.warning("Failed to log audit during shutdown: event loop not available")
            except Exception:
                pass
            sys.exit(f"agent_registry server start failed: {e}")


if __name__ == "__main__":
    main()
