#!/usr/bin/env python3
"""
Windows Development Startup Script

This script starts both TCP internal service and HTTP server on Windows for local debugging.
Unlike production code which blocks Windows startup, this script allows Windows development.

Usage:
    python tests/windows_dev_startup.py

To stop: Press Ctrl+C

IMPORTANT - How to enable CLI commands on Windows:
    
    The CLI (python -m agent_registry.cli) uses UDS (Unix Domain Socket) which is NOT 
    supported on Windows. To enable CLI commands for Windows debugging, you need to 
    manually modify the following files:

    1. agent_registry/cli/uds_client.py:
       - Comment out the Windows platform check (lines 62-68):
         
         BEFORE:
             if self.is_windows:
                 logger.error("Registry center startup failed...")
                 return {...}
         
         AFTER:
             # if self.is_windows:
             #     logger.error("Registry center startup failed...")
             #     return {...}
       
       - Change socket type from AF_UNIX to AF_INET:
         
         BEFORE (line 75):
             client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
         
         AFTER:
             client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
       
       - Change connect from socket path to TCP address:
         
         BEFORE (line 77):
             client_socket.connect(self.socket_path)
         
         AFTER:
             client_socket.connect(("127.0.0.1", 1108))

    2. agent_registry/cli/uds_client.py (bottom of file):
       - Comment out the warning in get_uds_client() (lines 184-185):
         
         BEFORE:
             if IS_WINDOWS:
                 logger.error("Registry center startup failed...")
         
         AFTER:
             # if IS_WINDOWS:
             #     logger.error("Registry center startup failed...")

    After these modifications:
    - Run: python tests/windows_dev_startup.py
    - Then CLI commands will work: python -m agent_registry.cli

    Remember to revert these changes before committing to production!

Note:
    - UDS (Unix Domain Socket) is not supported on Windows, so we use TCP socket instead
    - This is ONLY for local debugging purposes
    - Production code still blocks Windows startup as expected
"""

import json
import os
import socket
import sys
import threading
import time
import platform

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger


HTTP_PORT = 5000
TCP_INTERNAL_PORT = 1108
TCP_INTERNAL_HOST = "127.0.0.1"


class TCPInternalService:
    """TCP-based internal service for Windows (replaces UDS)"""
    
    def __init__(self, registry, config, port: int = TCP_INTERNAL_PORT):
        self.port = port
        self.host = TCP_INTERNAL_HOST
        self.registry = registry
        self.config = config
        self._running = False
        self._server_socket = None
        
        from agent_registry.internal.registry_center_internal_service import RequestDispatcher
        self.dispatcher = RequestDispatcher()
    
    def start(self):
        """Start TCP internal service"""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(5)
            self._running = True
            logger.info(f"TCP internal service started on {self.host}:{self.port}")
            
            while self._running:
                try:
                    self._server_socket.settimeout(1.0)
                    conn, _ = self._server_socket.accept()
                    thread = threading.Thread(target=self._handle_request, args=(conn,), daemon=True)
                    thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self._running:
                        logger.error(f"Error accepting connection: {e}")
        except Exception as e:
            logger.error(f"Failed to start TCP service: {e}")
        finally:
            if self._server_socket:
                self._server_socket.close()
    
    def stop(self):
        """Stop TCP internal service"""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except:
                pass
        logger.info("TCP internal service stopped")
    
    def _handle_request(self, conn):
        """Handle incoming TCP request"""
        try:
            data = conn.recv(4096)
            if not data:
                return
            
            raw_request = json.loads(data.decode('utf-8'))
            from pydantic import ValidationError
            from agent_registry.internal.protocols.request import InternalRequest
            
            try:
                request = InternalRequest(**raw_request)
            except ValidationError as e:
                response = {"success": False, "error": "Invalid request format", "message": str(e)}
                conn.send(json.dumps(response).encode('utf-8'))
                return
            
            handler = self.dispatcher.get_handler(request.action)
            
            if not handler:
                response = {"success": False, "error": f"Unknown action: {request.action}"}
            else:
                response = handler.handle(request.params, self.registry, self.config)
            
            conn.send(json.dumps(response).encode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON request: {e}")
            response = {"success": False, "error": "Invalid JSON format"}
            conn.send(json.dumps(response).encode('utf-8'))
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            response = {"success": False, "error": str(e)}
            conn.send(json.dumps(response).encode('utf-8'))
        finally:
            conn.close()


class TCPClient:
    """TCP client for testing internal service on Windows"""
    
    def __init__(self, host: str = TCP_INTERNAL_HOST, port: int = TCP_INTERNAL_PORT):
        self.host = host
        self.port = port
    
    def send_request(self, action: str, params: dict) -> dict:
        """Send a request to the TCP internal service"""
        request = {"action": action, "params": params}
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((self.host, self.port))
            sock.send(json.dumps(request).encode('utf-8'))
            response = sock.recv(4096)
            return json.loads(response.decode('utf-8'))
        finally:
            sock.close()


_tcp_service = None
_http_thread = None
_shutdown_event = threading.Event()


def start_tcp_internal_service():
    """Start TCP internal service"""
    from agent_registry.registry_instance import get_registry
    from common.util.config_util import get_conf
    
    registry = get_registry()
    config = get_conf()
    
    global _tcp_service
    _tcp_service = TCPInternalService(registry, config, port=TCP_INTERNAL_PORT)
    
    tcp_thread = threading.Thread(target=_tcp_service.start, daemon=True)
    tcp_thread.start()
    
    logger.info(f"TCP internal service thread started on port {TCP_INTERNAL_PORT}")
    return _tcp_service


def start_http_server():
    """Start HTTP server"""
    import uvicorn
    from agent_registry.server import app
    
    logger.info(f"Starting HTTP server on port {HTTP_PORT}...")
    
    def run_server():
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=HTTP_PORT,
            log_level="info"
        )
    
    global _http_thread
    _http_thread = threading.Thread(target=run_server, daemon=False)
    _http_thread.start()
    
    logger.info(f"HTTP server thread started on port {HTTP_PORT}")


