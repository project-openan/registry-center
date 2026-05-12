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

"""
CLI UDS Client

Unified socket client for CLI commands to communicate with internal UDS service.
All CLI commands that need internal service access should use this client.
"""

import json
import socket
from typing import Dict, Any, Optional, List

from loguru import logger


class UDSClient:
    """
    UDS Socket Client for CLI

    Communicates with internal service via Unix Domain Socket.
    All CLI commands should use this client for internal operations.
    """

    SOCKET_PATH = "run/registry-center/internal.sock"

    def __init__(self, socket_path: str = None):
        self.socket_path = socket_path or self.SOCKET_PATH

    def send_request(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send request to internal UDS service

        Args:
            action: Action type (e.g., "approval")
            params: Request parameters

        Returns:
            Response dict with success, error, message, data fields
        """
        request = {
            "action": action,
            "params": params
        }

        client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client_socket.connect(self.socket_path)
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Socket not found",
                "message": f"Internal service is not running (socket: {self.socket_path})"
            }
        except PermissionError:
            return {
                "success": False,
                "error": "Permission denied",
                "message": "You don't have permission to access registry center"
            }
        except ConnectionRefusedError:
            return {
                "success": False,
                "error": "Connection refused",
                "message": "Internal service is not accepting connections"
            }

        try:
            client_socket.send(json.dumps(request).encode('utf-8'))

            response = client_socket.recv(4096)
            result = json.loads(response.decode('utf-8'))

            return result
        except json.JSONDecodeError as e:
            logger.error(f"Invalid response from server: {e}")
            return {
                "success": False,
                "error": "Invalid response",
                "message": str(e)
            }
        except Exception as e:
            logger.error(f"Error communicating with server: {e}")
            return {
                "success": False,
                "error": "Communication error",
                "message": str(e)
            }
        finally:
            client_socket.close()

    def approval_agent(self, agent_name: str, organization: str) -> Dict[str, Any]:
        """Approve registered agent"""
        return self.send_request("approval", {
            "agent_name": agent_name,
            "organization": organization
        })

    def get_agent(self, agent_name: str, organization: str) -> Dict[str, Any]:
        """Get single agent metadata (agent_name, organization, status, tag)"""
        return self.send_request("get_agent", {
            "agent_name": agent_name,
            "organization": organization
        })

    def list_agents(self) -> Dict[str, Any]:
        """Get all agents metadata"""
        return self.send_request("list_agents", {})

    def add_tags(self, agent_name: str, organization: str, tags: List[str]) -> Dict[str, Any]:
        """Add tags to agent"""
        return self.send_request("add_tag", {
            "agent_name": agent_name,
            "organization": organization,
            "tags": tags
        })

    # Tag entity management methods
    def create_tag(self, name: str) -> Dict[str, Any]:
        """Create a new tag entity"""
        return self.send_request("create_tag", {"name": name})

    def get_tag(self, tag_id: str = None, name: str = None) -> Dict[str, Any]:
        """Get tag by tag_id or name"""
        params = {}
        if tag_id:
            params["tag_id"] = tag_id
        elif name:
            params["name"] = name
        return self.send_request("get_tag", params)

    def update_tag(self, tag_id: str, new_name: str) -> Dict[str, Any]:
        """Update tag name"""
        return self.send_request("update_tag", {
            "tag_id": tag_id,
            "name": new_name
        })

    def delete_tag(self, tag_id: str) -> Dict[str, Any]:
        """Delete a tag"""
        return self.send_request("delete_tag", {"tag_id": tag_id})

    def list_tags(self) -> Dict[str, Any]:
        """List all tags"""
        return self.send_request("list_tags", {})

_client: Optional[UDSClient] = None


def get_uds_client() -> UDSClient:
    """Get global UDS client instance"""
    global _client
    if _client is None:
        _client = UDSClient()
    return _client