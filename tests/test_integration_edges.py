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
Edge-coverage tests for the integration plane building blocks.

Complements the per-module unit suites with lifecycle and failure-mode
edges that the happy-path tests do not reach:

- listener.py: double-start guard, stop-before-start, thread-exit during
  startup and the silent startup-timeout path (uvicorn.Server stubbed out
  so no socket is ever opened).
- audit_sink.py: partial batch failure degrades to the local file with a
  rate-limited warning while the writer thread survives; stop() joins
  within its timeout even when a write is in flight.
- ban.py: ban expiry exactly at cooldown end (+ epsilon), on_lift callback
  contract, and containment of a raising on_lift callback.
- credentials.py: duplicate certificate CN, invalid role, disabled entries,
  and the duplicate-credential-id guard (marked xfail: see the test reason
  for the source bug that makes it unreachable).

All timing-sensitive paths use injected clocks or stubbed servers; the only
real waits are bounded polling loops and one bounded in-flight-write stall.
"""

import threading
import time

import pytest
from loguru import logger

import agent_registry.integration.listener as listener_module
from agent_registry.integration.audit_sink import AuditMySqlSink
from agent_registry.integration.ban import BanTracker
from agent_registry.integration.credentials import load_credentials
from agent_registry.integration.listener import ThirdPartyAccessServer
from common.util.authenticate_util import CallerRole


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def loguru_caplog(caplog):
    """Route loguru records into pytest's caplog (pattern from
    tests/test_integration_audit_sink.py). DEBUG level so debug-branch
    messages are observable too."""
    handler_id = logger.add(caplog.handler, format="{message}", level="DEBUG")
    yield caplog
    logger.remove(handler_id)


class _FakeConfObj:
    """Minimal stand-in for common.util.ssl_config conf_singleton_obj.

    ssl_keyfile_password='' keeps load_cert_password on its b"" fast path
    (no password file), so no cert material is needed.
    """

    ssl_certfile = 'cert.pem'
    ssl_keyfile = 'key.pem'
    ssl_keyfile_password = ''
    ssl_ca_certs = None
    ssl_crl_file = ''

    def get_crl_list(self):
        return []


def _integration_conf():
    """Minimal config that lets start() reach the uvicorn.Server stub.

    ThirdPartyAuthnHandler (constructed inside start()) requires a
    fingerprint key in static-bearer mode, and StaticBearerProvider requires
    the HMAC key.
    """
    return {
        'integration.enabled': 'true',
        'integration.auth.fingerprint_key': 'test-fingerprint-key',
        'integration.auth.static.hmac_key': 'test-hmac-key',
    }


class _StubServer:
    """uvicorn.Server stand-in: never reaches the started state.

    block=False -> run() returns immediately (thread exits during startup).
    block=True  -> run() waits on should_exit (thread stays alive until
    stop()), which drives the startup-timeout path.
    """

    block = False
    instance_count = 0

    def __init__(self, config):
        _StubServer.instance_count += 1
        self.config = config
        self.started = False
        self.should_exit = False

    def run(self):
        while _StubServer.block and not self.should_exit:
            time.sleep(0.01)


@pytest.fixture
def stub_uvicorn_server(monkeypatch):
    _StubServer.block = False
    _StubServer.instance_count = 0
    monkeypatch.setattr(listener_module.uvicorn, 'Server', _StubServer)
    yield _StubServer
    _StubServer.block = False


@pytest.fixture
def preserve_integration_authn_handler():
    """start() overwrites HandlerRegistry._instances[INTEGRATION_AUTHENTICATE];
    restore whatever was registered before the test."""
    from common.custom.custom_handle import HandlerRegistry
    from common.custom.interface_type import InterfaceType
    saved = dict(HandlerRegistry._instances)
    yield
    HandlerRegistry._instances.clear()
    HandlerRegistry._instances.update(saved)


# ---------------------------------------------------------------------------
# listener.py — ThirdPartyAccessServer lifecycle edges
# ---------------------------------------------------------------------------

class TestListenerLifecycle:

    def test_double_start_logs_warning_and_keeps_single_thread(
            self, monkeypatch, stub_uvicorn_server,
            preserve_integration_authn_handler, loguru_caplog):
        monkeypatch.setattr(listener_module, '_STARTUP_TIMEOUT_SECONDS', 0.3)
        _StubServer.block = True  # thread stays alive past the startup loop

        server = ThirdPartyAccessServer(_integration_conf(), conf_obj=_FakeConfObj())
        server.start()
        first_thread = server._thread
        assert first_thread is not None
        assert first_thread.is_alive()

        server.start()  # second call must be refused by the guard

        assert server._thread is first_thread, "second start() must not spawn a new thread"
        assert _StubServer.instance_count == 1, "second start() must not build a new server"
        assert "already started" in loguru_caplog.text
        server.stop()

    def test_stop_before_start_is_noop(self, stub_uvicorn_server, loguru_caplog):
        server = ThirdPartyAccessServer(_integration_conf(), conf_obj=_FakeConfObj())
        server.stop()  # must not raise
        assert server._thread is None
        assert server._server is None
        assert _StubServer.instance_count == 0, "stop() before start() must not build a server"
        assert "stopped" not in loguru_caplog.text, "no-op stop() must stay silent"

    def test_thread_exit_during_startup_logs_error_and_returns(
            self, monkeypatch, stub_uvicorn_server,
            preserve_integration_authn_handler, loguru_caplog):
        # Short timeout is a safety net: the loop is expected to leave via the
        # is_alive() branch on its first or second iteration.
        monkeypatch.setattr(listener_module, '_STARTUP_TIMEOUT_SECONDS', 2)
        _StubServer.block = False  # run() returns immediately -> thread dies

        server = ThirdPartyAccessServer(_integration_conf(), conf_obj=_FakeConfObj())
        server.start()  # must return promptly, not spin for the full timeout

        assert "thread exited during startup" in loguru_caplog.text
        assert "started on https://" not in loguru_caplog.text
        assert server._thread is not None  # error path keeps the (dead) thread ref
        server.stop()

    def test_startup_timeout_returns_quietly_with_thread_alive(
            self, monkeypatch, stub_uvicorn_server,
            preserve_integration_authn_handler, loguru_caplog):
        monkeypatch.setattr(listener_module, '_STARTUP_TIMEOUT_SECONDS', 0.3)
        _StubServer.block = True  # thread alive, started never becomes True

        server = ThirdPartyAccessServer(_integration_conf(), conf_obj=_FakeConfObj())
        t0 = time.monotonic()
        server.start()
        elapsed = time.monotonic() - t0

        assert elapsed >= 0.2, "start() must honor the startup window"
        assert elapsed < 5, "start() must return after the startup timeout"
        assert "started on https://" not in loguru_caplog.text
        assert "thread exited during startup" not in loguru_caplog.text
        assert server._thread.is_alive(), "stub thread must still run after timeout"
        server.stop()


# ---------------------------------------------------------------------------
# audit_sink.py — failure-mode edges
# ---------------------------------------------------------------------------

AUDIT_ENTRY = {
    "time": "2026-09-21T01:00:00",
    "client_ip": "10.1.1.9",
    "user_name": "nms_gateway",
    "level": "MINOR",
    "operation_name": "Register Agent",
    "object_name": "Agent",
    "result": "SUCCESS",
    "details": {"agentName": "a"},
}


class _BatchFailingCursor:
    """Cursor whose executemany succeeds only on the FIRST call ever made
    (call counter shared across re-created connections via the state dict)."""

    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        pass

    def executemany(self, sql, rows):
        self.state["executemany_calls"] = self.state.get("executemany_calls", 0) + 1
        if self.state["executemany_calls"] >= 2:
            raise RuntimeError("injected batch insert failure")
        self.state["rows"].extend(rows)

    def close(self):
        pass


class _RecordingConnection:
    def __init__(self, state):
        self.state = state

    def cursor(self):
        return _BatchFailingCursor(self.state)

    def close(self):
        self.state["closed"] = self.state.get("closed", 0) + 1


class TestAuditSinkEdgeCases:

    @staticmethod
    def _make_sink(state, batch_size, flush_interval):
        conf = {
            "audit.mysql.enabled": "true",
            "audit.mysql.host": "127.0.0.1",
            "audit.mysql.port": "3306",
            "audit.mysql.name": "audit_db",
            "audit.mysql.username": "audit_writer",
            "audit.mysql.password": "audit_pwd",
            "audit.mysql.batch_size": str(batch_size),
            "audit.mysql.flush_interval": str(flush_interval),
        }
        sink = AuditMySqlSink(conf)
        sink._connect = lambda: _RecordingConnection(state)
        return sink

    def test_partial_batch_failure_degrades_with_rate_limited_warning(
            self, loguru_caplog):
        state = {"rows": []}
        sink = self._make_sink(state, batch_size=2, flush_interval=0.1)
        sink.start()
        try:
            for i in range(6):
                sink.enqueue(dict(AUDIT_ENTRY, user_name=f"user-{i}"))
            # Two batches attempted: the first lands, the second fails. Each
            # failure closes the connection, so closed >= 2 proves both
            # failure paths (warning included) fully ran.
            deadline = time.monotonic() + 5
            while state.get("closed", 0) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)

            assert state.get("executemany_calls", 0) >= 3, "first batch must have been attempted"
            assert len(state["rows"]) == 2, "only the first batch reaches the sink state"
            degraded = [r for r in loguru_caplog.records
                        if "degraded to local file only" in r.getMessage()]
            assert len(degraded) == 1, (
                "exactly one warning despite repeated failures (rate-limited)")
            assert sink._thread is not None and sink._thread.is_alive(), (
                "batch failure must not kill the writer thread")
        finally:
            sink.stop()

    def test_stop_during_in_flight_write_joins_within_timeout(self, monkeypatch):
        state = {"rows": []}
        sink = self._make_sink(state, batch_size=10, flush_interval=0.05)
        entered = threading.Event()
        release = threading.Event()
        written = []

        def slow_write(conn, batch):
            entered.set()
            release.wait(timeout=2)  # bounded stall standing in for a slow INSERT
            written.append(len(batch))

        monkeypatch.setattr(sink, "_write_batch", slow_write)
        sink.start()
        sink.enqueue(AUDIT_ENTRY)
        assert entered.wait(timeout=5), "writer never reached _write_batch"

        writer_thread = sink._thread
        t0 = time.monotonic()
        sink.stop()
        elapsed = time.monotonic() - t0
        release.set()  # hygiene: no-op once the stall has expired

        assert written == [1], "in-flight write must complete, not be abandoned"
        assert not writer_thread.is_alive(), "join(timeout=10) must leave the thread dead"
        assert sink._thread is None
        assert elapsed < 10, "stop() must return before its join timeout expires"


# ---------------------------------------------------------------------------
# ban.py — expiry race window and on_lift callback contract
# ---------------------------------------------------------------------------

class _FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class TestBanTrackerExpiry:

    def test_ban_lifts_at_cooldown_end_and_on_lift_receives_key(self, loguru_caplog):
        clock = _FakeClock(now=1000.0)
        lifted = []
        tracker = BanTracker(threshold=1, cooldown_seconds=100, clock=clock,
                             on_lift=lifted.append)

        assert tracker.record_failure("alice") is True  # threshold=1: instant ban
        assert tracker.is_banned("alice") is True
        assert tracker.remaining_seconds("alice") == 100
        assert tracker.is_banned("bob") is False  # untouched key, no callback

        clock.now = 1100.5  # cooldown end (1100.0) + epsilon

        assert tracker.is_banned("alice") is False, "ban must lift after cooldown"
        assert lifted == ["alice"], "on_lift fires once, with the exact key"
        assert tracker.remaining_seconds("alice") == 0

        assert tracker.record_failure("alice") is True, "post-lift failure starts a fresh ban"
        assert tracker.is_banned("alice") is True
        clock.now = 1101.0  # still inside the new cooldown window (ends 1200.5)
        assert tracker.is_banned("alice") is True
        assert lifted == ["alice"], "no extra on_lift while the new ban holds"

    def test_failure_counter_restarts_after_lift(self):
        clock = _FakeClock(now=2000.0)
        tracker = BanTracker(threshold=2, cooldown_seconds=50, clock=clock)

        tracker.record_failure("k")
        assert tracker.record_failure("k") is True  # second failure -> banned
        clock.now = 2050.0

        assert tracker.is_banned("k") is False  # lifted; counter must be cleared
        assert tracker.record_failure("k") is False, "count restarts at 1, not 2"
        assert tracker.is_banned("k") is False
        assert tracker.record_failure("k") is True, "second fresh failure bans again"

    def test_on_lift_exception_is_contained_and_debug_logged(self, loguru_caplog):
        clock = _FakeClock(now=1000.0)
        calls = []

        def failing_callback(key):
            calls.append(key)
            raise RuntimeError("audit backend down")

        tracker = BanTracker(threshold=1, cooldown_seconds=100, clock=clock,
                             on_lift=failing_callback)
        tracker.record_failure("k")
        clock.now = 1100.5

        assert tracker.is_banned("k") is False, "on_lift failure must not escape is_banned"
        assert calls == ["k"]
        assert "Ban-lift audit callback failed" in loguru_caplog.text
        assert tracker.is_banned("k") is False, "ban stays lifted after the failed callback"
        assert calls == ["k"], "callback must not re-fire on subsequent checks"


# ---------------------------------------------------------------------------
# credentials.py — loading corner cases
# ---------------------------------------------------------------------------

def _write_conf(tmp_path, text):
    path = tmp_path / 'integration_credentials.conf'
    path.write_text(text, encoding='utf-8')
    return str(path)


class TestCredentialLoadingEdges:

    def test_duplicate_certificate_cn_keeps_first_entry(self, tmp_path, loguru_caplog):
        path = _write_conf(tmp_path,
                           'credential.first.identity=alpha\n'
                           'credential.first.cn=shared-cn\n'
                           'credential.first.role=nms_oss\n'
                           'credential.second.identity=beta\n'
                           'credential.second.cn=shared-cn\n'
                           'credential.second.role=nms_oss\n')
        tokens, certs = load_credentials(path)
        assert list(certs.keys()) == ['shared-cn']
        assert certs['shared-cn'].identity == 'alpha'
        assert "Duplicate certificate CN" in loguru_caplog.text
        assert tokens == {}

    def test_invalid_role_is_skipped_with_warning(self, tmp_path, loguru_caplog):
        digest = 'b' * 64
        path = _write_conf(tmp_path,
                           'credential.bad.identity=svc\n'
                           f'credential.bad.token_hash={digest}\n'
                           'credential.bad.role=bogus_role\n'
                           'credential.good.identity=svc2\n'
                           f'credential.good.token_hash={digest}\n'
                           'credential.good.role=nms_oss\n')
        tokens, certs = load_credentials(path)
        assert 'bad' not in tokens and 'bad' not in certs
        assert tokens['good'].role is CallerRole.NMS_OSS
        assert "invalid role" in loguru_caplog.text

    def test_disabled_entry_is_skipped_while_enabled_ones_load(self, tmp_path):
        digest = 'c' * 64
        path = _write_conf(tmp_path,
                           'credential.on.identity=svc\n'
                           f'credential.on.token_hash={digest}\n'
                           'credential.on.role=nms_oss\n'
                           'credential.off.identity=ghost\n'
                           f'credential.off.token_hash={digest}\n'
                           'credential.off.role=nms_oss\n'
                           'credential.off.enabled=false\n')
        tokens, certs = load_credentials(path)
        assert list(tokens.keys()) == ['on']
        assert certs == {}

    @pytest.mark.xfail(
        strict=True,
        reason="Source bug (credentials.py): configparser runs in strict mode, so two "
               "entries sharing a credential_id raise DuplicateOptionError inside "
               "load_conf_as_dict, which swallows it and returns {} — the whole "
               "credential file is silently discarded. Consequently the 'Duplicate "
               "credential id; keeping first' guard in load_credentials is "
               "unreachable: grouped is keyed by credential_id, so the same id can "
               "never be visited twice.")
    def test_duplicate_credential_id_keeps_first_entry(self, tmp_path, loguru_caplog):
        path = _write_conf(tmp_path,
                           'credential.dup.identity=first-identity\n'
                           f'credential.dup.token_hash={"d" * 64}\n'
                           'credential.dup.role=nms_oss\n'
                           'credential.dup.identity=second-identity\n'
                           f'credential.dup.token_hash={"e" * 64}\n'
                           'credential.dup.role=nms_oss\n')
        tokens, _ = load_credentials(path)
        assert tokens['dup'].identity == 'first-identity'
        assert 'second-identity' not in {e.identity for e in tokens.values()}
        assert "Duplicate credential id" in loguru_caplog.text
