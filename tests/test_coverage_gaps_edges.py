# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Coverage-gap batch 4: remaining error/edge branches across small modules.

Modules covered here:

* ``agent_registry/integration/authn.py``                (extractor/provider contracts)
* ``agent_registry/integration/token_acquisition.py``    (scope/body validation)
* ``agent_registry/integration/credentials.py``          (credential file loading)
* ``common/util/database_config.py``                     (integers/paths/uri validation)
* ``agent_registry/internal/handlers/approval_handler.py`` (deprecated/rejected paths)
* ``agent_registry/signature/agent_card_signature_validator.py`` (loop guard)
* ``common/llm/provider/generic_llm.py``                 (_deep_replace / __del__)
* ``agent_registry/persistence/__init__.py``             (load_from_file OSError)
* ``agent_registry/persistence/precheck.py``             (describe targets / vectordb)
* ``common/util/authenticate_util.py``                   (principal helpers)
* ``agent_registry/health/__init__.py``                  (service facade)
* ``agent_registry/identity.py``                         (identity resolution edges)
* ``agent_registry/broadcast/event_bus.py``              (consumer error/overflow)
* ``agent_registry/broadcast/subscriptions.py``          (SQL/file store CRUD)
* ``agent_registry/internal/tcp_internal_service.py``    (TCP lifecycle)
* ``common/llm/config/model_sources.py``                 (validation errors)
* ``agent_registry/cert_check.py``                       (strength/chain edges)
* ``common/util/conf_obj.py``                            (CRL list rendering)

