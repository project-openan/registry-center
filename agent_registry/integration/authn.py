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

"""Standards-first authentication for the integration access plane."""

import asyncio
import hashlib
import hmac
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.parse import urlparse

import httpx
import jwt

from agent_registry.integration.credentials import CredentialEntry, load_credentials
from common.custom.custom_handle import BaseHandler, HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.util.app_config import get_conf
from common.util.authenticate_util import (
    AUTH_METHOD_CERTIFICATE, AUTH_METHOD_OAUTH2_INTROSPECTION,
    AUTH_METHOD_OAUTH2_JWT, AUTH_METHOD_STATIC_BEARER,
    AuthFailureReason, AuthenticationError, CallerRole, CallerType, Principal,
)

_FAIL = "Authentication failed"


@dataclass(frozen=True)
class Credential:
    kind: str
    value: str = ''
    peer_certificate: Optional[dict] = None
    fingerprint: str = ''


@dataclass(frozen=True)
class AuthenticationContext:
    client_ip: str


def token_fingerprint(token: str, key: str) -> str:
    return hmac.new(key.encode(), token.encode(), hashlib.sha256).hexdigest()


class CredentialExtractor(ABC):
    @abstractmethod
    def extract(self, request: Any) -> Optional[Credential]:
        raise NotImplementedError


class BearerTokenExtractor(CredentialExtractor):
    def __init__(self, fingerprint_key: str):
        if not fingerprint_key:
            raise ValueError("integration.auth.fingerprint_key is required")
        self._key = fingerprint_key

    def extract(self, request: Any) -> Optional[Credential]:
        headers = request.headers
        values = headers.getlist('authorization') if hasattr(headers, 'getlist') else []
        if not values:
            value = headers.get('Authorization')
            values = [value] if value else []
        if not values:
            return None
        if len(values) != 1:
            raise AuthenticationError(AuthFailureReason.INVALID_TOKEN_FORMAT, _FAIL)
        parts = values[0].strip().split()
        if len(parts) != 2 or parts[0].lower() != 'bearer' or not parts[1]:
            raise AuthenticationError(AuthFailureReason.INVALID_TOKEN_FORMAT, _FAIL)
        token = parts[1]
        return Credential('bearer', value=token,
                          fingerprint=token_fingerprint(token, self._key))


class TlsPeerCertificateExtractor(CredentialExtractor):
    def extract(self, request: Any) -> Optional[Credential]:
        cert = request.scope.get('tls_peer_cert') if hasattr(request, 'scope') else None
        return Credential('mtls', peer_certificate=cert) if cert else None


class AuthenticationProvider(ABC):
    provider_id = ''
    credential_kind = ''

    @abstractmethod
    async def authenticate(self, credential: Credential,
                           context: AuthenticationContext) -> Principal:
        raise NotImplementedError


class AuthenticationProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, AuthenticationProvider] = {}

    def register(self, provider: AuthenticationProvider) -> None:
        if not provider.provider_id:
            raise ValueError("provider_id is required")
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> AuthenticationProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ValueError(f"Unknown authentication provider: {provider_id}") from exc


_CUSTOM_PROVIDERS: Dict[str, AuthenticationProvider] = {}
_CUSTOM_EXTRACTORS: Dict[str, CredentialExtractor] = {}


def register_authentication_provider(provider: AuthenticationProvider,
                                     extractor: CredentialExtractor) -> None:
    """Register a business-owned provider without changing core request logic."""
    if not provider.provider_id or not provider.credential_kind:
        raise ValueError("Custom provider id and credential kind are required")
    _CUSTOM_PROVIDERS[provider.provider_id] = provider
    _CUSTOM_EXTRACTORS[provider.provider_id] = extractor


class ScopeRoleMapper:
    def __init__(self, mapping: Mapping[str, str]):
        self._mapping = {scope: CallerRole(role) for scope, role in mapping.items()}

    def role_for(self, scopes: Iterable[str]) -> Optional[CallerRole]:
        roles = {self._mapping[s] for s in scopes if s in self._mapping}
        if len(roles) > 1:
            raise AuthenticationError(AuthFailureReason.INVALID_TOKEN, _FAIL)
        return next(iter(roles), None)


def _principal(context: AuthenticationContext, *, subject: str, method: str,
               credential_id: str, role: Optional[CallerRole], issuer: str = '',
               client_id: str = '', scopes=(), owner: str = '', tenant: str = '') -> Principal:
    if not subject or role is None:
        raise AuthenticationError(AuthFailureReason.INVALID_TOKEN, _FAIL)
    return Principal(client_ip=context.client_ip, identity=subject, subject=subject,
                     caller_type=CallerType.INTEGRATION, role=role,
                     auth_method=method, owner=owner or subject, issuer=issuer,
                     client_id=client_id, scopes=scopes, tenant=tenant,
                     credential_id=credential_id)


