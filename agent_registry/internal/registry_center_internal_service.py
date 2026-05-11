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

import json
import os
import socket
import threading
from typing import Dict, Type, Optional

from loguru import logger
from pydantic import ValidationError

from agent_registry.internal.handlers import BaseUDSHandler
from agent_registry.internal.handlers.approval_handler import ApprovalHandler
from agent_registry.internal.handlers.get_agent_handler import GetAgentHandler
from agent_registry.internal.handlers.list_agents_handler import ListAgentsHandler
from agent_registry.internal.handlers.tag_handler import (
    TagAddHandler, TagRemoveHandler, TagUpdateHandler,
    TagGetHandler, TagListHandler
)
from agent_registry.internal.protocols.actions import Action
from agent_registry.internal.protocols.request import InternalRequest
from agent_registry.registry_instance import get_registry
from common.util.config_util import get_conf


class RequestDispatcher:
    _handlers: Dict[str, Type[BaseUDSHandler]] = {
        Action.APPROVAL: ApprovalHandler,
        Action.GET_AGENT: GetAgentHandler,
        Action.LIST_AGENTS: ListAgentsHandler,
        Action.ADD_TAG: TagAddHandler,
        Action.REMOVE_TAG: TagRemoveHandler,
        Action.UPDATE_TAG: TagUpdateHandler,
        Action.GET_TAG: TagGetHandler,
        Action.LIST_TAG: TagListHandler,
    }

    def get_handler(self, action: str) -> Optional[BaseUDSHandler]:
        handler_class = self._handlers.get(action)
        if handler_class:
            return handler_class()
        return None

    def register_handler(self, action: str, handler_class: Type[BaseUDSHandler]):
        self._handlers[action] = handler_class


class RegistryCenterInternalService:
    SOCKET_PATH = "run/registry-center/internal.sock"
    SOCKET_DIR = "run/registry-center"

    def __init__(self):
        self.socket_path = self.SOCKET_PATH
        self.registry = get_registry()
        self.config = get_conf()
        self.dispatcher = RequestDispatcher()
        self._running = False

    def start(self):
        self._ensure_socket_dir()
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

        server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server_socket.bind(self.socket_path)
            os.chmod(self.socket_path, 0o660)
            server_socket.listen(5)
            self._running = True
            logger.info(f"Internal service started on UDS socket: {self.socket_path}")

            while self._running:
                try:
                    server_socket.settimeout(1.0)
                    conn, _ = server_socket.accept()
                    thread = threading.Thread(target=self._handle_request, args=(conn,))
                    thread.daemon = True
                    thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self._running:
                        logger.error(f"Error accepting connection: {e}")
        except Exception as e:
            logger.error(f"Failed to start UDS service: {e}")
        finally:
            server_socket.close()
            self._cleanup_socket()

    def stop(self):
        self._running = False
        self._cleanup_socket()

    def _ensure_socket_dir(self):
        os.makedirs(self.SOCKET_DIR, exist_ok=True)
        os.chmod(self.SOCKET_DIR, 0o750)

    def _cleanup_socket(self):
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

    def _handle_request(self, conn):
        logger.info("[InternalService] Entering _handle_request method")
        try:
            data = conn.recv(4096)
            logger.info(f"[InternalService] Received data: {len(data)} bytes")
            if not data:
                logger.warning("[InternalService] No data received, returning")
                return

            raw_request = json.loads(data.decode('utf-8'))
            logger.info(f"[InternalService] Request action: {raw_request.get('action')}")
            logger.debug(f"[InternalService] Request params: {raw_request.get('params')}")

            try:
                request = InternalRequest(**raw_request)
                logger.info(f"[InternalService] Request validated, action={request.action}")
            except ValidationError as e:
                logger.error(f"[InternalService] Invalid request format: {e}")
                response = {"success": False, "error": "Invalid request format", "message": str(e)}
                conn.send(json.dumps(response).encode('utf-8'))
                return

            handler = self.dispatcher.get_handler(request.action)
            logger.info(f"[InternalService] Handler found: {handler.__class__.__name__ if handler else 'None'}")

            if not handler:
                logger.error(f"[InternalService] Unknown action: {request.action}")
                response = {
                    "success": False,
                    "error": f"Unknown action: {request.action}"
                }
            else:
                logger.info(f"[InternalService] Calling handler.handle()")
                response = handler.handle(request.params, self.registry, self.config)
                logger.info(f"[InternalService] Handler returned response: success={response.get('success')}")

            conn.send(json.dumps(response).encode('utf-8'))
            logger.info("[InternalService] Response sent successfully")
        except json.JSONDecodeError as e:
            logger.error(f"[InternalService] Invalid JSON request: {e}")
            response = {"success": False, "error": "Invalid JSON format"}
            conn.send(json.dumps(response).encode('utf-8'))
        except Exception as e:
            logger.error(f"[InternalService] Error handling request: {e}")
            import traceback
            logger.error(f"[InternalService] Traceback: {traceback.format_exc()}")
            response = {"success": False, "error": str(e)}
            conn.send(json.dumps(response).encode('utf-8'))
        finally:
            conn.close()
            logger.info("[InternalService] Connection closed")