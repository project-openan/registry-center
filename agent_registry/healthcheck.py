# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Container HTTP probe using the service's configured protocol and TLS trust."""

import os
import ssl
from pathlib import Path
from urllib.request import ProxyHandler, HTTPSHandler, build_opener

from common.util.app_config import get_conf, get_root_path


def _path(value: str) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else Path(get_root_path()) / path)


def probe() -> None:
    """Raise on an unsuccessful probe; never disable TLS certificate checks."""
    config = get_conf()
    host = os.environ.get('REGISTRY_HEALTHCHECK_HOST', '127.0.0.1')
    # docker exec/HEALTHCHECK inherits the image environment, not the exports
    # performed by PID 1's entrypoint. Match its platform PORT precedence.
    port = int(os.environ.get('PORT') or config.get('port', 5000))
    secure = str(config.get('enable_https', 'true')).lower() == 'true'
    handlers = [ProxyHandler({})]  # Local probe must not traverse an HTTP proxy.
    if secure:
        context = ssl.create_default_context(cafile=_path(config.get('ssl_ca_certs', 'etc/ssl/trust.cer')))
        cert = os.environ.get('REGISTRY_HEALTHCHECK_CLIENT_CERT')
        key = os.environ.get('REGISTRY_HEALTHCHECK_CLIENT_KEY')
        if str(config.get('verify_client', 'true')).lower() == 'true' and not cert:
            raise ValueError('mTLS probe requires REGISTRY_HEALTHCHECK_CLIENT_CERT and CLIENT_KEY')
        if cert:
            context.load_cert_chain(_path(cert), _path(key) if key else None)
        handlers.append(HTTPSHandler(context=context))
    authority = f'[{host}]' if ':' in host else host
    url = f'{"https" if secure else "http"}://{authority}:{port}/health'
    with build_opener(*handlers).open(url, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f'Health probe returned HTTP {response.status}')
        # The probe needs the status, not a potentially large registry snapshot.


if __name__ == '__main__':
    probe()
