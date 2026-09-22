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
Internal service tests

Covers the UDS/TCP internal service layers without starting the real app:
- RequestDispatcher handler lookup (known / unknown / custom actions)
- RegistryCenterInternalService._handle_request protocol handling
  (valid request, invalid JSON, validation error, unknown action, errors)
- TCPInternalService over a real loopback socket on an ephemeral port
- Direct handler.handle() contracts for the approval / get / list / set-tags
  handlers with a fake registry
"""

import json
import socket
import threading
import time

import pytest
from a2a.types import AgentCard
from google.protobuf.json_format import MessageToDict
from unittest.mock import Mock

import agent_registry.internal.registry_center_internal_service as rci_module
from agent_registry.internal.handlers.approval_handler import ApprovalHandler
from agent_registry.internal.handlers.base_handler import BaseUDSHandler
from agent_registry.internal.handlers.get_agent_handler import GetAgentHandler
from agent_registry.internal.handlers.list_agents_handler import ListAgentsHandler
from agent_registry.internal.handlers.set_tags_handler import SetTagsHandler
from agent_registry.internal.protocols.actions import Action
from agent_registry.internal.registry_center_internal_service import (
    RegistryCenterInternalService, RequestDispatcher
)
from agent_registry.internal.tcp_internal_service import TCPInternalService
from agent_registry.persistence.base import AgentRecord
from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import OperationResult


# ---------- shared test doubles ----------

class _RecordingHandler(BaseUDSHandler):
    """Stub UDS handler recording every call and answering with a canned response."""

    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response if response is not None else {"success": True, "message": "ok"}
        self.error = error

    def handle(self, params, registry, config):
        self.calls.append({"params": params, "registry": registry, "config": config})
        if self.error is not None:
            raise self.error
        return dict(self.response)


class _StubDispatcher:
    """Dispatcher stand-in answering only for its known actions."""

    def __init__(self, handler=None, known_actions=("echo",)):
        self.handler = handler
        self.known_actions = set(known_actions)
        self.requested = []

    def get_handler(self, action):
        self.requested.append(action)
        return self.handler if action in self.known_actions else None


class _AuditRecorder:
    """Async audit handler recording every entry."""

    def __init__(self):
        self.entries = []

    async def handle(self, entry):
        self.entries.append(entry)
        return None


class _StubAsyncHandler:
    """Stand-in for common.custom BaseHandler implementations (GET / QUERY / audit)."""

    def __init__(self, result=None):
        self.result = result
        self.calls = []

    async def handle(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def _install_handler(interface_type, handler):
    """Temporarily register an instance in the process-wide HandlerRegistry."""
    key = interface_type.value
    previous = HandlerRegistry._instances.get(key)
    HandlerRegistry._instances[key] = handler

    def _restore():
        if previous is None:
            HandlerRegistry._instances.pop(key, None)
        else:
            HandlerRegistry._instances[key] = previous

    return _restore


@pytest.fixture
def audit_recorder():
    recorder = _AuditRecorder()
    restore = _install_handler(InterfaceType.AUDIT, recorder)
    yield recorder
    restore()


def _make_card(name="test_agent", organization="test_org"):
    return AgentCard(
        name=name,
        description=f"{name} description",
        version="1.0.0",
        provider={"organization": organization, "url": "https://test.com"},
        skills=[],
    )


class _FakeConn:
    """Socket stand-in feeding one payload to _handle_request and capturing the reply."""

    def __init__(self, payload: bytes = b""):
        self._payload = payload
        self.sent = b""
        self.closed = False

    def recv(self, _bufsize):
        data, self._payload = self._payload, b""
        return data

    def send(self, data):
        self.sent += data
        return len(data)

    def close(self):
        self.closed = True


# ---------- RequestDispatcher ----------

class TestRequestDispatcher:
    def test_get_handler_returns_instance_for_known_action(self):
        dispatcher = RequestDispatcher()

        assert isinstance(dispatcher.get_handler(Action.APPROVAL), ApprovalHandler)
        assert isinstance(dispatcher.get_handler(Action.GET_AGENT), GetAgentHandler)
        assert isinstance(dispatcher.get_handler(Action.LIST_AGENTS), ListAgentsHandler)
        assert isinstance(dispatcher.get_handler(Action.SET_TAG), SetTagsHandler)

    def test_get_handler_unknown_action_returns_none(self):
        dispatcher = RequestDispatcher()

        assert dispatcher.get_handler("definitely_not_an_action") is None
        assert dispatcher.get_handler("") is None

    def test_get_handler_returns_fresh_instance_per_call(self):
        dispatcher = RequestDispatcher()

        first = dispatcher.get_handler(Action.GET_AGENT)
        second = dispatcher.get_handler(Action.GET_AGENT)

        assert first is not second

    def test_register_handler_adds_custom_action(self):
        dispatcher = RequestDispatcher()
        original = dict(RequestDispatcher._handlers)  # class-level dict, restore after
        try:
            dispatcher.register_handler("custom_action", _RecordingHandler)

            handler = dispatcher.get_handler("custom_action")
            assert isinstance(handler, _RecordingHandler)
        finally:
            RequestDispatcher._handlers.clear()
            RequestDispatcher._handlers.update(original)


# ---------- RegistryCenterInternalService (UDS service, request path only) ----------

@pytest.fixture
def uds_service(monkeypatch):
    monkeypatch.setattr(rci_module, "get_registry", lambda: Mock(name="registry"))
    monkeypatch.setattr(rci_module, "get_conf", lambda: {"ip": "127.0.0.1", "port": 5000})
    return RegistryCenterInternalService()


class TestRegistryCenterInternalService:
    def test_init_wires_registry_config_and_dispatcher(self, uds_service):
        assert isinstance(uds_service.dispatcher, RequestDispatcher)
        assert uds_service.registry is not None
        assert uds_service.config == {"ip": "127.0.0.1", "port": 5000}
        assert uds_service.socket_path == RegistryCenterInternalService.SOCKET_PATH
        assert uds_service._running is False

    def test_valid_request_calls_handler_and_sends_response(self, uds_service):
        registry = uds_service.registry
        config = uds_service.config
        handler = _RecordingHandler(response={"success": True, "message": "done"})
        uds_service.dispatcher = _StubDispatcher(handler, known_actions=(Action.GET_AGENT,))

        conn = _FakeConn(json.dumps({"action": Action.GET_AGENT,
                                     "params": {"agent_name": "a1"}}).encode("utf-8"))
        uds_service._handle_request(conn)

        assert len(handler.calls) == 1
        assert handler.calls[0]["params"] == {"agent_name": "a1"}
        assert handler.calls[0]["registry"] is registry
        assert handler.calls[0]["config"] is config
        assert json.loads(conn.sent.decode("utf-8")) == {"success": True, "message": "done"}
        assert conn.closed

    def test_invalid_json_returns_format_error(self, uds_service):
        conn = _FakeConn(b"{this is not json")
        uds_service._handle_request(conn)

        response = json.loads(conn.sent.decode("utf-8"))
        assert response == {"success": False, "error": "Invalid JSON format"}
        assert conn.closed

    def test_validation_error_response_shape(self, uds_service):
        # "action" is a required field of InternalRequest; omitting it
        # must produce the structured validation error, not a crash
        conn = _FakeConn(json.dumps({"params": {}}).encode("utf-8"))
        uds_service._handle_request(conn)

        response = json.loads(conn.sent.decode("utf-8"))
        assert response["success"] is False
        assert response["error"] == "Invalid request format"
        assert "action" in response["message"]
        assert conn.closed

    def test_unknown_action_returns_error(self, uds_service):
        uds_service.dispatcher = _StubDispatcher(None, known_actions=())

        conn = _FakeConn(json.dumps({"action": "bogus_action", "params": {}}).encode("utf-8"))
        uds_service._handle_request(conn)

        response = json.loads(conn.sent.decode("utf-8"))
        assert response == {"success": False, "error": "Unknown action: bogus_action"}
        assert conn.closed

    def test_empty_payload_sends_nothing_but_closes(self, uds_service):
        conn = _FakeConn(b"")
        uds_service._handle_request(conn)

        assert conn.sent == b""
        assert conn.closed

    def test_handler_exception_is_reported_as_error_response(self, uds_service):
        handler = _RecordingHandler(error=RuntimeError("handler boom"))
        uds_service.dispatcher = _StubDispatcher(handler, known_actions=("echo",))

        conn = _FakeConn(json.dumps({"action": "echo", "params": {}}).encode("utf-8"))
        uds_service._handle_request(conn)

        response = json.loads(conn.sent.decode("utf-8"))
        assert response == {"success": False, "error": "handler boom"}
        assert conn.closed

    def test_known_action_reaches_real_dispatcher_handler(self, uds_service, audit_recorder):
        # End-to-end through the real RequestDispatcher: the approval handler
        # rejects the request before touching the registry
        uds_service.registry.find_by_key.return_value = None
        uds_service.config = {"agent_approval_enabled": "true"}

        conn = _FakeConn(json.dumps({"action": Action.APPROVAL, "params": {
            "agent_name": "a1", "organization": "org1"}}).encode("utf-8"))
        uds_service._handle_request(conn)

        response = json.loads(conn.sent.decode("utf-8"))
        assert response["success"] is False
        assert response["error"] == "Agent not found"
        assert audit_recorder.entries[0]["result"] == OperationResult.FAILURE


# ---------- TCPInternalService (real loopback sockets) ----------

def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_for_port(port: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _roundtrip(port: int, payload: bytes) -> dict:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.settimeout(5)
        client.sendall(payload)
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    data = b"".join(chunks)
    assert data, "server closed the connection without sending a response"
    return json.loads(data.decode("utf-8"))


@pytest.fixture
def tcp_service():
    """Real TCPInternalService on an ephemeral loopback port with a stubbed dispatcher."""
    registry = Mock(name="registry")
    config = {"ip": "127.0.0.1", "port": 5000}
    port = _free_port()
    handler = _RecordingHandler(response={"success": True, "message": "echo ok"})
    service = TCPInternalService(registry=registry, config=config, host="127.0.0.1", port=port)
    service.dispatcher = _StubDispatcher(handler, known_actions=("echo",))
    thread = threading.Thread(target=service.start, daemon=True)
    thread.start()
    assert _wait_for_port(port), "TCP internal service did not start listening"
    yield service, port, handler, registry
    service.stop()
    thread.join(timeout=5)


class TestTCPInternalService:
    def test_constructor_stores_host_port_registry_config(self):
        registry = Mock()
        config = {"key": "value"}
        port = _free_port()

        service = TCPInternalService(registry=registry, config=config,
                                     host="127.0.0.1", port=port)

        assert service.host == "127.0.0.1"
        assert service.port == port
        assert service.registry is registry
        assert service.config is config
        assert service._running is False
        assert service._server_socket is None

    def test_valid_request_returns_handler_response(self, tcp_service):
        service, port, handler, registry = tcp_service

        response = _roundtrip(port, json.dumps(
            {"action": "echo", "params": {"agent_name": "a1"}}).encode("utf-8"))

        assert response == {"success": True, "message": "echo ok"}
        assert len(handler.calls) == 1
        assert handler.calls[0]["params"] == {"agent_name": "a1"}
        assert handler.calls[0]["registry"] is registry

    def test_missing_params_defaults_to_empty_dict(self, tcp_service):
        service, port, handler, _ = tcp_service

        response = _roundtrip(port, json.dumps({"action": "echo"}).encode("utf-8"))

        assert response == {"success": True, "message": "echo ok"}
        assert handler.calls[0]["params"] == {}

    def test_invalid_json_returns_format_error(self, tcp_service):
        service, port, _, _ = tcp_service

        response = _roundtrip(port, b"{broken json")

        assert response == {"success": False, "error": "Invalid JSON format"}

    def test_validation_error_response_shape(self, tcp_service):
        service, port, _, _ = tcp_service

        response = _roundtrip(port, json.dumps({"params": {}}).encode("utf-8"))

        assert response["success"] is False
        assert response["error"] == "Invalid request format"
        assert "action" in response["message"]

    def test_unknown_action_returns_error(self, tcp_service):
        service, port, _, _ = tcp_service

        response = _roundtrip(port, json.dumps(
            {"action": "no_such_action", "params": {}}).encode("utf-8"))

        assert response == {"success": False, "error": "Unknown action: no_such_action"}

    def test_stop_marks_service_stopped_and_closes_port(self, tcp_service):
        service, port, _, _ = tcp_service

        service.stop()

        assert service._running is False
        # On Linux a connection accepted from the listen backlog can still
        # complete after close(); the authoritative signal is the service
        # state plus the closed socket handle.
        assert service._server_socket is None or service._server_socket.fileno() == -1


# ---------- ApprovalHandler ----------

class TestApprovalHandler:
    @pytest.fixture
    def handler(self):
        return ApprovalHandler()

    @pytest.fixture
    def registry(self):
        registry = Mock()
        registry.find_by_key.return_value = Mock(name="agent")
        registry.get_status.return_value = "registered"
        registry.update_status.return_value = True
        return registry

    def test_missing_params_returns_error_and_audits_failure(self, handler, registry, audit_recorder):
        result = handler.handle({"agent_name": "", "organization": ""}, registry, {})

        assert result["success"] is False
        assert result["error"] == "Missing required params: agent_name or organization"
        registry.find_by_key.assert_not_called()
        assert audit_recorder.entries[0]["result"] == OperationResult.FAILURE

    def test_approval_disabled_returns_error(self, handler, registry, audit_recorder):
        result = handler.handle({"agent_name": "a1", "organization": "org1"}, registry, {})

        assert result["success"] is False
        assert result["error"] == "Approval function is disabled"
        assert "agent_approval_enabled=false" in result["message"]
        registry.find_by_key.assert_not_called()

    def test_agent_not_found(self, handler, registry, audit_recorder):
        registry.find_by_key.return_value = None

        result = handler.handle({"agent_name": "ghost", "organization": "org1"},
                                registry, {"agent_approval_enabled": "true"})

        assert result["success"] is False
        assert result["error"] == "Agent not found"
        assert "ghost" in result["message"]

    def test_already_published_rejected(self, handler, registry, audit_recorder):
        registry.get_status.return_value = "published"

        result = handler.handle({"agent_name": "a1", "organization": "org1"},
                                registry, {"agent_approval_enabled": "true"})

        assert result["success"] is False
        assert result["error"] == "Agent already published"
        registry.update_status.assert_not_called()

    def test_success_publishes_agent_and_audits_success(self, handler, registry, audit_recorder):
        result = handler.handle({"agent_name": "a1", "organization": "org1"},
                                registry, {"agent_approval_enabled": "true"})

        assert result["success"] is True
        assert result["message"] == "Agent approval successful"
        assert result["data"] == {"agent_name": "a1", "organization": "org1",
                                  "status": "published"}
        registry.update_status.assert_called_once_with("a1", "org1", "published")
        assert audit_recorder.entries[0]["result"] == OperationResult.SUCCESS

    def test_user_name_defaults_to_admin_in_audit(self, handler, registry, audit_recorder):
        handler.handle({"agent_name": "a1", "organization": "org1"},
                       registry, {"agent_approval_enabled": "true"})

        assert audit_recorder.entries[0]["user_name"] == "admin"

    def test_explicit_user_name_reaches_audit(self, handler, registry, audit_recorder):
        handler.handle({"agent_name": "a1", "organization": "org1", "user_name": "op_user"},
                       registry, {"agent_approval_enabled": "true"})

        assert audit_recorder.entries[0]["user_name"] == "op_user"

    def test_update_status_failure_returns_error(self, handler, registry, audit_recorder):
        registry.update_status.side_effect = RuntimeError("db down")

        result = handler.handle({"agent_name": "a1", "organization": "org1"},
                                registry, {"agent_approval_enabled": "true"})

        assert result["success"] is False
        assert result["error"] == "db down"
        assert result["message"] == "Failed to update agent status"


# ---------- GetAgentHandler ----------

class TestGetAgentHandler:
    @pytest.fixture
    def handler(self):
        return GetAgentHandler()

    @pytest.fixture
    def registry(self):
        registry = Mock()
        registry.get_status.return_value = "registered"
        registry.get_agent_tags.return_value = ["production"]
        registry.get_created_at.return_value = "2026-01-01T00:00:00Z"
        registry.get_updated_at.return_value = "2026-02-01T00:00:00Z"
        return registry

    @pytest.fixture
    def get_stub(self):
        record = AgentRecord(agent_card=_make_card())
        stub = _StubAsyncHandler(result=record)
        restore = _install_handler(InterfaceType.GET, stub)
        yield stub
        restore()

    def test_missing_params_returns_error_without_lookup(self, handler, registry):
        restore = _install_handler(InterfaceType.GET, _StubAsyncHandler(result=None))
        try:
            result = handler.handle({"agent_name": "a1"}, registry, {})
        finally:
            restore()

        assert result["success"] is False
        assert result["error"] == "Missing required params: agent_name or organization"

    def test_agent_not_found(self, handler, registry, get_stub):
        get_stub.result = None

        result = handler.handle({"agent_name": "ghost", "organization": "org1"}, registry, {})

        assert result["success"] is False
        assert result["error"] == "Agent not found"
        assert get_stub.calls == [(("ghost", "org1"), {})]

    def test_success_returns_agentcard_with_metadata(self, handler, registry, get_stub):
        result = handler.handle({"agent_name": "test_agent", "organization": "test_org"},
                                registry, {})

        assert result["success"] is True
        assert result["message"] == "Agent retrieved successfully"
        expected_card = MessageToDict(_make_card(), preserving_proto_field_name=True)
        assert result["data"]["agentcard"] == expected_card
        assert result["data"]["status"] == "registered"
        assert result["data"]["tag"] == ["production"]
        assert result["data"]["created_at"] == "2026-01-01T00:00:00Z"
        assert result["data"]["updated_at"] == "2026-02-01T00:00:00Z"

    def test_registry_none_values_fall_back_to_defaults(self, handler, registry, get_stub):
        registry.get_status.return_value = None
        registry.get_agent_tags.return_value = None
        registry.get_created_at.return_value = None
        registry.get_updated_at.return_value = None

        result = handler.handle({"agent_name": "test_agent", "organization": "test_org"},
                                registry, {})

        assert result["data"]["status"] == "published"
        assert result["data"]["tag"] == []
        assert result["data"]["created_at"] == ""
        assert result["data"]["updated_at"] == ""


# ---------- ListAgentsHandler ----------

class TestListAgentsHandler:
    @pytest.fixture
    def handler(self):
        return ListAgentsHandler()

    @pytest.fixture
    def registry(self):
        return Mock()

    @pytest.fixture
    def query_stub(self):
        stub = _StubAsyncHandler(result=[])
        restore = _install_handler(InterfaceType.QUERY, stub)
        yield stub
        restore()

    def test_empty_registry_returns_zero_count(self, handler, registry, query_stub):
        result = handler.handle({}, registry, {})

        assert result["success"] is True
        assert result["data"] == {"agents": [], "count": 0}

    def test_lists_agents_with_metadata(self, handler, registry, query_stub):
        card_a = _make_card("agent_a", "org_a")
        card_b = _make_card("agent_b", "org_b")
        query_stub.result = [card_a, card_b]
        statuses = {("agent_a", "org_a"): "registered", ("agent_b", "org_b"): None}
        tags = {("agent_a", "org_a"): ["prod"], ("agent_b", "org_b"): None}
        registry.get_status.side_effect = lambda n, o: statuses[(n, o)]
        registry.get_agent_tags.side_effect = lambda n, o: tags[(n, o)]
        registry.get_created_at.return_value = None
        registry.get_updated_at.return_value = None

        result = handler.handle({}, registry, {})

        assert result["success"] is True
        assert result["data"]["count"] == 2
        agents = result["data"]["agents"]
        assert agents[0] == {"agent_name": "agent_a", "organization": "org_a",
                             "status": "registered", "tag": ["prod"],
                             "created_at": "", "updated_at": ""}
        # None values from the registry fall back to the documented defaults
        assert agents[1]["status"] == "published"
        assert agents[1]["tag"] == []

    def test_registry_errors_propagate_as_exceptions(self, handler, registry, query_stub):
        query_stub.result = [_make_card("agent_a", "org_a")]
        registry.get_status.side_effect = RuntimeError("storage offline")

        with pytest.raises(RuntimeError, match="storage offline"):
            handler.handle({}, registry, {})


# ---------- SetTagsHandler ----------

class TestSetTagsHandler:
    @pytest.fixture
    def handler(self):
        return SetTagsHandler()

    @pytest.fixture
    def registry(self):
        registry = Mock()
        registry.get_tag_by_name.return_value = Mock(name="tag entity")
        registry.find_by_key.return_value = Mock(name="agent")
        registry.update_agent_tags.return_value = True
        registry.get_agent_tags.return_value = ["production"]
        return registry

    def test_missing_params_returns_error_and_audits_failure(self, handler, registry, audit_recorder):
        result = handler.handle({"tags": ["production"]}, registry, {})

        assert result["success"] is False
        assert result["error"] == "Missing required params: agent_name or organization"
        assert audit_recorder.entries[0]["result"] == OperationResult.FAILURE

    def test_tags_not_a_list_returns_invalid_param_type(self, handler, registry, audit_recorder):
        result = handler.handle({"agent_name": "a1", "organization": "org1",
                                 "tags": "production"}, registry, {})

        assert result["success"] is False
        assert result["error"] == "Invalid param type"
        assert result["message"] == "tags must be a list"

    def test_invalid_tag_characters_fail_validation(self, handler, registry, audit_recorder):
        result = handler.handle({"agent_name": "a1", "organization": "org1",
                                 "tags": ["bad tag!"]}, registry, {})

        assert result["success"] is False
        assert result["error"] == "Tag validation failed"
        assert "bad tag!" in result["message"]
        registry.get_tag_by_name.assert_not_called()

    def test_tags_missing_from_tag_library_rejected(self, handler, registry, audit_recorder):
        registry.get_tag_by_name.return_value = None

        result = handler.handle({"agent_name": "a1", "organization": "org1",
                                 "tags": ["ghost_tag"]}, registry, {})

        assert result["success"] is False
        assert result["error"] == "Invalid tags"
        assert "ghost_tag" in result["message"]
        registry.find_by_key.assert_not_called()

    def test_agent_not_found(self, handler, registry, audit_recorder):
        registry.find_by_key.return_value = None

        result = handler.handle({"agent_name": "ghost", "organization": "org1",
                                 "tags": ["production"]}, registry, {})

        assert result["success"] is False
        assert result["error"] == "Agent not found"
        registry.update_agent_tags.assert_not_called()

    def test_success_sets_tags_and_audits_success(self, handler, registry, audit_recorder):
        result = handler.handle({"agent_name": "a1", "organization": "org1",
                                 "tags": ["production"]}, registry, {})

        assert result["success"] is True
        assert result["message"] == "Tags set successfully"
        assert result["data"] == {"agent_name": "a1", "organization": "org1",
                                  "tag": ["production"]}
        registry.update_agent_tags.assert_called_once_with("a1", "org1", ["production"])
        success_entries = [e for e in audit_recorder.entries if e["result"] == OperationResult.SUCCESS]
        assert len(success_entries) == 1
        assert success_entries[0]["details"]["updated_tags"] == ["production"]

    def test_empty_tags_defaults_to_empty_list(self, handler, registry):
        # params without "tags" default to []; the agent ends up with no tags
        registry.get_agent_tags.return_value = []

        result = handler.handle({"agent_name": "a1", "organization": "org1"}, registry, {})

        assert result["success"] is True
        assert result["data"]["tag"] == []
        registry.get_tag_by_name.assert_not_called()

    def test_update_agent_tags_failure_returns_error(self, handler, registry, audit_recorder):
        registry.update_agent_tags.side_effect = RuntimeError("db down")

        result = handler.handle({"agent_name": "a1", "organization": "org1",
                                 "tags": ["production"]}, registry, {})

        assert result["success"] is False
        assert result["error"] == "db down"
        assert result["message"] == "Failed to set tags"