Every test asserts observable results per tests/TEST_DESIGN.md.
"""

import asyncio
import base64
import json
import socket as socket_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

import agent_registry.broadcast.subscriptions as subscriptions_mod
import agent_registry.cert_check as cert_check
import agent_registry.integration.authn as authn_mod
import agent_registry.integration.credentials as credentials_mod
import agent_registry.integration.token_acquisition as token_acq
import agent_registry.identity as identity_mod
import agent_registry.persistence as persistence_mod
import agent_registry.persistence.precheck as precheck_mod
import common.util.authenticate_util as auth_util
import common.util.conf_obj as conf_obj_mod
import common.util.database_config as db_config
from agent_registry.broadcast.event_bus import EventBus
from agent_registry.broadcast.outbox import MemoryOutbox
from agent_registry.broadcast.subscriptions import (
    FileSubscriptionStore, MemorySubscriptionStore, SqlSubscriptionStore, Subscription,
)
from common.cert.cert_parser import (
    CertParseException, parse_cer_certificate, parse_crl_list, parse_pem_files,
)
from common.llm.config import model_sources
from common.llm.provider.generic_llm import GenericLLM
from common.util.validation_result import ValidationResult


# ==========================================================================
# TC-AUTHN: integration/authn.py
# ==========================================================================

class _FakeHeaders:
    def __init__(self, single=None):
        self._single = single

    def getlist(self, name):
        return []

    def get(self, name):
        return self._single


def test_authn_bearer_extractor_requires_key():
    """TC-AUTHN-101 | 空 fingerprint_key 时构造 BearerTokenExtractor 抛 ValueError

    输入: fingerprint_key = ""
    预期输出: ValueError，message 含 "fingerprint_key is required"
    断言点: 异常类型 + 消息关键字
    防回归: 若 key 校验被删，token 指纹会用空 key 计算
    """
    with pytest.raises(ValueError, match="fingerprint_key is required"):
        authn_mod.BearerTokenExtractor("")


def test_authn_provider_registry_register_and_get():
    """TC-AUTHN-102 | provider_id 为空注册抛错；未知 provider 查询抛 ValueError

    输入: provider_id="" 的替身 / get("missing")
    预期输出: 注册 → ValueError "provider_id is required"；查询 → ValueError "Unknown authentication provider"
    断言点: 两个异常类型 + 消息关键字
    防回归: 若空 id 校验被删，provider 会以空键注册
    """
    registry = authn_mod.AuthenticationProviderRegistry()
    with pytest.raises(ValueError, match="provider_id is required"):
        registry.register(SimpleNamespace(provider_id="", credential_kind="bearer"))
    with pytest.raises(ValueError, match="Unknown authentication provider: missing"):
        registry.get("missing")


def test_authn_register_custom_provider_requires_id_and_kind():
    """TC-AUTHN-103 | 自定义 provider 缺 id/kind 时注册被拒绝

    输入: provider_id="" 的替身与 extractor
    预期输出: ValueError，message 含 "Custom provider id and credential kind are required"
    断言点: 异常类型 + 消息关键字
    防回归: 若校验被删，坏 provider 进入全局注册表
    """
    with pytest.raises(ValueError, match="Custom provider id and credential kind are required"):
        authn_mod.register_authentication_provider(
            SimpleNamespace(provider_id="", credential_kind=""), extractor=object())


def test_authn_static_bearer_requires_hmac_key():
    """TC-AUTHN-104 | StaticBearerProvider 空 hmac_key 抛 ValueError

    输入: hmac_key = ""
    预期输出: ValueError，message 含 "static.hmac_key is required"
    断言点: 异常类型 + 消息关键字
    防回归: 若校验被删，token 比对会用空密钥
    """
    with pytest.raises(ValueError, match="static.hmac_key is required"):
        authn_mod.StaticBearerProvider({}, "")


def test_authn_parse_scopes_variants():
    """TC-AUTHN-105 | _parse_scopes 处理 list/tuple/set/其它类型

    输入: ["a", "b"] / ("c",) / {"d"} / 123 / None
    预期输出: frozenset({"a","b"}) / {"c"} / {"d"} / 空 / 空
    断言点: 五个返回值精确相等
    防回归: 若集合分支被删，scope 过滤会失效
    """
    assert authn_mod._parse_scopes(["a", "b"]) == frozenset({"a", "b"})
    assert authn_mod._parse_scopes(("c",)) == frozenset({"c"})
    assert authn_mod._parse_scopes({"d"}) == frozenset({"d"})
    assert authn_mod._parse_scopes(123) == frozenset()
    assert authn_mod._parse_scopes(None) == frozenset()


def test_authn_handler_unsupported_mode():
    """TC-AUTHN-106 | 未知 integration.auth.mode 抛 ValueError

    输入: config mode="weird"，fingerprint_key 已提供
    预期输出: ValueError，message 含 "Unsupported integration authentication mode: weird"
    断言点: 异常类型 + 消息关键字
    防回归: 若模式白名单被删，坏模式会静默走默认分支
    """
    with pytest.raises(ValueError, match="Unsupported integration authentication mode: weird"):
        authn_mod.ThirdPartyAuthnHandler(config={
            "integration.auth.mode": "weird",
            "integration.auth.fingerprint_key": "k",
        })


def test_authn_credential_hint_swallows_auth_error():
    """TC-AUTHN-107 | credential_hint 在提取抛 AuthenticationError 时返回空串

    输入: mode="mtls" 的 handler；extractor 抛 AuthenticationError
    预期输出: ""
    断言点: 返回空串（审计提示不因坏请求崩溃）
    防回归: 若 except 被删，无效凭证会让日志路径抛异常
    """
    handler = authn_mod.ThirdPartyAuthnHandler(config={"integration.auth.mode": "mtls"})
    handler.extractors = [SimpleNamespace(
        extract=lambda request: (_ for _ in ()).throw(
            authn_mod.AuthenticationError(authn_mod.AuthFailureReason.INVALID_TOKEN_FORMAT, "fail")))]
    assert handler.credential_hint(SimpleNamespace(headers=_FakeHeaders())) == ""


def test_authn_handle_rejects_kind_mismatch():
    """TC-AUTHN-108 | 凭证类型与 provider 不匹配时返回 INVALID_CREDENTIALS

    输入: mode="mtls"；extractor 返回 kind="bearer" 的凭证
    预期输出: AuthenticationError，reason=INVALID_CREDENTIALS
    断言点: 异常类型 + reason 枚举值
    防回归: 若 kind 比对被删，bearer token 会被交给证书 provider
    """
    handler = authn_mod.ThirdPartyAuthnHandler(config={"integration.auth.mode": "mtls"})
    handler.extractors = [SimpleNamespace(
        extract=lambda request: authn_mod.Credential("bearer", value="tok"))]
    with pytest.raises(authn_mod.AuthenticationError) as exc:
        asyncio.run(handler.handle("1.2.3.4", SimpleNamespace(headers=_FakeHeaders())))
    assert exc.value.reason == authn_mod.AuthFailureReason.INVALID_CREDENTIALS


def test_authn_handle_missing_credentials():
    """TC-AUTHN-109 | 所有 extractor 都未命中凭证时返回 MISSING_CREDENTIALS

    输入: mode="mtls"；extractor 返回 None
    预期输出: AuthenticationError，reason=MISSING_CREDENTIALS
    断言点: 异常类型 + reason 枚举值
    防回归: 若空凭证检查被删，provider 会收到 None
    """
    handler = authn_mod.ThirdPartyAuthnHandler(config={"integration.auth.mode": "mtls"})
    handler.extractors = [SimpleNamespace(extract=lambda request: None)]
    with pytest.raises(authn_mod.AuthenticationError) as exc:
        asyncio.run(handler.handle("1.2.3.4", SimpleNamespace(headers=_FakeHeaders())))
    assert exc.value.reason == authn_mod.AuthFailureReason.MISSING_CREDENTIALS


# ==========================================================================
# TC-TOKEN: integration/token_acquisition.py
# ==========================================================================

def test_token_error_unknown_reason_downgrades():
    """TC-TOKEN-101 | 未知错误码被降级为 temporarily_unavailable/503

    输入: TokenAcquisitionError("internal_detail")
    预期输出: error == "temporarily_unavailable" 且 status_code == 503
    断言点: 两个属性（内部错误细节不外泄）
    防回归: 若白名单被删，上游错误描述会透给客户端
    """
    err = token_acq.TokenAcquisitionError("internal_detail")
    assert err.error == "temporarily_unavailable"
    assert err.status_code == 503


@pytest.mark.parametrize("bad_value", [None, 123, "scope\x01", "bad\tscope"])
def test_token_invalid_scope_rejected(bad_value):
    """TC-TOKEN-102 | scope 非字符串或含非法字符时抛 invalid_scope

    输入: None / 123 / "scope\\x01" / "bad\\tscope"（控制字符不在合法区间）
    预期输出: TokenAcquisitionError，error == "invalid_scope"
    断言点: 异常类型 + error 值
    防回归: 若 scope 校验被删，任意字符串进入 token 请求
    """
    with pytest.raises(token_acq.TokenAcquisitionError, match="invalid_scope"):
        token_acq._scopes(bad_value)


def test_token_valid_scope_parsed():
    """TC-TOKEN-103 | 合法 scope 解析为 frozenset

    输入: "read write"
    预期输出: frozenset({"read", "write"})
    断言点: 返回值精确相等
    防回归: 若解析被改坏，合法请求被误拒
    """
    assert token_acq._scopes("read write") == frozenset({"read", "write"})


class _FakeTokenRequest:
    DEFAULT_HEADERS = {"content-type": "application/x-www-form-urlencoded"}

    def __init__(self, body=b"", basic=None, query=""):
        self.url = SimpleNamespace(query=query)
        self.stream = _FakeTokenRequest._stream(body)
        merged = dict(self.DEFAULT_HEADERS)
        merged.update(basic or {})
        self.headers = SimpleNamespace(get=lambda name, default=None: merged.get(name, default),
                                       getlist=lambda name: [])

    @staticmethod
    def _stream(body):
        async def gen():
            yield body
        return gen


def test_token_body_decode_error_mapped():
    """TC-TOKEN-104 | 请求体非法 UTF-8 → invalid_request

    输入: body = b"\\xff\\xfe grant_type=client_credentials"
    预期输出: TokenAcquisitionError，error == "invalid_request"
    断言点: 异常类型 + error 值
    防回归: 若解码异常未捕获，请求处理崩溃
    """
    request = _FakeTokenRequest(body=b"\xff\xfe grant_type=client_credentials",
                                basic={})
    with pytest.raises(token_acq.TokenAcquisitionError, match="invalid_request"):
        asyncio.run(token_acq._read_token_request(request))


def test_token_duplicate_fields_rejected():
    """TC-TOKEN-105 | 重复字段或未知字段 → invalid_request；错误 grant_type → unsupported_grant_type

    输入: "grant_type=client_credentials&grant_type=client_credentials" /
          "grant_type=client_credentials&evil=1" /
          "grant_type=password"
    预期输出: invalid_request / invalid_request / unsupported_grant_type
    断言点: 三个异常的 error 值
    防回归: 若字段白名单被删，任意参数进入 token 端点
    """
    basic = {}
    with pytest.raises(token_acq.TokenAcquisitionError) as exc:
        asyncio.run(token_acq._read_token_request(_FakeTokenRequest(
            b"grant_type=client_credentials&grant_type=client_credentials", basic)))
    assert exc.value.error == "invalid_request"

    with pytest.raises(token_acq.TokenAcquisitionError) as exc:
        asyncio.run(token_acq._read_token_request(_FakeTokenRequest(
            b"grant_type=client_credentials&evil=1", basic)))
    assert exc.value.error == "invalid_request"

    with pytest.raises(token_acq.TokenAcquisitionError) as exc:
        asyncio.run(token_acq._read_token_request(_FakeTokenRequest(
            b"grant_type=password", basic)))
    assert exc.value.error == "unsupported_grant_type"


# ==========================================================================
# TC-CRED: integration/credentials.py
# ==========================================================================

def _cred_file(tmp_path, body):
    path = tmp_path / "credentials.conf"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_cred_missing_file_returns_empty():
    """TC-CRED-101 | 凭证文件不存在时返回空 ({}, {})

    输入: 不存在的路径
    预期输出: ({}, {})
    断言点: 两个空 dict（缺失文件不致命）
    防回归: 若缺文件分支抛错，无凭证部署无法启动
    """
    assert credentials_mod.load_credentials(str(Path("no") / "such.conf")) == ({}, {})


def test_cred_skips_entries_missing_identity(tmp_path):
    """TC-CRED-102 | 缺 identity/token_hash 的条目被跳过；非法 token_hash 也被跳过

    输入: credential_a 仅 token_hash 无 identity；credential_b token_hash="abc"
    预期输出: tokens/certificates 均为空
    断言点: 两个空 dict
    防回归: 若 identity/hash 校验被删，匿名或弱哈希凭证可用
    """
    path = _cred_file(tmp_path, (
        "credential.cred_a.token_hash = " + "a" * 64 + "\n"
        "credential.cred_b.identity = user-b\n"
        "credential.cred_b.token_hash = abc\n"
    ))
    tokens, certs = credentials_mod.load_credentials(path)
    assert tokens == {} and certs == {}


def test_cred_valid_entry_and_duplicate_cn_keep_first(tmp_path):
    """TC-CRED-103 | 合法条目被装载；重复 CN 保留第一条

    输入: cred_x(token+identity) 与 cred_y(cert cn=client-1) 与 cred_z(cert cn=client-1)
    预期输出: tokens 含 cred_x；certificates["client-1"].credential_id == "cred_y"
    断言点: tokens 键 + certificates 键与保留的 id
    防回归: 若去重逻辑被删，同一 CN 的后写覆盖先写
    """
    body = (
        "credential.cred_x.identity = user-1\n"
        "credential.cred_x.token_hash = " + "1" * 64 + "\n"
        "credential.cred_x.role = vendor_agent\n"
        "credential.cred_y.identity = user-y\n"
        "credential.cred_y.cn = client-1\n"
        "credential.cred_y.role = vendor_agent\n"
        "credential.cred_z.identity = user-z\n"
        "credential.cred_z.cn = client-1\n"
        "credential.cred_z.role = vendor_agent\n"
    )
    path = _cred_file(tmp_path, body)
    tokens, certs = credentials_mod.load_credentials(path)
    assert set(tokens) == {"cred_x"}
    assert tokens["cred_x"].identity == "user-1"
    assert set(certs) == {"client-1"}
    assert certs["client-1"].credential_id == "cred_y"


# ==========================================================================
# TC-DBCFG: common/util/database_config.py
# ==========================================================================

_PROFILE = db_config.DatabaseProfile(
    defaults={"pool_min": "5", "pool_max": "10", "ca_file": "certs/ca.cer", "uri": ""},
    env={}, secrets={}, required=(),
    integers={"pool_min": (1, 100), "pool_max": (1, 100)},
    paths=("ca_file",),
)


def test_dbcfg_integer_conversion_and_defaults(tmp_path, monkeypatch):
    """TC-DBCFG-101 | 整数字段字符串转 int；缺失字段跳过校验

    输入: 空配置目录（raw={}），defaults 中 pool_min="5"
    预期输出: config["pool_min"] == 5（int）；无异常
    断言点: 类型与值
    防回归: 若 int 转换被删，连接池参数以字符串传入驱动
    """
    monkeypatch.setattr(db_config, "read_profile_file", lambda *a, **kw: {})
    config = db_config.load_profile("pg", _PROFILE, tmp_path)
    assert config["pool_min"] == 5 and isinstance(config["pool_min"], int)


def test_dbcfg_invalid_integer_rejected(tmp_path, monkeypatch):
    """TC-DBCFG-102 | 非整数字段抛 DatabaseConfigError

    输入: raw pool_min = "abc" / "1.5" / True
    预期输出: DatabaseConfigError，message 含 "invalid pool_min"
    断言点: 异常类型 + 消息关键字（bool 也要被拒）
    防回归: 若 bool 检查被删，True 会被 int() 接受为 1
    """
    monkeypatch.setattr(db_config, "read_profile_file", lambda *a, **kw: {"pool_min": "abc"})
    with pytest.raises(db_config.DatabaseConfigError, match="invalid pool_min"):
        db_config.load_profile("pg", _PROFILE, tmp_path)

    monkeypatch.setattr(db_config, "read_profile_file", lambda *a, **kw: {"pool_min": True})
    with pytest.raises(db_config.DatabaseConfigError, match="invalid pool_min"):
        db_config.load_profile("pg", _PROFILE, tmp_path)


def test_dbcfg_relative_path_made_absolute(tmp_path, monkeypatch):
    """TC-DBCFG-103 | 相对路径字段基于 root 转绝对路径；非字符串路径报错

    输入: ca_file="certs/ca.cer" / ca_file=123
    预期输出: 绝对路径 str(root/"certs/ca.cer")；非字符串 → DatabaseConfigError
    断言点: 路径值 + 异常
    防回归: 若路径解析被删，工作目录变化会导致证书加载失败
    """
    monkeypatch.setattr(db_config, "read_profile_file", lambda *a, **kw: {"ca_file": "certs/ca.cer"})
    config = db_config.load_profile("pg", _PROFILE, tmp_path)
    assert config["ca_file"] == str(Path(tmp_path) / "certs/ca.cer")

    monkeypatch.setattr(db_config, "read_profile_file", lambda *a, **kw: {"ca_file": 123})
    with pytest.raises(db_config.DatabaseConfigError, match="invalid ca_file"):
        db_config.load_profile("pg", _PROFILE, tmp_path)


def test_dbcfg_uri_credentials_rejected(tmp_path, monkeypatch):
    """TC-DBCFG-104 | URI 内嵌凭据被拒绝；非法 URI 报 invalid uri

    输入: uri="postgresql://user:pass@h/db" / uri="http://[bad"
    预期输出: DatabaseConfigError "credentials in uri are not allowed" / "invalid uri"
    断言点: 两个异常消息关键字（凭据永不落配置）
    防回归: 若 uri 校验被删，密码可能进入连接串
    """
    monkeypatch.setattr(db_config, "read_profile_file",
                        lambda *a, **kw: {"uri": "postgresql://user:pass@h/db"})
    with pytest.raises(db_config.DatabaseConfigError, match="credentials in uri are not allowed"):
        db_config.load_profile("pg", _PROFILE, tmp_path)

    monkeypatch.setattr(db_config, "read_profile_file", lambda *a, **kw: {"uri": "http://["})
    with pytest.raises(db_config.DatabaseConfigError, match="invalid uri"):
        db_config.load_profile("pg", _PROFILE, tmp_path)


# ==========================================================================
# TC-APPROVE: internal/handlers/approval_handler.py
# ==========================================================================

def _approval_registry(status):
    return SimpleNamespace(
        find_by_key=lambda name, org: SimpleNamespace(name=name),
        get_status=lambda name, org: status,
        update_status=lambda *a, **kw: True,
    )


def test_approve_deprecated_is_terminal():
    """TC-APPROVE-101 | deprecated 状态的 agent 不能被重新批准

    输入: get_status → "deprecated"；approval_enabled=true
    预期输出: success=False，error=="Agent is deprecated"，message 含 "terminal state"
    断言点: 三个响应字段
    防回归: 若终态检查被删，废弃卡片可被复活
    """
    from agent_registry.internal.handlers.approval_handler import ApprovalHandler
    resp = ApprovalHandler().handle(
        {"agent_name": "a", "organization": "o", "user_name": "op"},
        _approval_registry("deprecated"), {"agent_approval_enabled": "true"})
    assert resp["success"] is False
    assert resp["error"] == "Agent is deprecated"
    assert "terminal state" in resp["message"]


def test_approve_rejected_requires_resubmit():
    """TC-APPROVE-102 | rejected 状态不能直接批准（必须重新提交）

    输入: get_status → "rejected"；approval_enabled=true
    预期输出: success=False，error=="Invalid review transition"，message 含 "resubmitted"
    断言点: 三个响应字段
    防回归: 若状态机检查被删，被拒卡片绕过复核直接发布
    """
    from agent_registry.internal.handlers.approval_handler import ApprovalHandler
    resp = ApprovalHandler().handle(
        {"agent_name": "a", "organization": "o", "user_name": "op"},
        _approval_registry("rejected"), {"agent_approval_enabled": "true"})
    assert resp["success"] is False
    assert resp["error"] == "Invalid review transition"
    assert "resubmit" in resp["message"]


# ==========================================================================
# TC-CSIGN: signature/agent_card_signature_validator.py
# ==========================================================================

def test_csign_sync_validate_forbidden_on_event_loop(monkeypatch):
    """TC-CSIGN-101 | 事件循环内调用同步校验抛 RuntimeError 并指引用 async API

    输入: _validate_backend 返回 None（需要 JKU 校验）；asyncio.run 包裹同步调用
    预期输出: RuntimeError，message 含 "validate_agent_card_async"
    断言点: 异常类型 + 消息关键字（防 asyncio.run 嵌套）
    防回归: 若守卫被删，事件循环内嵌套 asyncio.run 直接崩溃
    """
    from agent_registry.signature.agent_card_signature_validator import AgentCardSignatureValidator
    validator = AgentCardSignatureValidator.__new__(AgentCardSignatureValidator)
    validator._signature_validation_enabled = True
    monkeypatch.setattr(validator, "_validate_backend", lambda card: None)

    async def scenario():
        with pytest.raises(RuntimeError, match="validate_agent_card_async"):
            validator.validate_agent_card(SimpleNamespace(signatures=[]))

    asyncio.run(scenario())


# ==========================================================================
# TC-GLLM: common/llm/provider/generic_llm.py
# ==========================================================================

def test_gllm_deep_replace_placeholder_variants():
    """TC-GLLM-101 | _deep_replace：整串占位符原样返回值；部分匹配做串内替换（bool/int/list 分支）

    输入: "$MODEL"（list/bool/int/str）与 "url=$V&x"（str/bool/int/list 部分匹配）
    预期输出: 整串 → 值本身；部分匹配 → bool→"true"、int→"5"、list→JSON、str→内联
    断言点: 八个返回值精确相等
    防回归: 若占位符替换被改坏，请求模板会带 $VAR 发出去
    """
    assert GenericLLM._deep_replace("$MODEL", {"MODEL": ["a", "b"]}) == ["a", "b"]
    assert GenericLLM._deep_replace("$MODEL", {"MODEL": {"k": 1}}) == {"k": 1}
    assert GenericLLM._deep_replace("$MODEL", {"MODEL": True}) is True
    assert GenericLLM._deep_replace("$MODEL", {"MODEL": 5}) == 5
    assert GenericLLM._deep_replace("url=$V&x", {"V": "http://x"}) == "url=http://x&x"
    assert GenericLLM._deep_replace("flag=$V", {"V": True}) == "flag=true"
    assert GenericLLM._deep_replace("n=$V", {"V": 7}) == "n=7"
    assert GenericLLM._deep_replace("docs=$V", {"V": ["d1"]}) == 'docs=["d1"]'


def test_gllm_deep_replace_nested_structures():
    """TC-GLLM-102 | _deep_replace 递归处理 dict 与 list

    输入: {"a": ["$V", {"b": "$V"}]}
    预期输出: {"a": ["x", {"b": "x"}]}
    断言点: 返回结构逐字段相等
    防回归: 若递归分支被删，嵌套模板不会被替换
    """
    assert GenericLLM._deep_replace({"a": ["$V", {"b": "$V"}]}, {"V": "x"}) \
        == {"a": ["x", {"b": "x"}]}


# ==========================================================================
# TC-STORE2: persistence/__init__.py load_from_file
# ==========================================================================

def test_store_load_from_file_size_check_failure(tmp_path, monkeypatch):
    """TC-STORE2-101 | 文件大小检查抛 OSError 时返回空列表

    输入: 存在的 JSON 文件；os.path.getsize 抛 OSError
    预期输出: []（不抛异常）
    断言点: 返回空列表
    防回归: 若 OSError 未捕获，启动时读文件崩溃
    """
    target = tmp_path / "agents.json"
    target.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(persistence_mod.os.path, "getsize",
                        lambda p: (_ for _ in ()).throw(OSError("stat failed")))
    assert persistence_mod.load_from_file(str(target)) == []


# ==========================================================================
# TC-PRECHK: persistence/precheck.py
# ==========================================================================

def test_prechk_describe_targets_by_mode():
    """TC-PRECHK-102 | _describe_target 按 mode 输出可读的连接描述

    输入: gaussdb / mysql / sqlite / file / 未知 mode
    预期输出: 各 mode 的描述串包含主机与库名；未知 mode 原样返回
    断言点: 五个返回值关键字
    防回归: 若描述分支被删，故障提示缺失关键信息
    """
    conf = {"gauss.host": "g-host", "gauss.port": "5432", "gauss.database": "g_db",
            "gauss.username": "g_user",
            "mysql.host": "m-host", "mysql.port": "3306", "mysql.name": "m_db",
            "mysql.username": "m_user",
            "sqlite.path": "data/x.db", "file.path": "data/x.json"}
    assert "g-host" in precheck_mod._describe_target("gauss", conf)
    assert "g_db" in precheck_mod._describe_target("gauss", conf)
    assert "m-host" in precheck_mod._describe_target("mysql", conf)
    assert "m_db" in precheck_mod._describe_target("mysql", conf)
    assert precheck_mod._describe_target("sqlite", conf) == "data/x.db"
    assert precheck_mod._describe_target("file", conf) == "data/x.json"
    assert precheck_mod._describe_target("weird", conf) == "weird"


# ==========================================================================
# TC-AUTHUTIL: common/util/authenticate_util.py
# ==========================================================================

def test_authutil_principal_helpers():
    """TC-AUTHUTIL-101 | Principal.is_integration 与 audit_identity

    输入: INTEGRATION 类型 principal（identity="svc"）/ INTERNAL 类型（identity=None）
    预期输出: is_integration True/False；audit_identity "svc"/""
    断言点: 四个返回值
    防回归: 若类型判断被删，审计身份串会包含敏感信息
    """
    p = auth_util.Principal(client_ip="1.1.1.1", identity="svc",
                            caller_type=auth_util.CallerType.INTEGRATION)
    q = auth_util.Principal(client_ip="1.1.1.1", identity=None)
    assert p.is_integration() is True
    assert q.is_integration() is False
    assert p.audit_identity() == "svc"
    assert q.audit_identity() == ""


def test_authutil_authenticate_wraps_principal_failure(monkeypatch):
    """TC-AUTHUTIL-102 | Principal 构造失败时 authenticate 包装为 AuthenticationError

    输入: monkeypatch Principal 构造抛 RuntimeError
    预期输出: AuthenticationError，reason=INVALID_CREDENTIALS
    断言点: 异常类型 + reason
    防回归: 若包装被删，原始异常（可能含敏感信息）直接外泄
    """
    monkeypatch.setattr(auth_util, "Principal",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(auth_util.AuthenticationError) as exc:
        auth_util.authenticate("1.1.1.1", object())
    assert exc.value.reason == auth_util.AuthFailureReason.INVALID_CREDENTIALS


# ==========================================================================
# TC-HEALTH2: health/__init__.py
# ==========================================================================

def test_health_service_facade_and_invalid_int():
    """TC-HEALTH2-101 | _int_conf 非法值回退默认；service.get/close 正常

    输入: heartbeat.interval="abc"；MemoryHeartbeatStore；record 后 get/close
    预期输出: interval 回退 30；get 返回记录的 state；close 后 store 关闭
    断言点: interval 值 + get 返回的 name + close 调用
    防回归: 若配置回退被删，坏配置导致启动崩溃
    """
    from agent_registry.health import HealthService, _int_conf
    from agent_registry.health.store import MemoryHeartbeatStore

    assert _int_conf({"k": "abc"}, "k", 7) == 7
    assert _int_conf({"k": "3"}, "k", 7) == 3

    service = HealthService(MemoryHeartbeatStore(),
                            {"heartbeat.enabled": "true", "heartbeat.interval": "abc"})
    assert service.interval == 30
    _, state = service.record_heartbeat("agent-9", "org-9")
    assert service.get("agent-9", "org-9") is state
    assert service.status_of("agent-9", "org-9") == "healthy"
    service.close()  # Memory 后端 close 为空操作；不得抛异常
    assert service.store is not None


# ==========================================================================
# TC-IDNT: identity.py
# ==========================================================================

def _request(headers=None, scope=None):
    req = SimpleNamespace(scope=scope or {},
                          headers=SimpleNamespace(get=lambda name, default=None: headers))
    return req


def test_idnt_peer_cert_variants():
    """TC-IDNT-101 | cn_from_peer_cert：dict 带/不带 CN、字符串、其它类型

    输入: {"subject": [[("commonName", "a1")]]} / {"subject": [[("ou", "x")]]} / "CN=a2" / 123 / None
    预期输出: "a1" / None / "a2" / None / None
    断言点: 五个返回值
    防回归: 若字符串分支被删，RFC4514 主题串无法识别
    """
    assert identity_mod.cn_from_peer_cert({"subject": [[("commonName", "a1")]]}) == "a1"
    assert identity_mod.cn_from_peer_cert({"subject": [[("ou", "x")]]}) is None
    assert identity_mod.cn_from_peer_cert("CN=a2,OU=x") == "a2"
    assert identity_mod.cn_from_peer_cert(123) is None
    assert identity_mod.cn_from_peer_cert(None) is None


def test_idnt_direct_peer_ip_variants():
    """TC-IDNT-102 | direct_peer_ip：tuple/list/str/缺失

    输入: ("10.0.0.1", 8443) / ["10.0.0.2"] / "10.0.0.3" / {} / None
    预期输出: "10.0.0.1" / "10.0.0.2" / "10.0.0.3" / None / None
    断言点: 五个返回值
    防回归: 若 str 分支被删，直连对端识别失败
    """
    assert identity_mod.direct_peer_ip({identity_mod.SCOPE_DIRECT_PEER: ("10.0.0.1", 8443)}) == "10.0.0.1"
    assert identity_mod.direct_peer_ip({identity_mod.SCOPE_DIRECT_PEER: ["10.0.0.2"]}) == "10.0.0.2"
    assert identity_mod.direct_peer_ip({identity_mod.SCOPE_DIRECT_PEER: "10.0.0.3"}) == "10.0.0.3"
    assert identity_mod.direct_peer_ip({}) is None
    assert identity_mod.direct_peer_ip(None) is None


def test_idnt_token_mode_without_principal():
    """TC-IDNT-103 | token 模式下 scope 无 principal 时返回未验证身份

    输入: owner.identity.mode=token；scope 无 registry_principal
    预期输出: CallerIdentity(source=token, verified=False, detail 含 "no authenticated token")
    断言点: 三个字段
    防回归: 若检查被删，无凭证请求会拿到身份
    """
    result = identity_mod.resolve_caller_identity(_request(), {"owner.identity.mode": "token"})
    assert result.source == "token"
    assert result.verified is False
    assert "no authenticated token" in result.detail


def test_idnt_trusted_proxy_without_header():
    """TC-IDNT-104 | 可信代理未发送身份头时返回未验证

    输入: mode=trusted_proxy；trusted.ips 含直连 IP；直连 peer 存在；头为空
    预期输出: CallerIdentity(source=trusted_proxy, verified=False, detail 含 "no usable")
    断言点: 三个字段
    防回归: 若空头检查被删，代理可发送任意身份
    """
    config = {"owner.identity.mode": "trusted_proxy",
              "owner.trusted.proxy.ips": "10.0.0.9"}
    request = _request(headers=None,
                       scope={identity_mod.SCOPE_DIRECT_PEER: ("10.0.0.9", 80)})
    result = identity_mod.resolve_caller_identity(request, config)
    assert result.source == "trusted_proxy"
    assert result.verified is False
    assert "no usable" in result.detail


def test_idnt_describe_configuration_all_sources():
    """TC-IDNT-105 | describe_identity_configuration 覆盖全部身份源

    输入: trusted_proxy(含 ip) / certificate / token / none / 缺省
    预期输出: 描述串分别含 "trusted_proxy=10.0.0.9" / "verify_client" / "standards-first" /
              "no verifiable identity source"
    断言点: 四个描述串关键字
    防回归: 若描述分支被删，启动日志丢失关键配置信息
    """
    assert "trusted_proxy=10.0.0.9" in identity_mod.describe_identity_configuration({
        "owner.identity.mode": "trusted_proxy", "owner.trusted.proxy.ips": "10.0.0.9"})
    assert "verify_client" in identity_mod.describe_identity_configuration({
        "owner.identity.mode": "certificate"})
    assert "standards-first" in identity_mod.describe_identity_configuration({
        "owner.identity.mode": "token"})
    assert "no verifiable identity source" in identity_mod.describe_identity_configuration({
        "owner.identity.mode": "none"})


def test_idnt_warnings_and_strict_failures():
    """TC-IDNT-106 | 隔离开启时各身份源的告警与 strict 升级

    输入: trusted_proxy 无 ip / token+mtls / none / certificate+https 关闭
    预期输出: 各产生 1 条告警；strict_startup_failures 在 strict=true 时返回告警、否则空
    断言点: 告警数量与内容关键字 + strict 升级行为
    防回归: 若告警被删，错误部署会静默以全 401 状态对外服务
    """
    warnings = identity_mod.identity_configuration_warnings({
        "owner.isolation.enabled": "true", "owner.identity.mode": "trusted_proxy"})
    assert len(warnings) == 1 and "trusted.proxy.ips" in warnings[0]

    warnings = identity_mod.identity_configuration_warnings({
        "owner.isolation.enabled": "true", "owner.identity.mode": "token",
        "integration.auth.mode": "mtls"})
    assert len(warnings) == 1 and "token provider" in warnings[0]

    warnings = identity_mod.identity_configuration_warnings({
        "owner.isolation.enabled": "true", "owner.identity.mode": "none"})
    assert len(warnings) == 1 and "owner.identity.mode=none" in warnings[0]

    warnings = identity_mod.identity_configuration_warnings({
        "owner.isolation.enabled": "true", "owner.identity.mode": "certificate",
        "enable_https": "false"})
    assert len(warnings) == 1 and "enable_https=false" in warnings[0]

    assert identity_mod.strict_startup_failures({
        "startup.strict.identity": "true", "owner.isolation.enabled": "true",
        "owner.identity.mode": "none"}) == \
        identity_mod.identity_configuration_warnings({
            "owner.isolation.enabled": "true", "owner.identity.mode": "none"})
    assert identity_mod.strict_startup_failures({
        "startup.strict.identity": "false", "owner.isolation.enabled": "true",
        "owner.identity.mode": "none"}) == []


# ==========================================================================
# TC-EVBUS: broadcast/event_bus.py
# ==========================================================================

def test_evbus_consumer_survives_dispatcher_and_recovery_failures():
    """TC-EVBUS-101 | run_consumer：dispatcher.submit/recover 抛错被记录，循环继续

    输入: publish 2 个事件；假 dispatcher.submit/recover 均抛错；bus._overflowed=True
    预期输出: 两个事件都被尝试投递（submit 调用 2 次）；recover 被调用且 _overflowed 重新置位
    断言点: submit/recover 调用次数 + _overflowed 状态
    防回归: 若异常未捕获，消费线程死亡导致事件积压
    """
    bus = EventBus(MemoryOutbox(), dispatch_enabled=True)

    class FailingDispatcher:
        def __init__(self):
            self.submits = []
            self.recovers = 0

        def submit(self, event):
            self.submits.append(event.event_id)
            raise RuntimeError("dispatcher down")

        def recover(self):
            self.recovers += 1
            raise RuntimeError("recover down")

    dispatcher = FailingDispatcher()
    bus.attach_dispatcher(dispatcher)
    bus._overflowed = True
    from agent_registry.broadcast.events import EventType
    bus.publish(EventType.AGENT_HEALTH_CHANGED, {"a": 1})
    bus.publish(EventType.AGENT_HEALTH_CHANGED, {"a": 2})

    async def scenario():
        task = asyncio.get_running_loop().create_task(bus.run_consumer(0.01))
        await asyncio.sleep(0.08)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert len(dispatcher.submits) == 2
    assert dispatcher.recovers >= 1
    assert bus._overflowed is True  # recover 失败 → 保持溢出标记


# ==========================================================================
# TC-SUBS: broadcast/subscriptions.py
# ==========================================================================

def _sqlite_backend():
    import sqlite3

    class Backend:
        param_ph = '?'
        supports_create_index_if_not_exists = True

        def __init__(self):
            self.conn = sqlite3.connect(':memory:')

        def _execute_write(self, sql, params=()):
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur.rowcount

        def _execute_read_one(self, sql, params=()):
            return self.conn.execute(sql, tuple(params)).fetchone()

        def _execute_read_all(self, sql, params=()):
            return self.conn.execute(sql, tuple(params)).fetchall()

        def ensure_index(self, if_not_exists_sql, plain_sql):
            self._execute_write(if_not_exists_sql)

    return Backend()


def test_subs_sql_store_full_crud_roundtrip():
    """TC-SUBS-101 | SqlSubscriptionStore create/get/list_all/delete 全链路读回

    输入: 内存 SQLite 后端；创建订阅（含 filters 与 secret）
    预期输出: create 返回带 id 的订阅；get 读回字段一致；list_all 含 1 条；delete 后 get 为 None 且二次 delete False
    断言点: 字段逐项读回 + delete 返回值序列 True/False
    防回归: 若序列化/反序列化被改坏，订阅在重启后丢失过滤器
    """
    store = SqlSubscriptionStore(_sqlite_backend())
    created = store.create(Subscription(
        subscription_id="", callback_url="https://cb",
        event_types=["AGENT_HEALTH_CHANGED"], organizations=["org-1"],
        tags=["gpu"], secret="s3cret"))
    assert created.subscription_id.startswith("sub_")

    fetched = store.get(created.subscription_id)
    assert fetched is not None
    assert fetched.callback_url == "https://cb"
    assert fetched.event_types == ["AGENT_HEALTH_CHANGED"]
    assert fetched.organizations == ["org-1"]
    assert fetched.tags == ["gpu"]
    assert fetched.secret == "s3cret"

    assert len(store.list_all()) == 1
    assert store.delete(created.subscription_id) is True
    assert store.get(created.subscription_id) is None
    assert store.delete(created.subscription_id) is False
    store.close()


def test_subs_sql_placeholder_fallback():
    """TC-SUBS-102 | 后端未定义 param_ph 时占位符回退为 %s

    输入: 无 param_ph 属性的后端替身
    预期输出: store._ph == "%s"
    断言点: 属性值（MySQL/PG 兼容路径）
    防回归: 若回退被删，非 sqlite 后端 SQL 绑定符错误
    """
    class NoPlaceholderBackend:
        def _execute_write(self, sql, params=()):
            return 0

    store = SqlSubscriptionStore(NoPlaceholderBackend())
    assert store._ph == "%s"
    store.close()


def test_subs_file_store_corrupt_file_returns_empty(tmp_path):
    """TC-SUBS-103 | 损坏的订阅文件被忽略并返回空存储

    输入: 文件内容 "not-json" / 非列表 JSON "{'a': 1}"
    预期输出: list_all() == []（异常被记录不抛出）
    断言点: 空列表 ×2
    防回归: 若解析异常未捕获，单个坏文件让启动失败
    """
    bad = tmp_path / "subs.json"
    bad.write_text("not-json", encoding="utf-8")
    assert FileSubscriptionStore(str(bad)).list_all() == []

    bad.write_text('{"a": 1}', encoding="utf-8")
    assert FileSubscriptionStore(str(bad)).list_all() == []


def test_subs_file_store_roundtrip_and_delete(tmp_path):
    """TC-SUBS-104 | FileSubscriptionStore 持久化读回与删除

    输入: 创建 2 个订阅；新实例读回；删除 1 个
    预期输出: 读回数量 2 且 secret 保留；删除后数量 1；文件内容同步
    断言点: 数量 + secret 字段 + delete 返回值
    防回归: 若 _save 被删，订阅只在内存存在
    """
    path = tmp_path / "subs.json"
    store = FileSubscriptionStore(str(path))
    s1 = store.create(Subscription(subscription_id="", callback_url="https://a", secret="k1"))
    store.create(Subscription(subscription_id="", callback_url="https://b"))

    reopened = FileSubscriptionStore(str(path))
    assert len(reopened.list_all()) == 2
    assert reopened.get(s1.subscription_id).secret == "k1"

    assert reopened.delete(s1.subscription_id) is True
    assert len(reopened.list_all()) == 1
    assert len(FileSubscriptionStore(str(path)).list_all()) == 1

    store.close()
    reopened.close()


def test_subs_event_matching_filters():
    """TC-SUBS-105 | event_matches 的事件类型/组织/标签过滤

    输入: 事件 (AGENT_HEALTH_CHANGED, {"organization": "o1", "tags": ["gpu"]}) 与四种订阅
    预期输出: 类型不匹配 False；组织不匹配 False；标签不交集 False；全匹配 True
    断言点: 四个布尔结果
    防回归: 若过滤逻辑被改坏，订阅方收到无关事件
    """
    from agent_registry.broadcast.events import EventType, build_event

    event = build_event(EventType.AGENT_HEALTH_CHANGED,
                        {"organization": "o1", "tags": ["gpu"]}, registry_version=0)
    assert subscriptions_mod.event_matches(event, Subscription(
        subscription_id="s", callback_url="u", event_types=["AGENT_REGISTERED"])) is False
    assert subscriptions_mod.event_matches(event, Subscription(
        subscription_id="s", callback_url="u", organizations=["o2"])) is False
    assert subscriptions_mod.event_matches(event, Subscription(
        subscription_id="s", callback_url="u", tags=["tpu"])) is False
    assert subscriptions_mod.event_matches(event, Subscription(
        subscription_id="s", callback_url="u",
        event_types=["AGENT_HEALTH_CHANGED"], organizations=["o1"], tags=["gpu"])) is True


# ==========================================================================
# TC-TCPI: internal/tcp_internal_service.py
# ==========================================================================

class _FakeTcpConn:
    def __init__(self, payload=b""):
        self.payload = payload
        self.sent = []
        self.closed = False

    def recv(self, bufsize):
        data, self.payload = self.payload, b""
        return data

    def send(self, data):
        self.sent.append(json.loads(data.decode("utf-8")))

    def close(self):
        self.closed = True


def _tcp_service(monkeypatch, tmp_path, accepts):
    """构造带假 server socket 的 TCPInternalService。"""
    from agent_registry.internal import tcp_internal_service as tcp_mod

    class FakeServerSocket:
        def __init__(self, family, type):
            self.bound = None
            self.closed = False
            self._accepts = list(accepts)

        def setsockopt(self, *a):
            pass

        def bind(self, addr):
            self.bound = addr

        def listen(self, backlog):
            pass

        def settimeout(self, t):
            pass

        def accept(self):
            item = self._accepts.pop(0) if self._accepts else socket_mod.timeout()
            if isinstance(item, Exception):
                raise item
            return item, ("addr", 0)

        def close(self):
            self.closed = True

    server = FakeServerSocket(2, 1)
    monkeypatch.setattr(tcp_mod, "socket",
                        SimpleNamespace(socket=lambda family, type: server,
                                        AF_INET=2, SOCK_STREAM=1, SOL_SOCKET=0,
                                        SO_REUSEADDR=1, timeout=socket_mod.timeout))
    monkeypatch.setattr("agent_registry.registry_instance.get_registry",
                        lambda: SimpleNamespace(name="fake"))
    monkeypatch.setattr(tcp_mod, "get_conf", lambda: {"k": "v"})

    class SyncThread:
        def __init__(self, target=None, args=(), daemon=None, **kw):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(tcp_mod.threading, "Thread", SyncThread)
    svc = tcp_mod.TCPInternalService(host="127.0.0.1", port=1234)
    return svc, server


def test_tcp_service_accepts_and_stops(monkeypatch):
    """TC-TCPI-101 | start()：timeout 重试、接受连接、handler 运行后退出并关闭 socket

    输入: accept 依次 [timeout, timeout, 含合法请求的连接]；handler 将 _running 置 False
    预期输出: bind 到 (host, port)；handler 响应已发送；server 关闭；_running False
    断言点: bind 地址 + 响应 + server.closed
    防回归: 若 accept 循环改坏，服务挂死
    """
    svc, server = _tcp_service(monkeypatch, None, [
        socket_mod.timeout(), socket_mod.timeout(),
        _FakeTcpConn(json.dumps({"action": "echo", "params": {"p": 1}}).encode()),
    ])

    class EchoHandler:
        def handle(self, params, registry, config):
            svc._running = False
            return {"success": True, "data": params}

    svc.dispatcher.register_handler("echo", EchoHandler)
    svc.start()
    assert server.bound == ("127.0.0.1", 1234)
    assert server.closed is True
    assert svc._running is False


def test_tcp_service_accept_error_and_bind_failure(monkeypatch):
    """TC-TCPI-102 | accept 抛错记录后继续；bind 失败被兜底且 socket 关闭

    输入: accept 抛 RuntimeError 后由连接处理置 _running=False；另一实例 bind 抛 OSError
    预期输出: 两者均不崩溃；bind 失败路径 server.closed 为 True
    断言点: 无异常 + closed 状态
    防回归: 若兜底被删，端口占用导致启动线程裸崩
    """
    svc, server = _tcp_service(monkeypatch, None, [
        socket_mod.timeout(),
        _FakeTcpConn(json.dumps({"action": "echo", "params": {}}).encode()),
    ])

    class StopHandler:
        def handle(self, params, registry, config):
            svc._running = False
            return {"success": True, "data": params}

    svc.dispatcher.register_handler("echo", StopHandler)
    svc.start()
    assert server.closed is True

    class BindFailSocket:
        def __init__(self, family, type):
            self.closed = False

        def setsockopt(self, *a):
            pass

        def bind(self, addr):
            raise OSError("in use")

        def close(self):
            self.closed = True

    from agent_registry.internal import tcp_internal_service as tcp_mod
    monkeypatch.setattr(tcp_mod, "socket",
                        SimpleNamespace(socket=lambda family, type: BindFailSocket(2, 1),
                                        AF_INET=2, SOCK_STREAM=1, SOL_SOCKET=0,
                                        SO_REUSEADDR=1, timeout=socket_mod.timeout))
    svc2 = tcp_mod.TCPInternalService()
    svc2.start()
    assert svc2._server_socket.closed is True


def test_tcp_service_handle_request_paths(monkeypatch):
    """TC-TCPI-103 | _handle_request：空载荷/坏 JSON/缺 action/未知 action/handler 异常

    输入: 五种连接载荷
    预期输出: 空载荷不回包；坏 JSON 回 "Invalid JSON format"；缺 action 回
              "Invalid request format"；未知 action 回 "Unknown action: ..."；
              handler 抛错回 {"success": False, "error": ...}
    断言点: 每个分支响应 dict
    防回归: 任一响应契约改坏，TCP 客户端解析失败
    """
    svc, _ = _tcp_service(monkeypatch, None, [])

    conn = _FakeTcpConn(b"")
    svc._handle_request(conn)
    assert conn.sent == [] and conn.closed is True

    conn = _FakeTcpConn(b"not-json")
    svc._handle_request(conn)
    assert conn.sent == [{"success": False, "error": "Invalid JSON format"}]

    conn = _FakeTcpConn(json.dumps({"params": {}}).encode())
    svc._handle_request(conn)
    assert conn.sent[0]["error"] == "Invalid request format"

    conn = _FakeTcpConn(json.dumps({"action": "nope"}).encode())
    svc._handle_request(conn)
    assert conn.sent == [{"success": False, "error": "Unknown action: nope"}]

    class BoomHandler:
        def handle(self, params, registry, config):
            raise RuntimeError("tcp down")

    svc.dispatcher.register_handler("boom", BoomHandler)
    conn = _FakeTcpConn(json.dumps({"action": "boom"}).encode())
    svc._handle_request(conn)
    assert conn.sent[0]["success"] is False
    assert conn.sent[0]["error"] == "tcp down"


def test_tcp_service_stop_with_close_failure(monkeypatch):
    """TC-TCPI-104 | stop()：socket 关闭抛错被吞掉，_running 置 False

    输入: _server_socket.close 抛 OSError
    预期输出: 无异常；_running False
    断言点: 无异常 + 状态
    防回归: 若 close 异常未捕获，停止流程中断
    """
    svc, server = _tcp_service(monkeypatch, None, [])
    svc._running = True
    server.close = lambda: (_ for _ in ()).throw(OSError("already closed"))
    svc._server_socket = server
    svc.stop()
    assert svc._running is False


# ==========================================================================
# TC-MSRC: common/llm/config/model_sources.py
# ==========================================================================

class _NullSource:
    def get(self, name):
        return None


def _write_yaml(tmp_path, body):
    path = tmp_path / "models.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_msrc_profile_registration_and_build():
    """TC-MSRC-101 | 重复注册 profile 抛错；未知 provider 构建抛错；aoc 缺凭据抛错

    输入: register_profile 重名 / build_profile("nope", "chat") / aoc_signed 无 app_key
    预期输出: ValueError("Duplicate model profile") / ValueError("No model profile") /
              ValueError("requires auth.app_key_env")
    断言点: 三个异常消息关键字
    防回归: 若校验被删，profile 冲突或缺失凭据会静默通过
    """
    with pytest.raises(ValueError, match="Duplicate model profile: openai_compatible/chat"):
        model_sources.register_profile("openai_compatible", "chat", lambda c, g: {})
    with pytest.raises(ValueError, match="No model profile for nope/chat"):
        model_sources.build_profile("nope", "chat", lambda f: None)
    with pytest.raises(ValueError, match="requires auth.app_key_env"):
        model_sources.build_profile("aoc_signed", "chat", lambda f: None)


def test_msrc_auth_values_validation():
    """TC-MSRC-102 | auth 块校验：非 mapping/非法字段名/互斥字段/非标量

    输入: auth=42 / {"BAD!": "x"} / {"api_code": "1", "api_code_env": "E"} /
          {"api_code": ["list"]}
    预期输出: ValueError 消息分别含 "must be a mapping" / "invalid field name" /
              "are mutually exclusive" / "must be a scalar"
    断言点: 四个异常消息关键字
    防回归: 若 auth 校验被删，凭据可被内联进 YAML
    """
    with pytest.raises(ValueError, match="must be a mapping"):
        model_sources._auth_values(42, _NullSource(), "chat.auth")
    with pytest.raises(ValueError, match="invalid field name"):
        model_sources._auth_values({"BAD!": "x"}, _NullSource(), "chat.auth")
    with pytest.raises(ValueError, match="are mutually exclusive"):
        model_sources._auth_values({"api_code": "1", "api_code_env": "E"},
                                   _NullSource(), "chat.auth")
    with pytest.raises(ValueError, match="must be a scalar"):
        model_sources._auth_values({"api_code": ["list"]}, _NullSource(), "chat.auth")


def _load(tmp_path, body, source=None):
    path = _write_yaml(tmp_path, body)
    return model_sources.load_model_configs(source or _NullSource(), path)


def test_msrc_structural_validation_errors(tmp_path):
    """TC-MSRC-103 | YAML 结构校验：缺文件/非 models 顶层/models 非 mapping/坏 capability/非 dict 项

    输入: 不存在路径 / "root: 1" / "models: 42" / "models: {1: {}}" / "models: {chat: 3}"
    预期输出: FileNotFoundError / "expected a single 'models' mapping" /
              "'models' must be a mapping" / "invalid capability name" / "must be a mapping"
    断言点: 异常类型与消息关键字
    防回归: 若结构校验被删，坏配置产生难懂的下游错误
    """
    with pytest.raises(FileNotFoundError, match="Model configuration file not found"):
        model_sources.load_model_configs(_NullSource(), tmp_path / "missing.yaml")

    with pytest.raises(ValueError, match="expected a single 'models' mapping"):
        _load(tmp_path, "root: 1\n")
    with pytest.raises(ValueError, match="'models' must be a mapping"):
        _load(tmp_path, "models: 42\n")
    with pytest.raises(ValueError, match="invalid capability name"):
        _load(tmp_path, "models:\n  1:\n    model: m\n    url: https://h\n")
    with pytest.raises(ValueError, match="chat must be a mapping"):
        _load(tmp_path, "models:\n  chat: 3\n")


def test_msrc_field_validation_errors(tmp_path):
    """TC-MSRC-104 | 字段校验：未知字段/model 缺失/url 缺失/provider 非串/description 非串

    输入: 五种坏 YAML（各缺一个必填或含未知字段）
    预期输出: ValueError 消息分别含 "unsupported fields" / "model is required" /
              "url is required" / "provider must be a string" / "description must be a string"
    断言点: 五个异常消息关键字
    防回归: 若字段校验被删，坏模型定义进入运行时
    防泄漏: url 含内嵌凭据也被拒绝
    """
    with pytest.raises(ValueError, match="unsupported fields"):
        _load(tmp_path, "models:\n  chat:\n    model: m\n    url: https://h\n    bogus: 1\n")
    with pytest.raises(ValueError, match="model is required"):
        _load(tmp_path, "models:\n  chat:\n    url: https://h\n")
    with pytest.raises(ValueError, match="url is required"):
        _load(tmp_path, "models:\n  chat:\n    model: m\n")
    with pytest.raises(ValueError, match="provider must be a string"):
        _load(tmp_path, "models:\n  chat:\n    model: m\n    url: https://h\n    provider: 3\n")
    with pytest.raises(ValueError, match="description must be a string"):
        _load(tmp_path, "models:\n  chat:\n    model: m\n    url: https://h\n    description: 3\n")
    with pytest.raises(ValueError, match="must be an HTTP\\(S\\) URL without embedded credentials"):
        _load(tmp_path, "models:\n  chat:\n    model: m\n    url: https://user:pass@h\n")


def test_msrc_valid_config_loaded(tmp_path):
    """TC-MSRC-105 | 合法配置加载后字段齐全

    输入: 标准 chat 配置（model/url/timeout/verify_ssl/api_key_env）
    预期输出: result["chat"]["model"]/["url"]/["timeout"] 与 YAML 一致；api_key 来自环境
    断言点: 四个字段值
    防回归: 若加载管线被改坏，模型配置丢失默认值
    """

    class EnvSource:
        def get(self, name):
            return "sk-live" if name == "MY_KEY_ENV" else None

    result = _load(tmp_path,
                   "models:\n  chat:\n    model: gpt-x\n    url: https://api.example.com\n"
                   "    timeout: 12\n    verify_ssl: false\n    api_key_env: MY_KEY_ENV\n",
                   EnvSource())
    cfg = result["chat"]
    assert cfg["model"] == "gpt-x"
    assert cfg["url"] == "https://api.example.com"
    assert cfg["timeout"] == 12.0
    assert cfg["verify_ssl"] is False
    assert cfg["api_key"] == "sk-live"


# ==========================================================================
# TC-CERTCHK: cert_check.py
# ==========================================================================

def _self_signed(key, not_before=None, not_after=None):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ut-check")])
    start = not_before or (datetime.now(timezone.utc) - timedelta(days=1))
    end = not_after or (datetime.now(timezone.utc) + timedelta(days=30))
    builder = (x509.CertificateBuilder()
               .subject_name(name).issuer_name(name)
               .public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(start).not_valid_after(end)
               .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True))
    return builder.sign(key, hashes.SHA256())


def test_certchk_not_yet_valid_certificate(tmp_path):
    """TC-CERTCHK-101 | 未生效证书的 validity period 检查失败并给出 notBefore

    输入: not_valid_before = 明天的证书
    预期输出: (False, results)；results 含 ("validity period", False, detail 含 "not yet valid")
    断言点: passed=False + detail 关键字
    防回归: 若时间窗检查被删，未生效证书被放行
    """
    cert = _self_signed(rsa.generate_private_key(public_exponent=65537, key_size=3072),
                        not_before=datetime.now(timezone.utc) + timedelta(days=1))
    path = tmp_path / "client.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    passed, results = cert_check.check_certificate(str(path))
    assert passed is False
    entry = next(r for r in results if r[0] == "validity period")
    assert entry[1] is False
    assert "not yet valid" in entry[2]


def test_certchk_ec_strength_weak_and_strong(tmp_path):
    """TC-CERTCHK-102 | EC 密钥强度：P-192 失败 / P-256 通过

    输入: secp192r1 与 secp256r1 证书
    预期输出: 192 → 该项 False 且 detail 含 "bits < required 256"；256 → True
    断言点: 两个 key strength 结果
    防回归: 若 EC 分支被删，弱椭圆曲线密钥被放行
    """
    weak = _self_signed(ec.generate_private_key(ec.SECP192R1()))
    weak_path = tmp_path / "weak.pem"
    weak_path.write_bytes(weak.public_bytes(serialization.Encoding.PEM))
    passed, results = cert_check.check_certificate(str(weak_path))
    entry = next(r for r in results if r[0] == "key strength (EC)")
    assert entry[1] is False
    assert "bits < required 256" in entry[2]
    assert passed is False

    strong = _self_signed(ec.generate_private_key(ec.SECP256R1()))
    strong_path = tmp_path / "strong.pem"
    strong_path.write_bytes(strong.public_bytes(serialization.Encoding.PEM))
    passed, results = cert_check.check_certificate(str(strong_path))
    entry = next(r for r in results if r[0] == "key strength (EC)")
    assert entry[1] is True


def test_certchk_unreadable_ca_bundle(tmp_path):
    """TC-CERTCHK-103 | CA bundle 不可读时 trust chain 失败并给出原因

    输入: 合法客户端证书 + 垃圾 CA 文件
    预期输出: trust chain False，detail 含 "CA bundle unreadable"
    断言点: detail 关键字
    防回归: 若读文件异常未捕获，坏 CA 让工具崩溃
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    cert = _self_signed(key)
    cert_path = tmp_path / "client.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(b"garbage")
    passed, results = cert_check.check_certificate(str(cert_path), ca_path=str(ca_path))
    entry = next(r for r in results if r[0] == "trust chain")
    assert entry[1] is False
    assert "CA bundle unreadable" in entry[2]


