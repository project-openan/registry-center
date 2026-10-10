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

"""
Integration access port listener.

Runs the integration FastAPI application on a dedicated port in a daemon
thread (multi-listener precedent: the internal TCP service). The port is
HTTPS by default. Explicit HTTP deployments retain application authentication
but send credentials in plaintext; mTLS-only policies are rejected in HTTP mode.
"""

import asyncio
import ssl
import threading
import time
from typing import Optional

import uvicorn
from loguru import logger

from agent_registry.cipher_converter import CipherConverter
from agent_registry.identity import install_tls_peer_cert_injection
from agent_registry.integration.app import close_integration_resources, integration_app
from common.util.ssl_config import conf_singleton_obj, load_cert_password

DEFAULT_ENCODING = 'utf-8'
DEFAULT_INTEGRATION_PORT = 5001
_STARTUP_TIMEOUT_SECONDS = 30

# ---------------------------------------------------------------------------
# Peer-certificate injection.
#
# uvicorn does not expose the TLS peer certificate to the ASGI application.
# The shared implementation in agent_registry.identity wraps the HTTP cycle so
# every request scope carries scope["tls_peer_cert"] (and the direct peer
# address used by owner.identity.mode=trusted_proxy). Installed at import time
# because the integration server can be started without start.py; the main
# port uses the same implementation.
# ---------------------------------------------------------------------------
import logging as _stdlib_logging

install_tls_peer_cert_injection()


class _IntegrationAccessLogFilter(_stdlib_logging.Filter):
    """Redact query strings at the shared transport logging boundary.

    Main-listener dictConfig recreates handlers after integration startup, so
    access_log=False alone is insufficient. Logger filters survive that reset.
    Uvicorn h11/httptools access records use (peer, method, URL, version, status).
    """

    def filter(self, record):
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            # Includes 404s and proxy root_path, independent of routing or port.
            record.args = (*args[:2], args[2].split('?', 1)[0], *args[3:])
        return True


_stdlib_logging.getLogger('uvicorn.access').addFilter(_IntegrationAccessLogFilter())

def _make_ssl_context_factory(conf_obj, require_client_cert: bool):
    """Build a uvicorn ssl_context_factory for this listener.

    Delegates the base context (server chain, verify mode, CA bundle,
    ciphers) to uvicorn's default factory, then adds the CRL leaf check so
    revoked client certificates are rejected during the TLS handshake.
    """

    def ssl_context_factory(config: uvicorn.Config, default_factory) -> ssl.SSLContext:
        ctx = default_factory()
        if require_client_cert and conf_obj.ssl_crl_file and len(conf_obj.get_crl_list()) > 0:
            ctx.load_verify_locations(conf_obj.ssl_crl_file)
            ctx.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
        return ctx

    return ssl_context_factory


