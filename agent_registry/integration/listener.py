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
HTTPS-only — credentials never traverse plaintext HTTP. Disabled by
default; enabled purely via configuration.
"""

import ssl
import threading
import time

import uvicorn
import uvicorn.protocols.http.h11_impl as h11_impl
from loguru import logger

from agent_registry.cipher_converter import CipherConverter
from agent_registry.integration.app import integration_app
from common.util.ssl_config import conf_singleton_obj, load_cert_password

DEFAULT_ENCODING = 'utf-8'
DEFAULT_INTEGRATION_PORT = 5001
_STARTUP_TIMEOUT_SECONDS = 30

# ---------------------------------------------------------------------------
# Peer-certificate injection.
#
# uvicorn does not expose the TLS peer certificate to the ASGI application.
# RequestResponseCycle owns the request scope; wrap its run_asgi to copy the
# peer certificate from the connection's SSL object into
# scope["tls_peer_cert"] before the app runs. The extra scope key is benign
# for the main port (nothing reads it there).
# ---------------------------------------------------------------------------
import logging as _stdlib_logging

_uvicorn_records: list = []


class _UvicornRecordSink(_stdlib_logging.Handler):
    def emit(self, record):
        try:
            _uvicorn_records.append(record)
        except Exception:
            pass


_stdlib_logging.getLogger("uvicorn").addHandler(_UvicornRecordSink())
_stdlib_logging.getLogger("uvicorn.error").addHandler(_UvicornRecordSink())

_cycle_run_asgi = h11_impl.RequestResponseCycle.run_asgi


async def _run_asgi_with_peer_cert(self, app):
    peer_cert = None
    try:
        ssl_object = self.transport.get_extra_info('ssl_object') if self.transport else None
        if ssl_object is not None:
            peer_cert = ssl_object.getpeercert()
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"Failed to read TLS peer certificate: {e}")
    self.scope['tls_peer_cert'] = peer_cert
    return await _cycle_run_asgi(self, app)


h11_impl.RequestResponseCycle.run_asgi = _run_asgi_with_peer_cert


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
        self._server: uvicorn.Server = None
        self._thread: threading.Thread = None
        self._startup_error: Optional[BaseException] = None

    def start(self) -> None:
        """Start the listener. No-op when integration access is disabled."""
        if not self.enabled:
            logger.info("Integration access port disabled (integration.enabled=false)")
            return
        if self._thread is not None:
            logger.warning("Integration access server already started")
            return

        # Resolve the handler before opening the socket so invalid or incomplete
        # authentication configuration fails during startup, not on first use.
        from agent_registry.integration.authn import ThirdPartyAuthnHandler
        from common.custom.custom_handle import HandlerRegistry
        from common.custom.interface_type import InterfaceType
        auth_config = dict(self.config)
        if self.require_client_cert and 'integration.auth.mode' not in auth_config:
            auth_config['integration.auth.mode'] = 'mtls'
        HandlerRegistry._instances[InterfaceType.INTEGRATION_AUTHENTICATE.value] = (
            ThirdPartyAuthnHandler(
                credential_file=str(auth_config.get('integration.credential.file', '')),
                config=auth_config))

        cert_reqs = ssl.CERT_REQUIRED if self.require_client_cert else ssl.CERT_NONE
        raw_ciphers = self.config.get('tls.cipher') or ''
        uv_config = uvicorn.Config(
            app=integration_app,
            host=self.host,
            port=self.port,
            ssl_certfile=self.conf_obj.ssl_certfile,
            ssl_keyfile=self.conf_obj.ssl_keyfile,
            ssl_keyfile_password=load_cert_password(
                self.conf_obj.ssl_keyfile_password).decode(DEFAULT_ENCODING),
            ssl_ca_certs=self.conf_obj.ssl_ca_certs if self.require_client_cert else None,
            ssl_cert_reqs=cert_reqs,
            ssl_ciphers=CipherConverter.convert(raw_ciphers) if raw_ciphers.strip() else None,
            ssl_context_factory=_make_ssl_context_factory(
                self.conf_obj, self.require_client_cert),
            timeout_keep_alive=0,
            log_level="info",
        )
        logger.info(f"Integration access TLS: verify_mode={cert_reqs}, "
                    f"crl_check={'on' if self.require_client_cert and len(self.conf_obj.get_crl_list()) > 0 else 'off'}")
        self._server = uvicorn.Server(uv_config)

        def _run_server():
            try:
                self._server.run()
            except BaseException as exc:  # noqa: BLE001 - diagnostics sink
                self._startup_error = exc
                raise

        self._thread = threading.Thread(
            target=_run_server, daemon=True, name="integration-access")
        self._thread.start()

        deadline = time.time() + _STARTUP_TIMEOUT_SECONDS
        while not self._server.started and time.time() < deadline:
            if not self._thread.is_alive():
                print(f"[integration-listener][diag] thread exited during startup; "
                      f"startup_error={self._startup_error!r}", flush=True)
                logger.error("Integration access server thread exited during startup")
                return
            time.sleep(0.1)
        if not self._server.started:
            # The thread is alive but never completed startup — surface what
            # uvicorn was doing when the deadline hit (diagnosability).
            logger.error(
                f"Integration access server startup timeout after "
                f"{_STARTUP_TIMEOUT_SECONDS}s: thread alive={self._thread.is_alive()}, "
                f"bind target={self._server.config.host}:{self._server.config.port}")
        if not self._server.started:
            # print() (not logger): pytest captures it into the CI failure report
            uv_records = [r.getMessage() for r in _uvicorn_records]
            print(f"[integration-listener][diag] started={self._server.started} "
                  f"thread_alive={self._thread.is_alive()} "
                  f"startup_error={self._startup_error!r} "
                  f"uvicorn_records={uv_records[-10:]}", flush=True)
        if self._server.started:
            logger.info(f"Integration access server started on https://{self.host}:{self.port} "
                        f"(client cert required: {self.require_client_cert})")

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._thread = None
        self._server = None
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