def print_startup_info():
    """Print startup information"""
    print("\n" + "=" * 70)
    print("  Windows Development Startup - Registry Center")
    print("=" * 70)
    print(f"  Platform:     {platform.system()}")
    print(f"  Python:       {sys.version.split()[0]}")
    print(f"  HTTP Port:    {HTTP_PORT}")
    print(f"  TCP Port:     {TCP_INTERNAL_PORT}")
    print("=" * 70)
    print("\n  Services:")
    print(f"    - HTTP REST API:      http://127.0.0.1:{HTTP_PORT}")
    print(f"    - TCP Internal API:   127.0.0.1:{TCP_INTERNAL_PORT}")
    print("\n  Endpoints:")
    print(f"    - Agent Cards:        http://127.0.0.1:{HTTP_PORT}/rest/v1/registry-center/agent-cards")
    print(f"    - Semantic Query:     http://127.0.0.1:{HTTP_PORT}/rest/v1/registry-center/agent-cards/semantic-query")
    print(f"    - JWKS:               http://127.0.0.1:{HTTP_PORT}/.well-known/jwks.json")
    print("\n  IMPORTANT: To enable CLI commands, see file header for")
    print("  instructions on modifying agent_registry/cli/uds_client.py")
    print("=" * 70)
    print("\n  Press Ctrl+C to stop all services.\n")


def main():
    """Start all services and keep running"""
    if platform.system() != "Windows":
        logger.error("This script is designed for Windows environment only.")
        logger.error("For Linux, use the production startup script: python -m agent_registry.start")
        sys.exit(1)
    
    print_startup_info()
    
    logger.info("Initializing registry...")
    from agent_registry.registry_instance import initialize_registry
    initialize_registry()
    
    logger.info("Starting TCP internal service...")
    start_tcp_internal_service()
    
    time.sleep(1)
    
    logger.info("Starting HTTP server...")
    start_http_server()
    
    logger.info("All services started. Running until Ctrl+C...")
    logger.info(f"HTTP: http://127.0.0.1:{HTTP_PORT}")
    logger.info(f"TCP:  127.0.0.1:{TCP_INTERNAL_PORT}")
    logger.info("Note: Press Ctrl+C in this terminal to stop services.")
    
    try:
        while not _shutdown_event.is_set():
            _shutdown_event.wait(timeout=1.0)
    except KeyboardInterrupt:
        logger.info("\nKeyboardInterrupt received, stopping services...")
        global _tcp_service
        if _tcp_service:
            _tcp_service.stop()
        logger.info("Services stopped.")


if __name__ == "__main__":
    main()