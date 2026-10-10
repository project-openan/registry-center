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
Verified caller identity for the main port.

An AgentCard owner is an authorization anchor, so it must come from a
credential the caller cannot choose:

* ``certificate`` (default) — the CN of the *verified* TLS peer certificate.
  uvicorn does not expose the peer certificate to the ASGI application, so
  :func:`install_tls_peer_cert_injection` copies it from the connection's SSL
  object into ``scope["tls_peer_cert"]`` (same mechanism the integration
  listener uses).
* ``trusted_proxy`` — an identity header written by a reverse proxy that
  terminates mTLS. Only honoured when the *direct* peer address is in
  ``owner.trusted.proxy.ips``; the header is ignored otherwise. This mode
  requires the deployment to keep the application port unreachable except
  through that proxy and to strip the header from external requests.
* ``none`` — no identity is accepted; ownership enforcement is unavailable.

A bare ``X-SSL-Client-DN`` header is client-forgeable and is never used
outside ``trusted_proxy`` mode. Requests whose identity cannot be verified are
reported as unverified, and the write paths reject them instead of falling
back to the header (fail closed).
"""

import importlib
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional, Sequence

from loguru import logger

from common.cert.cert_cn_parser import extract_cn_from_subject, validate_cn

CERTIFICATE = 'certificate'
TRUSTED_PROXY = 'trusted_proxy'
NONE = 'none'
TOKEN = 'token'
KNOWN_SOURCES = (CERTIFICATE, TRUSTED_PROXY, TOKEN, NONE)

#: Config key selecting the identity source.
OWNER_IDENTITY_MODE = 'owner.identity.mode'
#: Config key listing the reverse-proxy addresses allowed to supply the header.
OWNER_TRUSTED_PROXY_IPS = 'owner.trusted.proxy.ips'
#: Config key promoting identity fail-closed warnings to a startup failure.
STRICT_STARTUP = 'startup.strict.identity'

#: ASGI scope key carrying the verified peer certificate.
SCOPE_PEER_CERT = 'tls_peer_cert'
#: ASGI scope key carrying the TCP peer address that opened the connection.
SCOPE_DIRECT_PEER = 'tls_direct_peer'

IDENTITY_HEADER = 'X-SSL-Client-DN'

_PATCH_FLAG = '_registry_peer_cert_patched'


@dataclass(frozen=True)
class CallerIdentity:
    """The caller identity a request may act as.

    ``verified`` is the only value authorization may rely on: it is True only
    when the identity was derived from a credential (peer certificate or a
    trusted proxy's header) rather than from caller-controlled input.
    """

    owner: Optional[str] = None
    source: str = NONE
    verified: bool = False
    detail: str = ''

    def audit_identity(self) -> str:
        """Identity string for audit records; empty unless verified."""
        return self.owner or '' if self.verified else ''


UNVERIFIED = CallerIdentity()


def identity_mode(config: Dict[str, Any]) -> str:
    """Resolve the configured identity source, fail-closed on unknown values."""
    config = config or {}
    raw = str(config.get(OWNER_IDENTITY_MODE, config.get(OWNER_IDENTITY_MODE.replace('.', '_'), CERTIFICATE)) or '').strip().lower()
    if raw in KNOWN_SOURCES:
        return raw
    logger.error(
        f"Unknown {OWNER_IDENTITY_MODE}='{raw}'; expected one of {', '.join(KNOWN_SOURCES)}. "
        "Refusing to trust any caller-supplied identity.")
    return NONE


def trusted_proxy_ips(config: Dict[str, Any]) -> FrozenSet[str]:
    """Parse the trusted reverse-proxy address list."""
    config = config or {}
    raw = str(config.get(OWNER_TRUSTED_PROXY_IPS, config.get(OWNER_TRUSTED_PROXY_IPS.replace('.', '_'), '')) or '')
    return frozenset(item.strip() for item in raw.split(',') if item.strip())


def cn_from_peer_cert(peer_cert: Any) -> Optional[str]:
    """Extract the subject CN from an SSL peer certificate.

    ``ssl.SSLSocket.getpeercert()`` returns a mapping only for certificates
    the TLS stack validated; it returns an empty mapping when verification was
    disabled, which is exactly why an unvalidated connection yields no
    identity here.
    """
    if not peer_cert:
        return None
    if isinstance(peer_cert, dict):
        for rdn in peer_cert.get('subject', ()) or ():
            for key, value in rdn:
                if str(key).lower() in ('commonname', 'cn'):
                    return value
        return None
    if isinstance(peer_cert, str):
        return extract_cn_from_subject(peer_cert)
    return None


def direct_peer_ip(scope: Dict[str, Any]) -> Optional[str]:
    """Return the TCP peer address that opened the connection.

    ``scope["client"]`` is rewritten by uvicorn's proxy-headers middleware when
    a trusted ``X-Forwarded-For`` arrives, so the address captured by
    :func:`install_tls_peer_cert_injection` is required. Missing transport
    evidence must not fall back to the rewritten application address.
    """
    peer = (scope or {}).get(SCOPE_DIRECT_PEER)
    if isinstance(peer, (tuple, list)) and peer:
        return str(peer[0])
    if isinstance(peer, str):
        return peer
    return None


def _validated_owner(cn: Optional[str], mode: str) -> Optional[str]:
    """Validate the CN format in strict mode; returns None when unusable."""
    if not cn:
        return None
    if mode == 'strict' and not validate_cn(cn):
        logger.warning(f"Invalid CN format in verified identity: {cn}")
        return None
    return cn


def resolve_caller_identity(request: Any, config: Dict[str, Any]) -> CallerIdentity:
    """Resolve the caller identity for a request (never trusts bare headers)."""
    scope = getattr(request, 'scope', None) or {}
    source = identity_mode(config)
    validation_mode = str((config or {}).get('owner.validation.mode', 'strict') or 'strict')

    if source == NONE:
        return CallerIdentity(source=NONE, verified=False,
                              detail=f'{OWNER_IDENTITY_MODE}=none')

    if source == TOKEN:
        from common.util.authenticate_util import Principal
        principal = scope.get('registry_principal')
        if not isinstance(principal, Principal) or not principal.identity:
            return CallerIdentity(source=TOKEN, detail='no authenticated token principal')
        # owner is attribution metadata, not an authorization anchor.
        return CallerIdentity(owner=principal.identity, source=TOKEN, verified=True)

    if source == CERTIFICATE:
        cn = _validated_owner(cn_from_peer_cert(scope.get(SCOPE_PEER_CERT)), validation_mode)
        if not cn:
            return CallerIdentity(source=CERTIFICATE, verified=False,
                                  detail='no verified client certificate')
        return CallerIdentity(owner=cn, source=CERTIFICATE, verified=True)

    # trusted_proxy
    allowed = trusted_proxy_ips(config)
    if not allowed:
        return CallerIdentity(source=TRUSTED_PROXY, verified=False,
                              detail=f'{OWNER_TRUSTED_PROXY_IPS} is not configured')
    peer_ip = direct_peer_ip(scope)
    if not peer_ip:
        return CallerIdentity(source=TRUSTED_PROXY, verified=False,
                              detail='direct peer address unavailable')
    if peer_ip not in allowed:
        return CallerIdentity(source=TRUSTED_PROXY, verified=False,
                              detail=f'direct peer {peer_ip} is not a trusted proxy')
    try:
        header_value = request.headers.get(IDENTITY_HEADER)
    except Exception:  # pragma: no cover - defensive
        header_value = None
    cn = _validated_owner(extract_cn_from_subject(header_value) if header_value else None,
                          validation_mode)
    if not cn:
        return CallerIdentity(source=TRUSTED_PROXY, verified=False,
                              detail=f'trusted proxy sent no usable {IDENTITY_HEADER}')
    return CallerIdentity(owner=cn, source=TRUSTED_PROXY, verified=True)


def describe_identity_configuration(config: Dict[str, Any]) -> str:
    """Human-readable identity configuration summary for startup logs."""
    source = identity_mode(config)
    if source == TRUSTED_PROXY:
        ips = trusted_proxy_ips(config)
        detail = f"trusted_proxy={','.join(sorted(ips)) or '<unset>'}"
    elif source == CERTIFICATE:
        detail = f"verify_client={str((config or {}).get('verify_client', 'true')).lower()}"
    elif source == TOKEN:
        detail = 'standards-first authentication provider (integration.auth.* policy)'
    else:
        detail = 'no verifiable identity source'
    return f"owner identity source: {source} ({detail})"


def identity_configuration_warnings(config: Dict[str, Any]) -> Sequence[str]:
    """Fail-closed configuration problems worth surfacing at startup."""
    warnings = []
    isolation = str((config or {}).get('owner.isolation.enabled', 'false')).lower() == 'true'
    source = identity_mode(config)
    if not isolation:
        return warnings
    if source == CERTIFICATE:
        if str((config or {}).get('enable_https', 'true')).lower() == 'false':
            warnings.append(
                "owner.isolation.enabled=true with owner.identity.mode=certificate but "
                "enable_https=false: an HTTP listener cannot verify TLS peer certificates. "
                "Enable HTTPS with mTLS or configure a verified trusted proxy identity source.")
        if str((config or {}).get('verify_client', 'true')).lower() == 'false':
            warnings.append(
                "owner.isolation.enabled=true with owner.identity.mode=certificate but "
                "verify_client=false: no peer certificate is validated, so ownership "
                "changes will be rejected with 401. Enable mTLS or configure "
                f"{OWNER_IDENTITY_MODE}={TRUSTED_PROXY} plus {OWNER_TRUSTED_PROXY_IPS}.")
    elif source == TRUSTED_PROXY:
        if not trusted_proxy_ips(config):
            warnings.append(
                f"owner.isolation.enabled=true with {OWNER_IDENTITY_MODE}=trusted_proxy but "
                f"{OWNER_TRUSTED_PROXY_IPS} is empty: every identity header is ignored and "
                "ownership changes will be rejected with 401.")
    elif source == TOKEN:
        if str(config.get('integration.auth.mode', 'static_bearer')) == 'mtls':
            warnings.append('owner.identity.mode=token requires a token provider, not integration.auth.mode=mtls')
    else:
        warnings.append(
            "owner.isolation.enabled=true but owner.identity.mode=none: no caller identity "
            "can be verified, so ownership changes will be rejected with 401.")
    return warnings


def strict_startup_failures(config: Dict[str, Any]) -> Sequence[str]:
    """Identity problems that must stop startup when strict startup is enabled.

    ``startup.strict.identity=true`` promotes the fail-closed warnings above to a
    hard failure, so a production deployment cannot come up in a state where every
    ownership write is rejected with 401 while the service looks healthy. It is off
    by default so development deployments keep starting with a warning.
    """
    config = config or {}
    raw = config.get(STRICT_STARTUP, config.get(STRICT_STARTUP.replace('.', '_'), 'false'))
    if str(raw).strip().lower() != 'true':
        return []
    return list(identity_configuration_warnings(config))


# ---------------------------------------------------------------------------
# Peer-certificate injection
# ---------------------------------------------------------------------------

def _wrap_run_asgi(original):
    async def _run_asgi_with_peer_cert(self, app):
        peer_cert = None
        direct_peer = None
        try:
            transport = getattr(self, 'transport', None)
            ssl_object = transport.get_extra_info('ssl_object') if transport else None
            if ssl_object is not None:
                peer_cert = ssl_object.getpeercert()
            if transport is not None:
                direct_peer = transport.get_extra_info('peername')
        except Exception as e:  # pragma: no cover - defensive
            logger.debug(f"Failed to read TLS peer certificate: {e}")
        scope = getattr(self, 'scope', None)
        if isinstance(scope, dict):
            scope[SCOPE_PEER_CERT] = peer_cert
            scope[SCOPE_DIRECT_PEER] = direct_peer
        return await original(self, app)

    setattr(_run_asgi_with_peer_cert, _PATCH_FLAG, True)
    return _run_asgi_with_peer_cert


def install_tls_peer_cert_injection() -> Sequence[str]:
    """Patch uvicorn's HTTP cycles so requests carry the peer certificate.

    Idempotent. Patches every available HTTP implementation (h11 and, when
    installed, httptools) because uvicorn picks the protocol automatically.
    """
    patched = []
    for module_name in ('uvicorn.protocols.http.h11_impl',
                        'uvicorn.protocols.http.httptools_impl'):
        try:
            module = importlib.import_module(module_name)
        except Exception:  # pragma: no cover - optional dependency
            continue
        cycle = getattr(module, 'RequestResponseCycle', None)
        if cycle is None:  # pragma: no cover - defensive
            continue
        if getattr(cycle.run_asgi, _PATCH_FLAG, False):
            patched.append(module_name)
            continue
        cycle.run_asgi = _wrap_run_asgi(cycle.run_asgi)
        patched.append(module_name)
    return patched
