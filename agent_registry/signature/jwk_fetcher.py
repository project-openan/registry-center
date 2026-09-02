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
import httpx
from typing import Optional, Callable, Set
from urllib.parse import urlparse
from jwt import PyJWK
from loguru import logger
from agent_registry.signature.models import JWK, JWKS
from agent_registry.signature.public_key_manager import PublicKeyManager


class JWKFetcher:
    """JWK fetcher"""

    REQUEST_TIMEOUT = 10

    def __init__(
        self,
        public_key_manager: Optional[PublicKeyManager] = None,
        jwk_allowlist: Optional[str] = None,
    ):
        self.session = httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT)
        self.public_key_manager = public_key_manager
        self.jwk_allowlist = self._parse_allowlist(jwk_allowlist or "")

    @staticmethod
    def _parse_allowlist(raw: str) -> Set[str]:
        """Parse a comma-separated host allowlist into a normalized set."""
        return {host.strip().lower() for host in raw.split(",") if host.strip()}

    def _is_jku_host_allowed(self, jku: str) -> bool:
        """
        Check whether a jku URL host is permitted for key fetch.

        The allowlist is the operator-declared trust boundary for signer-supplied
        jku URLs (CWE-863). When no allowlist is configured the jku path fails
        closed: no external key material is fetched from card-controlled input,
        and only backend keys are used for verification.
        """
        if not self.jwk_allowlist:
            logger.error(
                "jku key fetch disabled: 'jwk_allowlist' is not configured. "
                "Configure etc/conf/server.conf jwk_allowlist (or REGISTRY_JWK_ALLOWLIST) "
                "to enable signer-supplied jku key lookup."
            )
            return False

        try:
            host = (urlparse(jku).hostname or "").lower()
        except Exception as e:
            logger.error(f"Failed to parse jku URL '{jku}': {e}")
            return False

        if not host:
            logger.error(f"jku URL has no host: {jku}")
            return False

        if host in self.jwk_allowlist:
            return True

        logger.error(f"jku host '{host}' is not in the configured allowlist")
        return False

    async def fetch_jwks(self, jku: str) -> Optional[JWKS]:
        """
        Fetch JWKS from a URL.

        Args:
            jku: JWK Set URL.

        Returns:
            Optional[JWKS]: JWKS object, None on failure.
        """
        try:
            logger.info(f"Fetching JWKS from: {jku}")

            if not self._is_jku_host_allowed(jku):
                return None

            if not jku.startswith('https://'):
                logger.error(f"JKU must use HTTPS: {jku}")
                return None

            response = await self.session.get(jku)
            if response.status_code != 200:
                logger.error(f"Failed to fetch JWKS, status: {response.status_code}")
                return None

            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > 1_048_576:
                logger.error(f"JWKS response too large: {content_length} bytes (max 1MB)")
                return None

            jwks_data = response.json()
            return JWKS(**jwks_data)

        except httpx.TimeoutException:
            logger.error(f"Timeout while fetching JWKS from: {jku}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"Request error while fetching JWKS: {e}")
            return None
        except Exception as e:
            logger.error(f"Error while fetching JWKS: {e}")
            return None

    @staticmethod
    def find_key_by_id(jwks: JWKS, kid: str) -> Optional[JWK]:
        """
        Find a public key from JWKS by kid.

        Args:
            jwks: JWKS object.
            kid: Key ID.

        Returns:
            Optional[JWK]: JWK object, None if not found.
        """
        if jwks is None:
            return None
        try:
            for key in jwks.keys:
                if key.kid == kid:
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

    async def fetch_jku_key(self, kid: str, jku: str) -> Optional[PyJWK]:
        """
        Fetch a public key from a jku URL.

        Args:
            kid: Key ID.
            jku: JWK Set URL.

        Returns:
            Optional[PyJWK]: JWK object, None if not found.
        """
        jwks = await self.fetch_jwks(jku)
        if jwks:
            jwk = self.find_key_by_id(jwks, kid)
            if jwk:
                return self._convert_to_pyjwk(jwk)
        return None

    @staticmethod
    def _convert_to_pyjwk(jwk: JWK) -> PyJWK:
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

            if jwk.kty == "EC":
                if jwk.crv:
                    pyjwk_dict["crv"] = jwk.crv
                pyjwk_dict["x"] = jwk.x
                if jwk.y:
                    pyjwk_dict["y"] = jwk.y
            elif jwk.kty == "RSA":
                if jwk.n:
                    pyjwk_dict["n"] = jwk.n
                if jwk.e:
                    pyjwk_dict["e"] = jwk.e

            return PyJWK(pyjwk_dict)

        except Exception as e:
            logger.error(f"Failed to convert JWK to PyJWK: {e}")
            raise