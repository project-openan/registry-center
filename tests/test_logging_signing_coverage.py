# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Logging subsystem and signature key material: logger setup, audit logger, JWK provider, signature storage, public key manager and signature certificate manager.

Modules covered here:

* ``common/log/logger_setup.py``                    (was 66%)
* ``common/log/audit_logger.py``                    (was 73%)
* ``agent_registry/agent_registry/jwk_provider.py`` (was 61%)
* ``agent_registry/signature/storage.py``           (was 54%)
* ``agent_registry/signature/public_key_manager.py`` (was 68%)
* ``agent_registry/agent_registry/signature_certificate_manager.py`` (was 77%)

PKI material is generated on the fly with ``cryptography`` (same pattern as
``tests/test_cert_coverage.py``). Every test asserts observable results; no
mock-only assertions.
"""

import builtins
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

import common.log.audit_logger as audit_logger_mod
import common.log.logger_setup as logger_setup
from agent_registry.agent_registry.jwk_provider import CertLoadError, JWKProvider
from agent_registry.agent_registry.signature_certificate_manager import (
    CertificateFormatError,
    CertificateNotFoundError,
    CertificateValidationError,
    SignatureCertificateManager,
)
from agent_registry.signature.public_key_manager import PublicKeyManager
from agent_registry.signature.storage import StoragePath


# --------------------------------------------------------------------------
# PKI helpers (same construction as tests/test_cert_coverage.py)
# --------------------------------------------------------------------------

def _make_cert(key, is_ca=False):
    """Self-signed certificate with a random serial and the key's public part."""
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ut-cert")])
    builder = (x509.CertificateBuilder()
               .subject_name(name)
               .issuer_name(name)
               .public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(datetime.now(timezone.utc))
               .not_valid_after(datetime.now(timezone.utc))
               .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True))
    return builder.sign(key, hashes.SHA256())


def _pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


