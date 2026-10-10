# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Fresh child process, full FastAPI lifespan and real HTTP/HTTPS CRUD.

Copies only Python sources/public templates; no operator configs or credentials.
This is not a Docker or MySQL acceptance test.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import time

import httpx
import pytest
from test_transport_identity_contract import _materials
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "test-only-process-vendor-token"


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_fresh_service_authenticated_crud_and_keys(protocol, tmp_path):
    workspace = tmp_path / "service"
    for package in ("agent_registry", "common"):
        for path in (ROOT / package).rglob("*.py"):
            target = workspace / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    conf_dir = workspace / "etc/conf"
    conf_dir.mkdir(parents=True)
    for name in ("server.conf", "persistence.conf"):
        shutil.copyfile(ROOT / "etc/conf" / (name + ".example"), conf_dir / name)
        shutil.copyfile(ROOT / "etc/conf" / (name + ".example"), conf_dir / (name + ".example"))
    for name in ("server.properties", "log_config.conf"):
        shutil.copyfile(ROOT / "etc/conf" / name, conf_dir / name)
    secret = "test-only-process-hmac"
    digest = hmac.new(secret.encode(), TOKEN.encode(), hashlib.sha256).hexdigest()
    (conf_dir / "integration_credentials.conf").write_text(
        f"credential.vendor.identity=test-vendor\ncredential.vendor.role=vendor_agent\n"
        f"credential.vendor.token_hash={digest}\n")
    cert, key, pwd, private = _materials(tmp_path)
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.BestAvailableEncryption(b"Process#2026")))
    pwd.write_text("Process#2026")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("REGISTRY_", "DB_", "MYSQL_", "INTEGRATION_", "PERSISTENCE_"))}
    env.update(PYTHONPATH=str(workspace), PYTHON_DOTENV_DISABLED="1", REGISTRY_ENABLE_HTTPS=str(protocol == "https").lower(),
               REGISTRY_VERIFY_CLIENT="false", REGISTRY_OWNER_IDENTITY_MODE="token",
               REGISTRY_INTEGRATION_AUTH_MODE="static_bearer", INTEGRATION_FINGERPRINT_KEY="process-test-fingerprint",
               INTEGRATION_TOKEN_HMAC_KEY=secret, REGISTRY_AGENT_APPROVAL_ENABLED="false",
               REGISTRY_SIGNATURE_VALIDATION_ENABLED="false", PERSISTENCE_MODE="file",
               REGISTRY_JWK_CERT_PATH=str(cert), REGISTRY_JWK_PRIVATE_KEY_PATH=str(key),
               REGISTRY_JWK_PRIVATE_KEY_PASSWORD=str(pwd), REGISTRY_HEARTBEAT_ENABLED="false",
               REGISTRY_SSL_CERTFILE=str(cert), REGISTRY_SSL_KEYFILE=str(key),
               REGISTRY_SSL_KEYFILE_PASSWORD=str(pwd), REGISTRY_SSL_CA_CERTS=str(tmp_path / "not-needed-ca.cer"))
    code = """
import os, sys, uvicorn
from common.util.app_config import get_conf
conf = get_conf()
options = {}
if conf['enable_https'] == 'true':
    from common.util.conf_obj import ConfObj
    from common.cert.cert_validater import CertValidator
    result = CertValidator(ConfObj.as_object(conf)).validate()
    assert result.is_valid, result.message
    options = dict(ssl_certfile=conf['ssl_certfile'], ssl_keyfile=conf['ssl_keyfile'],
                   ssl_keyfile_password='Process#2026')
uvicorn.run('agent_registry.server:app', host='127.0.0.1', port=int(sys.argv[1]),
            log_level='warning', **options)
"""
    with (tmp_path / "service.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-c", code, str(port)], cwd=workspace,
                                   env=env, stdout=log, stderr=log)
        try:
            verify = ssl.create_default_context(cafile=str(cert)) if protocol == "https" else True
            with httpx.Client(base_url=f"{protocol}://127.0.0.1:{port}", verify=verify, trust_env=False) as client:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        pytest.fail((tmp_path / "service.log").read_text(encoding="utf-8")[-4000:])
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() > deadline:
                        pytest.fail("Isolated service readiness timeout; see service.log")
                    time.sleep(0.1)
                path = "/rest/v1/registry-center/agent-cards"
                assert client.get(path).status_code == 401
                headers = {"Authorization": "Bearer " + TOKEN}
                card = dict(name="ProcessAgent", provider={"organization": "ProcessOrg"},
                            description="Isolated service", version="1.0", skills=[])
                response = client.post(path, headers=headers, json={"agentCards": [card]})
                assert response.status_code == 201, response.text
                exact = path + "/ProcessOrg/ProcessAgent"
                response = client.get(exact, headers=headers)
                assert response.status_code == 200 and len(response.json()["agentCards"]) == 1, response.text
                assert response.json()["agentCards"][0]["signatures"]
                assert client.get("/rest/v1/registry-center/keys").status_code == 200
                assert client.put(exact, headers=headers, json={"agentCards": [dict(card, description="Updated")]}).status_code == 200
                assert client.delete(exact, headers=headers).status_code == 200
                assert client.get(exact, headers=headers).json()["agentCards"] == []
        finally:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
