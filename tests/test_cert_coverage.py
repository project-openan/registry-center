# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Certificate parsing / validation coverage tests.

Covers ``common/cert/cert_parser.py`` and ``common/cert/cert_validater.py``.

PKI material is generated on the fly with the same helpers the existing suites use
(``tests/test_start_boot.py`` and ``tests/test_integration_cert_auth.py``): a 3072-bit
CA, a 3072-bit server identity (plain + encrypted key), a 2048-bit weak key, an
EC P-256 identity, a v2 CRL, a v1 CRL and an expired CRL. Everything lands in a
``tmp_path_factory`` directory — no network, no real ``etc/ssl`` files, no sleeps.

The one fixture double used here is ``cert_validater.cert_parser`` when a runtime
object cannot be produced with ``cryptography`` (an empty certificate list and a
v1 certificate: ``CertificateBuilder`` only emits v3). Those doubles are scoped by
``monkeypatch`` and only replace the parse step, never the decision under test.
"""

import datetime
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from common.cert import cert_parser
from common.cert.cert_exception import CertParseException
from common.cert.cert_validater import (
    CRLValidator,
    CerContentValidator,
    CerContentValidatorLink,
    CertValidator,
    CommonContentValidator,
    PathValidator,
    PathValidatorLink,
    PrivateKeyValidator,
)
from common.cert.x509_obj import CertObj, X509Obj
from common.util.conf_obj import ConfObj
from common.util.validation_result import ValidationResult

PASSWORD = "RegTest#2026"
NOT_AFTER = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)


# --------------------------------------------------------------------------
# PKI helpers (same construction as tests/test_start_boot.py)
# --------------------------------------------------------------------------

def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _make_cert(cn, key, issuer_cert, issuer_key, not_after=NOT_AFTER,
               not_before=None, is_ca=False, san=False):
    start = not_before or (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
    builder = (x509.CertificateBuilder()
               .subject_name(_name(cn))
               .issuer_name(issuer_cert.subject if issuer_cert else _name(cn))
               .public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(start)
               .not_valid_after(not_after)
               .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True))
    if san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(cn)]), critical=False)
    return builder.sign(issuer_key or key, hashes.SHA256())


def _write_cert(path, cert):
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


def _write_key(path, key, password=None):
    if password is None:
        payload = key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption())
    else:
        payload = key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.BestAvailableEncryption(password.encode()))
    path.write_bytes(payload)
    return path


def _make_crl(issuer_cert, issuer_key, last_update, next_update, serials=(), extensions=True):
    builder = (x509.CertificateRevocationListBuilder()
               .issuer_name(issuer_cert.subject)
               .last_update(last_update)
               .next_update(next_update))
    for serial in serials:
        builder = builder.add_revoked_certificate(
            x509.RevokedCertificateBuilder()
            .serial_number(serial)
            .revocation_date(last_update)
            .build())
    if extensions:
        builder = builder.add_extension(x509.CRLNumber(1), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    root = tmp_path_factory.mktemp("cert-coverage")
    now = datetime.datetime.now(datetime.timezone.utc)

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_cert = _make_cert("Coverage CA", ca_key, None, None, is_ca=True)

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    server_cert = _make_cert("registry.example", server_key, ca_cert, ca_key, san=True)

    enc_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    enc_cert = _make_cert("registry.example", enc_key, ca_cert, ca_key, san=True)

    weak_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    weak_cert = _make_cert("weak.example", weak_key, ca_cert, ca_key)

    ec_key = ec.generate_private_key(ec.SECP256R1())
    ec_cert = _make_cert("ec.example", ec_key, ca_cert, ca_key)

    expired_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    expired_cert = _make_cert(
        "expired.example", expired_key, ca_cert, ca_key,
        not_before=now - datetime.timedelta(days=30),
        not_after=now - datetime.timedelta(days=10))

    crl = _make_crl(ca_cert, ca_key, now - datetime.timedelta(days=1),
                    now + datetime.timedelta(days=10), serials=[server_cert.serial_number])
    crl_v1 = _make_crl(ca_cert, ca_key, now - datetime.timedelta(days=1),
                       now + datetime.timedelta(days=10), extensions=False)
    crl_expired = _make_crl(ca_cert, ca_key, now - datetime.timedelta(days=30),
                            now - datetime.timedelta(days=1))
    ca_crl = _make_crl(ca_cert, ca_key, now - datetime.timedelta(days=1),
                       now + datetime.timedelta(days=10))

    paths = {
        "root": root,
        "ca_key": _write_key(root / "ca.pem", ca_key),
        "ca": _write_cert(root / "ca.cer", ca_cert),
        "server_cert": _write_cert(root / "server.cer", server_cert),
        "server_key": _write_key(root / "server_key.pem", server_key),
        "enc_cert": _write_cert(root / "server_enc.cer", enc_cert),
        "enc_key": _write_key(root / "server_enc_key.pem", enc_key, PASSWORD),
        "weak_cert": _write_cert(root / "weak.cer", weak_cert),
        "weak_enc_key": _write_key(root / "weak_enc_key.pem", weak_key, PASSWORD),
        "ec_cert": _write_cert(root / "ec.cer", ec_cert),
        "ec_key": _write_key(root / "ec_key.pem", ec_key),
        "expired_cert": _write_cert(root / "expired.cer", expired_cert),
        "crl": _write_cert(root / "revocationlist.crl", crl),
        "crl_v1": _write_cert(root / "revocationlist_v1.crl", crl_v1),
        "crl_expired": _write_cert(root / "revocationlist_expired.crl", crl_expired),
        "ca_crl": _write_cert(root / "ca.crl", ca_crl),
        "password_file": root / "cert_pwd",
        "garbage_pem": root / "garbage.pem",
        "garbage_cer": root / "garbage.cer",
        "der_cer": root / "der.cer",
        "server_conf": root / "server.conf",
    }
    paths["ca_cert"] = ca_cert
    paths["ca_key_obj"] = ca_key
    paths["server_cert_obj"] = server_cert
    paths["enc_cert_obj"] = enc_cert
    paths["password_file"].write_text(PASSWORD, encoding="utf-8")
    paths["garbage_pem"].write_text("-----BEGIN CERTIFICATE-----\nnot-base64\n", encoding="utf-8")
    paths["garbage_cer"].write_text("-----BEGIN CRL-----\nnope\n", encoding="utf-8")
    paths["der_cer"].write_bytes(server_cert.public_bytes(serialization.Encoding.DER))
    paths["server_conf"].write_text("enable_https=true\n", encoding="utf-8")
    return paths


def _conf(pki, **overrides):
    """Build a real ConfObj pointing at the generated PKI.

    The identity certificate and the private key must belong to the same pair,
    otherwise the private-key stage fails on the public-key comparison.
    """
    values = {
        "ssl_certfile": str(pki["enc_cert"]),
        "ssl_keyfile": str(pki["enc_key"]),
        "ssl_keyfile_password": str(pki["password_file"]),
        "ssl_ca_certs": str(pki["ca"]),
        "ssl_crl_file": str(pki["crl"]),
        "verify_client": "true",
    }
    values.update(overrides)
    return ConfObj.as_object(values)


@pytest.fixture
def config_file(monkeypatch, pki):
    """Point CertValidator at an existing server.conf without touching the repo."""
    import common.cert.cert_validater as module
    monkeypatch.setattr(module, "CONFIG_FILE_PATH", str(pki["server_conf"]))
    return pki["server_conf"]


# --------------------------------------------------------------------------
# cert_parser
# --------------------------------------------------------------------------

class TestParseCerCertificate:
    def test_extracts_single_certificate_metadata(self, pki):
        """TC-CERT-001 | 解析单个 PEM 证书并抽取主体、签发者、序列号、有效期与 CN

        输入: parse_cer_certificate(server.cer)
        预期输出: X509Obj 含 1 条 CertObj；subject 含 CN=registry.example；
              issuer 含 CN=Coverage CA；version 为 v3；cn == "registry.example"；
              serial_number 为十六进制串；public_key 与证书公钥相同
        断言点: 列表长度；六个字段的具体值与类型；公钥对象与源证书一致
        防回归: 若字段抽取串位（subject/issuer 互换）或漏抽 CN，本用例失败
        """
        parsed = cert_parser.parse_cer_certificate(str(pki["server_cert"]))

        assert len(parsed.cert_list) == 1
        info = parsed.cert_list[0]
        assert "CN=registry.example" in info.subject
        assert "CN=Coverage CA" in info.issuer
        assert info.version is x509.Version.v3
        assert info.cn == "registry.example"
        assert info.serial_number == hex(pki["server_cert_obj"].serial_number)
        assert info.public_key.public_numbers() == pki["server_cert_obj"].public_key().public_numbers()
        assert info.valid_from == pki["server_cert_obj"].not_valid_before_utc.isoformat()
        assert info.valid_to == pki["server_cert_obj"].not_valid_after_utc.isoformat()

    def test_concatenated_pem_yields_ordered_certificate_list(self, pki):
        """TC-CERT-002 | 同一个 PEM 文件里的多张证书按文件顺序全部解析

        输入: 把 server.cer 与 ca.cer 拼成一个文件后解析
        预期输出: cert_list 长度为 2，[0] 为叶子证书（CN=registry.example），[1] 为 CA（CN=Coverage CA）
        断言点: 条数与顺序；每条的 CN
        防回归: 若只取第一张证书，证书链校验会退化为单证书校验，本用例失败
        """
        combined = pki["root"] / "chain.cer"
        combined.write_bytes(pki["server_cert"].read_bytes() + pki["ca"].read_bytes())

        parsed = cert_parser.parse_cer_certificate(str(combined))

        assert [info.cn for info in parsed.cert_list] == ["registry.example", "Coverage CA"]

    def test_der_binary_is_rejected_with_reason(self, pki):
        """TC-CERT-003 | DER 二进制证书被拒绝，异常说明缺少 PEM 头

        输入: parse_cer_certificate(der.cer)（DER 编码，无 "-----BEGIN "）
        预期输出: CertParseException，消息含 "Unsupported der binary type"
        断言点: 异常类型 + 消息关键字
        防回归: 若 DER 被当作 PEM 继续解析，会抛出泄露路径的底层异常，本用例失败
        """
        with pytest.raises(CertParseException, match="Unsupported der binary type"):
            cert_parser.parse_cer_certificate(str(pki["der_cer"]))

    def test_corrupt_pem_is_wrapped_without_parser_details(self, pki):
        """TC-CERT-004 | 损坏的 PEM 被包装成固定文案，不泄露底层解析细节

        输入: parse_cer_certificate(garbage.pem)（有 PEM 头但内容非法）
        预期输出: CertParseException，消息恰为 "Parse certificate error! "
        断言点: 异常类型；str(exc) 完全等于固定文案（防敏感信息泄露）
        防回归: 若改为透传原始异常消息，本用例失败（该文案是安全要求）
        """
        with pytest.raises(CertParseException) as excinfo:
            cert_parser.parse_cer_certificate(str(pki["garbage_pem"]))

        assert str(excinfo.value) == "Parse certificate error! "

    def test_missing_file_is_wrapped(self, tmp_path):
        """TC-CERT-005 | 文件不存在时同样抛出包装后的 CertParseException

        输入: parse_cer_certificate(<tmp>/absent.cer)
        预期输出: CertParseException，消息为 "Parse certificate error! "
        断言点: 异常类型 + 完整消息（不包含文件路径）
        防回归: 若直接抛 FileNotFoundError，调用方按 CertParseException 捕获会漏掉，本用例失败
        """
        with pytest.raises(CertParseException) as excinfo:
            cert_parser.parse_cer_certificate(str(tmp_path / "absent.cer"))

        assert str(excinfo.value) == "Parse certificate error! "


class TestParsePemFiles:
    def test_parses_encrypted_private_key(self, pki):
        """TC-CERT-006 | 用正确口令解析加密私钥

        输入: parse_pem_files(server_enc.key, PASSWORD)
        预期输出: RSAPrivateKey，key_size 3072，公钥与 server_enc.cer 匹配
        断言点: 返回类型；key_size；公私钥 public_numbers 相等
        防回归: 若口令未传给 cryptography（或多传空字节串），加密私钥无法解析，本用例失败
        """
        key = cert_parser.parse_pem_files(str(pki["enc_key"]), PASSWORD.encode())

        assert isinstance(key, rsa.RSAPrivateKey)
        assert key.key_size == 3072
        assert key.public_key().public_numbers() == pki["enc_cert_obj"].public_key().public_numbers()
        assert key.public_key().public_numbers() != pki["server_cert_obj"].public_key().public_numbers()

    def test_parses_plain_private_key_without_password(self, pki):
        """TC-CERT-007 | 未加密私钥在不传口令时正常解析

        输入: parse_pem_files(server.key, None)
        预期输出: RSAPrivateKey，key_size 3072
        断言点: 返回类型与 key_size
        防回归: 若实现总是传 b"" 作为口令，未加密私钥会解析失败，本用例失败
        """
        key = cert_parser.parse_pem_files(str(pki["server_key"]), None)

        assert isinstance(key, rsa.RSAPrivateKey)
        assert key.key_size == 3072

    def test_wrong_password_is_wrapped(self, pki):
        """TC-CERT-008 | 错误口令解析失败并包装为固定文案

        输入: parse_pem_files(server_enc.key, b"WrongPass#1")
        预期输出: CertParseException，消息恰为 "Parse private key error! "
        断言点: 异常类型 + 完整消息
        防回归: 若口令错误被静默忽略返回 None，调用方会拿 None 做后续判断，本用例失败
        """
        with pytest.raises(CertParseException) as excinfo:
            cert_parser.parse_pem_files(str(pki["enc_key"]), b"WrongPass#1")

        assert str(excinfo.value) == "Parse private key error! "

    def test_password_for_unencrypted_key_is_wrapped(self, pki):
        """TC-CERT-009 | 给未加密私钥传口令时报错而不是静默成功

        输入: parse_pem_files(server.key, b"RegTest#2026")
        预期输出: CertParseException，消息为 "Parse private key error! "
        断言点: 异常类型 + 完整消息
        防回归: 若口令与加密状态不匹配时返回密钥，配置错误会被掩盖，本用例失败
        """
        with pytest.raises(CertParseException) as excinfo:
            cert_parser.parse_pem_files(str(pki["server_key"]), PASSWORD.encode())

        assert str(excinfo.value) == "Parse private key error! "

    def test_garbage_key_file_is_wrapped(self, pki):
        """TC-CERT-010 | 非私钥内容被拒绝并包装

        输入: parse_pem_files(garbage_cer)（CRL 头 + 非法内容）
        预期输出: CertParseException，消息为 "Parse private key error! "
        断言点: 异常类型 + 完整消息
        防回归: 若把证书文件当私钥读而不校验，后续签名会在运行期才失败，本用例失败
        """
        with pytest.raises(CertParseException) as excinfo:
            cert_parser.parse_pem_files(str(pki["garbage_cer"]), None)

        assert str(excinfo.value) == "Parse private key error! "


class TestParseCrlList:
    def test_parses_crl_with_revoked_serials(self, pki):
        """TC-CERT-011 | 解析 PEM CRL，保留吊销序列号与有效期

        输入: parse_crl_list(revocationlist.crl)
        预期输出: CertificateRevocationList，issuer 为 Coverage CA，
              吊销列表含 server 证书序列号，extensions 非空（v2）
        断言点: issuer；吊销条目集合；last_update/next_update；extensions 数量 > 0
        防回归: 若 CRL 解析返回 None 或丢弃吊销条目，吊销检查会永远通过，本用例失败
        """
        crl = cert_parser.parse_crl_list(str(pki["crl"]))

        assert isinstance(crl, x509.CertificateRevocationList)
        assert crl.issuer == pki["ca_cert"].subject
        assert pki["server_cert_obj"].serial_number in {entry.serial_number for entry in crl}
        assert len(crl.extensions) > 0
        assert crl.last_update_utc < crl.next_update_utc

    def test_der_crl_is_rejected_with_reason(self, pki):
        """TC-CERT-012 | DER 二进制 CRL 被拒绝并说明原因

        输入: 把 CRL 以 DER 编码写出后解析
        预期输出: CertParseException，消息含 "Unsupported der binary type"
        断言点: 异常类型 + 消息关键字
        防回归: 若 DER CRL 进入 PEM 解析路径，会抛泄露细节的底层异常，本用例失败
        """
        der_path = pki["root"] / "der.crl"
        der_path.write_bytes(cert_parser.parse_crl_list(str(pki["crl"])).public_bytes(
            serialization.Encoding.DER))

        with pytest.raises(CertParseException, match="Unsupported der binary type"):
            cert_parser.parse_crl_list(str(der_path))

    def test_corrupt_crl_is_wrapped(self, pki):
        """TC-CERT-013 | 损坏的 CRL 内容被包装为固定文案

        输入: parse_crl_list(garbage_cer)
        预期输出: CertParseException，消息恰为 "Parse crl file error! "
        断言点: 异常类型 + 完整消息
        防回归: 若透传底层异常消息（含 ASN.1 细节），本用例失败
        """
        with pytest.raises(CertParseException) as excinfo:
            cert_parser.parse_crl_list(str(pki["garbage_cer"]))

        assert str(excinfo.value) == "Parse crl file error! "

    def test_missing_crl_file_is_wrapped(self, tmp_path):
        """TC-CERT-014 | CRL 文件不存在时抛出包装后的异常

        输入: parse_crl_list(<tmp>/absent.crl)
        预期输出: CertParseException，消息为 "Parse crl file error! "
        断言点: 异常类型 + 完整消息
        防回归: 若抛 FileNotFoundError，命令行预检按类型捕获会漏判，本用例失败
        """
        with pytest.raises(CertParseException) as excinfo:
            cert_parser.parse_crl_list(str(tmp_path / "absent.crl"))

        assert str(excinfo.value) == "Parse crl file error! "


# --------------------------------------------------------------------------
# PathValidator / validation links
# --------------------------------------------------------------------------

class TestPathValidator:
    def test_required_empty_path_reports_config_tip(self, pki):
        """TC-CERT-020 | 必填路径为空：判定失败并给出配置项提示

        输入: PathValidator("", suffix=".cer", is_required=True, conf_tip="ssl_certfile")
        预期输出: ValidationResult(is_valid=False)，消息含 "Cert file path is empty!"、
              '"ssl_certfile"' 与 "etc/conf/server.conf"
        断言点: is_valid；消息中的三处关键字
        防回归: 若必填校验被跳过，缺失证书的部署会带病启动，本用例失败
        """
        result = PathValidator("", suffix=".cer", is_required=True,
                               conf_tip="ssl_certfile").validate()

        assert result.is_valid is False
        assert "Cert file path is empty!" in result.message
        assert '"ssl_certfile"' in result.message
        assert "etc/conf/server.conf" in result.message

    def test_optional_empty_path_is_accepted(self, pki):
        """TC-CERT-021 | 选填路径为空视为"未配置"，判定通过

        输入: PathValidator("", suffix="", is_required=False)
        预期输出: ValidationResult(True, "Not config! ")
        断言点: is_valid 为 True；消息恰为 "Not config! "
        防回归: 若选填项为空也报错，未配置 CRL 的部署无法启动，本用例失败
        """
        result = PathValidator("", suffix="", is_required=False).validate()

        assert result.is_valid is True
        assert result.message == "Not config! "

    def test_missing_file_reports_absolute_path(self, tmp_path, pki):
        """TC-CERT-022 | 路径存在性校验失败时回显配置的绝对路径

        输入: PathValidator(<tmp>/absent.cer, suffix=".cer")
        预期输出: is_valid=False，消息含 "Cert file not exist：" 与传入的完整路径
        断言点: is_valid；消息中的固定前缀与路径
        防回归: 若存在性校验被删除，后续解析才报错且提示不含配置路径，本用例失败
        """
        missing = str(tmp_path / "absent.cer")

        result = PathValidator(missing, suffix=".cer", conf_tip="ssl_certfile").validate()

        assert result.is_valid is False
        assert "Cert file not exist：" in result.message
        assert missing in result.message

    def test_extension_check_is_case_insensitive(self, tmp_path, pki):
        """TC-CERT-023 | 后缀校验大小写不敏感，错误后缀被拒绝

        输入: 把 server.cer 复制为 SERVER.CER（放行）、改名为 server.pem（拒绝）
        预期输出: .CER -> True；.pem -> False 且消息含 "extension is not support"
        断言点: 两次 is_valid；失败消息关键字
        防回归: 若后缀比较未 lower()，Windows 导出的大写后缀会被误拒，本用例失败
        """
        upper = tmp_path / "SERVER.CER"
        upper.write_bytes(pki["server_cert"].read_bytes())
        wrong = tmp_path / "server.pem"
        wrong.write_bytes(pki["server_cert"].read_bytes())

        assert PathValidator(str(upper), suffix=".cer").validate().is_valid is True
        rejected = PathValidator(str(wrong), suffix=".cer", conf_tip="ssl_certfile").validate()
        assert rejected.is_valid is False
        assert "extension is not support" in rejected.message

    def test_empty_suffix_skips_extension_check(self, tmp_path, pki):
        """TC-CERT-024 | suffix 为空时跳过后缀校验（口令文件等无后缀资源）

        输入: 无后缀的密码文件，PathValidator(path, suffix="")
        预期输出: is_valid True，消息为空串
        断言点: is_valid；message == ""
        防回归: 若空 suffix 仍做后缀比较，密码文件永远过不了校验，本用例失败
        """
        password_file = tmp_path / "cert_pwd"
        password_file.write_text("secret", encoding="utf-8")

        result = PathValidator(str(password_file), suffix="").validate()

        assert result.is_valid is True
        assert result.message == ""

    def test_optional_flag_only_relaxes_the_empty_check(self, tmp_path):
        """TC-CERT-025 | is_required 只放开"路径为空"，配了路径却缺文件仍失败

        输入: PathValidator(<tmp>/absent.crl, suffix=".crl", is_required=False) 与
              PathValidator("", suffix=".crl", is_required=False)
        预期输出: 前者 is_valid False 且消息含 "Cert file not exist："；
              后者 is_valid True 且消息 "Not config! "
        断言点: 两次 is_valid 与消息（明确"未配置"与"配置错误"的分界）
        防回归: 若把缺失文件也当作可选放行，CRL/CA 路径写错会被静默忽略，本用例失败
        """
        missing = str(tmp_path / "absent.crl")

        configured = PathValidator(missing, suffix=".crl", is_required=False).validate()
        omitted = PathValidator("", suffix=".crl", is_required=False).validate()

        assert configured.is_valid is False
        assert "Cert file not exist：" in configured.message
        assert omitted.is_valid is True
        assert omitted.message == "Not config! "


class TestValidatorLinks:
    def test_path_link_requires_trust_material_for_mutual_tls(self, pki):
        """TC-CERT-026 | 双向认证时路径校验链包含 CA 与 CRL（5 项），单向时只有 3 项

        输入: ConfObj(verify_client=true) 与 ConfObj(verify_client=false)
        预期输出: 前者 5 个 PathValidator 且第 4 项 conf_tip 为 ssl_ca_certs；
              后者 3 项
        断言点: 链长度；第 4 项后缀/必填性；以及完整路径校验的最终结果
        防回归: 若 CERT_NONE 判断反了，单向部署会强制要求 CA 文件，本用例失败
        """
        mutual = PathValidatorLink(_conf(pki))
        one_way = PathValidatorLink(_conf(pki, verify_client="false"))

        assert len(mutual.link) == 5
        assert mutual.link[3].suffix == ".cer"
        assert mutual.link[4].suffix == ".crl"
        assert mutual.link[4].is_required is False
        assert len(one_way.link) == 3
        mutual_result = mutual.validate()
        one_way_result = one_way.validate()
        assert mutual_result.is_valid is True, mutual_result.message
        assert one_way_result.is_valid is True, one_way_result.message

    def test_path_link_stops_at_first_invalid_link(self, pki):
        """TC-CERT-027 | 路径校验链在第一个失败项处短路返回该项结果

        输入: ConfObj 的 ssl_certfile 指向不存在文件，其余合法
        预期输出: is_valid False，消息指向 ssl_certfile（而不是后续 ssl_keyfile）
        断言点: is_valid；消息含 "ssl_certfile" 且不含 "ssl_keyfile\""
        防回归: 若链路忽略中间失败继续跑，错误提示会指向最后一个配置项，本用例失败
        """
        conf = _conf(pki, ssl_certfile=str(pki["root"] / "absent.cer"))

        result = PathValidatorLink(conf).validate()

        assert result.is_valid is False
        assert '"ssl_certfile"' in result.message
        assert '"ssl_keyfile"' not in result.message

    def test_cer_link_includes_ca_only_when_verifying_clients(self, pki):
        """TC-CERT-028 | 内容校验链在双向认证时额外校验信任证书

        输入: ConfObj(verify_client=true) 与 ConfObj(verify_client=false)
        预期输出: 前者 2 个 CerContentValidator（ssl_certfile、ssl_ca_certs），后者 1 个
        断言点: 链长度；两条链的整体校验结果均为通过
        防回归: 若 CA 证书内容校验被漏掉，过期/弱算法的信任锚可被加载，本用例失败
        """
        mutual = CerContentValidatorLink(_conf(pki))
        one_way = CerContentValidatorLink(_conf(pki, verify_client="false"))

        assert len(mutual.link) == 2
        assert mutual.link[0].cert_path == str(pki["enc_cert"])
        assert mutual.link[1].cert_path == str(pki["ca"])
        assert len(one_way.link) == 1
        assert mutual.validate().is_valid is True
        assert one_way.validate().is_valid is True


# --------------------------------------------------------------------------
# CommonContentValidator key/validity helpers
# --------------------------------------------------------------------------

class TestContentHelpers:
    def test_public_key_length_rules(self, pki):
        """TC-CERT-029 | 公钥强度规则：RSA≥3072、EC≥256，其它算法一律拒绝

        输入: 3072 位 RSA、2048 位 RSA、P-256 EC 的公钥，以及一个非密钥对象
        预期输出: True、False、True、False
        断言点: 四个返回值（逐项断言，覆盖两个 isinstance 分支与兜底 return False）
        防回归: 若阈值从 3072 降到 2048，弱密钥证书会被放行，本用例失败
        """
        assert CommonContentValidator.validate_public_key_length(
            pki["server_cert_obj"].public_key()) is True
        assert CommonContentValidator.validate_public_key_length(
            cert_parser.parse_cer_certificate(str(pki["weak_cert"])).cert_list[0].public_key) is False
        assert CommonContentValidator.validate_public_key_length(
            cert_parser.parse_cer_certificate(str(pki["ec_cert"])).cert_list[0].public_key) is True
        assert CommonContentValidator.validate_public_key_length(object()) is False

    def test_private_key_length_rules(self, pki):
        """TC-CERT-030 | 私钥强度规则：RSA≥3072、EC≥256，其它对象一律拒绝

        输入: 3072 位 RSA 私钥、2048 位 RSA 私钥、P-256 EC 私钥、非密钥对象
        预期输出: True、False、True、False
        断言点: 四个返回值（覆盖两个 isinstance 分支与兜底 return False）
        防回归: 若私钥强度检查只判 RSA，EC 密钥会被误拒，本用例失败
        """
        weak_key = cert_parser.parse_pem_files(str(pki["weak_enc_key"]), PASSWORD.encode())
        ec_key = cert_parser.parse_pem_files(str(pki["ec_key"]), None)

        assert CommonContentValidator.validate_private_key_length(
            cert_parser.parse_pem_files(str(pki["server_key"]), None)) is True
        assert CommonContentValidator.validate_private_key_length(weak_key) is False
        assert CommonContentValidator.validate_private_key_length(ec_key) is True
        assert CommonContentValidator.validate_private_key_length(object()) is False

    def test_certificate_validity_accepts_current_and_rejects_boundaries(self, pki):
        """TC-CERT-031 | 有效期判定：当前时间在区间内通过，过期/未生效/非法时间串拒绝

        输入: 合法证书、过期证书、未生效证书（not_before 在未来）、
              以及手工构造 valid_from="not-a-date" 的 X509Obj
        预期输出: True、False、False、False
        断言点: 四个返回值（覆盖 ValueError 分支与 out-of-range 分支）
        防回归: 若时间比较方向写反（now < valid_from 也被放行），过期证书可用，本用例失败
        """
        valid = cert_parser.parse_cer_certificate(str(pki["server_cert"]))
        expired = cert_parser.parse_cer_certificate(str(pki["expired_cert"]))
        future = X509Obj(cert_list=[CertObj.from_dict({
            "valid_from": (datetime.datetime.now(datetime.timezone.utc)
                           + datetime.timedelta(days=1)).isoformat(),
            "valid_to": (datetime.datetime.now(datetime.timezone.utc)
                         + datetime.timedelta(days=2)).isoformat(),
            "public_key": pki["server_cert_obj"].public_key(),
        })])
        malformed = X509Obj(cert_list=[CertObj.from_dict({"valid_from": "not-a-date",
                                                          "valid_to": "also-bad"})])

        assert CommonContentValidator.validate_certificate_validity(valid) is True
        assert CommonContentValidator.validate_certificate_validity(expired) is False
        assert CommonContentValidator.validate_certificate_validity(future) is False
        assert CommonContentValidator.validate_certificate_validity(malformed) is False

    def test_base_validate_is_inert(self, pki):
        """TC-CERT-032 | 内容校验基类的 validate 不返回结果（由子类实现）

        输入: CommonContentValidator("any").validate()
        预期输出: None
        断言点: 返回值 is None
        防回归: 若基类改为返回 True，未覆盖的校验器会被当作"通过"，本用例失败
        """
        assert CommonContentValidator("any").validate() is None


class TestCerContentValidator:
    def test_valid_rsa_certificate_passes(self, pki):
        """TC-CERT-033 | 3072 位 RSA 证书通过内容校验并回显路径

        输入: CerContentValidator(server.cer, conf_tip="ssl_certfile")
        预期输出: is_valid True，消息含 "CER certificate validation passed!" 与证书路径
        断言点: is_valid；消息中的固定文案与路径
        防回归: 若通过消息里的路径被改成别的配置项，排障会指向错误文件，本用例失败
        """
        result = CerContentValidator(str(pki["server_cert"]), conf_tip="ssl_certfile").validate()

        assert result.is_valid is True
        assert "CER certificate validation passed!" in result.message
        assert str(pki["server_cert"]) in result.message

    def test_valid_ec_certificate_passes(self, pki):
        """TC-CERT-034 | P-256 EC 证书按 ≥256 位规则通过

        输入: CerContentValidator(ec.cer)
        预期输出: is_valid True
        断言点: is_valid；消息含 "validation passed"
        防回归: 若只接受 RSA，国密/EC 部署无法启动，本用例失败
        """
        result = CerContentValidator(str(pki["ec_cert"]), conf_tip="ssl_certfile").validate()

        assert result.is_valid is True
        assert "CER certificate validation passed!" in result.message

    def test_empty_certificate_list_is_rejected(self, pki):
        """TC-CERT-035 | 解析结果为空证书列表时明确拒绝（而非静默通过）

        输入: monkeypatch parse_cer_certificate 返回 X509Obj(cert_list=[])
        预期输出: is_valid False，消息含 "No certificate found!"
        断言点: is_valid；消息关键字；conf_tip 中的配置项名
        防回归: 若空列表被当作"无需校验"放行，空证书文件可启动服务，本用例失败
        """
        import common.cert.cert_validater as module
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(module.cert_parser, "parse_cer_certificate",
                          lambda path: X509Obj(cert_list=[]))
            result = CerContentValidator(str(pki["server_cert"]), conf_tip="ssl_certfile").validate()

        assert result.is_valid is False
        assert "No certificate found!" in result.message
        assert '"ssl_certfile"' in result.message

    def test_non_v3_certificate_is_rejected(self, pki):
        """TC-CERT-036 | 非 X.509v3 证书被拒绝

        输入: monkeypatch parse_cer_certificate 返回 version=v1 的 CertObj
              （CertificateBuilder 只产出 v3，故用解析结果替身）
        预期输出: is_valid False，消息含 "Certificate format is not X.509v3"
        断言点: is_valid；消息关键字
        防回归: 若 v3 校验被删除，缺少扩展约束的旧证书可通过，本用例失败
        """
        import common.cert.cert_validater as module
        legacy = X509Obj(cert_list=[CertObj.from_dict({
            "version": x509.Version.v1,
            "public_key": pki["server_cert_obj"].public_key(),
            "valid_from": pki["server_cert_obj"].not_valid_before_utc.isoformat(),
            "valid_to": pki["server_cert_obj"].not_valid_after_utc.isoformat(),
        })])
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(module.cert_parser, "parse_cer_certificate", lambda path: legacy)
            result = CerContentValidator(str(pki["server_cert"]), conf_tip="ssl_certfile").validate()

        assert result.is_valid is False
        assert "Certificate format is not X.509v3" in result.message

    def test_weak_rsa_key_is_rejected(self, pki):
        """TC-CERT-037 | 2048 位 RSA 证书因密钥长度不达标被拒绝

        输入: CerContentValidator(weak.cer)
        预期输出: is_valid False，消息含 "key algorithm or length does not meet requirements"
        断言点: is_valid；消息关键字
        防回归: 若强度阈值被下调，2048 位证书可通过校验，本用例失败
        """
        result = CerContentValidator(str(pki["weak_cert"]), conf_tip="ssl_certfile").validate()

        assert result.is_valid is False
        assert "key algorithm or length does not meet requirements" in result.message

    def test_expired_certificate_is_rejected(self, pki):
        """TC-CERT-038 | 过期证书因有效期不通过被拒绝

        输入: CerContentValidator(expired.cer)
        预期输出: is_valid False，消息含 "Certificate is not valid at current time."
        断言点: is_valid；消息关键字
        防回归: 若有效期校验被跳过，过期证书可继续对外提供 TLS，本用例失败
        """
        result = CerContentValidator(str(pki["expired_cert"]), conf_tip="ssl_certfile").validate()

        assert result.is_valid is False
        assert "Certificate is not valid at current time." in result.message

    def test_parse_failure_is_reported_with_conf_tip(self, pki):
        """TC-CERT-039 | 解析异常被转成校验失败，并附带配置项提示

        输入: CerContentValidator(garbage.pem)
        预期输出: is_valid False，消息以 "Parse certificate error!" 开头且含 '"ssl_certfile"'
        断言点: is_valid；消息前缀与配置项提示
        防回归: 若异常直接向上抛，CLI 预检会以栈回溯退出而不是友好提示，本用例失败
        """
        result = CerContentValidator(str(pki["garbage_pem"]), conf_tip="ssl_certfile").validate()

        assert result.is_valid is False
        assert result.message.startswith("Parse certificate error!")
        assert '"ssl_certfile"' in result.message


class TestPrivateKeyValidator:
    def test_password_complexity_matrix(self, pki):
        """TC-CERT-040 | 口令复杂度：长度≥8 且至少两类字符

        输入: "", "Ab1!ab"（6 位）, "abcdefgh"（单类）, "Abcdefgh"（两类）, "RegTest#2026"
        预期输出: False、False、False、True、True
        断言点: 五个返回值（分别命中长度不足、单类字符两个拒绝分支与通过分支）
        防回归: 若字符类别阈值从 2 改为 1，纯字母口令会被接受，本用例失败
        """
        validator = PrivateKeyValidator(str(pki["enc_key"]))

        assert validator.password_verify("") is False
        assert validator.password_verify("Ab1!ab") is False
        assert validator.password_verify("abcdefgh") is False
        assert validator.password_verify("Abcdefgh") is True
        assert validator.password_verify(PASSWORD) is True

    def test_valid_password_and_matching_key_passes(self, pki):
        """TC-CERT-041 | 口令正确且私钥与证书匹配时通过，并清空口令缓存

        输入: PrivateKeyValidator(server_enc.key, PASSWORD, server_path=server_enc.cer)
        预期输出: is_valid True，消息含 "PEM privatekey validation passed!"；
              validate() 结束后 password_bytes 被置为 b''（finally）
        断言点: is_valid；消息；password_bytes 为空字节串
        防回归: 若 finally 清理被删除，口令以明文常驻内存，本用例失败
        """
        validator = PrivateKeyValidator(str(pki["enc_key"]), PASSWORD.encode(),
                                        server_path=str(pki["enc_cert"]),
                                        conf_tip="ssl_keyfile")

        result = validator.validate()

        assert result.is_valid is True
        assert "PEM privatekey validation passed!" in result.message
        assert validator.password_bytes == b''

    def test_weak_password_is_rejected_before_key_parsing(self, pki):
        """TC-CERT-042 | 弱口令在校验早期被拒绝，消息给出复杂度规则

        输入: PrivateKeyValidator(server_enc.key, b"abcdefgh")
        预期输出: is_valid False，消息含 "too week" 与 "Min length is 8"
        断言点: is_valid；消息中的两处关键字
        防回归: 若口令复杂度校验被跳过，弱口令私钥可直接加载，本用例失败
        """
        result = PrivateKeyValidator(str(pki["enc_key"]), b"abcdefgh",
                                     server_path=str(pki["enc_cert"])).validate()

        assert result.is_valid is False
        assert "too week" in result.message
        assert "Min length is 8" in result.message

    def test_weak_private_key_is_rejected(self, pki):
        """TC-CERT-043 | 2048 位私钥因强度不足被拒绝

        输入: PrivateKeyValidator(weak_enc.key, PASSWORD, server_path=weak.cer)
        预期输出: is_valid False，消息含 "key algorithm or length does not meet requirements"
        断言点: is_valid；消息关键字
        防回归: 若私钥强度校验缺失，弱口令/弱密钥组合可上线，本用例失败
        """
        result = PrivateKeyValidator(str(pki["weak_enc_key"]), PASSWORD.encode(),
                                     server_path=str(pki["weak_cert"])).validate()

        assert result.is_valid is False
        assert "key algorithm or length does not meet requirements" in result.message

    def test_key_not_matching_certificate_is_rejected(self, pki):
        """TC-CERT-044 | 私钥与身份证书不匹配时拒绝，并指向相关配置项

        输入: PrivateKeyValidator(server_enc.key, PASSWORD, server_path=ca.cer)
        预期输出: is_valid False，消息含 "does not match the CER identity certificate"
        断言点: is_valid；消息关键字
        防回归: 若公钥比对被删除，加载不匹配的密钥对会在 TLS 握手期才失败，本用例失败
        """
        result = PrivateKeyValidator(str(pki["enc_key"]), PASSWORD.encode(),
                                     server_path=str(pki["ca"])).validate()

        assert result.is_valid is False
        assert "does not match the CER identity certificate" in result.message

    def test_wrong_password_reports_parse_error_and_clears_secret(self, pki):
        """TC-CERT-045 | 口令错误时返回解析失败，且异常路径同样清空口令缓存

        输入: PrivateKeyValidator(server_enc.key, b"WrongPass#1", server_path=server_enc.cer)
        预期输出: is_valid False，消息含 "Parse private key error!"；password_bytes == b''
        断言点: is_valid；消息关键字；finally 中的清理动作
        防回归: 若 except 分支绕过 finally（或提前 return 前不清空），本用例失败
        """
        validator = PrivateKeyValidator(str(pki["enc_key"]), b"WrongPass#1",
                                        server_path=str(pki["enc_cert"]))

        result = validator.validate()

        assert result.is_valid is False
        assert "Parse private key error!" in result.message
        assert validator.password_bytes == b''

    def test_missing_password_bytes_is_reported(self, pki):
        """TC-CERT-046 | 未提供口令字节时按校验失败返回，而不是抛 AttributeError

        输入: PrivateKeyValidator(server_enc.key, password_bytes=None)
        预期输出: is_valid False，消息含 "NoneType" 与配置项提示
        断言点: is_valid；消息关键字；password_bytes 被置空
        防回归: 若异常未被捕获，口令文件缺失会让服务启动崩溃而非给出配置提示，本用例失败
        """
        validator = PrivateKeyValidator(str(pki["enc_key"]), None,
                                        server_path=str(pki["enc_cert"]),
                                        conf_tip="ssl_keyfile")

        result = validator.validate()

        assert result.is_valid is False
        assert "NoneType" in result.message
        assert '"ssl_keyfile"' in result.message
        assert validator.password_bytes == b''


class TestCrlValidator:
    def test_absent_crl_is_optional(self, pki):
        """TC-CERT-047 | 未配置 CRL 时校验通过并说明"未配置"

        输入: CRLValidator("")
        预期输出: is_valid True，消息为 "CRL not config! "
        断言点: is_valid；完整消息
        防回归: 若把可选 CRL 当作必填，未配置吊销列表的部署无法启动，本用例失败
        """
        result = CRLValidator("", conf_tip="ssl_crl_file").validate()

        assert result.is_valid is True
        assert result.message == "CRL not config! "

    def test_missing_crl_file_is_rejected(self, tmp_path):
        """TC-CERT-048 | CRL 路径配置了但文件不存在：拒绝并回显路径

        输入: CRLValidator(<tmp>/absent.crl)
        预期输出: is_valid False，消息含 "CRL file not exist：" 与路径
        断言点: is_valid；消息前缀与路径
        防回归: 若存在性校验缺失，后续解析异常会掩盖"文件没部署"这一根因，本用例失败
        """
        missing = str(tmp_path / "absent.crl")

        result = CRLValidator(missing, conf_tip="ssl_crl_file").validate()

        assert result.is_valid is False
        assert "CRL file not exist：" in result.message
        assert missing in result.message

    def test_crl_without_extensions_is_not_v2(self, pki):
        """TC-CERT-049 | 无扩展的 CRL 被判为 v1，拒绝使用

        输入: CRLValidator(revocationlist_v1.crl)（构建时未添加任何扩展）
        预期输出: is_valid False，消息含 "CRL format is not X.509v2."
        断言点: is_valid；消息关键字；crl_list_data 已载入解析结果
        防回归: 若 v2 判定被删除，缺少 nextUpdate 约束的 v1 CRL 会被信任，本用例失败
        """
        validator = CRLValidator(str(pki["crl_v1"]), conf_tip="ssl_crl_file")

        result = validator.validate()

        assert result.is_valid is False
        assert "CRL format is not X.509v2." in result.message
        assert len(validator.crl_list_data.extensions) == 0

    def test_expired_crl_is_rejected(self, pki):
        """TC-CERT-050 | 已过期的 CRL 被拒绝

        输入: CRLValidator(revocationlist_expired.crl)（nextUpdate 已过）
        预期输出: is_valid False，消息含 "CRL is not valid at current time."
        断言点: is_valid；消息关键字
        防回归: 若有效期校验被跳过，过期吊销列表会继续生效（吊销失效），本用例失败
        """
        result = CRLValidator(str(pki["crl_expired"]), conf_tip="ssl_crl_file").validate()

        assert result.is_valid is False
        assert "CRL is not valid at current time." in result.message

    def test_valid_crl_passes_and_caches_list(self, pki):
        """TC-CERT-051 | 有效 CRL 通过校验并缓存解析结果供后续吊销查询

        输入: CRLValidator(revocationlist.crl)
        预期输出: is_valid True，消息含 "CRL validation passed!"；
              crl_list_data 为解析出的 CRL，且含被吊销的 server 序列号
        断言点: is_valid；消息；缓存的 CRL 类型与吊销条目
        防回归: 若不再缓存 crl_list_data，运行期吊销检查拿不到列表，本用例失败
        """
        validator = CRLValidator(str(pki["crl"]), conf_tip="ssl_crl_file")

        result = validator.validate()

        assert result.is_valid is True
        assert "CRL validation passed!" in result.message
        assert isinstance(validator.crl_list_data, x509.CertificateRevocationList)
        assert pki["server_cert_obj"].serial_number in {
            entry.serial_number for entry in validator.crl_list_data}

    def test_corrupt_crl_is_reported_as_failure(self, pki):
        """TC-CERT-052 | CRL 内容损坏时返回失败并保留配置提示

        输入: CRLValidator(garbage_cer)
        预期输出: is_valid False，消息含 "Parse crl file error!" 与 '"ssl_crl_file"'
        断言点: is_valid；消息中的两处关键字
        防回归: 若解析异常向上抛出，启动流程会以栈回溯中断，本用例失败
        """
        result = CRLValidator(str(pki["garbage_cer"]), conf_tip="ssl_crl_file").validate()

        assert result.is_valid is False
        assert "Parse crl file error!" in result.message
        assert '"ssl_crl_file"' in result.message


class TestCertValidator:
    def test_missing_config_file_blocks_validation(self, monkeypatch, pki, tmp_path):
        """TC-CERT-053 | 缺少 server.conf 时直接判定失败并提示配置路径

        输入: monkeypatch CONFIG_FILE_PATH 指向不存在的文件
        预期输出: is_valid False，消息含 "Config file not exists!" 与 "etc/conf/server.conf"
        断言点: is_valid；消息中的两处关键字
        防回归: 若跳过配置文件存在性检查，空配置会被当作默认值启动，本用例失败
        """
        import common.cert.cert_validater as module
        monkeypatch.setattr(module, "CONFIG_FILE_PATH", str(tmp_path / "absent.conf"))

        result = CertValidator(_conf(pki)).validate()

        assert result.is_valid is False
        assert "Config file not exists!" in result.message
        assert "etc/conf/server.conf" in result.message

    def test_full_valid_chain_with_mutual_tls(self, config_file, pki):
        """TC-CERT-054 | 完整校验链（路径→证书内容→私钥→CRL）全部通过并缓存 CRL

        输入: 合法 server.conf + server_enc.cer/enc.key(口令)/ca.cer/CRL，verify_client=true
        预期输出: is_valid True，消息为 CRL 阶段的通过文案；conf_obj.crl_list_data 为解析出的 CRL
        断言点: is_valid；消息内容；缓存对象类型与吊销序列号
        防回归: 若任一步骤被短路（例如 CRL 缓存不再写回 conf_obj），本用例失败
        """
        conf = _conf(pki)
        conf.crl_list_data = "stale"

        result = CertValidator(conf).validate()

        assert result.is_valid is True, result.message
        assert result.message == f"CRL validation passed! {pki['crl']}"
        assert isinstance(conf.crl_list_data, x509.CertificateRevocationList)
        assert pki["server_cert_obj"].serial_number in {
            entry.serial_number for entry in conf.crl_list_data}

    def test_one_way_tls_skips_crl_and_clears_cache(self, config_file, pki):
        """TC-CERT-055 | 单向认证不校验 CRL，并把缓存显式清空

        输入: verify_client=false、ssl_crl_file 指向不存在的文件
        预期输出: is_valid True；conf_obj.crl_list_data 被置为 None（即使预置了旧值）
        断言点: is_valid；crl_list_data is None
        防回归: 若 CERT_NONE 分支不清理缓存，上一轮配置的吊销列表会被误用，本用例失败
        """
        conf = _conf(pki, verify_client="false", ssl_crl_file=str(pki["root"] / "absent.crl"))
        conf.crl_list_data = "stale"

        result = CertValidator(conf).validate()

        assert result.is_valid is True, result.message
        assert result.message == ""
        assert conf.crl_list_data is None

    def test_path_stage_failure_is_returned_verbatim(self, config_file, pki):
        """TC-CERT-056 | 路径阶段失败时直接返回该阶段结果（不进入内容校验）

        输入: ssl_certfile 指向不存在文件
        预期输出: is_valid False，消息指向 ssl_certfile
        断言点: is_valid；消息含 '"ssl_certfile"'（而非 PEM/CRL 阶段文案）
        防回归: 若路径校验失败后仍继续执行，后续会以误导性错误覆盖根因，本用例失败
        """
        result = CertValidator(_conf(pki, ssl_certfile=str(pki["root"] / "absent.cer"))).validate()

        assert result.is_valid is False
        assert '"ssl_certfile"' in result.message
        assert "not exist" in result.message

    def test_content_stage_failure_is_returned_verbatim(self, config_file, pki):
        """TC-CERT-057 | 证书内容阶段失败时返回该阶段结果

        输入: ssl_certfile 指向 2048 位弱证书
        预期输出: is_valid False，消息含 "key algorithm or length"
        断言点: is_valid；消息关键字
        防回归: 若内容校验结果被忽略，弱密钥证书仍能通过启动校验，本用例失败
        """
        result = CertValidator(_conf(pki, ssl_certfile=str(pki["weak_cert"]),
                                     ssl_ca_certs=str(pki["ca"]))).validate()

        assert result.is_valid is False
        assert "key algorithm or length does not meet requirements" in result.message

    def test_private_key_stage_failure_is_returned_verbatim(self, config_file, pki):
        """TC-CERT-058 | 私钥阶段失败时返回该阶段结果并指向 ssl_keyfile

        输入: ssl_keyfile 指向 2048 位加密私钥
        预期输出: is_valid False，消息含 "key algorithm or length" 与 '"ssl_keyfile"'
        断言点: is_valid；消息中的阶段关键字与配置项名
        防回归: 若私钥校验被跳过（只校验证书），弱密钥仍可上线，本用例失败
        """
        result = CertValidator(_conf(pki, ssl_keyfile=str(pki["weak_enc_key"]))).validate()

        assert result.is_valid is False
        assert "key algorithm or length does not meet requirements" in result.message
        assert '"ssl_keyfile"' in result.message
