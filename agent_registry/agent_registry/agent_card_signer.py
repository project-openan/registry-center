from typing import Optional, Dict, Any
from loguru import logger
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from cryptography import x509
import json


class AgentCardSigner:
    def __init__(
        self,
        private_key_path: str,
        password_path: Optional[str] = None,
        jku_url: Optional[str] = None,
        algorithm: str = "RS256",
        sign_enabled: bool = True
    ):
        self.private_key_path = private_key_path
        self.password_path = password_path
        self.jku_url = jku_url
        self.algorithm = algorithm
        self.sign_enabled = sign_enabled
        self._private_key = None
        self._password = None
        self._algorithm_map = {
            "RS256": hashes.SHA256(),
            "RS384": hashes.SHA384(),
            "RS512": hashes.SHA512()
        }
        
        if self.sign_enabled:
            self._load_credentials()

    def is_enabled(self) -> bool:
        return self.sign_enabled

    def _load_credentials(self):
        try:
            with open(self.private_key_path, 'rb') as f:
                private_key_data = f.read()
            
            password = None
            if self.password_path:
                with open(self.password_path, 'r') as f:
                    password = f.read().strip()
            
            self._private_key = serialization.load_pem_private_key(
                private_key_data,
                password=password,
                backend=default_backend()
            )
            
            logger.info("Private key loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load private key: {e}")
            raise

    def _canonicalize_agent_card(self, agent_card: Dict[str, Any]) -> Dict[str, Any]:
        try:
            canonical = {}
            for key in sorted(agent_card.keys()):
                value = agent_card[key]
                if isinstance(value, dict):
                    canonical[key] = self._canonicalize_agent_card(value)
                elif isinstance(value, list):
                    canonical[key] = sorted(value)
                else:
                    canonical[key] = value
            return canonical
        except Exception as e:
            logger.error(f"Failed to canonicalize agent card: {e}")
            raise

    def _create_jwk_header(self, kid: str) -> Dict[str, str]:
        try:
            public_key = self._private_key.public_key()
            numbers = public_key.public_numbers()
            
            jwk = {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": self.algorithm,
                "n": self._base64url_encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, 'big')),
                "e": self._base64url_encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, 'big'))
            }
            
            return jwk
        except Exception as e:
            logger.error(f"Failed to create JWK header: {e}")
            raise

    def _base64url_encode(self, data: bytes) -> str:
        import base64
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')

    def _create_signature(self, data: str) -> str:
        try:
            data_bytes = data.encode('utf-8')
            
            signature = self._private_key.sign(
                data_bytes,
                padding.PKCS1v15(),
                self._algorithm_map.get(self.algorithm, hashes.SHA256())
            )
            
            signature_b64 = self._base64url_encode(signature)
            return signature_b64
        except Exception as e:
            logger.error(f"Failed to create signature: {e}")
            raise

    def sign_agent_card(self, agent_card: Any) -> Any:
        if not self.sign_enabled:
            logger.debug("Signing is disabled, returning original agent card")
            return agent_card
        
        try:
            agent_card_dict = agent_card.model_dump() if hasattr(agent_card, 'model_dump') else agent_card
            
            canonical_card = self._canonicalize_agent_card(agent_card_dict)
            canonical_json = json.dumps(canonical_card, separators=(',', ':'), sort_keys=True)
            
            signature = self._create_signature(canonical_json)
            
            kid = self.jku_url.split('/')[-1] if self.jku_url else "default_kid"
            jwk_header = self._create_jwk_header(kid)
            
            signatures = getattr(agent_card, 'signatures', [])
            if not isinstance(signatures, list):
                signatures = []
            
            new_signature = {
                "protected": jwk_header,
                "signature": signature
            }
            
            signatures.append(new_signature)
            
            if hasattr(agent_card, 'model_copy'):
                signed_card = agent_card.model_copy()
                signed_card.signatures = signatures
                return signed_card
            else:
                agent_card_dict['signatures'] = signatures
                return agent_card_dict
            
        except Exception as e:
            logger.warning(f"Failed to sign agent card: {e}. Returning original agent card.")
            return agent_card
