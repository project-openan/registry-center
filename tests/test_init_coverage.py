# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Interactive wizard + non-interactive validation coverage tests
(``agent_registry/init.py``).

Every test re-roots the wizard at ``tmp_path`` by patching
``agent_registry.init.get_root_path``, so no repository file (``etc/conf/server.conf``,
``etc/conf/persistence.conf``, ``etc/conf/cipher.key``) is ever read or written.

Prompts are driven by a strict fake ``input``: it consumes a pre-declared answer list
and raises if the wizard asks more questions than expected, so a prompt added or
removed by a regression fails the test instead of hanging.

Certificates are generated on the fly (same helper style as
``tests/test_integration_cert_auth.py``) under the same ``tmp_path``.
"""

import datetime
import json
import os

import pytest
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

import agent_registry.init as init_module
from agent_registry.init import InitCommand, main, validate_non_interactive_config
from common.cert.x509_obj import X509Obj
from common.util import cipher_util
from common.util.validation_result import ValidationResult


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _feed(monkeypatch, answers):
    """Replace input() with a strict queue; returns the queue for leftover checks."""
    queue = list(answers)

    def fake_input(prompt=""):
        if not queue:
            raise AssertionError(f"wizard asked for more input than expected: {prompt!r}")
        return queue.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    return queue


@pytest.fixture
def wizard(tmp_path, monkeypatch):
    """An InitCommand whose etc/conf lives under tmp_path.

    The shared password prompt is replaced by a guard that fails loudly: it reads
    from the real terminal (getpass), so an unexpected password prompt must break the
    test instead of blocking the suite.
    """
    monkeypatch.setattr(init_module, "get_root_path", lambda: str(tmp_path))
    monkeypatch.setattr(init_module, "input_password_with_validation",
                        lambda prompt: pytest.fail(f"unexpected password prompt: {prompt!r}"))
    (tmp_path / "etc" / "conf").mkdir(parents=True)
    return InitCommand()


@pytest.fixture
def wizard_with_config(wizard, tmp_path):
    """Wizard with a pre-existing server.conf (drives the "default" branches)."""
    def _write(content):
        (tmp_path / "etc" / "conf" / "server.conf").write_text(content, encoding="utf-8")
        wizard.existing_config = wizard._parse_config_file(wizard.config_file)
        return wizard
    return _write


def _read(path):
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read()


# --------------------------------------------------------------------------
# init_command
# --------------------------------------------------------------------------

class TestInitCommandFlow:
    def test_defaults_for_https_and_signing_flags(self, wizard, monkeypatch, capsys):
        """TC-INIT-001 | 空回车沿用既有默认值：HTTPS/签名保持开启，签名校验关闭

        输入: ip=""、port=""、enable_https=""（默认 true）、registry.sign.enabled=""（默认 true）、
              signature_validation_enabled="n"、agent_approval_enabled=""
        预期输出: TLS/签名/JWK 配置函数各被调用 1 次；server.conf 中
              enable_https=true、registry.sign.enabled=true、signature_validation_enabled=false、
              agent_approval_enabled=false，且 ip/port 取默认 127.0.0.1/5000
        断言点: 三个分支函数调用次数；落盘文件逐项断言；输入队列被完全消费
        防回归: 若"空输入=关闭"或默认值分支被改写，部署会意外停用 TLS/签名，本用例失败
        """
        tls = {"ssl_certfile": "/tls/cert.cer", "verify_client": "true"}
        sign = {"sign_certfile": "/sign/cert.cer"}
        jwk = {"jwk_cert_path": "/jwk/cert.cer"}
        tls_mock = monkeypatch.setattr(wizard, "config_tls_cert", lambda: dict(tls))
        sign_mock = monkeypatch.setattr(wizard, "config_sign_cert", lambda: dict(sign))
        jwk_mock = monkeypatch.setattr(wizard, "config_jwk_cert", lambda: dict(jwk))
        monkeypatch.setattr(wizard, "config_persistence", lambda: {"persistence.mode": "file"})
        queue = _feed(monkeypatch, ["", "", "", "", "n", ""])

        wizard.init_command()

        assert queue == []
        content = _read(wizard.config_file)
        assert "ip=127.0.0.1" in content
        assert "port=5000" in content
        assert "enable_https=true" in content
        assert "registry.sign.enabled=true" in content
        assert "signature_validation_enabled=false" in content
        assert "agent_approval_enabled=false" in content
        assert "ssl_certfile=/tls/cert.cer" in content
        assert "sign_certfile=/sign/cert.cer" in content
        assert "jwk_cert_path=/jwk/cert.cer" in content
        assert "persistence.mode=file" in _read(wizard.persistence_config_file)
        assert "Signature validation disabled" in capsys.readouterr().out

    def test_disabled_stages_skip_certificate_wizards(self, wizard, monkeypatch, capsys):
        """TC-INIT-002 | 关闭 HTTPS/签名时跳过对应证书向导，校验项回落默认

        输入: enable_https="n"、registry.sign.enabled="n"、signature_validation_enabled=""、
              agent_approval_enabled="y"
        预期输出: config_tls_cert/config_sign_cert/config_jwk_cert 均不被调用；
              server.conf 中 enable_https=false、registry.sign.enabled=false、
              signature_validation_enabled=true（默认）、agent_approval_enabled=true
        断言点: 三个向导函数的调用次数为 0；落盘四项配置；提示语含"set to default: true"
        防回归: 若关闭开关后仍要求输入证书路径，无人值守配置会卡在交互提示，本用例失败
        """
        calls = []
        monkeypatch.setattr(wizard, "config_tls_cert",
                            lambda: calls.append("tls") or {})
        monkeypatch.setattr(wizard, "config_sign_cert",
                            lambda: calls.append("sign") or {})
        monkeypatch.setattr(wizard, "config_jwk_cert",
                            lambda: calls.append("jwk") or {})
        monkeypatch.setattr(wizard, "config_persistence", lambda: {"persistence.mode": "file"})
        _feed(monkeypatch, ["", "", "n", "n", "", "y"])

        wizard.init_command()

        assert calls == []
        content = _read(wizard.config_file)
        assert "enable_https=false" in content
        assert "registry.sign.enabled=false" in content
        assert "signature_validation_enabled=true" in content
        assert "agent_approval_enabled=true" in content
        assert "Signature validation set to default: true" in capsys.readouterr().out

    def test_disabling_approval_is_blocked_by_pending_agents(self, wizard_with_config,
                                                             monkeypatch, capsys):
        """TC-INIT-003 | 存在待审核 Agent 时禁止关闭审批，进程以 1 退出

        输入: 既有配置 agent_approval_enabled=true，审批输入 "n"，
              注册表存在 1 个 status=registered 的 Agent
        预期输出: SystemExit(1)；提示"不能直接关闭"与待审核数量；不写 server.conf
        断言点: 异常类型与退出码；提示中的数量；文件未生成（未发生半截配置）
        防回归: 若该保护被删除，待审核卡片会直接可发现（越权发布），本用例失败
        """
        wizard = wizard_with_config("agent_approval_enabled=true\n")
        agent = _agent_card("pending-agent", "org-1")
        registry = _fake_registry([agent], status="registered")
        import agent_registry.registry_instance as registry_instance
        monkeypatch.setattr(registry_instance, "get_registry", lambda: registry)
        monkeypatch.setattr(wizard, "config_persistence", lambda: {"persistence.mode": "file"})
        _feed(monkeypatch, ["", "", "n", "n", "", "n"])

        with pytest.raises(SystemExit) as excinfo:
            wizard.init_command()

        out = capsys.readouterr().out
        assert excinfo.value.code == 1
        assert "Approval function is enabled, cannot disable directly!" in out
        assert "There are 1 agents in 'registered' status" in out
        # 退出发生在保存之前：既有配置保持原样，未被本次向导改写
        assert _read(wizard.config_file) == "agent_approval_enabled=true\n"
        assert not os.path.exists(wizard.persistence_config_file)

    def test_disabling_approval_allowed_without_pending_agents(self, wizard_with_config,
                                                              monkeypatch, capsys):
        """TC-INIT-004 | 无待审核 Agent 时允许关闭审批

        输入: 既有配置 agent_approval_enabled=true，审批输入 "n"，
              注册表所有 Agent 均为 published
        预期输出: 不退出；server.conf 中 agent_approval_enabled=false
        断言点: 落盘值；提示语"Approval function disabled"；find_all 被调用
        防回归: 若保护逻辑对 published 也拦截，正常下线流程被阻断，本用例失败
        """
        wizard = wizard_with_config("agent_approval_enabled=true\n")
        registry = _fake_registry([_agent_card("live-agent", "org-1")], status="published")
        import agent_registry.registry_instance as registry_instance
        monkeypatch.setattr(registry_instance, "get_registry", lambda: registry)
        monkeypatch.setattr(wizard, "config_persistence", lambda: {"persistence.mode": "file"})
        _feed(monkeypatch, ["", "", "n", "n", "", "n"])

        wizard.init_command()

        assert "agent_approval_enabled=false" in _read(wizard.config_file)
        assert "Approval function disabled" in capsys.readouterr().out
        registry.find_all.assert_called_once_with()


    def test_explicit_yes_answers_enable_all_stages(self, wizard, monkeypatch, capsys):
        """TC-INIT-050 | 显式 "y" 开启 HTTPS/签名/签名校验，"n" 在无待审核时关闭审批

        输入: enable_https="y"、registry.sign.enabled="y"、signature_validation_enabled="y"、
              agent_approval_enabled="n"（既有配置无审批项 → 当前值 false）
        预期输出: server.conf 中三项均为 true、agent_approval_enabled=false；
              TLS/签名/JWK 向导各调用一次；提示含 "Signature validation enabled"
              与 "Approval function disabled"
        断言点: 落盘四项；三个向导调用次数；两处提示语
        防回归: 若 'y' 分支被删除（只认 "yes"/大小写敏感），显式开启会被静默忽略，本用例失败
        """
        calls = []
        monkeypatch.setattr(wizard, "config_tls_cert", lambda: calls.append("tls") or {})
        monkeypatch.setattr(wizard, "config_sign_cert", lambda: calls.append("sign") or {})
        monkeypatch.setattr(wizard, "config_jwk_cert", lambda: calls.append("jwk") or {})
        monkeypatch.setattr(wizard, "config_persistence", lambda: {"persistence.mode": "file"})
        _feed(monkeypatch, ["", "", "y", "y", "y", "n"])

        wizard.init_command()

        content = _read(wizard.config_file)
        assert "enable_https=true" in content
        assert "registry.sign.enabled=true" in content
        assert "signature_validation_enabled=true" in content
        assert "agent_approval_enabled=false" in content
        assert calls == ["tls", "sign", "jwk"]
        out = capsys.readouterr().out
        assert "Signature validation enabled" in out
        assert "Approval function disabled" in out


def _agent_card(name, organization):
    from a2a.types import AgentCard
    card = AgentCard(name=name, provider={"organization": organization,
                                         "url": "https://example.test"},
                     description="d", version="1.0.0", skills=[])
    return card


def _fake_registry(agents, status):
    from unittest.mock import MagicMock
    registry = MagicMock()
    registry.find_all.return_value = agents
    registry.get_status.return_value = status
    return registry


# --------------------------------------------------------------------------
# certificate wizards
# --------------------------------------------------------------------------

class TestCertificateWizards:
    def test_tls_wizard_saves_new_key_password(self, wizard, monkeypatch):
        """TC-INIT-005 | 私钥变更时重新采集口令并写入口令文件

        输入: ssl_certfile=/tls/cert.cer、ssl_keyfile=/tls/key.pem（与默认值不同）、
              ssl_ca_certs=/tls/ca.cer、ssl_cert_certs=""（可选）、verify_client="n"
        预期输出: ssl_keyfile_password 为 save_password_file 的返回值；
              verify_client="false"；ssl_cert_certs=""
        断言点: 整个返回字典；save_password_file 的入参（密码, 私钥路径）；
              input_password 调用次数
        防回归: 若私钥变更后沿用旧口令文件，新私钥会被错误口令加载，本用例失败
        """
        monkeypatch.setattr(wizard, "validate_cert_path", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "validate_file_permissions", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "input_password", lambda prompt: "Pass#2026")
        saved = []
        monkeypatch.setattr(wizard, "save_password_file",
                            lambda password, key: saved.append((password, key)) or "/tls/key_pwd")
        _feed(monkeypatch, ["/tls/cert.cer", "/tls/key.pem", "/tls/ca.cer", "", "n"])

        config = wizard.config_tls_cert()

        assert config == {
            "ssl_certfile": "/tls/cert.cer",
            "ssl_keyfile": "/tls/key.pem",
            "ssl_ca_certs": "/tls/ca.cer",
            "ssl_cert_certs": "",
            "ssl_keyfile_password": "/tls/key_pwd",
            "verify_client": "false",
        }
        assert saved == [("Pass#2026", "/tls/key.pem")]

    def test_tls_wizard_keeps_existing_password_and_verify_default(self, wizard_with_config,
                                                                  monkeypatch):
        """TC-INIT-006 | 私钥未变更时沿用旧口令文件；verify_client 空输入取默认值

        输入: 既有配置含 ssl_keyfile_password=/old/pwd 与 verify_client=false，
              四个路径均空输入（取默认），verify_client 空输入
        预期输出: ssl_keyfile_password 保持 /old/pwd；verify_client 保持 "false"
        断言点: 两个字段；save_password_file 未被调用
        防回归: 若未变更私钥也重写口令文件，口令文件可能被意外清空，本用例失败
        """
        wizard = wizard_with_config(
            "ssl_certfile=/tls/cert.cer\n"
            "ssl_keyfile=/tls/key.pem\n"
            "ssl_keyfile_password=/old/pwd\n"
            "ssl_ca_certs=/tls/ca.cer\n"
            "verify_client=false\n")
        monkeypatch.setattr(wizard, "validate_cert_path", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "validate_file_permissions", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "save_password_file",
                            lambda *a, **k: pytest.fail("password file must not be rewritten"))
        _feed(monkeypatch, ["", "", "", "", ""])

        config = wizard.config_tls_cert()

        assert config["ssl_keyfile_password"] == "/old/pwd"
        assert config["verify_client"] == "false"
        assert config["ssl_certfile"] == "/tls/cert.cer"

    def test_tls_wizard_verify_client_yes(self, wizard, monkeypatch):
        """TC-INIT-007 | verify_client 输入 "y" 时开启客户端证书校验

        输入: verify_client="y"，其余路径取默认值，私钥变更并采集口令
        预期输出: config["verify_client"] == "true"
        断言点: 该字段值；口令文件路径被回填
        防回归: 若 'y' 分支被删除，默认 false 部署无法开启双向认证，本用例失败
        """
        monkeypatch.setattr(wizard, "validate_cert_path", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "validate_file_permissions", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "input_password", lambda prompt: "Pass#2026")
        monkeypatch.setattr(wizard, "save_password_file", lambda *a, **k: "/pwd")
        _feed(monkeypatch, ["/a.cer", "/b.pem", "/c.cer", "", "y"])

        config = wizard.config_tls_cert()

        assert config["verify_client"] == "true"
        assert config["ssl_keyfile_password"] == "/pwd"

    def test_sign_wizard_saves_new_key_password(self, wizard, monkeypatch):
        """TC-INIT-008 | 签名私钥变更时采集并保存口令

        输入: sign_certfile=/s/cert.cer、sign_keyfile=/s/key.pem、口令 Pass#2026
        预期输出: sign_keyfile_password 为口令文件路径
        断言点: 返回字典三个字段；save_password_file 入参
        防回归: 若签名私钥口令复用 TLS 口令，轮换签名密钥会静默失败，本用例失败
        """
        monkeypatch.setattr(wizard, "validate_cert_path", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "validate_file_permissions", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "input_password", lambda prompt: "Pass#2026")
        saved = []
        monkeypatch.setattr(wizard, "save_password_file",
                            lambda password, key: saved.append((password, key)) or "/s/key_pwd")
        _feed(monkeypatch, ["/s/cert.cer", "/s/key.pem"])

        config = wizard.config_sign_cert()

        assert config == {"sign_certfile": "/s/cert.cer", "sign_keyfile": "/s/key.pem",
                          "sign_keyfile_password": "/s/key_pwd"}
        assert saved == [("Pass#2026", "/s/key.pem")]

    def test_jwk_wizard_saves_new_key_password(self, wizard, monkeypatch):
        """TC-INIT-009 | JWK 私钥变更时采集并保存口令

        输入: jwk_cert_path=/j/cert.cer、jwk_private_key_path=/j/key.pem、口令 Pass#2026
        预期输出: jwk_private_key_password 为口令文件路径
        断言点: 返回字典三个字段；save_password_file 入参
        防回归: 若 JWK 分支忘记保存口令，重启后无法用加密私钥生成 JWKS，本用例失败
        """
        monkeypatch.setattr(wizard, "validate_cert_path", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "validate_file_permissions", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "input_password", lambda prompt: "Pass#2026")
        saved = []
        monkeypatch.setattr(wizard, "save_password_file",
                            lambda password, key: saved.append((password, key)) or "/j/key_pwd")
        _feed(monkeypatch, ["/j/cert.cer", "/j/key.pem"])

        config = wizard.config_jwk_cert()

        assert config == {"jwk_cert_path": "/j/cert.cer",
                          "jwk_private_key_path": "/j/key.pem",
                          "jwk_private_key_password": "/j/key_pwd"}
        assert saved == [("Pass#2026", "/j/key.pem")]

    def test_jwk_wizard_keeps_existing_password(self, wizard_with_config, monkeypatch):
        """TC-INIT-010 | JWK 私钥未变更时沿用既有口令文件

        输入: 既有配置 jwk_private_key_password=/old/jwk_pwd，两个路径空输入
        预期输出: jwk_private_key_password == "/old/jwk_pwd"
        断言点: 该字段；save_password_file 未被调用
        防回归: 若每次运行都重写口令文件，只读挂载会失败，本用例失败
        """
        wizard = wizard_with_config(
            "jwk_cert_path=/j/cert.cer\n"
            "jwk_private_key_path=/j/key.pem\n"
            "jwk_private_key_password=/old/jwk_pwd\n")
        monkeypatch.setattr(wizard, "validate_cert_path", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "validate_file_permissions", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "save_password_file",
                            lambda *a, **k: pytest.fail("password file must not be rewritten"))
        _feed(monkeypatch, ["", ""])

        assert wizard.config_jwk_cert()["jwk_private_key_password"] == "/old/jwk_pwd"

    def test_sign_wizard_keeps_existing_password(self, wizard_with_config, monkeypatch):
        """TC-INIT-051 | 签名私钥未变更时沿用既有口令文件

        输入: 既有配置 sign_keyfile_password=/old/sign_pwd，两个路径空输入
        预期输出: sign_keyfile_password == "/old/sign_pwd"
        断言点: 该字段；save_password_file 未被调用（否则只读部署会失败）
        防回归: 若签名口令无条件重写，签名私钥口令会被清空，验签全部失败，本用例失败
        """
        wizard = wizard_with_config(
            "sign_certfile=/s/cert.cer\n"
            "sign_keyfile=/s/key.pem\n"
            "sign_keyfile_password=/old/sign_pwd\n")
        monkeypatch.setattr(wizard, "validate_cert_path", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "validate_file_permissions", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "save_password_file",
                            lambda *a, **k: pytest.fail("password file must not be rewritten"))
        _feed(monkeypatch, ["", ""])

        config = wizard.config_sign_cert()

        assert config["sign_keyfile_password"] == "/old/sign_pwd"
        assert config["sign_certfile"] == "/s/cert.cer"


# --------------------------------------------------------------------------
# input_path loop
# --------------------------------------------------------------------------

class TestInputPath:
    def test_empty_required_path_reprompts(self, wizard, monkeypatch, capsys):
        """TC-INIT-011 | 必填路径为空时提示错误并重新询问

        输入: 依次输入 ""、"/good.cer"
        预期输出: 返回 "/good.cer"；输出含一次 "Error: path cannot be empty"
        断言点: 返回值；提示语出现次数；输入队列被完全消费
        防回归: 若空输入被当作有效路径返回，配置会写入空路径，本用例失败
        """
        monkeypatch.setattr(wizard, "validate_cert_path", lambda *a, **k: (True, ""))
        monkeypatch.setattr(wizard, "validate_file_permissions", lambda *a, **k: (True, ""))
        queue = _feed(monkeypatch, ["", "/good.cer"])

        assert wizard.input_path("cert", "", ".cer") == "/good.cer"
        assert queue == []
        assert capsys.readouterr().out.count("Error: path cannot be empty") == 1

    def test_invalid_path_reprompts_with_validation_message(self, wizard, monkeypatch, capsys):
        """TC-INIT-012 | 路径校验失败时打印校验消息并重新询问

        输入: 第一次 "/bad.cer"（校验返回 False）、第二次 "/good.cer"
        预期输出: 返回 "/good.cer"；输出含 "Error: <message>"
        断言点: 返回值；validate_cert_path 调用 2 次；提示语
        防回归: 若校验失败后直接放行，错误的后缀/路径会写进配置，本用例失败
        """
        responses = [(False, "Incorrect file extension, expected .cer"), (True, "")]
        calls = []
        monkeypatch.setattr(wizard, "validate_cert_path",
                            lambda *a, **k: calls.append(a) or responses.pop(0))
        monkeypatch.setattr(wizard, "validate_file_permissions", lambda *a, **k: (True, ""))
        _feed(monkeypatch, ["/bad.cer", "/good.cer"])

        assert wizard.input_path("cert", "", ".cer") == "/good.cer"
        assert len(calls) == 2
        assert "Error: Incorrect file extension, expected .cer" in capsys.readouterr().out

    def test_permission_warning_allows_retry_or_accept(self, wizard, monkeypatch, capsys):
        """TC-INIT-013 | 权限告警后可由用户选择继续或重填

        输入: 第一次回答 "n"（不继续），第二次回答 "y"（继续）
        预期输出: 返回第二个路径 "/k2.pem"；输出含两次 "Warning:"
        断言点: 返回值；validate_file_permissions 调用 2 次；告警次数
        防回归: 若确认输入被忽略（直接接受），过度宽松权限的私钥会被静默使用，本用例失败
        """
        monkeypatch.setattr(wizard, "validate_cert_path", lambda *a, **k: (True, ""))
        checks = []
        monkeypatch.setattr(wizard, "validate_file_permissions",
                            lambda path: checks.append(path) or (False, "permissions too open"))
        queue = _feed(monkeypatch, ["/k.pem", "n", "/k2.pem", "y"])

        assert wizard.input_path("key", "", ".pem") == "/k2.pem"
        assert checks == ["/k.pem", "/k2.pem"]
        assert queue == []
        assert capsys.readouterr().out.count("Warning: permissions too open") == 2

    def test_optional_track_change_empty_returns_flag(self, wizard, monkeypatch):
        """TC-INIT-014 | 可选且跟踪变更时，空输入返回 ("", False)

        输入: input_path("crl", default="", suffix=".crl", required=False, track_change=True)
              且用户空回车
        预期输出: ("", False)
        断言点: 返回元组两个元素；输入队列被完全消费
        防回归: 若该分支返回裸字符串，调用方解包会抛 ValueError，本用例失败
        """
        queue = _feed(monkeypatch, [""])

        assert wizard.input_path("crl", "", ".crl", required=False, track_change=True) == ("", False)
        assert queue == []

    def test_optional_without_track_change_returns_empty_string(self, wizard, monkeypatch):
        """TC-INIT-015 | 可选但不跟踪变更时，空输入返回 ""

        输入: input_path("crl", default="", suffix=".crl", required=False) 且用户空回车
        预期输出: ""
        断言点: 返回值类型与内容
        防回归: 若返回 ("", False) 元组，非 track_change 调用方会拿到错误类型，本用例失败
        """
        _feed(monkeypatch, [""])

        assert wizard.input_path("crl", "", ".crl", required=False) == ""

    def test_input_password_delegates_to_shared_validator(self, wizard, monkeypatch):
        """TC-INIT-016 | input_password 委托公共口令输入组件（复用复杂度校验）

        输入: 打桩 input_password_with_validation 返回 "Pass#2026"
        预期输出: input_password 返回同一口令；组件收到原样 prompt
        断言点: 返回值；打桩函数的调用参数
        防回归: 若向导自己读口令（绕过复杂度校验），弱口令可写入口令文件，本用例失败
        """
        calls = []
        monkeypatch.setattr(init_module, "input_password_with_validation",
                            lambda prompt: calls.append(prompt) or "Pass#2026")

        assert wizard.input_password("Enter key password") == "Pass#2026"
        assert calls == ["Enter key password"]


# --------------------------------------------------------------------------
# validate_cert_path / validate_file_permissions
# --------------------------------------------------------------------------

class TestPathValidation:
    def test_validate_cert_path_matrix(self, wizard, tmp_path):
        """TC-INIT-017 | 路径校验矩阵：空值/不存在/目录/后缀/可选/大小写

        输入: 7 组 (path, suffix, required)
        预期输出: 逐组返回 (False, "Path cannot be empty")、(True, "")、
              (False, "File does not exist: <p>")、(True, "")、(False, "Not a valid file: <p>")、
              (False, "Incorrect file extension, expected .cer")、(True, "")
        断言点: 每组的是否通过与消息（含具体路径/期望后缀）
        防回归: 若存在性/类型/后缀任一校验被删除，错误配置会在启动期才暴露，本用例失败
        """
        missing = str(tmp_path / "absent.cer")
        directory = tmp_path / "dir.cer"
        directory.mkdir()
        valid = tmp_path / "server.CER"
        valid.write_bytes(b"x")

        assert wizard.validate_cert_path("", ".cer", required=True) == (False, "Path cannot be empty")
        assert wizard.validate_cert_path("", ".cer", required=False) == (True, "")
        assert wizard.validate_cert_path(missing, ".cer", required=True) == (
            False, f"File does not exist: {missing}")
        assert wizard.validate_cert_path(missing, ".cer", required=False) == (True, "")
        assert wizard.validate_cert_path(str(directory), ".cer", required=True) == (
            False, f"Not a valid file: {directory}")
        assert wizard.validate_cert_path(str(valid), ".pem", required=True) == (
            False, "Incorrect file extension, expected .pem")
        assert wizard.validate_cert_path(str(valid), ".cer", required=True) == (True, "")
        assert wizard.validate_cert_path(str(valid), "", required=True) == (True, "")

    @pytest.mark.skipif(os.name == "nt", reason="POSIX 权限位在 Windows 上不生效")
    def test_secure_permissions_pass(self, wizard, tmp_path):
        """TC-INIT-018 | 0600 权限的私钥通过权限检查

        输入: 权限为 0o600 的文件
        预期输出: (True, "")
        断言点: 返回值元组
        防回归: 若把 0600 也判为过宽，正常部署无法通过向导，本用例失败
        """
        key = tmp_path / "key.pem"
        key.write_text("secret", encoding="utf-8")
        os.chmod(key, 0o600)

        assert wizard.validate_file_permissions(str(key)) == (True, "")

    @pytest.mark.skipif(os.name == "nt", reason="POSIX 权限位在 Windows 上不生效")
    def test_permissive_permissions_reported_with_mode(self, wizard, tmp_path):
        """TC-INIT-019 | 过宽权限被拒绝，消息回显当前权限位

        输入: 权限为 0o644 的文件
        预期输出: (False, "File <p> has overly permissive permissions (current: 644), security risk")
        断言点: 是否通过；消息中的权限位 "644" 与路径
        防回归: 若权限检查被删除，组内可读的私钥会通过校验（CWE-732），本用例失败
        """
        key = tmp_path / "key.pem"
        key.write_text("secret", encoding="utf-8")
        os.chmod(key, 0o644)

        passed, message = wizard.validate_file_permissions(str(key))

        assert passed is False
        assert message == (f"File {key} has overly permissive permissions "
                           f"(current: 644), security risk")

    def test_stat_error_is_reported(self, wizard, tmp_path, monkeypatch):
        """TC-INIT-020 | 无法读取权限时返回失败并携带底层原因

        输入: monkeypatch os.stat 抛 PermissionError("denied")
        预期输出: (False, "Cannot read file permissions: denied")
        断言点: 是否通过；消息内容
        防回归: 若异常未被捕获，权限读取失败会让向导崩溃而不是提示，本用例失败
        """
        key = tmp_path / "key.pem"
        key.write_text("secret", encoding="utf-8")

        real_stat = os.stat

        def _denied(path, *args, **kwargs):
            if "key.pem" in str(path):
                raise PermissionError("denied")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(init_module.os, "name", "posix")
        monkeypatch.setattr(init_module.os, "stat", _denied)

        assert wizard.validate_file_permissions(str(key)) == (
            False, "Cannot read file permissions: denied")


# --------------------------------------------------------------------------
# validate_certificate
# --------------------------------------------------------------------------

def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _build_cert(key, cn="registry.example"):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (x509.CertificateBuilder()
            .subject_name(_name(cn))
            .issuer_name(_name(cn))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))


PASSWORD = "Pass#2026"


@pytest.fixture
def pki(tmp_path):
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = _build_cert(rsa_key)
    cert_path = tmp_path / "server.cer"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path = tmp_path / "server_key.pem"
    key_path.write_bytes(rsa_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.BestAvailableEncryption(PASSWORD.encode())))

    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_cert = tmp_path / "other.cer"
    other_cert.write_bytes(_build_cert(other_key, "other.example").public_bytes(
        serialization.Encoding.PEM))

    ec_key = ec.generate_private_key(ec.SECP256R1())
    ec_cert = tmp_path / "ec.cer"
    ec_cert.write_bytes(_build_cert(ec_key, "ec.example").public_bytes(
        serialization.Encoding.PEM))

    return {"cert": cert_path, "key": key_path, "other_cert": other_cert,
            "ec_cert": ec_cert, "garbage": _write_garbage(tmp_path)}


def _write_garbage(tmp_path):
    path = tmp_path / "garbage.cer"
    path.write_text("-----BEGIN CERTIFICATE-----\nnope\n", encoding="utf-8")
    return path


class TestValidateCertificate:
    """``InitCommand.validate_certificate`` 的正反向契约。

    历史缺陷：``CertObj.public_key`` 存放的是已解析的公钥对象，却被当成方法调用，
    且 RSA 类型取自不存在的 ``x509.RSAPublicKey``，导致该校验对任何证书都恒失败
    （异常被兜底成 "Certificate validation failed: ..."）。修复后这里固化正确行为。
    """

    def test_matching_pair_passes(self, wizard, pki):
        """TC-INIT-021 | 证书与私钥匹配时应通过校验

        输入: validate_certificate(server.cer, server_key.pem, "Pass#2026")
        预期输出: (True, "")
        断言点: 返回值元组（布尔与空消息）
        防回归: 若公钥读取或公私钥比对被改坏，本用例失败
        """
        assert wizard.validate_certificate(str(pki["cert"]), str(pki["key"]), PASSWORD) == (True, "")

    def test_mismatched_pair_is_reported(self, wizard, pki):
        """TC-INIT-022 | 私钥与证书不匹配时应返回明确消息

        输入: validate_certificate(other.cer, server_key.pem, "Pass#2026")
        预期输出: (False, "Private key does not match certificate")
        断言点: 是否通过；完整消息
        防回归: 若比对逻辑被删或恒真，本用例失败
        """
        assert wizard.validate_certificate(str(pki["other_cert"]), str(pki["key"]),
                                           PASSWORD) == (False, "Private key does not match certificate")

    def test_non_rsa_certificate_is_rejected(self, wizard, pki):
        """TC-INIT-023 | 非 RSA 证书应被拒绝

        输入: validate_certificate(ec.cer, server_key.pem, "Pass#2026")
        预期输出: (False, "Unsupported certificate algorithm, RSA only")
        断言点: 是否通过；完整消息
        防回归: 若 RSA 类型判断写成恒真/恒假，本用例失败
        """
        assert wizard.validate_certificate(str(pki["ec_cert"]), str(pki["key"]),
                                           PASSWORD) == (False, "Unsupported certificate algorithm, RSA only")

    def test_wrong_password_is_wrapped(self, wizard, pki):
        """TC-INIT-026 | 口令错误时应给出可读失败消息

        输入: validate_certificate(server.cer, server_key.pem, "WrongPass#1")
        预期输出: (False, "Certificate validation failed: Parse private key error! ")
        断言点: 是否通过；完整消息
        防回归: 若私钥解析异常未被包装，本用例失败
        """
        assert wizard.validate_certificate(str(pki["cert"]), str(pki["key"]),
                                           "WrongPass#1") == (
            False, "Certificate validation failed: Parse private key error! ")

    def test_certificate_without_public_key_is_rejected(self, wizard, pki, monkeypatch):
        """TC-INIT-052 | 证书缺少公钥时给出明确消息

        输入: parse_cer_certificate 返回 public_key=None 的 CertObj
        预期输出: (False, "Certificate has no public key")
        断言点: 是否通过；完整消息
        防回归: 若缺少 None 判断，会被 isinstance 误报成"算法不支持"
        """
        from common.cert.x509_obj import CertObj, X509Obj

        empty_cert = CertObj()
        empty_cert.public_key = None
        monkeypatch.setattr(
            "agent_registry.init.parse_cer_certificate",
            lambda path: X509Obj(cert_list=[empty_cert]),
        )

        assert wizard.validate_certificate(str(pki["cert"]), str(pki["key"]),
                                           PASSWORD) == (False, "Certificate has no public key")

    def test_empty_certificate_file_is_rejected(self, wizard, pki, monkeypatch):
        """TC-INIT-024 | 证书文件不含证书时返回 "Certificate file is empty"

        输入: monkeypatch parse_cer_certificate 返回空证书列表
        预期输出: (False, "Certificate file is empty")
        断言点: 是否通过；完整消息
        防回归: 若空列表走进 cert_list[0] 取值，会抛 IndexError 而非可读提示，本用例失败
        """
        monkeypatch.setattr(init_module, "parse_cer_certificate",
                            lambda path: X509Obj(cert_list=[]))

        assert wizard.validate_certificate(str(pki["cert"]), str(pki["key"]),
                                           PASSWORD) == (False, "Certificate file is empty")

    def test_parse_failure_is_wrapped(self, wizard, pki):
        """TC-INIT-025 | 解析失败转成 "Certificate validation failed: ..." 消息

        输入: validate_certificate(garbage.cer, server_key.pem, "Pass#2026")
        预期输出: (False, "Certificate validation failed: Parse certificate error! ")
        断言点: 是否通过；消息前缀与内层文案
        防回归: 若异常外抛，向导会以栈回溯退出而不是提示用户重填，本用例失败
        """
        passed, message = wizard.validate_certificate(str(pki["garbage"]), str(pki["key"]),
                                                      PASSWORD)

        assert passed is False
        assert message == "Certificate validation failed: Parse certificate error! "


# --------------------------------------------------------------------------
# save_password_file
# --------------------------------------------------------------------------

class TestSavePasswordFile:
    @pytest.mark.skipif(os.name == "nt", reason="POSIX 权限位在 Windows 上不生效")
    def test_password_is_encrypted_and_owner_only(self, wizard, tmp_path, monkeypatch):
        """TC-INIT-027 | 口令落盘：与私钥同目录的 <stem>_pwd 文件、加密内容、0600 权限

        输入: save_password_file("Pass#2026", <tmp>/sub/server_key.pem)
        预期输出: 返回 <tmp>/sub/server_key_pwd；文件内容以 "enc:v1:" 开头，
              解密回 "Pass#2026"；权限为 0600
        断言点: 返回路径；文件存在；密文前缀；解密往返相等；权限位
        防回归: 若口令以明文落盘或权限放宽，凭证泄露（CWE-256/732），本用例失败
        """
        monkeypatch.setenv("REGISTRY_CIPHER_KEY", Fernet.generate_key().decode())
        monkeypatch.setattr(cipher_util, "_fernet", None)
        sub = tmp_path / "sub"
        sub.mkdir()

        result = wizard.save_password_file("Pass#2026", str(sub / "server_key.pem"))

        assert result == str(sub / "server_key_pwd")
        stored = (sub / "server_key_pwd").read_text(encoding="utf-8")
        assert stored.startswith("enc:v1:")
        assert cipher_util.decrypt(stored) == b"Pass#2026"
        assert oct(os.stat(sub / "server_key_pwd").st_mode & 0o777) == "0o600"


# --------------------------------------------------------------------------
# config file writers
# --------------------------------------------------------------------------

class TestSaveConfigFile:
    def test_duplicate_keys_are_collapsed_and_last_line_newline_added(self, wizard, tmp_path):
        """TC-INIT-028 | 既有文件中重复键只保留一条新值；末尾无换行的行被补换行

        输入: server.conf = "enable_https=false\\nenable_https=false\\n# tail"（末行无换行），
              写入 {"enable_https": "true"}
        预期输出: "enable_https=true\\n# tail\\n"（重复键被折叠，注释保留，末行补换行）
        断言点: 读回内容完全相等；重复键出现次数为 1
        防回归: 若重复键被保留，解析时后者覆盖前者，配置生效值不可预测，本用例失败
        """
        wizard.config_file = str(tmp_path / "etc" / "conf" / "server.conf")
        os.makedirs(os.path.dirname(wizard.config_file), exist_ok=True)
        with open(wizard.config_file, "w", encoding="utf-8") as stream:
            stream.write("enable_https=false\nenable_https=false\n# tail")

        wizard.save_config_to_file({"enable_https": "true"})

        content = _read(wizard.config_file)
        assert content == "enable_https=true\n# tail\n"
        assert content.count("enable_https") == 1

    def test_missing_keys_are_appended(self, wizard):
        """TC-INIT-029 | 既有文件缺少的键追加到末尾，已有键更新不重复

        输入: server.conf = "ip=1.2.3.4\\n"，写入 {"ip": "5.6.7.8", "port": "8443"}
        预期输出: "ip=5.6.7.8\\nport=8443\\n"
        断言点: 读回内容完全相等
        防回归: 若缺失键不追加，向导的新配置不会生效，本用例失败
        """
        os.makedirs(os.path.dirname(wizard.config_file), exist_ok=True)
        with open(wizard.config_file, "w", encoding="utf-8") as stream:
            stream.write("ip=1.2.3.4\n")

        wizard.save_config_to_file({"ip": "5.6.7.8", "port": "8443"})

        assert _read(wizard.config_file) == "ip=5.6.7.8\nport=8443\n"

    def test_new_file_is_created_and_case_insensitive_update(self, wizard):
        """TC-INIT-030 | 不存在的配置文件按序创建，键名大小写不敏感匹配

        输入: 文件不存在，写入 {"ip": "10.0.0.1", "port": "8080"}；
              再以 {"IP": "10.0.0.2"} 更新（既有键为大写）
        预期输出: 首次创建含两行；更新后 IP 行被替换为 10.0.0.2 且无重复
        断言点: 两步后的文件内容
        防回归: 若大小写不敏感匹配被删除，更新会追加 IP= 造成重复键，本用例失败
        """
        wizard.save_config_to_file({"ip": "10.0.0.1", "port": "8080"})
        assert _read(wizard.config_file) == "ip=10.0.0.1\nport=8080\n"

        with open(wizard.config_file, "w", encoding="utf-8") as stream:
            stream.write("IP=10.0.0.1\nport=8080\n")

        wizard.save_config_to_file({"ip": "10.0.0.2"})

        content = _read(wizard.config_file)
        assert content == "IP=10.0.0.2\nport=8080\n"

    def test_persistence_config_duplicate_and_tail_newline(self, wizard, tmp_path):
        """TC-INIT-031 | persistence.conf 折叠重复键、补齐末行换行并追加新键

        输入: persistence.conf = "persistence.mode=file\\npersistence.mode=file\\n# tail"
              （末行无换行），写入 {"persistence.mode": "sqlite", "sqlite.path": "data/a.db"}
        预期输出: "persistence.mode=sqlite\\n# tail\\nsqlite.path=data/a.db\\n"
        断言点: 读回内容完全相等（重复键折叠 + 末行补换行 + 缺失键追加）
        防回归: 若缺失键不追加，向导选择的路径不会生效，本用例失败
        """
        os.makedirs(os.path.dirname(wizard.persistence_config_file), exist_ok=True)
        with open(wizard.persistence_config_file, "w", encoding="utf-8") as stream:
            stream.write("persistence.mode=file\npersistence.mode=file\n# tail")

        wizard.save_persistence_config_to_file({"persistence.mode": "sqlite",
                                               "sqlite.path": "data/a.db"})

        assert _read(wizard.persistence_config_file) == (
            "persistence.mode=sqlite\n# tail\nsqlite.path=data/a.db\n")

    def test_new_persistence_file_gets_header_and_values(self, wizard):
        """TC-INIT-032 | 新建 persistence.conf 时写入许可证头与全部配置项

        输入: 文件不存在，写入 {"persistence.mode": "file", "sqlite.path": "data/x.db"}
        预期输出: 文件以 "# Copyright (c) 2026 Huawei" 开头并含两行配置
        断言点: 头部行；两行键值
        防回归: 若头部丢失，SCA/合规扫描会报缺少许可证头，本用例失败
        """
        wizard.save_persistence_config_to_file({"persistence.mode": "file",
                                                "sqlite.path": "data/x.db"})

        content = _read(wizard.persistence_config_file)
        assert content.startswith("# Copyright (c) 2026 Huawei")
        assert "persistence.mode=file\n" in content
        assert "sqlite.path=data/x.db\n" in content


# --------------------------------------------------------------------------
# config_persistence
# --------------------------------------------------------------------------

class TestPersistenceWizard:
    def test_default_file_mode_returns_early(self, wizard, monkeypatch):
        """TC-INIT-033 | 存储模式空输入取默认 file，并立即返回（不追问连接字段）

        输入: 存储模式输入 ""（无既有配置 → 默认 file）
        预期输出: {"persistence.mode": "file"}；不再有额外提问
        断言点: 返回字典完全相等；输入队列被完全消费
        防回归: 若 file 模式仍追问 host/database，默认部署会卡住，本用例失败
        """
        queue = _feed(monkeypatch, [""])

        assert wizard.config_persistence() == {"persistence.mode": "file"}
        assert queue == []

    def test_invalid_mode_reprompts(self, wizard, monkeypatch, capsys):
        """TC-INIT-034 | 非法存储模式提示并重新询问

        输入: 依次输入 "bogus"、"sqlite"，随后 path 空输入取默认
        预期输出: 返回 {"persistence.mode": "sqlite", "_connection_profile": ("sqlite", {...})}；
              输出含 "Invalid storage mode"
        断言点: 返回字典；提示语；sqlite profile 的 path 默认值
        防回归: 若非法模式被接受，启动期才会因未知后端失败，本用例失败
        """
        monkeypatch.setattr("common.util.database_config.read_profile_file",
                            lambda name, root: {})
        _feed(monkeypatch, ["bogus", "sqlite", ""])

        config = wizard.config_persistence()

        assert config["persistence.mode"] == "sqlite"
        assert config["_connection_profile"] == ("sqlite", {"path": "data/agents.db"})
        assert "Invalid storage mode" in capsys.readouterr().out

    def test_postgresql_prompts_use_profile_fallbacks(self, wizard, monkeypatch):
        """TC-INIT-035 | PostgreSQL：文件中的 host 作为默认值，其余字段用 profile 默认值

        输入: profile 文件提供 {"host": "db.internal"}；五个字段全部空输入
        预期输出: profile = {host: db.internal, port: 5432, database: registry_center,
              user: opena2a_t, password_env: POSTGRES_PASSWORD}
        断言点: 连接名与五个字段值（含口令变量名兜底）
        防回归: 若口令变量名兜底丢失，启动期无法解析口令环境变量，本用例失败
        """
        monkeypatch.setattr("common.util.database_config.read_profile_file",
                            lambda name, root: {"host": "db.internal"})
        queue = _feed(monkeypatch, ["postgresql", "", "", "", "", ""])

        config = wizard.config_persistence()

        name, profile = config["_connection_profile"]
        assert name == "postgresql"
        assert profile["host"] == "db.internal"
        assert profile["port"] == 5432
        assert profile["database"] == "registry_center"
        assert profile["user"] == "opena2a_t"
        assert profile["password_env"] == "POSTGRES_PASSWORD"
        # profile.defaults 的其余字段被原样合并进来（连接超时与连接池边界）
        assert {"connect_timeout", "pool_min", "pool_max"} <= set(profile)
        assert queue == []

    def test_mysql_and_gauss_password_variable_defaults(self, wizard, monkeypatch):
        """TC-INIT-036 | MySQL/Gauss 的口令变量兜底分别为 MYSQL_PASSWORD/GAUSS_PASSWORD

        输入: profile 文件为空；mysql 五字段空输入、gauss 五字段空输入
        预期输出: mysql password_env=MYSQL_PASSWORD；gauss（连接名 gaussdb）
              password_env=GAUSS_PASSWORD
        断言点: 两次返回的连接名与 password_env 字段
        防回归: 若按模式名映射失败（gauss vs gaussdb），口令变量提示错误，本用例失败
        """
        monkeypatch.setattr("common.util.database_config.read_profile_file",
                            lambda name, root: {})
        _feed(monkeypatch, ["mysql", "", "", "", "", "", "gauss", "", "", "", "", ""])

        mysql_config = wizard.config_persistence()
        gauss_config = wizard.config_persistence()

        assert mysql_config["_connection_profile"][0] == "mysql"
        assert mysql_config["_connection_profile"][1]["password_env"] == "MYSQL_PASSWORD"
        assert gauss_config["_connection_profile"][0] == "gaussdb"
        assert gauss_config["_connection_profile"][1]["password_env"] == "GAUSS_PASSWORD"

    def test_literal_secret_in_profile_is_rejected(self, wizard, monkeypatch):
        """TC-INIT-037 | 连接 profile 里出现字面口令时拒绝继续

        输入: read_profile_file 返回 {"host": "h", "password": "secret"}
        预期输出: ValueError，消息含 "must use secret variable references"
        断言点: 异常类型 + 消息关键字
        防回归: 若字面口令被直接接受，明文凭据会被写入 db/*.json（CWE-256），本用例失败
        """
        monkeypatch.setattr("common.util.database_config.read_profile_file",
                            lambda name, root: {"host": "h", "password": "secret"})
        _feed(monkeypatch, ["postgresql"])

        with pytest.raises(ValueError, match="must use secret variable references"):
            wizard.config_persistence()

    def test_connection_profile_is_written_as_owner_only_json(self, wizard, tmp_path,
                                                              monkeypatch):
        """TC-INIT-038 | 选中连接 profile 时写入 etc/conf/db/<name>.json 且权限 0600

        输入: save_persistence_config_to_file({"_connection_profile": ("postgresql", {...}),
              "persistence.mode": "postgresql"})
        预期输出: etc/conf/db/postgresql.json 内容为缩进 2 的 JSON + 换行；权限 0600；
              persistence.conf 含 persistence.mode=postgresql
        断言点: JSON 内容逐字段；文件权限；persistence.conf 行
        防回归: 若 profile 未落盘或权限放宽，重启后连接参数丢失/泄露，本用例失败
        """
        config = {"persistence.mode": "postgresql",
                  "_connection_profile": ("postgresql",
                                          {"host": "db.internal", "port": 5432,
                                           "password_env": "POSTGRES_PASSWORD"})}

        wizard.save_persistence_config_to_file(config)

        target = tmp_path / "etc" / "conf" / "db" / "postgresql.json"
        assert json.loads(target.read_text(encoding="utf-8")) == {
            "host": "db.internal", "port": 5432, "password_env": "POSTGRES_PASSWORD"}
        assert target.read_text(encoding="utf-8").endswith("\n")
        if os.name != "nt":
            assert oct(os.stat(target).st_mode & 0o777) == "0o600"
        assert "persistence.mode=postgresql" in _read(wizard.persistence_config_file)
        assert "_connection_profile" not in _read(wizard.persistence_config_file)


# --------------------------------------------------------------------------
# validate_non_interactive_config
# --------------------------------------------------------------------------

@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """Fake installation root + patched config loaders for the non-interactive check."""
    import common.util.app_config as app_config
    import agent_registry.identity as identity

    root = tmp_path / "install"
    (root / "etc" / "conf").mkdir(parents=True)
    for name in ("server.conf", "server.properties", "persistence.conf"):
        (root / "etc" / "conf" / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(init_module, "get_root_path", lambda: str(root))

    state = {"conf": {"port": "5000", "enable_https": "false"},
             "persistence": {"persistence.mode": "file"},
             "failures": []}
    monkeypatch.setattr(app_config, "get_conf", lambda: state["conf"])
    monkeypatch.setattr(app_config, "get_persistence_conf", lambda: state["persistence"])
    monkeypatch.setattr(identity, "strict_startup_failures",
                        lambda conf: state["failures"])
    state["root"] = root
    return state


class TestNonInteractiveValidation:
    def test_missing_configuration_file_is_reported(self, deployment, tmp_path, monkeypatch):
        """TC-INIT-039 | 缺少 etc/conf 部署文件时报错并指出文件名

        输入: 删除 server.properties
        预期输出: ValueError("Missing etc/conf/server.properties; provide deployment configuration first")
        断言点: 异常类型 + 完整消息
        防回归: 若缺文件时继续校验，会以空配置启动服务，本用例失败
        """
        (deployment["root"] / "etc" / "conf" / "server.properties").unlink()

        with pytest.raises(ValueError) as excinfo:
            validate_non_interactive_config()

        assert str(excinfo.value) == ("Missing etc/conf/server.properties; "
                                      "provide deployment configuration first")

    @pytest.mark.parametrize("port", ["0", "65536", "abc", "٥٠٠٠", ""])
    def test_invalid_port_is_rejected(self, deployment, port):
        """TC-INIT-040 | 端口必须是 1..65535 的十进制整数

        输入: port 依次为 "0"、"65536"、"abc"、"٥٠٠٠"（非 ASCII 数字）、""
        预期输出: ValueError("Server port must be an integer between 1 and 65535")
        断言点: 异常类型 + 完整消息（五种非法形态各一）
        防回归: 若只做 int() 转换，非 ASCII 数字或 0 端口会通过校验，本用例失败
        """
        deployment["conf"]["port"] = port

        with pytest.raises(ValueError) as excinfo:
            validate_non_interactive_config()

        assert str(excinfo.value) == "Server port must be an integer between 1 and 65535"

    def test_non_boolean_switch_is_rejected(self, deployment):
        """TC-INIT-041 | 布尔型开关只接受 true/false

        输入: enable_https="yes"
        预期输出: ValueError("enable_https must be true or false")
        断言点: 异常类型 + 完整消息
        防回归: 若用真值判断（非空字符串即真），"yes"/"off" 会被静默当成 true，本用例失败
        """
        deployment["conf"]["enable_https"] = "yes"

        with pytest.raises(ValueError) as excinfo:
            validate_non_interactive_config()

        assert str(excinfo.value) == "enable_https must be true or false"

    def test_strict_identity_failures_are_joined(self, deployment):
        """TC-INIT-042 | 严格身份校验失败项合并成一条消息

        输入: strict_startup_failures 返回 ["owner identity missing", "token key missing"]
        预期输出: ValueError("owner identity missing; token key missing")
        断言点: 异常类型 + 完整消息（分隔符为 "; "）
        防回归: 若失败项只取第一条，运维会逐条修复反复重启，本用例失败
        """
        deployment["failures"] = ["owner identity missing", "token key missing"]

        with pytest.raises(ValueError) as excinfo:
            validate_non_interactive_config()

        assert str(excinfo.value) == "owner identity missing; token key missing"

    def test_unknown_persistence_mode_is_rejected(self, deployment):
        """TC-INIT-043 | 未知 persistence.mode 被拒绝并列出合法值

        输入: persistence.mode="redis"
        预期输出: ValueError("persistence.mode must be file, sqlite, postgresql, gauss or mysql")
        断言点: 异常类型 + 完整消息
        防回归: 若模式白名单被删除，启动期才会因后端缺失而失败，本用例失败
        """
        deployment["persistence"]["persistence.mode"] = "redis"

        with pytest.raises(ValueError) as excinfo:
            validate_non_interactive_config()

        assert str(excinfo.value) == ("persistence.mode must be file, sqlite, "
                                      "postgresql, gauss or mysql")

    def test_https_enabled_runs_certificate_validator(self, deployment, monkeypatch):
        """TC-INIT-044 | 启用 HTTPS 时执行证书校验，失败则抛出校验器消息

        输入: enable_https="true"，CertValidator 返回 ValidationResult(False, "cert expired")
        预期输出: ValueError("cert expired")；校验器被构造一次
        断言点: 异常消息；构造次数
        防回归: 若非交互启动跳过证书校验，坏证书会在运行期才暴露，本用例失败
        """
        import common.cert.cert_validater as cert_module
        calls = []

        class _Rejecting:
            def __init__(self, conf):
                calls.append(conf)

            def validate(self):
                return ValidationResult(False, "cert expired")

        monkeypatch.setattr(cert_module, "CertValidator", _Rejecting)
        deployment["conf"]["enable_https"] = "true"

        with pytest.raises(ValueError) as excinfo:
            validate_non_interactive_config()

        assert str(excinfo.value) == "cert expired"
        assert len(calls) == 1

    def test_https_enabled_and_valid_certificate_passes(self, deployment, monkeypatch):
        """TC-INIT-045 | 启用 HTTPS 且证书校验通过时整体校验通过

        输入: enable_https="true"，CertValidator 返回 ValidationResult(True, "")
        预期输出: 无异常，返回 None
        断言点: 返回值为 None；校验器被构造一次
        防回归: 若通过分支误报失败，合法部署无法启动，本用例失败
        """
        import common.cert.cert_validater as cert_module
        calls = []

        class _Accepting:
            def __init__(self, conf):
                calls.append(conf)

            def validate(self):
                return ValidationResult(True, "")

        monkeypatch.setattr(cert_module, "CertValidator", _Accepting)
        deployment["conf"]["enable_https"] = "true"

        assert validate_non_interactive_config() is None
        assert len(calls) == 1

    def test_https_disabled_skips_certificate_validator(self, deployment, monkeypatch):
        """TC-INIT-046 | 关闭 HTTPS 时不做证书校验

        输入: enable_https="false"，CertValidator 被替换为"一旦构造就失败"的替身
        预期输出: 无异常，返回 None
        断言点: 返回值为 None（替身未被构造）
        防回归: 若关闭 HTTPS 仍校验证书，纯 HTTP 部署要求提供证书文件，本用例失败
        """
        import common.cert.cert_validater as cert_module

        class _Forbidden:
            def __init__(self, conf):
                pytest.fail("CertValidator must not run when HTTPS is disabled")

        monkeypatch.setattr(cert_module, "CertValidator", _Forbidden)

        assert validate_non_interactive_config() is None


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------

class TestMain:
    def test_validation_failure_exits_with_message(self, monkeypatch, capsys):
        """TC-INIT-047 | --non-interactive 校验失败时以退出码 1 结束并打印原因

        输入: validate_non_interactive_config 抛 ValueError("boom")
        预期输出: SystemExit(1)；stderr 含 "Configuration validation failed: boom"
        断言点: 退出码；stderr 消息
        防回归: 若失败仍返回 0，容器会带着坏配置启动，本用例失败
        """
        monkeypatch.setattr(init_module, "validate_non_interactive_config",
                            lambda: (_ for _ in ()).throw(ValueError("boom")))

        with pytest.raises(SystemExit) as excinfo:
            main(["--non-interactive"])

        assert excinfo.value.code == 1
        assert "Configuration validation failed: boom" in capsys.readouterr().err

    def test_validation_success_prints_confirmation(self, monkeypatch, capsys):
        """TC-INIT-048 | --non-interactive 校验通过时打印确认信息

        输入: validate_non_interactive_config 正常返回
        预期输出: 无异常；stdout 含 "Configuration validation passed"
        断言点: 输出文本（含"存储连通性由 serve 检查"说明）
        防回归: 若成功路径也报错退出，健康部署会被误判失败，本用例失败
        """
        calls = []
        monkeypatch.setattr(init_module, "validate_non_interactive_config",
                            lambda: calls.append("validated"))

        main(["--non-interactive"])

        assert calls == ["validated"]
        assert ("Configuration validation passed (storage connectivity is checked by serve)."
                in capsys.readouterr().out)

    def test_default_mode_runs_interactive_wizard(self, monkeypatch):
        """TC-INIT-049 | 无参数时运行交互式向导（InitCommand.init_command）

        输入: main([])
        预期输出: InitCommand 被构造一次，init_command 被调用一次
        断言点: 构造次数与调用次数
        防回归: 若默认分支被改成非交互校验，`python -m agent_registry.init` 不再能配置部署，本用例失败
        """
        events = []

        class _Recorder:
            def __init__(self):
                events.append("constructed")

            def init_command(self):
                events.append("init_command")

        monkeypatch.setattr(init_module, "InitCommand", _Recorder)

        main([])

        assert events == ["constructed", "init_command"]