class StaticBearerProvider(AuthenticationProvider):
    provider_id = 'static_bearer'
    credential_kind = 'bearer'

    def __init__(self, entries: Mapping[str, CredentialEntry], hmac_key: str):
        if not hmac_key:
            raise ValueError("integration.auth.static.hmac_key is required")
        self._entries, self._key = entries, hmac_key

    async def authenticate(self, credential: Credential, context: AuthenticationContext) -> Principal:
        digest = token_fingerprint(credential.value, self._key)
        entry = next((e for e in self._entries.values()
                      if hmac.compare_digest(e.token_hash, digest)), None)
        if entry is None:
            raise AuthenticationError(AuthFailureReason.INVALID_TOKEN, _FAIL)
        return _principal(context, subject=entry.identity, method=AUTH_METHOD_STATIC_BEARER,
                          credential_id=entry.credential_id, role=entry.role, owner=entry.owner)


class JwtBearerProvider(AuthenticationProvider):
    provider_id = 'oauth2_jwt'
    credential_kind = 'bearer'

    def __init__(self, issuer: str, audience: str, jwks_uri: str,
                 algorithms: Iterable[str], mapper: ScopeRoleMapper):
        if not issuer or not audience or not jwks_uri:
            raise ValueError("JWT issuer, audience and jwks_uri are required")
        if urlparse(jwks_uri).scheme != 'https':
            raise ValueError("JWKS URI must use HTTPS")
        self.issuer, self.audience, self.algorithms = issuer, audience, list(algorithms)
        if not self.algorithms or any(a.strip().lower() == 'none' for a in self.algorithms):
            raise ValueError("At least one safe JWT algorithm is required")
        self._jwks = jwt.PyJWKClient(jwks_uri, cache_jwk_set=True, lifespan=300)
        self._mapper = mapper

    def _decode(self, token: str) -> dict:
        key = self._jwks.get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=self.algorithms,
                          issuer=self.issuer, audience=self.audience,
                          options={'require': ['exp', 'iss', 'aud', 'sub']})

    async def authenticate(self, credential: Credential, context: AuthenticationContext) -> Principal:
        try:
            claims = await asyncio.to_thread(self._decode, credential.value)
            scopes = _parse_scopes(claims.get('scope', ''))
            return _principal(context, subject=str(claims['sub']), method=AUTH_METHOD_OAUTH2_JWT,
                              credential_id=f"{self.issuer}:{claims.get('client_id', claims['sub'])}",
                              role=self._mapper.role_for(scopes), issuer=self.issuer,
                              client_id=str(claims.get('client_id', '')), scopes=scopes,
                              tenant=str(claims.get('tenant', '')))
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(AuthFailureReason.INVALID_TOKEN, _FAIL) from exc


