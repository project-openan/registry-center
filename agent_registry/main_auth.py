# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Optional main-port Token policy reusing the integration authentication ports.

Credentials/policies are shared; built-in providers and their async transports
are created separately for each listener. Business-registered custom providers
remain externally owned and shared; they must support concurrent listener use.
Existing certificate/proxy modes retain their behavior. Owner-scoped writes
continue through the existing guard.
"""

from fastapi import HTTPException
from starlette.responses import JSONResponse

from agent_registry.identity import TOKEN, identity_mode
from common.util.authenticate_util import CallerRole, Principal


class MainTokenPolicy:
    def __init__(self):
        self.handler = None

    async def start(self, config: dict):
        if identity_mode(config) != TOKEN:
            return
        from agent_registry.integration.authn import ThirdPartyAuthnHandler
        if str(config.get('integration.auth.mode', 'static_bearer')) == 'mtls':
            raise ValueError('Token identity requires a token authentication provider')
        self.handler = ThirdPartyAuthnHandler(config=config)

    async def close(self):
        handler, self.handler = self.handler, None
        if handler is not None:
            await handler.aclose()

    async def authenticate(self, request):
        from agent_registry.integration.app import authenticate_request
        if self.handler is None:
            raise HTTPException(503, 'Main authentication provider unavailable')
        principal = await authenticate_request(request, self.handler)
        if not isinstance(principal, Principal) or not principal.identity or principal.role is None:
            raise HTTPException(503, 'Authentication provider returned no verified identity')
        self._authorize(request, principal)
        request.scope['registry_principal'] = principal

    @staticmethod
    def _authorize(request, principal):
        if principal.role == CallerRole.NMS_OSS:
            return
        path = request.url.path.rstrip('/')
        base = '/rest/v1/registry-center'
        cards = base + '/agent-cards'
        # Non-administrative main-port access is deliberately limited to public
        # discovery and owner-scoped card writes. Subscriptions, management,
        # registration metadata and graph APIs use the existing integration
        # routes with their operation-specific role policy, or NMS credentials.
        discovery = request.method in {'GET', 'HEAD'} and (
            path == cards or path.startswith(cards + '/') and path.count('/') == 6)
        semantic = request.method == 'POST' and path == cards + '/semantic-query'
        vendor_write = principal.role == CallerRole.VENDOR_AGENT and (
            request.method == 'POST' and path == cards
            or request.method in {'PUT', 'DELETE'} and path.startswith(cards + '/') and path.count('/') == 6
            or request.method == 'POST' and path.startswith(cards + '/')
            and path.count('/') == 7 and path.endswith('/heartbeat'))
        if not (discovery or semantic or vendor_write):
            raise HTTPException(403, 'Use an authorized integration operation or administrator credential')


main_token_policy = MainTokenPolicy()


async def main_token_middleware(request, call_next, config):
    path = request.url.path
    protected = path == '/rest/v1/registry-center' or path.startswith('/rest/v1/registry-center/')
    if (identity_mode(config) != TOKEN or not protected or request.method == 'OPTIONS'
            or path == '/rest/v1/registry-center/keys'):
        return await call_next(request)
    try:
        await main_token_policy.authenticate(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code,
                            content={'errors': {'error': [{'errorMessage': exc.detail}]}},
                            headers=exc.headers)
    return await call_next(request)
