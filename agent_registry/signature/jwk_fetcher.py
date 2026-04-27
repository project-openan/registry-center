import requests
from typing import Optional, Callable
from jwt import PyJWK
from loguru import logger
from agent_registry.signature.models import JWK, JWKS
from agent_registry.signature.public_key_manager import PublicKeyManager


class JWKFetcher:
    """JWK fetcher"""

    REQUEST_TIMEOUT = 10  # 10 second timeout

    def __init__(self, public_key_manager: Optional[PublicKeyManager] = None):
        self.session = requests.Session()
        self.session.timeout = self.REQUEST_TIMEOUT
        self.public_key_manager = public_key_manager

    def fetch_jwks(self, jku: str) -> Optional[JWKS]:
        """
        Fetch JWKS from a URL.

        Args:
            jku: JWK Set URL.

        Returns:
            Optional[JWKS]: JWKS object, None on failure.
        """
        try:
            logger.info(f"Fetching JWKS from: {jku}")

            if not jku.startswith('https://'):
                logger.error(f"JKU must use HTTPS: {jku}")
                return None

            response = self.session.get(jku)
            if response.status_code != 200:
                logger.error(f"Failed to fetch JWKS, status: {response.status_code}")
                return None

            jwks_data = response.json()
            return JWKS(**jwks_data)

        except requests.exceptions.Timeout:
            logger.error(f"Timeout while fetching JWKS from: {jku}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while fetching JWKS: {e}")
            return None
        except Exception as e:
            logger.error(f"Error while fetching JWKS: {e}")
            return None

    def find_key_by_id(self, jwks: JWKS, kid: str) -> Optional[JWK]:
        """
        Find a public key from JWKS by kid.

        Args:
            jwks: JWKS object.
            kid: Key ID.

        Returns:
            Optional[JWK]: JWK object, None if not found.
        """
        try:
            for key in jwks.keys:
                if (key.kid == kid):
                    logger.info(f"Found key by kid: {kid}")
                    return key

            logger.warning(f"Key not found in JWKS: {kid}")
            return None
        except Exception as e:
            logger.error(f"Error while finding key: {e}")
            return None

    def fetch_from_backend(
        self,
        kid: str,
        organization: Optional[str],
        agent_name: str,
        provider_url: Optional[str] = None
    ) -> Optional[PyJWK]:
        """
        Fetch a public key from the backend.

        Args:
            kid: Key ID.
            organization: Organization name (optional).
            agent_name: Agent name.
            provider_url: Provider URL (optional, used when organization is None).

        Returns:
            Optional[PyJWK]: PyJWK object, None if not found.
        """
        try:
            if not self.public_key_manager:
                logger.warning("PublicKeyManager not configured")
                return None

            jwk = self.public_key_manager.get_public_key(organization, agent_name, kid, provider_url)
            if jwk:
                logger.info(f"Found backend key for kid: {kid}")
                return self._convert_to_pyjwk(jwk)
            else:
                logger.info(f"Backend key not found for kid: {kid}")
                return None
        except Exception as e:
            logger.error(f"Failed to get backend key: {e}")
            return None

    def create_backend_key_fetcher(
        self,
        organization: Optional[str],
        agent_name: str,
        provider_url: Optional[str] = None
    ) -> Callable[[str, str], Optional[PyJWK]]:
        """
        Create a backend public key fetch function (closure).

        Args:
            organization: Organization name (optional).
            agent_name: Agent name.
            provider_url: Provider URL (optional, used when organization is None).

        Returns:
            Callable: A function accepting (kid, jku) that returns a PyJWK object.
        """
        def fetch_backend_key(kid: str, jku: str) -> Optional[PyJWK]:
            return self.fetch_from_backend(kid, organization, agent_name, provider_url)

        return fetch_backend_key

    def fetch_jku_key(self, kid: str, jku: str) -> Optional[PyJWK]:
        """
        Fetch a public key from a jku URL.

        Args:
            kid: Key ID.
            jku: JWK Set URL.

        Returns:
            Optional[PyJWK]: JWK object, None if not found.
        """
        jwks = self.fetch_jwks(jku)
        if jwks:
            jwk = self.find_key_by_id(jwks, kid)
            if jwk:
                return self._convert_to_pyjwk(jwk)
        return None

    def _convert_to_pyjwk(self, jwk: JWK):
        """
        Convert custom JWK object to jwt.api_jwk.PyJWK object.

        Args:
            jwk: Custom JWK object.

        Returns:
            jwt.api_jwk.PyJWK object.
        """
        try:
            pyjwk_dict = {
                "kty": jwk.kty,
                "kid": jwk.kid,
                "use": jwk.use,
                "alg": jwk.alg
            }

            if jwk.crv:
                pyjwk_dict["crv"] = jwk.crv

            pyjwk_dict["x"] = jwk.x
            pyjwk_dict["y"] = jwk.y

            if jwk.n:
                pyjwk_dict["n"] = jwk.n

            if jwk.e:
                pyjwk_dict["e"] = jwk.e

            return PyJWK(pyjwk_dict)

        except Exception as e:
            logger.error(f"Failed to convert JWK to PyJWK: {e}")
            raise