class IntrospectionBearerProvider(AuthenticationProvider):
    provider_id = 'oauth2_introspection'
    credential_kind = 'bearer'

    def __init__(self, endpoint: str, client_id: str, client_secret: str,
                 issuer: str, audience: str, mapper: ScopeRoleMapper,
                 timeout: float = 3.0, cache_seconds: int = 30,
                 client: Optional[httpx.AsyncClient] = None):
        if urlparse(endpoint).scheme != 'https':
            raise ValueError("Introspection endpoint must use HTTPS")
        if not client_id or not client_secret:
            raise ValueError("Introspection client credentials are required")
        self.endpoint, self.client_id, self.client_secret = endpoint, client_id, client_secret
        self.issuer, self.audience, self.mapper = issuer, audience, mapper
        self.timeout, self.cache_seconds = timeout, cache_seconds
        self.client = client or httpx.AsyncClient()
        self._cache: Dict[str, tuple] = {}

    async def authenticate(self, credential: Credential, context: AuthenticationContext) -> Principal:
        now = time.time()
        cached = self._cache.get(credential.fingerprint)
        if cached and cached[0] > now:
            data = cached[1]
        else:
            try:
                response = await self.client.post(self.endpoint, data={'token': credential.value},
                                                  auth=(self.client_id, self.client_secret),
                                                  timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                raise AuthenticationError(AuthFailureReason.PROVIDER_UNAVAILABLE, _FAIL) from exc
            if not isinstance(data, dict) or data.get('active') is not True:
                raise AuthenticationError(AuthFailureReason.INVALID_TOKEN, _FAIL)
            try:
                expiry = float(data.get('exp', now + self.cache_seconds))
                nbf = float(data.get('nbf', 0))
            except (TypeError, ValueError) as exc:
                raise AuthenticationError(
                    AuthFailureReason.INVALID_TOKEN, _FAIL) from exc
            if expiry <= now or nbf > now:
                raise AuthenticationError(AuthFailureReason.INVALID_TOKEN, _FAIL)
            self._cache[credential.fingerprint] = (min(now + self.cache_seconds, expiry), data)
        if self.issuer and data.get('iss') != self.issuer:
            raise AuthenticationError(AuthFailureReason.INVALID_TOKEN, _FAIL)
        audiences = data.get('aud', [])
        audiences = [audiences] if isinstance(audiences, str) else audiences
        if self.audience and self.audience not in audiences:
            raise AuthenticationError(AuthFailureReason.INVALID_TOKEN, _FAIL)
        scopes = _parse_scopes(data.get('scope', ''))
        subject = str(data.get('sub') or data.get('client_id') or '')
        return _principal(context, subject=subject, method=AUTH_METHOD_OAUTH2_INTROSPECTION,
                          credential_id=f"{self.issuer}:{data.get('client_id', subject)}",
                          role=self.mapper.role_for(scopes), issuer=self.issuer,
                          client_id=str(data.get('client_id', '')), scopes=scopes)


class MtlsProvider(AuthenticationProvider):
    provider_id = 'mtls'
    credential_kind = 'mtls'

    def __init__(self, entries: Mapping[str, CredentialEntry]):
        self._entries = entries

    async def authenticate(self, credential: Credential, context: AuthenticationContext) -> Principal:
        cn = ''
        for rdn in (credential.peer_certificate or {}).get('subject') or ():
            for key, value in rdn:
                if key == 'commonName':
                    cn = value
        entry = self._entries.get(cn)
        if entry is None:
            raise AuthenticationError(AuthFailureReason.INVALID_CERTIFICATE, _FAIL)
        return _principal(context, subject=entry.identity, method=AUTH_METHOD_CERTIFICATE,
                          credential_id=entry.credential_id, role=entry.role, owner=entry.owner)


def _parse_scopes(value: Any) -> frozenset:
    if isinstance(value, str):
        return frozenset(value.split())
    if isinstance(value, (list, tuple, set)):
        return frozenset(str(v) for v in value)
    return frozenset()


def _scope_mapping(conf: Mapping[str, Any]) -> Dict[str, str]:
    prefix = 'integration.auth.scope_role.'
    return {key[len(prefix):]: str(value) for key, value in conf.items()
            if key.startswith(prefix) and value}


class ThirdPartyAuthnHandler(BaseHandler):
    def __init__(self, credential_file: str = '', config: Optional[Mapping[str, Any]] = None):
        conf = config if config is not None else get_conf()
        self.mode = str(conf.get('integration.auth.mode', 'static_bearer'))
        fingerprint_key = str(conf.get('integration.auth.fingerprint_key', ''))
        tokens, certs = load_credentials(credential_file or str(conf.get('integration.credential.file', '')))
        if self.mode == 'mtls':
            self.extractors = [TlsPeerCertificateExtractor()]
        elif self.mode in _CUSTOM_EXTRACTORS:
            self.extractors = [_CUSTOM_EXTRACTORS[self.mode], TlsPeerCertificateExtractor()]
        else:
            self.extractors = [BearerTokenExtractor(fingerprint_key), TlsPeerCertificateExtractor()]
        mapper = ScopeRoleMapper(_scope_mapping(conf))
        self.registry = AuthenticationProviderRegistry()
        self.registry.register(MtlsProvider(certs))
        for custom_provider in _CUSTOM_PROVIDERS.values():
            self.registry.register(custom_provider)
        if self.mode == 'static_bearer':
            self.registry.register(StaticBearerProvider(
                tokens, str(conf.get('integration.auth.static.hmac_key', ''))))
        elif self.mode == 'oauth2_jwt':
            self.registry.register(JwtBearerProvider(
                str(conf.get('integration.oauth2.issuer', '')),
                str(conf.get('integration.oauth2.audience', '')),
                str(conf.get('integration.oauth2.jwks_uri', '')),
                [a.strip() for a in str(conf.get('integration.oauth2.algorithms', 'RS256')).split(',')], mapper))
        elif self.mode == 'oauth2_introspection':
            self.registry.register(IntrospectionBearerProvider(
                str(conf.get('integration.oauth2.introspection_uri', '')),
                str(conf.get('integration.oauth2.client_id', '')),
                str(conf.get('integration.oauth2.client_secret', '')),
                str(conf.get('integration.oauth2.issuer', '')),
                str(conf.get('integration.oauth2.audience', '')), mapper,
                float(conf.get('integration.oauth2.timeout_seconds', 3)),
                int(conf.get('integration.oauth2.cache_seconds', 30))))
        elif self.mode in _CUSTOM_PROVIDERS:
            self.extractors = [_CUSTOM_EXTRACTORS[self.mode], TlsPeerCertificateExtractor()]
        elif self.mode != 'mtls':
            raise ValueError(f"Unsupported integration authentication mode: {self.mode}")

    def credential_hint(self, request: Any) -> str:
        try:
            credential = self.extractors[0].extract(request)
            return credential.fingerprint if credential else ''
        except AuthenticationError:
            return ''

    async def handle(self, client_ip: str, request: Any) -> Principal:
        credential = None
        for extractor in self.extractors:
            credential = extractor.extract(request)
            if credential:
                break
        if credential is None:
            raise AuthenticationError(AuthFailureReason.MISSING_CREDENTIALS, _FAIL)
        provider_id = 'mtls' if credential.kind == 'mtls' else self.mode
        provider = self.registry.get(provider_id)
        if provider.credential_kind != credential.kind:
            raise AuthenticationError(AuthFailureReason.INVALID_CREDENTIALS, _FAIL)
        return await provider.authenticate(credential, AuthenticationContext(client_ip))


def register_default() -> None:
    HandlerRegistry.register(InterfaceType.INTEGRATION_AUTHENTICATE, ThirdPartyAuthnHandler)


register_default()