def test_certchk_trust_chain_and_crl(tmp_path):
    """TC-CERTCHK-104 | 有效信任链通过；被吊销序列号在 CRL 中检出

    输入: CA 与其签发的客户端证书；CRL 吊销该序列号
    预期输出: 无 CRL 时信任链 True；吊销后该项 False 且 detail 含 "REVOKED"
    断言点: trust chain True + CRL 项 False + detail 关键字
    防回归: 若吊销检查被删，已吊销证书继续可用
    """
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_cert = _self_signed(ca_key)
    client_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    client_cert = (x509.CertificateBuilder()
                   .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "client-1")]))
                   .issuer_name(ca_cert.subject)
                   .public_key(client_key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
                   .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
                   .sign(ca_key, hashes.SHA256()))

    cert_path = tmp_path / "client.pem"
    cert_path.write_bytes(client_cert.public_bytes(serialization.Encoding.PEM))
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    passed, results = cert_check.check_certificate(str(cert_path), ca_path=str(ca_path))
    assert next(r for r in results if r[0] == "trust chain")[1] is True
    assert passed is True

    revoked_list = (x509.CertificateRevocationListBuilder()
                    .issuer_name(ca_cert.subject)
                    .last_update(datetime.now(timezone.utc))
                    .next_update(datetime.now(timezone.utc) + timedelta(days=1))
                    .add_revoked_certificate(x509.RevokedCertificateBuilder()
                                             .serial_number(client_cert.serial_number)
                                             .revocation_date(datetime.now(timezone.utc))
                                             .build()))
    crl_path = tmp_path / "revoked.crl"
    crl_path.write_bytes(revoked_list.sign(ca_key, hashes.SHA256()).public_bytes(
        serialization.Encoding.PEM))
    passed, results = cert_check.check_certificate(str(cert_path), ca_path=str(ca_path),
                                                   crl_path=str(crl_path))
    entry = next(r for r in results if r[0] == "CRL revocation status")
    assert entry[1] is False
    assert "REVOKED" in entry[2]
    assert passed is False


