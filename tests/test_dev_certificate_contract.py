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

"""Shared development certificate contract; mirrored in both services."""

import os
import ssl
import sys
import threading
import time

import httpx
import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI

import generate_selfsign_cert as cli
from common.cert.certificate_generator import CertificateGenerator
from common.util import conf_obj

PASSWORD = "Test-only!Password1"


def test_generated_signing_bundle_works_with_real_agent_card_signer(tmp_path, monkeypatch):
    import base64
    import json
    from a2a.types import AgentCard
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from google.protobuf.json_format import MessageToDict
    from agent_registry.agent_registry.agent_card_signer import AgentCardSigner
    from common.util.app_config import load_conf_as_dict
    from pathlib import Path

    # Exercise the public template's real paths, not hardcoded test-only aliases.
    template = load_conf_as_dict(str(Path(__file__).parents[1] / "etc/conf/server.conf.example"))
    monkeypatch.chdir(tmp_path)
    run_cli(monkeypatch, tmp_path / "etc/sign_cert", "dataSigning")
    signer = AgentCardSigner(
        cert_path=template["jwk_cert_path"],
        private_key_path=template["jwk_private_key_path"],
        password_path=template["jwk_private_key_password"],
    )
    card = AgentCard(name="test-agent", version="1.0")
    signed = signer.sign_agent_card(card)
    assert len(signed.signatures) == 1
    signature = signed.signatures[0].signature
    public_key = x509.load_pem_x509_certificate(Path(template["jwk_cert_path"]).read_bytes()).public_key()
    from a2a.utils.signing import create_signature_verifier
    create_signature_verifier(lambda kid, jku: public_key, ["RS256"])(signed)


def run_cli(monkeypatch, directory, usage="serverAuth", *options):
    monkeypatch.setattr(sys, "argv", ["generate_selfsign_cert", str(directory), usage, *options])
    monkeypatch.setattr(cli, "input_password_with_validation", lambda prompt: PASSWORD)
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0


@pytest.mark.parametrize("usage,name", [
    ("serverAuth", name) for name in
    ("server_RSA.cer", "server_key_RSA.pem", "server.cer", "trust.cer",
     "server_key.pem", "cert_pwd", "server_key_nopass.pem")
] + [("dataSigning", name) for name in ("sign.cer", "sign_key.pem", "cert_pwd")])
def test_cli_preflights_every_output_before_prompt(tmp_path, monkeypatch, usage, name):
    existing = tmp_path / name
    existing.write_bytes(b"existing credential")
    options = ["--plain-key"] if usage == "serverAuth" else []
    monkeypatch.setattr(sys, "argv", ["generate_selfsign_cert", str(tmp_path), usage, *options])
    monkeypatch.setattr(cli, "input_password_with_validation", lambda _: pytest.fail("unexpected prompt"))
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    assert existing.read_bytes() == b"existing credential"
    assert list(tmp_path.iterdir()) == [existing]


def test_export_refuses_existing_password_without_partial_bundle(tmp_path):
    assert CertificateGenerator().generate_self_signed_cert(str(tmp_path), "serverAuth", PASSWORD)
    (tmp_path / "cert_pwd").write_bytes(b"existing password")
    original = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(FileExistsError):
        cli._write_deploy_files(str(tmp_path), PASSWORD, plain_key=True)
    assert original == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_cli_rejects_password_that_tls_loader_would_treat_as_ciphertext(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["generate_selfsign_cert", str(tmp_path), "serverAuth"])
    monkeypatch.setattr(cli, "input_password_with_validation", lambda _: "enc:v1:Test-only!Password1")
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["demo-client.cer", "demo-client.key"])
def test_client_issuance_refuses_existing_credentials(tmp_path, monkeypatch, name):
    run_cli(monkeypatch, tmp_path)
    (tmp_path / name).write_bytes(b"existing client credential")
    original = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(FileExistsError):
        cli.issue_client_cert(str(tmp_path), "demo")
    assert original == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_client_name_cannot_escape_directory(tmp_path):
    with pytest.raises(ValueError, match="name"):
        cli.issue_client_cert(str(tmp_path), "../outside")
    assert not list(tmp_path.iterdir())


