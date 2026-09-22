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
Unit tests for agent_registry/start.py boot helpers.

Covers the testable units without booting the real HTTP server:
- _handle_shutdown_signal (stop internal service, then exit(0))
- internal service creation / start / stop lifecycle (TCP selection path on Windows)
- customized_create_ssl_context (cert chain, verify mode, CRL flags, ciphers)
- record_startup_log and the audit-on-failure block in main()

main()'s happy path is out of scope (requires full app boot).
"""

import asyncio
import datetime
import signal
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import agent_registry.start as start
from common.log.audit_logger import LogLevel, OperationName, OperationResult, OperatorObject
from common.util.validation_result import ValidationResult


# ---------- PKI helpers (replicated from tests/test_integration_cert_auth.py) ----------

def _gen_key():
    # 3072-bit: matches the certificate strength rule enforced by the
    # pre-check tool and the startup CertValidator
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def _name(cn: str):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _make_cert(cn, key, issuer_cert, issuer_key, not_after, is_ca=False):
    builder = (x509.CertificateBuilder()
               .subject_name(_name(cn))
               .issuer_name(issuer_cert.subject if issuer_cert else _name(cn))
               .public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(datetime.datetime.now(datetime.timezone.utc)
                                 - datetime.timedelta(days=1))
               .not_valid_after(not_after)
               .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True))
    return builder.sign(issuer_key or key, hashes.SHA256())


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    """CA, server certificate + key (plain and encrypted), and a CRL."""
    root = tmp_path_factory.mktemp("pki")
    not_after = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)

    ca_key = _gen_key()
    ca_cert = _make_cert("Test CA", ca_key, None, None, not_after, is_ca=True)
    (root / "ca.cer").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    server_key = _gen_key()
    server_cert = _make_cert("127.0.0.1", server_key, ca_cert, ca_key, not_after)
    (root / "server.key").write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    (root / "server.cer").write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))

    # Same server identity, but the key is encrypted with a password
    enc_key = _gen_key()
    enc_cert = _make_cert("127.0.0.1", enc_key, ca_cert, ca_key, not_after)
    (root / "server_enc.key").write_bytes(enc_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.BestAvailableEncryption(b"RegTest#2026")))
    (root / "server_enc.cer").write_bytes(enc_cert.public_bytes(serialization.Encoding.PEM))

    crl = (x509.CertificateRevocationListBuilder()
           .issuer_name(ca_cert.subject)
           .last_update(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
           .next_update(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30))
           .add_revoked_certificate(x509.RevokedCertificateBuilder()
                                    .serial_number(server_cert.serial_number)
                                    .revocation_date(datetime.datetime.now(datetime.timezone.utc)
                                                     - datetime.timedelta(days=1))
                                    .build()))
    crl = crl.sign(ca_key, hashes.SHA256())
    (root / "revocationlist.crl").write_bytes(crl.public_bytes(serialization.Encoding.PEM))

    return {
        "root": root,
        "ca": root / "ca.cer",
        "server_cert": root / "server.cer",
        "server_key": root / "server.key",
        "server_enc_cert": root / "server_enc.cer",
        "server_enc_key": root / "server_enc.key",
        "crl": root / "revocationlist.crl",
    }


class _StubConfObj:
    """Stand-in for common.util.ssl_config.conf_singleton_obj."""

    def __init__(self, crl_serials=(), crl_file=""):
        self.ssl_crl_file = str(crl_file) if crl_file else ""
        self.crl_serials = list(crl_serials)

    def get_crl_list(self):
        return self.crl_serials


class _AuditRecorder:
    """Async audit handler recording every entry it receives."""

    def __init__(self):
        self.entries = []

    async def handle(self, entry):
        self.entries.append(entry)
        return None


# ---------- shutdown signal ----------

class TestHandleShutdownSignal:
    def test_stops_internal_service_then_exits_zero(self, monkeypatch):
        calls = []
        monkeypatch.setattr(start, "stop_internal_service", lambda: calls.append("stop"))

        with pytest.raises(SystemExit) as excinfo:
            start._handle_shutdown_signal(signal.SIGTERM, None)

        assert excinfo.value.code == 0
        # stop must have happened before sys.exit(0) was reached
        assert calls == ["stop"]

    def test_registers_as_signal_handler_shape(self):
        # The handler is a plain callable usable with signal.signal()
        assert callable(start._handle_shutdown_signal)


# ---------- internal service lifecycle ----------

class _FakeInternalService:
    instances = []

    def __init__(self, *args, **kwargs):
        self.init_args = (args, kwargs)
        self.start_called = threading.Event()
        self.stop_calls = []
        type(self).instances.append(self)

    def start(self):
        self.start_called.set()

    def stop(self):
        self.stop_calls.append(True)


class TestInternalServiceLifecycle:
    @pytest.fixture(autouse=True)
    def _reset_module_globals(self):
        yield
        start._internal_service = None
        start._internal_thread = None

    def test_create_internal_service_uses_tcp_on_windows(self, monkeypatch):
        monkeypatch.setattr(start, "IS_WINDOWS", True)
        monkeypatch.setattr(start, "TCPInternalService", _FakeInternalService)
        _FakeInternalService.instances = []

        service = start._create_internal_service({"ip": "127.0.0.1", "port": 5000})

        assert isinstance(service, _FakeInternalService)
        # TCP service binds the fixed loopback defaults (127.0.0.1:1108),
        # server_config's ip/port are not forwarded to the service
        assert service.init_args == ((), {})

    def test_create_internal_service_uses_uds_on_posix(self, monkeypatch):
        monkeypatch.setattr(start, "IS_WINDOWS", False)
        monkeypatch.setattr(start, "RegistryCenterInternalService", _FakeInternalService)

        service = start._create_internal_service({})

        assert isinstance(service, _FakeInternalService)

    def test_start_internal_service_creates_and_starts_service_in_thread(self, monkeypatch):
        _FakeInternalService.instances = []
        monkeypatch.setattr(start, "IS_WINDOWS", True)
        monkeypatch.setattr(start, "TCPInternalService", _FakeInternalService)

        server_config = {"ip": "10.1.2.3", "port": "5000"}
        start.start_internal_service(server_config)

        assert len(_FakeInternalService.instances) == 1
        fake = _FakeInternalService.instances[0]
        assert start._internal_service is fake
        assert start._internal_thread is not None
        assert fake.start_called.wait(timeout=5), "service.start was never run by the thread"

    def test_stop_internal_service_stops_integration_audit_and_service(self, monkeypatch):
        stopped = []
        monkeypatch.setattr(start, "stop_integration_access", lambda: stopped.append("integration"))
        monkeypatch.setattr(start, "stop_audit_sink", lambda: stopped.append("audit_sink"))
        fake = _FakeInternalService()
        monkeypatch.setattr(start, "_internal_service", fake)

        start.stop_internal_service()

        assert stopped == ["integration", "audit_sink"]
        assert fake.stop_calls == [True]

    def test_stop_internal_service_without_service_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(start, "stop_integration_access", lambda: None)
        monkeypatch.setattr(start, "stop_audit_sink", lambda: None)
        monkeypatch.setattr(start, "_internal_service", None)

        start.stop_internal_service()  # must be idempotent / a no-op

    def test_stop_internal_service_swallows_service_stop_error(self, monkeypatch):
        class _BrokenService:
            def stop(self):
                raise RuntimeError("stop failed")

        monkeypatch.setattr(start, "stop_integration_access", lambda: None)
        monkeypatch.setattr(start, "stop_audit_sink", lambda: None)
        monkeypatch.setattr(start, "_internal_service", _BrokenService())

        start.stop_internal_service()  # error logged, not propagated


# ---------- customized_create_ssl_context ----------

class TestCustomizedCreateSslContext:
    def test_builds_server_context_without_ca(self, pki):
        ctx = start.customized_create_ssl_context(
            pki["server_cert"], pki["server_key"], None,
            ssl.PROTOCOL_TLS_SERVER, ssl.CERT_NONE, None, None)

        assert ctx.verify_mode == ssl.VerifyMode.CERT_NONE
        assert not (ctx.verify_flags & ssl.VERIFY_CRL_CHECK_LEAF)

    def test_verify_mode_follows_cert_reqs_and_loads_ca(self, pki):
        ctx = start.customized_create_ssl_context(
            pki["server_cert"], pki["server_key"], None,
            ssl.PROTOCOL_TLS_SERVER, ssl.CERT_REQUIRED, pki["ca"], None)

        assert ctx.verify_mode == ssl.VerifyMode.CERT_REQUIRED
        assert ctx.get_ca_certs(), "CA file was not loaded into the context"

    def test_crl_flags_set_when_crl_list_present(self, pki, monkeypatch):
        monkeypatch.setattr(start, "conf_singleton_obj",
                            _StubConfObj(crl_serials=["0x123"], crl_file=pki["crl"]))

        ctx = start.customized_create_ssl_context(
            pki["server_cert"], pki["server_key"], None,
            ssl.PROTOCOL_TLS_SERVER, ssl.CERT_REQUIRED, pki["ca"], None)

        assert ctx.verify_flags & ssl.VERIFY_CRL_CHECK_LEAF

    def test_crl_flags_clear_when_crl_list_empty(self, pki, monkeypatch):
        monkeypatch.setattr(start, "conf_singleton_obj", _StubConfObj(crl_serials=[]))

        ctx = start.customized_create_ssl_context(
            pki["server_cert"], pki["server_key"], None,
            ssl.PROTOCOL_TLS_SERVER, ssl.CERT_REQUIRED, pki["ca"], None)

        assert not (ctx.verify_flags & ssl.VERIFY_CRL_CHECK_LEAF)

    def test_ciphers_are_applied(self, pki):
        ctx = start.customized_create_ssl_context(
            pki["server_cert"], pki["server_key"], None,
            ssl.PROTOCOL_TLS_SERVER, ssl.CERT_NONE, None,
            "ECDHE-RSA-AES256-GCM-SHA384")

        cipher_names = [c["name"] for c in ctx.get_ciphers()]
        assert "ECDHE-RSA-AES256-GCM-SHA384" in cipher_names

    def test_encrypted_key_with_password(self, pki):
        ctx = start.customized_create_ssl_context(
            pki["server_enc_cert"], pki["server_enc_key"], "RegTest#2026",
            ssl.PROTOCOL_TLS_SERVER, ssl.CERT_NONE, None, None)

        assert ctx.verify_mode == ssl.VerifyMode.CERT_NONE

    def test_missing_certfile_raises(self, tmp_path):
        missing = tmp_path / "does_not_exist.cer"
        with pytest.raises(OSError):
            start.customized_create_ssl_context(
                missing, tmp_path / "no_key.pem", None,
                ssl.PROTOCOL_TLS_SERVER, ssl.CERT_NONE, None, None)


# ---------- record_startup_log ----------

    def test_accepts_newer_uvicorn_keyword_arguments(self, tmp_path):
        """Regression: uvicorn 0.53 passes alpn_protocols to
        create_ssl_context — the global patch must absorb new keyword
        arguments instead of raising TypeError (broke the cert-auth suite
        and the HTTPS boot path on trunk)."""
        import datetime
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        root = tmp_path / "pki"
        root.mkdir()
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder()
                .subject_name(name)
                .issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=30))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        (root / "s.key").write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
        (root / "s.cer").write_bytes(cert.public_bytes(serialization.Encoding.PEM))

        ctx = start.customized_create_ssl_context(
            str(root / "s.cer"), str(root / "s.key"), None,
            ssl.PROTOCOL_TLS_SERVER, ssl.CERT_NONE, None, None,
            alpn_protocols=["h2", "http/1.1"], some_future_kwarg="ignored")
        assert ctx is not None


class TestRecordStartupLog:
    def test_records_success_entry_with_config_ip_and_port(self, monkeypatch):
        recorder = _AuditRecorder()
        monkeypatch.setattr(start, "audit_handle", recorder)
        monkeypatch.setattr(start, "get_conf", lambda: {"ip": "10.0.0.8", "port": "5001"})
        monkeypatch.setenv("APP_USER", "cli_user")

        asyncio.run(start.record_startup_log())

        assert len(recorder.entries) == 1
        entry = recorder.entries[0]
        assert entry["operation_name"] == OperationName.START_SERVICE
        assert entry["result"] == OperationResult.SUCCESS
        assert entry["level"] == LogLevel.DANGER
        assert entry["object_name"] == OperatorObject.SERVICE
        assert entry["details"] == {"ip": "10.0.0.8", "port": "5001"}
        assert entry["user_name"] == "cli_user"

    def test_user_info_defaults_to_unknown(self, monkeypatch):
        monkeypatch.delenv("APP_USER", raising=False)
        monkeypatch.delenv("APP_UID", raising=False)
        monkeypatch.delenv("APP_GID", raising=False)

        info = start.get_user_info_from_env()

        assert info == {"username": "unknown", "uid": "unknown", "gid": "unknown"}

    def test_user_info_reads_environment(self, monkeypatch):
        monkeypatch.setenv("APP_USER", "svc_openan")
        monkeypatch.setenv("APP_UID", "1001")
        monkeypatch.setenv("APP_GID", "1001")

        info = start.get_user_info_from_env()

        assert info == {"username": "svc_openan", "uid": "1001", "gid": "1001"}


# ---------- main() failure paths (happy path out of scope) ----------

class _FakeSignalModule:
    """Records signal registrations instead of touching process state.

    Must expose SIGINT/SIGTERM: main() evaluates signal.SIGINT as the first
    argument, and its surrounding `except Exception: pass` would silently
    swallow an AttributeError if the constants were missing.
    """

    SIGINT = signal.SIGINT
    SIGTERM = signal.SIGTERM

    def __init__(self):
        self.registered = []

    def signal(self, signum, handler):
        self.registered.append((signum, handler))


class TestMainFailurePaths:
    @pytest.fixture
    def main_patches(self, monkeypatch):
        """Patch every external effect of main() so it can run without booting anything."""
        recorded = {"storage_precheck": 0, "internal_started": 0,
                    "integration_started": 0, "audit_sink_started": 0, "stops": 0}

        recorder = _AuditRecorder()
        monkeypatch.setattr(start, "audit_handle", recorder)
        monkeypatch.setattr(start, "get_conf", lambda: {"ip": "127.0.0.1", "port": "5000",
                                                        "enable_https": "true"})
        monkeypatch.setattr(start, "verify_storage_ready",
                            lambda: recorded.__setitem__("storage_precheck", 1))
        monkeypatch.setattr(start, "start_internal_service",
                            lambda cfg: recorded.__setitem__("internal_started", 1))
        monkeypatch.setattr(start, "start_integration_access",
                            lambda cfg: recorded.__setitem__("integration_started", 1))
        monkeypatch.setattr(start, "start_audit_sink",
                            lambda conf: recorded.__setitem__("audit_sink_started", 1))
        monkeypatch.setattr(start, "stop_internal_service",
                            lambda: recorded.__setitem__("stops", recorded["stops"] + 1))
        monkeypatch.setattr(start, "set_ssl_folder_permissions",
                            lambda: recorded.__setitem__("ssl_permissions", 1))
        fake_signal = _FakeSignalModule()
        monkeypatch.setattr(start, "signal", fake_signal)
        return recorded, recorder, fake_signal

    @staticmethod
    def _install_cert_validator(monkeypatch, result):
        class _FakeCertValidator:
            def __init__(self, conf_obj):
                self.conf_obj = conf_obj

            def validate(self):
                return result

        monkeypatch.setattr(start, "CertValidator", _FakeCertValidator)

    def test_exits_and_audits_failure_when_server_run_raises(self, main_patches, monkeypatch):
        recorded, recorder, _ = main_patches
        self._install_cert_validator(monkeypatch, ValidationResult(True, "ok"))

        class _ExplodingServer:
            def __init__(self, server_config, conf_obj):
                pass

            def run(self):
                raise RuntimeError("boom")

        monkeypatch.setattr(start, "CustomUvicornServer", _ExplodingServer)

        with pytest.raises(SystemExit) as excinfo:
            start.main()

        assert excinfo.value.code == "agent_registry server start failed: boom"
        assert recorded["storage_precheck"] == 1
        assert recorded["internal_started"] == 1
        assert recorded["integration_started"] == 1
        assert recorded["audit_sink_started"] == 1
        assert recorded["stops"] == 1
        # the failure audit entry carries the ip/port details from server.conf
        assert len(recorder.entries) == 1
        entry = recorder.entries[0]
        assert entry["operation_name"] == OperationName.START_SERVICE
        assert entry["result"] == OperationResult.FAILURE
        assert entry["level"] == LogLevel.DANGER
        assert entry["object_name"] == OperatorObject.SERVICE
        assert entry["details"] == {"ip": "127.0.0.1", "port": "5000"}

    def test_exits_with_validator_message_when_cert_invalid(self, main_patches, monkeypatch):
        recorded, recorder, _ = main_patches
        self._install_cert_validator(monkeypatch, ValidationResult(False, "server cert expired"))

        with pytest.raises(SystemExit) as excinfo:
            start.main()

        assert excinfo.value.code == "server cert expired"
        assert recorded["stops"] == 1
        # exits before permissions are set and before the server runs,
        # so no "start failed" audit entry is written on this path
        assert recorder.entries == []
        assert "ssl_permissions" not in recorded

    def test_registers_shutdown_signals_and_runs_http_server(self, main_patches, monkeypatch):
        recorded, _, fake_signal = main_patches
        # force the plain-HTTP branch
        monkeypatch.setattr(start, "get_conf",
                            lambda: {"ip": "127.0.0.1", "port": "5000", "enable_https": "false"})

        uvicorn_calls = []

        def _fake_uvicorn_run(app_arg, host=None, port=None):
            uvicorn_calls.append((app_arg, host, port))
            raise KeyboardInterrupt()

        monkeypatch.setattr(start, "uvicorn",
                            type("FakeUvicorn", (), {"run": staticmethod(_fake_uvicorn_run)}))

        start.main()  # KeyboardInterrupt is caught, shutdown completes normally

        assert len(uvicorn_calls) == 1
        app_arg, host, port = uvicorn_calls[0]
        assert app_arg is start.app
        assert host == "127.0.0.1"
        assert port == 5000
        assert (signal.SIGINT, start._handle_shutdown_signal) in fake_signal.registered
        assert (signal.SIGTERM, start._handle_shutdown_signal) in fake_signal.registered
        assert recorded["stops"] == 1