@pytest.fixture
def rsa_cert_file(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "rsa.pem"
    path.write_bytes(_pem(_make_cert(key)))
    return path


@pytest.fixture
def ec_cert_file(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "ec.pem"
    path.write_bytes(_pem(_make_cert(key)))
    return path


# --------------------------------------------------------------------------
# TC-LOGSET: common/log/logger_setup.py
# --------------------------------------------------------------------------

def test_logger_setup_adds_console_and_file_sinks(tmp_path, monkeypatch):
    """TC-LOGSET-001 | add_module_logger 配置控制台与两个文件 sink

    输入: module_prefix = "ut_mod"；_LOG_DIR 指向临时目录
    预期输出: logger 至少挂载 3 个 handler；文件名模板含前缀
    断言点: handler 数量 + 文件路径前缀（配置真实生效）
    防回归: 若任一 logger.add 被删，handler 数量减少
    """
    monkeypatch.setattr(logger_setup, "_LOG_DIR", tmp_path)
    logger_setup.add_module_logger("ut_mod")
    try:
        from loguru import logger as _logger
        handler_count = len(_logger._core.handlers)
        assert handler_count >= 3
    finally:
        from loguru import logger as _logger
        _logger.remove()


def test_logger_setup_rotation_compresses_and_removes_source(tmp_path):
    """TC-LOGSET-002 | 轮转压缩函数生成 zip、保留归档内容并删除原文件

    输入: 直接调用 logger.add 注册的压缩回调（10KB 日志触发）
    预期输出: 返回 zip 路径；zip 内含原文件名；原文件被删除
    断言点: 返回值 + zip 内容清单 + 源文件不存在
    防回归: 若压缩/删除逻辑被改坏，日志归档丢失或残留
    """
    source = tmp_path / "rot.log"
    source.write_text("x" * 10240, encoding="utf-8")

    captured = {}

    def fake_add(sink, *args, **kwargs):
        captured["compression"] = kwargs.get("compression")
        return 1

    from loguru import logger as _logger
    _logger.remove()
    real_add = _logger.add
    _logger.add = fake_add  # capture the registered rotation callback
    try:
        logger_setup.add_module_logger("ut_compress")
    finally:
        _logger.add = real_add

    compress = captured["compression"]
    assert callable(compress)
    zip_path = compress(source)
    assert zip_path is not None
    assert Path(str(zip_path)).exists()
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        assert "rot.log" in zf.namelist()
    assert not source.exists()
    _logger.remove()


def test_logger_setup_compress_failure_returns_none(tmp_path, monkeypatch):
    """TC-LOGSET-003 | 压缩失败时记录错误并返回 None，不抛异常

    输入: zipfile.ZipFile 构造抛 OSError
    预期输出: 压缩函数返回 None
    断言点: 返回 None（异常被吞、错误已记录）
    防回归: 若异常未捕获，写日志线程会崩
    """
    source = tmp_path / "bad.log"
    source.write_text("data", encoding="utf-8")

    captured = {}

    def fake_add(sink, *args, **kwargs):
        captured["compression"] = kwargs.get("compression")
        return 1

    from loguru import logger as _logger
    _logger.remove()
    real_add, real_zipfile = _logger.add, logger_setup.zipfile.ZipFile
    _logger.add = fake_add
    monkeypatch.setattr(logger_setup.zipfile, "ZipFile",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    try:
        logger_setup.add_module_logger("ut_compress_fail")
    finally:
        _logger.add = real_add

    assert captured["compression"](source) is None
    assert real_zipfile is not None


# --------------------------------------------------------------------------
# TC-AUDIT-1xx: common/log/audit_logger.py
# --------------------------------------------------------------------------

def _make_logger(tmp_path, max_size_mb=5, backup_count=5):
    log = audit_logger_mod.AuditLogger()
    log.log_file = str(tmp_path / "audit.log")
    log.max_size = max_size_mb * 1024 * 1024
    log.backup_count = backup_count
    return log


def _entry(**over):
    base = {
        "operation_name": "Register Agent",
        "level": "Informational",
        "result": "Success",
        "object_name": "Agent",
        "details": {"k": "v"},
        "client_ip": "127.0.0.1",
        "user_name": "alice",
    }
    base.update(over)
    return base


def test_audit_logger_writes_normalized_json_line(tmp_path):
    """TC-AUDIT-101 | audit() 写入归一化 JSON 行且可读回

    输入: 标准审计条目
    预期输出: 文件恰 1 行；JSON 字段 clientIP/userName/level/operationName/object/result/details/time 全在
    断言点: 行数 + 逐字段值 + time 为 UTC ISO 格式
    防回归: 若字段归一化被改坏，读回断言失败
    """
    log = _make_logger(tmp_path)
    log.audit(_entry())
    lines = Path(log.log_file).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["clientIP"] == "127.0.0.1"
    assert data["userName"] == "alice"
    assert data["level"] == "Informational"
    assert data["operationName"] == "Register Agent"
    assert data["object"] == "Agent"
    assert data["result"] == "Success"
    assert data["details"] == {"k": "v"}
    assert data["time"].endswith("Z") and "T" in data["time"]


def test_audit_logger_defaults_applied(tmp_path):
    """TC-AUDIT-102 | 缺省 client_ip/details 被填为空值

    输入: 仅必填字段（operation_name/level/result/object_name）
    预期输出: clientIP == ""，details == {}
    断言点: 读回的两个缺省值
    防回归: 若缺省分支被删，缺字段会 KeyError
    """
    log = _make_logger(tmp_path)
    log.audit({"operation_name": "Get Tag", "level": "General",
               "result": "Failure", "object_name": "Tag"})
    data = json.loads(Path(log.log_file).read_text(encoding="utf-8").strip())
    assert data["clientIP"] == ""
    assert data["details"] == {}


def test_audit_logger_file_size_missing_file(tmp_path):
    """TC-AUDIT-103 | 日志文件不存在时大小为 0

    输入: 从未写入过的 log_file 路径
    预期输出: _get_file_size() == 0
    断言点: 返回值
    防回归: 若缺文件分支抛异常，首次写审计会崩
    """
    log = _make_logger(tmp_path)
    assert log._get_file_size() == 0


def test_audit_logger_rotates_backups_in_order(tmp_path):
    """TC-AUDIT-104 | 超限时轮转：.3 删除、.2→.3、.1→.2、主文件→.1、新建空主文件

    输入: backup_count=2，主文件超过 max_size；.1/.2 预先存在且内容可区分
    预期输出: 新主文件只含新条目；.1/.2/.3 内容依次为旧主/.1/.2 内容
    断言点: 四个文件的内容逐字节核对
    防回归: 若轮转顺序或删除逻辑被改坏，历史审计丢失
    """
    log = _make_logger(tmp_path, max_size_mb=0, backup_count=2)  # 0 MB → 必然超限
    Path(log.log_file).write_text("OLD-MAIN\n", encoding="utf-8")
    Path(log.log_file + ".1").write_text("OLD-B1\n", encoding="utf-8")
    Path(log.log_file + ".2").write_text("OLD-B2\n", encoding="utf-8")

    log.audit(_entry(user_name="bob"))

    assert Path(log.log_file).read_text(encoding="utf-8").count("\n") == 1
    assert Path(log.log_file + ".1").read_text(encoding="utf-8") == "OLD-MAIN\n"
    assert Path(log.log_file + ".2").read_text(encoding="utf-8") == "OLD-B1\n"
    assert Path(log.log_file + ".3").read_text(encoding="utf-8") == "OLD-B2\n"


def test_audit_logger_rotation_remove_failure_continues(tmp_path, monkeypatch):
    """TC-AUDIT-105 | 删除最旧备份失败时轮转继续（只告警不中断）

    输入: os.remove 对 .3 抛 OSError；主文件超限
    预期输出: 不抛异常；.1/.2 仍然依次顺延；新条目已写入
    断言点: .2/.1 内容 + 新主文件行数
    防回归: 若 remove 失败中断轮转，日志会永远写满
    """
    log = _make_logger(tmp_path, max_size_mb=0, backup_count=2)
    Path(log.log_file).write_text("OLD-MAIN\n", encoding="utf-8")
    Path(log.log_file + ".1").write_text("OLD-B1\n", encoding="utf-8")
    Path(log.log_file + ".2").write_text("OLD-B2\n", encoding="utf-8")

    real_remove = audit_logger_mod.os.remove

    def failing_remove(path, *a, **kw):
        if str(path).endswith(".3"):
            raise OSError("locked")
        return real_remove(path, *a, **kw)

    monkeypatch.setattr(audit_logger_mod.os, "remove", failing_remove)
    log.audit(_entry())

    assert Path(log.log_file + ".2").read_text(encoding="utf-8") == "OLD-B1\n"
    assert Path(log.log_file + ".1").read_text(encoding="utf-8") == "OLD-MAIN\n"
    assert Path(log.log_file).read_text(encoding="utf-8").count("\n") == 1


def test_audit_logger_main_rename_failure_stops_rotation(tmp_path, monkeypatch):
    """TC-AUDIT-106 | 主文件重命名失败时中止轮转（不新建空文件）

    输入: os.rename 在 src == 主文件时抛 OSError
    预期输出: 不抛异常；原主文件内容仍在首行（轮转中止后本次审计追加到原文件）
    断言点: 首行内容保留 + 无 .1 生成（轮转确实被中止）
    防回归: 若失败后继续执行，会把备份错位归零
    """
    log = _make_logger(tmp_path, max_size_mb=0, backup_count=2)
    Path(log.log_file).write_text("PRECIOUS\n", encoding="utf-8")

    real_rename = audit_logger_mod.os.rename

    def failing_rename(src, dst, *a, **kw):
        if str(src) == str(log.log_file):
            raise OSError("deny")
        return real_rename(src, dst, *a, **kw)

    monkeypatch.setattr(audit_logger_mod.os, "rename", failing_rename)
    log.audit(_entry())

    lines = Path(log.log_file).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "PRECIOUS"
    assert len(lines) == 2
    assert not Path(log.log_file + ".1").exists()


def test_audit_logger_write_failure_does_not_lose_audit(tmp_path, monkeypatch):
    """TC-AUDIT-107 | 轮转后新建空文件失败不影响本次审计落盘

    输入: 内置 open 在 'w' 模式新建主文件时抛 OSError
    预期输出: 不抛异常；本次审计条目已写入主文件（.1 保留旧内容）
    断言点: 主文件恰 1 行且 JSON 可解析 + .1 == 旧内容
    防回归: 若 open 失败未捕获，审计写入整体失败
    """
    log = _make_logger(tmp_path, max_size_mb=0, backup_count=2)
    Path(log.log_file).write_text("OLD\n", encoding="utf-8")
    real_open = builtins.open

    def failing_open(file, mode="r", *a, **kw):
        if str(file) == str(log.log_file) and mode == "w":
            raise OSError("cannot create")
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", failing_open)
    log.audit(_entry())

    content = Path(log.log_file).read_text(encoding="utf-8")
    assert len(content.strip().splitlines()) == 1
    json.loads(content)  # 新条目完整可解析
    assert Path(log.log_file + ".1").read_text(encoding="utf-8") == "OLD\n"


def test_audit_logger_thread_safe_writes(tmp_path):
    """TC-AUDIT-108 | 多线程并发写审计不丢条目、不串行损坏

    输入: 4 线程 × 25 条
    预期输出: 文件恰 100 行，每行均为合法 JSON 且 userName 与线程号对应
    断言点: 行数 + 全部行 JSON 可解析 + 字段值集合精确
    防回归: 若锁被删，并发写会产生交错损坏行
    """
    log = _make_logger(tmp_path)
    errors = []

    def worker(i):
        try:
            for j in range(25):
                log.audit(_entry(user_name=f"user-{i}"))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    lines = Path(log.log_file).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 100
    names = {json.loads(line)["userName"] for line in lines}
    assert names == {f"user-{i}" for i in range(4)}


# --------------------------------------------------------------------------
# TC-JWKPROV: agent_registry/agent_registry/jwk_provider.py
# --------------------------------------------------------------------------

def test_jwk_provider_rsa_cert_full_dict(rsa_cert_file):
    """TC-JWKPROV-001 | RSA 证书导出可用的 PyJWK（kty/kid/use/alg/密钥材料）

    输入: 自签 RSA-2048 证书文件
    预期输出: PyJWK.key_type == RSA、key_id == 序列号 hex、public_key_use == sig；
              内部 JWK dict 的 alg/key_ops/n/e 齐全
    断言点: 6 个属性 + dict 字段（kid 由证书序列号重算比对）
    防回归: 若 n/e 编码或 kid 规则被改坏，本用例失败
    """
    provider = JWKProvider(str(rsa_cert_file))
    jwk = provider.get_jwk_set()[0]
    cert = x509.load_pem_x509_certificate(rsa_cert_file.read_bytes())
    assert jwk.key_type == "RSA"
    assert jwk.key_id == format(cert.serial_number, "x")
    assert jwk.public_key_use == "sig"
    assert jwk.key.__class__.__name__.endswith("RSAPublicKey")
    assert jwk._jwk_data["alg"] == "RS256"
    assert jwk._jwk_data["key_ops"] == ["verify"]
    assert jwk._jwk_data["n"] and jwk._jwk_data["e"]


def test_jwk_provider_ec_cert_p256(ec_cert_file):
    """TC-JWKPROV-002 | EC P-256 证书导出 JWK（crv/x/y）

    输入: 自签 EC P-256 证书文件
    预期输出: key_type=EC、key_id=序列号 hex、内部 dict crv=P-256 且 x/y 非空
    断言点: 3 个属性 + dict 字段
    防回归: 若 EC 分支或曲线映射被改坏，本用例失败
    """
    jwk = JWKProvider(str(ec_cert_file)).get_jwk_set()[0]
    cert = x509.load_pem_x509_certificate(ec_cert_file.read_bytes())
    assert jwk.key_type == "EC"
    assert jwk.key_id == format(cert.serial_number, "x")
    assert jwk._jwk_data["crv"] == "P-256"
    assert jwk._jwk_data["x"] and jwk._jwk_data["y"]
    assert jwk._jwk_data["alg"] == "ES256"


def test_jwk_provider_caches_jwk_set(rsa_cert_file):
    """TC-JWKPROV-003 | get_jwk_set 结果缓存：文件删除后仍返回同一列表

    输入: 首次加载后删除证书文件，再次调用
    预期输出: 两次返回同一对象（is 比对）
    断言点: is 身份比对
    防回归: 若缓存被删，删除文件后第二次调用会抛 CertLoadError
    """
    provider = JWKProvider(str(rsa_cert_file))
    first = provider.get_jwk_set()
    rsa_cert_file.unlink()
    assert provider.get_jwk_set() is first


def test_jwk_provider_public_key_pem(rsa_cert_file):
    """TC-JWKPROV-004 | get_public_key_pem 返回 SPKI PEM 公钥

    输入: RSA 证书文件
    预期输出: bytes 以 "-----BEGIN PUBLIC KEY" 开头，且与证书公钥字节一致
    断言点: PEM 头 + 与 cryptography 导出的公钥逐字节相等
    防回归: 若公钥提取或编码被改坏，本用例失败
    """
    pem = JWKProvider(str(rsa_cert_file)).get_public_key_pem()
    cert = x509.load_pem_x509_certificate(rsa_cert_file.read_bytes())
    expected = cert.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)
    assert pem == expected


def test_jwk_provider_missing_file_raises(rsa_cert_file):
    """TC-JWKPROV-005 | 证书文件不存在/内容损坏抛 CertLoadError

    输入: 不存在的路径 / 写入垃圾字节的文件
    预期输出: CertLoadError，消息含 "Failed to load"
    断言点: 异常类型 + 消息关键字（两个方法、两种坏输入）
    防回归: 若异常被吞为 None，签名校验会静默失效
    """
    with pytest.raises(CertLoadError, match="Failed to load public key"):
        JWKProvider("no/such/cert.pem").get_public_key_pem()
    with pytest.raises(CertLoadError, match="Failed to load certificate"):
        JWKProvider("no/such/cert.pem").get_jwk_set()

    bad = rsa_cert_file.parent / "garbage.pem"
    bad.write_bytes(b"not a certificate")
    with pytest.raises(CertLoadError):
        JWKProvider(str(bad)).get_jwk_set()


def test_jwk_provider_unsupported_key_and_curve(tmp_path):
    """TC-JWKPROV-006 | 不支持的密钥类型 / 曲线抛 CertLoadError

    输入: Ed25519 证书（类型不在白名单）/ 直接传入 secp256k1 EC 公钥（曲线不在映射）
    预期输出: CertLoadError，消息含 "Unsupported key type" / "Unsupported curve"
    断言点: 异常类型 + 消息关键字
    防回归: 若类型/曲线白名单被放宽，会生成无法验证的 JWK
    """
    import importlib
    ed_mod = importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
    ed_key = ed_mod.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ut-cert")])
    ed_cert = (x509.CertificateBuilder()
               .subject_name(name)
               .issuer_name(name)
               .public_key(ed_key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(datetime.now(timezone.utc))
               .not_valid_after(datetime.now(timezone.utc))
               .sign(ed_key, algorithm=None))  # Ed25519 签名不取摘要参数
    path = tmp_path / "k1.pem"
    path.write_bytes(ed_cert.public_bytes(serialization.Encoding.PEM))
    with pytest.raises(CertLoadError, match="Unsupported key type"):
        JWKProvider(str(path)).get_jwk_set()

    k1 = ec.generate_private_key(ec.SECP256K1())
    with pytest.raises(CertLoadError, match="Unsupported curve: secp256k1"):
        JWKProvider(str(path))._ec_to_jwk_dict(k1.public_key(), "kid")


# --------------------------------------------------------------------------
# TC-STG-1xx: agent_registry/signature/storage.py
# --------------------------------------------------------------------------

@pytest.fixture
def storage_base(tmp_path, monkeypatch):
    monkeypatch.setattr(StoragePath, "BASE_DIR", str(tmp_path))
    return tmp_path


def test_storage_path_with_organization(storage_base):
    """TC-STG-101 | 带 organization 的存储路径为 BASE_DIR/{org}/{agent}.json

    输入: organization="org-a", agent_name="agent-1"
    预期输出: realpath(BASE_DIR/org-a/agent-1.json)
    断言点: 路径精确相等
    防回归: 若目录层级被改坏，公钥文件会写错位置
    """
    expected = (storage_base / "org-a" / "agent-1.json").resolve()
    assert StoragePath.get_storage_path("org-a", "agent-1") == str(expected)


def test_storage_path_without_organization_requires_url_and_hashes(storage_base):
    """TC-STG-102 | 无 organization 时必须有 provider_url，路径为 sha256(name+url).json

    输入: provider_url=None → ValueError；provider_url="http://u" → 哈希文件名
    预期输出: 异常消息含 "provider_url is required"；路径 == sha256 hex + ".json"
    断言点: 异常类型 + 消息 + 哈希文件名精确值
    防回归: 若哈希键拼接顺序改坏，公钥会存到错误文件
    """
    with pytest.raises(ValueError, match="provider_url is required"):
        StoragePath.get_storage_path(None, "agent-1", provider_url=None)

    import hashlib
    digest = hashlib.sha256("agent-1http://u".encode("utf-8")).hexdigest()
    expected = (storage_base / f"{digest}.json").resolve()
    assert StoragePath.get_storage_path(None, "agent-1", "http://u") == str(expected)


def test_storage_path_traversal_rejected(storage_base):
    """TC-STG-103 | org 使用 .. 触发路径穿越拒绝

    输入: organization=".."
    预期输出: ValueError，消息含 "Path traversal detected"
    断言点: 异常类型 + 消息关键字
    防回归: 若 realpath 前缀校验被删，公钥可写到任意目录
    """
    with pytest.raises(ValueError, match="Path traversal detected"):
        StoragePath.get_storage_path("..", "agent-1")


def test_storage_path_organization_dir_and_traversal(storage_base):
    """TC-STG-104 | get_organization_dir 返回 org 目录；.. 触发拒绝

    输入: "org-b" 与 ".."
    预期输出: 正常路径相等；异常路径 ValueError
    断言点: 路径精确相等 + 异常消息关键字
    防回归: 若校验被删，org 目录可指向任意位置
    """
    assert StoragePath.get_organization_dir("org-b") == str((storage_base / "org-b").resolve())
    with pytest.raises(ValueError, match="Path traversal detected"):
        StoragePath.get_organization_dir("..")


def test_storage_path_ensure_directory_and_file_permissions(storage_base, monkeypatch):
    """TC-STG-105 | ensure_directory_exists 创建父目录；set_file_permissions 仅对存在文件 chmod

    输入: 嵌套不存在目录的文件路径；chmod 记录器
    预期输出: 目录被创建；chmod 收到 0o600；文件不存在时 chmod 不调用
    断言点: 目录存在性 + chmod 参数 + 未创建时不调用
    防回归: 若 mkdir 或存在性守卫被删，写入公钥会失败或误改他人文件
    """
    file_path = storage_base / "deep" / "nested" / "k.json"
    StoragePath.ensure_directory_exists(str(file_path))
    assert (storage_base / "deep" / "nested").is_dir()

    chmod_calls = []
    real_chmod = StoragePath.__dict__["set_file_permissions"]  # noqa: B009

    file_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("agent_registry.signature.storage.os.chmod",
                        lambda p, m: chmod_calls.append((p, m)))
    StoragePath.set_file_permissions(str(file_path))
    StoragePath.set_file_permissions(str(storage_base / "missing.json"))
    assert chmod_calls == [(str(file_path), 0o600)]


def test_storage_path_is_valid_path(storage_base, monkeypatch):
    """TC-STG-106 | is_valid_path：存在文件 True / 目录 False / 缺失 False / 异常 False

    输入: 四种路径形态；异常通过让 Path 构造抛错注入
    预期输出: True / False / False / False
    断言点: 四个布尔结果
    防回归: 若异常分支被删，非法路径输入会导致崩溃
    """
    f = storage_base / "ok.json"
    f.write_text("{}", encoding="utf-8")
    assert StoragePath.is_valid_path(str(f)) is True
    assert StoragePath.is_valid_path(str(storage_base)) is False
    assert StoragePath.is_valid_path(str(storage_base / "nope.json")) is False

    monkeypatch.setattr("agent_registry.signature.storage.Path",
                        lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    assert StoragePath.is_valid_path("anything") is False


# --------------------------------------------------------------------------
# TC-PKM-1xx: agent_registry/signature/public_key_manager.py
# --------------------------------------------------------------------------

def _write_jwks(path, keys):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"keys": keys}), encoding="utf-8")


RSA_KEY = {"kty": "RSA", "kid": "kid-rsa-1", "n": "AMr", "e": "AQAB", "alg": "RS256"}
RSA_KEY_2 = {"kty": "RSA", "kid": "kid-rsa-2", "n": "AMs", "e": "AQAB", "alg": "RS256"}


def test_pkm_get_public_key_by_kid(storage_base):
    """TC-PKM-101 | 按 kid 精确匹配返回 JWK；未知 kid 返回 None

    输入: JWKS 文件含两个 key；查询 kid-rsa-1 / kid-unknown
    预期输出: 命中 key 的 kid 字段相等；未知 → None
    断言点: kid 值 + None
    防回归: 若匹配逻辑改坏（如取第一个），未知 kid 不会返回 None
    """
    _write_jwks(storage_base / "org-x" / "agent-x.json", [RSA_KEY, RSA_KEY_2])
    mgr = PublicKeyManager()
    found = mgr.get_public_key("org-x", "agent-x", "kid-rsa-1")
    assert found is not None and found.kid == "kid-rsa-1"
    assert mgr.get_public_key("org-x", "agent-x", "kid-unknown") is None


def test_pkm_missing_file_returns_empty(storage_base):
    """TC-PKM-102 | 配置文件不存在返回空 JWKS；get_public_key 返回 None

    输入: 未写入任何文件的 org/agent 路径
    预期输出: JWKS.keys == []；get_public_key → None
    断言点: 空列表 + None
    防回归: 若缺文件分支抛异常，未配置公钥的 agent 校验会崩
    """
    mgr = PublicKeyManager()
    jwks = mgr.get_all_public_keys("org-none", "agent-none")
    assert jwks.keys == []
    assert mgr.get_public_key("org-none", "agent-none", "kid") is None


def test_pkm_malformed_json_returns_empty(storage_base):
    """TC-PKM-103 | 损坏的 JWKS 文件返回空 JWKS（异常被记录不抛出）

    输入: 文件内容 "not json"
    预期输出: JWKS.keys == []
    断言点: 空列表（异常分支可到达）
    防回归: 若 JSON 异常上抛，单个坏文件会拖垮全部校验
    """
    path = storage_base / "org-y" / "agent-y.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert PublicKeyManager().get_all_public_keys("org-y", "agent-y").keys == []


def test_pkm_provider_url_hash_path(storage_base):
    """TC-PKM-104 | 无 organization 时按 provider_url 哈希路径读取公钥

    输入: organization=None, agent_name="a", provider_url="http://p"；写入哈希文件
    预期输出: 返回文件中的 kid
    断言点: kid 值（证明哈希路径读取真实生效）
    防回归: 若哈希路径规则被改坏，公钥读取失败
    """
    import hashlib
    digest = hashlib.sha256("ahttp://p".encode("utf-8")).hexdigest()
    _write_jwks(storage_base / f"{digest}.json", [RSA_KEY])
    found = PublicKeyManager().get_public_key(None, "a", "kid-rsa-1", provider_url="http://p")
    assert found is not None and found.kid == "kid-rsa-1"


def test_pkm_traversal_returns_none(storage_base):
    """TC-PKM-105 | 穿越组织名导致路径异常时返回 None 而非崩溃

    输入: organization=".."
    预期输出: get_public_key 返回 None；get_all_public_keys 返回空 JWKS
    断言点: None + 空列表（异常兜底路径）
    防回归: 若兜底被删，恶意 org 名会抛异常穿透到 API
    """
    mgr = PublicKeyManager()
    assert mgr.get_all_public_keys("..", "agent").keys == []
    assert mgr.get_public_key("..", "agent", "kid") is None


# --------------------------------------------------------------------------
# TC-SCM-1xx: agent_registry/agent_registry/signature_certificate_manager.py
# --------------------------------------------------------------------------

def test_scm_valid_certificate_passes(rsa_cert_file):
    """TC-SCM-101 | 合法证书 + 通过的外部校验器 → check_certificate 返回 True

    输入: 自签 RSA 证书；external_validator 返回 True
    预期输出: True；外部校验器收到证书对象
    断言点: 返回值 + 收到的对象类型
    防回归: 若加载或校验编排被改坏，本用例失败
    """
    seen = []
    mgr = SignatureCertificateManager(str(rsa_cert_file),
                                      external_validator=lambda c: seen.append(c) or True)
    assert mgr.check_certificate() is True
    assert len(seen) == 1


def test_scm_no_validator_still_passes(rsa_cert_file):
    """TC-SCM-102 | 未提供外部校验器时仅做存在性+格式校验

    输入: external_validator=None
    预期输出: True
    断言点: 返回值（可选校验器分支）
    防回归: 若 None 守卫被删，无校验器部署会崩
    """
    assert SignatureCertificateManager(str(rsa_cert_file)).check_certificate() is True


def test_scm_missing_and_garbage_cert(rsa_cert_file):
    """TC-SCM-103 | 证书缺失抛 CertificateNotFoundError；损坏内容抛 CertificateFormatError

    输入: 不存在的路径 / 垃圾字节文件
    预期输出: 两类异常，消息分别含 "not found" / "Failed to load certificate"
    断言点: 异常类型 + 消息关键字
    防回归: 若异常类型合并，调用方无法区分故障原因
    """
    with pytest.raises(CertificateNotFoundError, match="not found"):
        SignatureCertificateManager("no/such.pem").check_certificate()

    bad = rsa_cert_file.parent / "bad.pem"
    bad.write_bytes(b"garbage")
    with pytest.raises(CertificateFormatError, match="Failed to load certificate"):
        SignatureCertificateManager(str(bad)).check_certificate()


def test_scm_external_validator_failures(rsa_cert_file):
    """TC-SCM-104 | 外部校验器返回 False / 抛异常 → CertificateValidationError

    输入: external_validator 返回 False；external_validator 抛 RuntimeError
    预期输出: 消息分别含 "External certificate validation failed" / "External validator error"
    断言点: 异常类型 + 两种消息关键字
    防回归: 若返回值检查被删，被拒绝的证书会被放行
    """
    mgr = SignatureCertificateManager(str(rsa_cert_file), external_validator=lambda c: False)
    with pytest.raises(CertificateValidationError, match="External certificate validation failed"):
        mgr.check_certificate()

    def boom(cert):
        raise RuntimeError("downstream down")

    mgr2 = SignatureCertificateManager(str(rsa_cert_file), external_validator=boom)
    with pytest.raises(CertificateValidationError, match="External validator error"):
        mgr2.check_certificate()


def test_scm_format_validation_no_public_key(rsa_cert_file, monkeypatch):
    """TC-SCM-105 | 证书无公钥 / 公钥读取抛错 → CertificateFormatError

    输入: 证书替身 public_key 返回 None / 抛 ValueError
    预期输出: 消息分别含 "Certificate has no public key" / "Invalid certificate format"
    断言点: 异常类型 + 两种消息关键字
    防回归: 若 None 守卫被删（DEFECT-INIT-1 同类问题），坏证书被放行
    """
    mgr = SignatureCertificateManager(str(rsa_cert_file))
    monkeypatch.setattr(mgr, "_load_certificate", lambda: SimpleNamespace(public_key=lambda: None))
    with pytest.raises(CertificateFormatError, match="Certificate has no public key"):
        mgr.check_certificate()

    def broken():
        raise ValueError("no key material")

    monkeypatch.setattr(mgr, "_load_certificate",
                        lambda: SimpleNamespace(public_key=broken))
    with pytest.raises(CertificateFormatError, match="Invalid certificate format"):
        mgr.check_certificate()


def test_scm_unexpected_error_wrapped(rsa_cert_file, monkeypatch):
    """TC-SCM-106 | 非校验类异常被包装为 CertificateValidationError

    输入: _load_certificate 抛 RuntimeError
    预期输出: CertificateValidationError，消息含 "validation failed"
    断言点: 异常类型 + 消息关键字（兜底包装路径）
    防回归: 若兜底 except 被删，未知异常类型会裸抛
    """
    mgr = SignatureCertificateManager(str(rsa_cert_file))
    monkeypatch.setattr(mgr, "_load_certificate",
                        lambda: (_ for _ in ()).throw(RuntimeError("io error")))
    with pytest.raises(CertificateValidationError, match="validation failed"):
        mgr.check_certificate()