def test_dangling_symlinks_are_not_overwritten(tmp_path):
    link = tmp_path / "cert_pwd"
    try:
        link.symlink_to(tmp_path / "missing")
    except OSError:
        pytest.skip("Creating symlinks requires OS privileges")
    with pytest.raises(FileExistsError):
        cli._require_new_paths([str(link)])
    assert link.is_symlink()


def test_bundle_cleans_only_its_new_files_when_a_race_occurs(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    real_open = os.open

    def racing_open(path, flags, mode):
        if path == str(second):
            second.write_bytes(b"concurrent writer")
        return real_open(path, flags, mode)

    monkeypatch.setattr(cli.os, "open", racing_open)
    with pytest.raises(FileExistsError):
        cli._write_new_files({str(first): b"new", str(second): b"new"})
    assert not first.exists()
    assert second.read_bytes() == b"concurrent writer"


def test_signing_bundle_is_separate_and_loadable(tmp_path, monkeypatch, capsys):
    run_cli(monkeypatch, tmp_path, "dataSigning")
    assert PASSWORD not in capsys.readouterr().out
    assert (tmp_path / "cert_pwd").read_bytes() == PASSWORD.encode()
    cert = x509.load_pem_x509_certificate((tmp_path / "sign.cer").read_bytes())
    key = serialization.load_pem_private_key((tmp_path / "sign_key.pem").read_bytes(), PASSWORD.encode())
    assert cert.public_key().public_numbers() == key.public_key().public_numbers()
    assert not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert not (tmp_path / "server.cer").exists()
    with pytest.raises(ValueError, match="cannot issue"):
        cli.issue_client_cert(str(tmp_path), "invalid")
    assert not (tmp_path / "invalid-client.key").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows requires service account ACLs")
def test_generated_private_files_are_owner_only(tmp_path, monkeypatch):
    run_cli(monkeypatch, tmp_path, "serverAuth", "--plain-key")
    cli.issue_client_cert(str(tmp_path), "demo")
    for name in ("server_key_RSA.pem", "server_key.pem", "server_key_nopass.pem", "cert_pwd", "demo-client.key"):
        assert (tmp_path / name).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("mutual_tls", [False, True])
def test_defaults_boot_real_uvicorn_https(tmp_path, monkeypatch, mutual_tls):
    """Actual default paths and password loader feed a live HTTPS REST endpoint."""
    directory = tmp_path / "etc" / "ssl"
    run_cli(monkeypatch, directory)
    monkeypatch.setattr(conf_obj, "ROOT_PATH", str(tmp_path))
    settings = conf_obj.ConfObj.as_object({"verify_client": "true" if mutual_tls else "false"})
    assert conf_obj.DEFAULT_KEY_PASSWORD == "etc/ssl/cert_pwd"
    try:
        from common.util.ssl_config import load_cert_password
    except ModuleNotFoundError as exc:
        if exc.name != "common.util.ssl_config":
            raise
        from common.util.conf_util import load_cert_password
    password = load_cert_password(settings.ssl_keyfile_password)
    assert password == PASSWORD.encode()
    from common.cert import cert_validater as certificate_validator

    test_config = tmp_path / "server.conf"
    test_config.write_text("enable_https=true\n", encoding="utf-8")
    monkeypatch.setattr(certificate_validator, "CONFIG_FILE_PATH", str(test_config))
    assert certificate_validator.CertValidator(settings).validate().is_valid
    context = ssl.create_default_context(cafile=settings.ssl_ca_certs)
    if mutual_tls:
        client_cert, client_key = cli.issue_client_cert(str(directory), "smoke")
        context.load_cert_chain(client_cert, client_key)
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="error",
        ssl_certfile=settings.ssl_certfile, ssl_keyfile=settings.ssl_keyfile,
        ssl_keyfile_password=password.decode(), ssl_ca_certs=settings.ssl_ca_certs,
        ssl_cert_reqs=settings.verify_client,
    )
    server = uvicorn.Server(config)
    sock = config.bind_socket()
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        url = f"https://127.0.0.1:{sock.getsockname()[1]}/health"
        with httpx.Client(verify=context, trust_env=False, timeout=3) as client:
            response = client.get(url)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        if mutual_tls:
            with httpx.Client(verify=ssl.create_default_context(cafile=settings.ssl_ca_certs),
                              trust_env=False, timeout=3) as client:
                with pytest.raises(httpx.TransportError):
                    client.get(url)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
