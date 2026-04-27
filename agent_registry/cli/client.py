"""
CLI HTTP Client

Calls Agent Registry service API, wraps all HTTP requests.
CLI commands interact with service through this client.
Uses standard library urllib to avoid extra dependencies.
"""

import json
import ssl
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any
from pathlib import Path

from agent_registry.cli.exceptions import ServiceError, ConfigError
from agent_registry.cli.constants import DEFAULT_TIMEOUT
from common.util.config_util import get_conf


class RegistryClient:
    """
    Agent Registry HTTP Client
    
    Wraps service API calls for CLI commands.
    
    Example:
        client = RegistryClient()
        agents = client.list_agents()
        agent = client.get_agent("MyAgent", "MyOrg")
    """
    
    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize client
        
        Args:
            base_url: Service address, e.g., "https://127.0.0.1:5000"
                      If None, read from config file
        """
        config = get_conf()
        
        if base_url:
            self.base_url = base_url
        else:
            ip = config.get("ip", "127.0.0.1")
            port = config.get("port", "5000")
            enable_https = config.get("enable_https", "true").lower() == "true"
            scheme = "https" if enable_https else "http"
            self.base_url = f"{scheme}://{ip}:{port}"
        
        self.timeout = DEFAULT_TIMEOUT
        self._ssl_context: Optional[ssl.SSLContext] = None
        
        # Client certificate configuration (for mutual TLS)
        self._cert_file: Optional[str] = None
        self._key_file: Optional[str] = None
        self._key_password: Optional[str] = None
        self._ca_certs: Optional[str] = None
        self._verify_server: bool = False
        
        # Check if verify_client is enabled
        verify_client = config.get("verify_client", "false").lower() == "true"
        if verify_client and self.base_url.startswith("https"):
            # Need client certificate - use server's cert as client cert for now
            # In production, should have separate client cert
            self._cert_file = config.get("ssl_certfile")
            self._key_file = config.get("ssl_keyfile")
            self._ca_certs = config.get("ssl_ca_certs")
            self._verify_server = True
    
    def _get_ssl_context(self) -> ssl.SSLContext:
        """
        Get SSL context
        
        Returns:
            ssl.SSLContext
        """
        if self._ssl_context is None:
            self._ssl_context = ssl.create_default_context()
            self._ssl_context.check_hostname = False
            
            if self._cert_file and self._key_file:
                # Load client certificate for mutual TLS
                try:
                    from common.util.conf_util import conf_singleton_obj, load_cert_password
                    
                    key_password = None
                    if self._key_password:
                        key_password = load_cert_password(self._key_password)
                    elif conf_singleton_obj.ssl_keyfile_password:
                        key_password = load_cert_password(conf_singleton_obj.ssl_keyfile_password)
                    
                    self._ssl_context.load_cert_chain(
                        certfile=self._cert_file,
                        keyfile=self._key_file,
                        password=key_password
                    )
                    
                    if self._ca_certs:
                        self._ssl_context.load_verify_locations(self._ca_certs)
                        self._ssl_context.verify_mode = ssl.CERT_REQUIRED
                    
                    if self._verify_server:
                        self._ssl_context.verify_mode = ssl.CERT_REQUIRED
                    else:
                        self._ssl_context.verify_mode = ssl.CERT_NONE
                        
                except Exception as e:
                    # If cert loading fails, fall back to no verification
                    self._ssl_context.verify_mode = ssl.CERT_NONE
            else:
                self._ssl_context.verify_mode = ssl.CERT_NONE
        
        return self._ssl_context
    
    def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Any:
        """
        Send HTTP request
        
        Args:
            method: HTTP method
            path: API path
            data: Request body data
            params: Query parameters
            
        Returns:
            Response data
            
        Raises:
            ServiceError: Service error
        """
        import urllib.parse
        
        # Encode special characters like spaces in path
        encoded_path = urllib.parse.quote(path, safe='/')
        url = f"{self.base_url}{encoded_path}"
        
        if params:
            encoded_params = []
            for k, v in params.items():
                if v is not None:
                    encoded_params.append(f"{urllib.parse.quote(str(k))}={urllib.parse.quote(str(v))}")
            if encoded_params:
                url = f"{url}?{('&'.join(encoded_params))}"
        
        headers = {"Content-Type": "application/json"}
        body = json.dumps(data).encode("utf-8") if data else None
        
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers=headers,
                method=method
            )
            
            ssl_ctx = self._get_ssl_context() if self.base_url.startswith("https") else None
            
            with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_ctx) as resp:
                content = resp.read().decode("utf-8")
                if content:
                    return json.loads(content)
                return None
        
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
                error_detail = json.loads(error_body).get("detail", error_body)
            except:
                error_detail = e.read().decode("utf-8") if e.fp else str(e)
            raise ServiceError(f"Service returned {e.code}: {error_detail}")
        
        except urllib.error.URLError as e:
            raise ServiceError(f"Connection error: {e.reason}")
        
        except Exception as e:
            raise ServiceError(f"Request failed: {e}")
    
    # ========== Agent API ==========
    
    def list_agents(
        self,
        name: Optional[str] = None,
        organization: Optional[str] = None
    ) -> List[Dict]:
        """
        Query agent list
        
        Args:
            name: Agent name (exact match)
            organization: Organization name (exact match)
            
        Returns:
            Agent list
        """
        return self._request("GET", "/rest/a2a-t/v1/agents/query", params={
            "name": name,
            "organization": organization
        })
    
    def get_agent(self, name: str, organization: str) -> Dict:
        """
        Get single agent details
        
        Args:
            name: Agent name
            organization: Organization name
            
        Returns:
            Agent details
        """
        return self._request("GET", f"/rest/a2a-t/v1/agents/{name}", params={
            "organization": organization
        })
    
    def register_agent(self, agent_card: Dict) -> bool:
        """
        Register agent
        
        Args:
            agent_card: AgentCard data
            
        Returns:
            Whether successful
        """
        return self._request("POST", "/rest/a2a-t/v1/agents/register", data=agent_card)
    
    def register_agent_from_file(self, file_path: str) -> bool:
        """
        Register agent from file
        
        Args:
            file_path: AgentCard JSON file path
            
        Returns:
            Whether successful
        """
        path = Path(file_path)
        if not path.exists():
            raise ConfigError(f"File not found: {file_path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            agent_card = json.load(f)
        
        return self.register_agent(agent_card)
    
    def update_agent(self, name: str, organization: str, agent_card: Dict) -> bool:
        """
        Update agent
        
        Args:
            name: Agent name
            organization: Organization name
            agent_card: New AgentCard data
            
        Returns:
            Whether successful
        """
        return self._request("PUT", f"/rest/a2a-t/v1/update_agent/{name}", data=agent_card, params={
            "organization": organization
        })
    
    def deregister_agent(self, name: str, organization: str) -> bool:
        """
        Deregister agent
        
        Args:
            name: Agent name
            organization: Organization name
            
        Returns:
            Whether successful
        """
        return self._request("DELETE", f"/rest/a2a-t/v1/deregister_agent/{name}", params={
            "organization": organization
        })
    
    def search_agents(self, task: str, top_n: int = 5) -> List[Dict]:
        """
        Semantic search for agents
        
        Args:
            task: Task description
            top_n: Return count
            
        Returns:
            Matching agent list
        """
        return self._request("GET", "/rest/a2a-t/v1/agents/retrieve", params={
            "task": task,
            "top_n": top_n
        })
    
    # ========== Health Check ==========
    
    def health_check(self) -> bool:
        """
        Check service health status
        
        Returns:
            Whether service is healthy
        """
        try:
            self._request("GET", "/rest/a2a-t/v1/agents/query")
            return True
        except ServiceError:
            return False
        except Exception:
            return False
    
    def health_check_debug(self) -> Dict[str, Any]:
        """
        Check service health with detailed error info
        
        Returns:
            Dict with health status and error details
        """
        result = {
            "healthy": False,
            "url": self.base_url,
            "error": None,
            "ssl_info": None
        }
        
        try:
            ssl_ctx = self._get_ssl_context() if self.base_url.startswith("https") else None
            if ssl_ctx:
                result["ssl_info"] = {
                    "verify_mode": ssl_ctx.verify_mode.name,
                    "check_hostname": ssl_ctx.check_hostname,
                    "has_client_cert": bool(self._cert_file),
                    "cert_file": self._cert_file,
                    "key_file": self._key_file,
                    "ca_certs": self._ca_certs
                }
            
            self._request("GET", "/rest/a2a-t/v1/agents/query")
            result["healthy"] = True
        except ServiceError as e:
            result["error"] = e.message
        except urllib.error.URLError as e:
            result["error"] = f"URLError: {e.reason}"
        except urllib.error.HTTPError as e:
            result["error"] = f"HTTPError {e.code}: {e.reason}"
        except ssl.SSLError as e:
            result["error"] = f"SSLError: {e}"
        except Exception as e:
            result["error"] = f"Exception: {type(e).__name__}: {e}"
        
        return result
    
    def get_service_info(self) -> Dict:
        """
        Get service information
        
        Returns:
            Service information dictionary
        """
        config = get_conf()
        return {
            "base_url": self.base_url,
            "ip": config.get("ip", "127.0.0.1"),
            "port": config.get("port", "5000"),
            "https": config.get("enable_https", "true").lower() == "true",
            "healthy": self.health_check()
        }


# Global client instance
_client: Optional[RegistryClient] = None


def get_client() -> RegistryClient:
    """
    Get global client instance
    
    Returns:
        RegistryClient
    """
    global _client
    if _client is None:
        _client = RegistryClient()
    return _client