class ThirdPartyAccessServer:
    """Owns the lifecycle of the integration access port."""

    def __init__(self, config: dict = None, conf_obj=None):
        self.config = config if config is not None else {}
        self.conf_obj = conf_obj if conf_obj is not None else conf_singleton_obj
        self.enabled = str(self.config.get('integration.enabled', 'false')).lower() == 'true'
        self.host = str(self.config.get('integration.ip', self.config.get('ip', '127.0.0.1')))
        self.port = int(self.config.get('integration.port', DEFAULT_INTEGRATION_PORT))
        self.require_client_cert = str(
            self.config.get('integration.client_cert', 'false')).lower() == 'true'
        self.enable_https = str(self.config.get('integration.enable_https', 'true')).lower() == 'true'
        self._server: uvicorn.Server = None
        self._thread: threading.Thread = None
        self._startup_error: Optional[BaseException] = None
        self._loop = None
        self._serve_task = None

    def start(self) -> None:
        """Start the listener. No-op when integration access is disabled."""
        if not self.enabled:
            logger.info("Integration access port disabled (integration.enabled=false)")
            return
        if self._thread is not None:
            logger.warning("Integration access server already started")
            return
        if not self.enable_https and (self.require_client_cert
                or self.config.get('integration.auth.mode') == 'mtls'):
            raise ValueError('Integration mTLS authentication requires integration.enable_https=true')

        # Resources are created and disposed in the listener's own event loop.
        from agent_registry.integration.authn import ThirdPartyAuthnHandler
        from agent_registry.integration.token_acquisition import configure_token_acquisition
        from common.custom.custom_handle import HandlerRegistry
        from common.custom.interface_type import InterfaceType
        auth_config = dict(self.config)
        if self.require_client_cert and 'integration.auth.mode' not in auth_config:
            auth_config['integration.auth.mode'] = 'mtls'
        cert_reqs = ssl.CERT_REQUIRED if self.require_client_cert else ssl.CERT_NONE
        raw_ciphers = self.config.get('tls.cipher') or ''
        tls_kwargs = {}
        if self.enable_https:
            tls_kwargs = dict(
                ssl_certfile=self.conf_obj.ssl_certfile,
                ssl_keyfile=self.conf_obj.ssl_keyfile,
                ssl_keyfile_password=load_cert_password(
                self.conf_obj.ssl_keyfile_password).decode(DEFAULT_ENCODING),
                ssl_ca_certs=self.conf_obj.ssl_ca_certs if self.require_client_cert else None,
                ssl_cert_reqs=cert_reqs,
                ssl_ciphers=CipherConverter.convert(raw_ciphers) if raw_ciphers.strip() else None,
                ssl_context_factory=_make_ssl_context_factory(self.conf_obj, self.require_client_cert),
            )
        else:
            logger.warning('Integration HTTP explicitly enabled: credentials travel in plaintext')
        uv_config = uvicorn.Config(
            app=integration_app, host=self.host, port=self.port,
            **tls_kwargs,
            # Keep Uvicorn's finite idle timeout, matching the main listener.
            # Closing immediately after a response races client connection pools.
            # Uvicorn's access log includes the raw query string, even on rejected
            # credential-in-URL requests. The structured integration audit is used instead.
            access_log=False,
            log_level="info",
        )
        # Certificate/configuration errors occur before any provider is allocated.
        uv_config.load()
        logger.info(f"Integration access TLS: verify_mode={cert_reqs}, "
                    f"crl_check={'on' if self.require_client_cert and len(self.conf_obj.get_crl_list()) > 0 else 'off'}")
        self._server = uvicorn.Server(uv_config)
        self._startup_error = None

        async def _serve():
            self._loop = asyncio.get_running_loop()
            self._serve_task = asyncio.current_task()
            handler, owned_service, owns_resources = None, None, False
            try:
                handler = ThirdPartyAuthnHandler(
                    credential_file=str(auth_config.get('integration.credential.file', '')),
                    config=auth_config)
                owned_service = configure_token_acquisition(auth_config)
                owns_resources = True
                HandlerRegistry._instances[InterfaceType.INTEGRATION_AUTHENTICATE.value] = handler
                await self._server.serve()
            finally:
                if owns_resources:
                    await close_integration_resources(expected_handler=handler,
                                                      expected_service=owned_service)
                elif handler is not None:
                    await handler.aclose()

        def _run_server():
            try:
                asyncio.run(_serve())
            except BaseException as exc:  # noqa: BLE001 - diagnostics sink
                self._startup_error = exc

        self._thread = threading.Thread(
            target=_run_server, daemon=True, name="integration-access")
        self._thread.start()

        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        while not self._server.started and time.monotonic() < deadline:
            if not self._thread.is_alive():
                logger.error("Integration access server thread exited during startup")
                error = self._startup_error
                self.stop()
                raise RuntimeError('Integration access startup failed') from error
            time.sleep(0.1)
        if not self._server.started:
            self.stop()
            raise RuntimeError('Integration access startup timed out')
        if self._server.started:
            logger.info(f"Integration access server started on {'https' if self.enable_https else 'http'}://{self.host}:{self.port} "
                        f"(client cert required: {self.require_client_cert})")

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.should_exit = True
        if self._thread is not None:
            if not self._server.started and self._loop is not None and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._serve_task.cancel)
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                raise RuntimeError('Integration access server did not stop')
        self._thread = None
        self._server = None
        self._loop = self._serve_task = None
        logger.info("Integration access server stopped")


_integration_server: ThirdPartyAccessServer = None


def start_integration_access(config: dict) -> None:
    """Start the integration access port if enabled (called from start.py)."""
    global _integration_server
    _integration_server = ThirdPartyAccessServer(config)
    _integration_server.start()


def stop_integration_access() -> None:
    global _integration_server
    if _integration_server is not None:
        _integration_server.stop()
        _integration_server = None