# ==========================================================================
# TC-CSPARSE: common/cert/cert_parser.py
# ==========================================================================

def test_csparse_missing_inputs_raise(tmp_path):
    """TC-CSPARSE-101 | 非 PEM 文件 / 无私钥 / 无 CRL 各抛 CertParseException

    输入: 空文件（无 BEGIN 标记）/ 仅含证书的 PEM（无私钥）/ 仅含证书的 PEM（当 CRL 解析）
    预期输出: 消息分别含 '"-----BEGIN" not found' / "Parse private key error" / 含 "crl" 的错误
    断言点: 异常类型 + 三种消息关键字
    防回归: 若空输入检查被删，解析返回 None 导致下游崩溃
    """
    empty = tmp_path / "empty.pem"
    empty.write_bytes(b"")
    with pytest.raises(CertParseException, match='"-----BEGIN" not found'):
        parse_cer_certificate(str(empty))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = _self_signed(key)
    cert_only = tmp_path / "cert_only.pem"
    cert_only.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    with pytest.raises(CertParseException, match="Parse private key error"):
        parse_pem_files(str(cert_only))
    with pytest.raises(CertParseException, match="crl"):
        parse_crl_list(str(cert_only))


def test_csparse_garbage_wraps_original_error(tmp_path):
    """TC-CSPARSE-102 | 非 PEM 内容被拒绝且不泄露原始细节

    输入: 内容 "definitely not pem" 的文件
    预期输出: CertParseException，消息不含文件原文（DER 模式提示）
    断言点: 异常类型 + 消息不含原始内容
    防回归: 若原始异常直接上抛，内部细节泄露给调用方
    """
    garbage = tmp_path / "garbage.pem"
    garbage.write_bytes(b"definitely not pem")
    with pytest.raises(CertParseException, match='"-----BEGIN" not found'):
        parse_cer_certificate(str(garbage))


# ==========================================================================
# TC-CONF: common/util/conf_obj.py
# ==========================================================================

def test_conf_get_crl_list_rendering():
    """TC-CONF-101 | get_crl_list：无数据返回 []；有数据渲染序列号 hex

    输入: crl_list_data=None / [SimpleNamespace(serial_number=0xABC)]
    预期输出: [] / ["0xabc"]
    断言点: 两个返回值
    防回归: 若渲染被删，CRL 信息缺失影响排障
    """
    obj = conf_obj_mod.ConfObj()
    obj.crl_list_data = None
    assert obj.get_crl_list() == []
    obj.crl_list_data = [SimpleNamespace(serial_number=0xABC)]
    assert obj.get_crl_list() == [hex(0xABC)]
