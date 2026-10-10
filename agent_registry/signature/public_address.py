# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Public key discovery is independent of the backend listener's protocol."""

from urllib.parse import urlsplit


def registry_jku_url(config: dict) -> str:
    explicit = str(config.get("registry.sign.jwks_url", "")).strip()
    base = str(config.get("registry.public.base_url", "")).strip().rstrip("/")
    if explicit:
        candidate = explicit
    elif base:
        candidate = base + "/rest/v1/registry-center/keys"
    else:
        host = str(config.get("ip", "127.0.0.1"))
        if host in {"0.0.0.0", "::", ""}:
            return ""  # Bind addresses are not public key-discovery addresses.
        if str(config.get("enable_https", "true")).lower() != "true":
            return ""  # HTTP consumers must pre-provision trusted keys.
        authority = f"[{host}]" if ":" in host else host
        candidate = f"https://{authority}:{config.get('port', 5000)}/rest/v1/registry-center/keys"
    parsed = urlsplit(candidate)
    # Accessing port rejects malformed/non-numeric/out-of-range authorities.
    _ = parsed.port
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.hostname in {"0.0.0.0", "::"} or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Registry public key URL must be a public HTTP(S) URL without credentials/query/fragment")
    if parsed.scheme == "http":
        if explicit:
            raise ValueError("registry.sign.jwks_url requires HTTPS; use pinned keys for HTTP")
        return ""
    return candidate
