# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""JWKFetcher coverage tests (agent_registry/signature/jwk_fetcher.py).

All HTTP traffic goes through ``httpx.MockTransport`` — no socket is opened, so the
suite is deterministic and offline. Every fetcher is closed at the end of its test so
no connection pool leaks between tests; no module-level singleton is touched.
"""

import base64

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK

from agent_registry.signature.jwk_fetcher import JWKFetcher
from agent_registry.signature.models import JWK, JWKS

ALLOWED_HOST = "keys.example.com"
JKU = "https://keys.example.com/jwks.json"

# Public coordinates of a real P-256 key (RFC 7515 appendix A.3).
EC_JWK = {
    "kty": "EC",
    "kid": "ec-key",
    "use": "sig",
    "alg": "ES256",
    "crv": "P-256",
    "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
    "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0",
}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _rsa_jwk(kid="rsa-key"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    numbers = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": _b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }


async def _fetcher_with_client(handler, allowlist=ALLOWED_HOST):
    """Create a fetcher whose session is a MockTransport-backed client."""
    fetcher = JWKFetcher(jwk_allowlist=allowlist)
    await fetcher.session.aclose()
    fetcher.session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return fetcher


# --------------------------------------------------------------------------
# Host allowlist (trust boundary)
# --------------------------------------------------------------------------

class TestHostAllowlist:
    def test_empty_allowlist_fails_closed(self):
        """TC-JWK-001 | 未配置允许列表时 jku 取键一律拒绝（fail closed）

        输入: JWKFetcher(jwk_allowlist=None)._is_jku_host_allowed("https://keys.example.com/j")
        预期输出: False
        断言点: 返回值为 False（安全默认值）；jwk_allowlist 为空集合
        防回归: 若未配置时返回 True，签名方可指定任意 key 地址（CWE-863），本用例失败
        """
        fetcher = JWKFetcher(jwk_allowlist=None)

        assert fetcher.jwk_allowlist == set()
        assert fetcher._is_jku_host_allowed(JKU) is False

    def test_userinfo_in_url_is_rejected(self):
        """TC-JWK-002 | URL 内嵌 userinfo 时拒绝取键

        输入: _is_jku_host_allowed("https://user:secret@keys.example.com/jwks.json")
        预期输出: False（即使 host 在允许列表内）
        断言点: 返回值为 False
        防回归: 若 userinfo 被忽略，攻击者可用合法 host 前缀构造钓鱼 URL，本用例失败
        """
        fetcher = JWKFetcher(jwk_allowlist=ALLOWED_HOST)

        assert fetcher._is_jku_host_allowed(
            "https://user:secret@keys.example.com/jwks.json") is False

    def test_unparsable_url_is_rejected(self, monkeypatch):
        """TC-JWK-003 | URL 解析抛异常时按拒绝处理并记录日志

        输入: monkeypatch urlparse 抛 ValueError，jku="https://keys.example.com/j"
        预期输出: False
        断言点: 返回值为 False（异常不外抛）
        防回归: 若解析异常向上传播，单条畸形 jku 会打断整个验签流程，本用例失败
        """
        import agent_registry.signature.jwk_fetcher as module

        def _boom(value):
            raise ValueError("bad url")

        monkeypatch.setattr(module, "urlparse", _boom)
        fetcher = JWKFetcher(jwk_allowlist=ALLOWED_HOST)

        assert fetcher._is_jku_host_allowed(JKU) is False

    def test_url_without_host_is_rejected(self):
        """TC-JWK-004 | 无主机名的 jku 被拒绝

        输入: _is_jku_host_allowed("https:///jwks.json")
        预期输出: False
        断言点: 返回值为 False
        防回归: 若空 host 落入允许列表比较，"" 与空配置组合会误放行，本用例失败
        """
        fetcher = JWKFetcher(jwk_allowlist=ALLOWED_HOST)

        assert fetcher._is_jku_host_allowed("https:///jwks.json") is False

    def test_allowlisted_host_matches_case_and_port_insensitively(self):
        """TC-JWK-005 | 允许列表按 host 匹配：大小写不敏感、忽略端口，未登记 host 拒绝

        输入: allowlist="Keys.Example.COM"；分别用 keys.example.com:8443、
              other.example.com
        预期输出: True、False
        断言点: 两次返回值
        防回归: 若把整个 netloc（含端口）与允许列表比较，带端口的 jku 永远不匹配，本用例失败
        """
        fetcher = JWKFetcher(jwk_allowlist="Keys.Example.COM")

        assert fetcher._is_jku_host_allowed("https://keys.example.com:8443/jwks.json") is True
        assert fetcher._is_jku_host_allowed("https://other.example.com/jwks.json") is False


# --------------------------------------------------------------------------
# fetch_jwks HTTP behaviour
# --------------------------------------------------------------------------

class TestFetchJwks:
    @pytest.mark.asyncio
    async def test_non_200_response_returns_none(self):
        """TC-JWK-006 | 非 200 响应按取键失败处理

        输入: MockTransport 返回 404
        预期输出: None
        断言点: 返回值为 None
        防回归: 若错误状态码仍解析响应体，攻击者可用 500 页面伪装 JWKS，本用例失败
        """
        fetcher = await _fetcher_with_client(lambda request: httpx.Response(404))
        try:
            assert await fetcher.fetch_jwks(JKU) is None
        finally:
            await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_content_length_over_limit_returns_none(self):
        """TC-JWK-007 | Content-Length 超过 1 MiB 时不再读取响应体

        输入: MockTransport 返回 200 且声明 Content-Length=1048577
        预期输出: None
        断言点: 返回值为 None；服务端只收到一次请求
        防回归: 若上限校验被删除，超大响应会耗尽内存（DoS），本用例失败
        """
        requests = []

        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, headers={"Content-Length": "1048577"}, content=b"{}")

        fetcher = await _fetcher_with_client(handler)
        try:
            assert await fetcher.fetch_jwks(JKU) is None
            assert requests == [JKU]
        finally:
            await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        """TC-JWK-008 | 请求超时按取键失败处理，异常不外抛

        输入: MockTransport handler 抛 httpx.ConnectTimeout
        预期输出: None
        断言点: 返回值为 None（TimeoutException 分支被单独捕获）
        防回归: 若超时异常外抛，一次网络抖动会让验签接口 500，本用例失败
        """
        def handler(request):
            raise httpx.ConnectTimeout("timed out")

        fetcher = await _fetcher_with_client(handler)
        try:
            assert await fetcher.fetch_jwks(JKU) is None
        finally:
            await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        """TC-JWK-009 | 传输层错误（连接失败）按取键失败处理

        输入: MockTransport handler 抛 httpx.ConnectError
        预期输出: None
        断言点: 返回值为 None（HTTPError 分支被捕获）
        防回归: 若 HTTPError 未捕获，jku 站点不可达会让验签抛异常，本用例失败
        """
        def handler(request):
            raise httpx.ConnectError("connection refused")

        fetcher = await _fetcher_with_client(handler)
        try:
            assert await fetcher.fetch_jwks(JKU) is None
        finally:
            await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_none(self):
        """TC-JWK-010 | 非 httpx 异常同样兜底为 None

        输入: MockTransport handler 抛 ValueError
        预期输出: None
        断言点: 返回值为 None（兜底 except 分支）
        防回归: 若兜底分支被删除，未知异常会穿透到验签调用方，本用例失败
        """
        def handler(request):
            raise ValueError("unexpected body handling")

        fetcher = await _fetcher_with_client(handler)
        try:
            assert await fetcher.fetch_jwks(JKU) is None
        finally:
            await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_successful_fetch_builds_key_set(self):
        """TC-JWK-011 | 200 + 合法 JWKS 返回按键解析后的密钥集

        输入: MockTransport 返回 {"keys": [EC_JWK]}
        预期输出: JWKS，含 1 个 kid="ec-key" 的 JWK；请求 URL 与 jku 完全一致
        断言点: 类型；键数量；kid；请求 URL
        防回归: 若响应体解析路径丢失 kid，后续按 kid 选键会全部失败，本用例失败
        """
        requests = []

        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, json={"keys": [EC_JWK]})

        fetcher = await _fetcher_with_client(handler)
        try:
            jwks = await fetcher.fetch_jwks(JKU)
        finally:
            await fetcher.aclose()

        assert isinstance(jwks, JWKS)
        assert [key.kid for key in jwks.keys] == ["ec-key"]
        assert requests == [JKU]

    @pytest.mark.asyncio
    async def test_aclose_closes_the_connection_pool(self):
        """TC-JWK-012 | aclose 关闭底层连接池

        输入: fetcher.aclose()
        预期输出: session.is_closed 为 True
        断言点: is_closed 状态（幂等关闭不抛异常）
        防回归: 若 aclose 不再关闭 session，停机时连接池泄漏，本用例失败
        """
        fetcher = JWKFetcher(jwk_allowlist=ALLOWED_HOST)
        assert fetcher.session.is_closed is False

        await fetcher.aclose()

        assert fetcher.session.is_closed is True

    @pytest.mark.asyncio
    async def test_host_outside_allowlist_never_reaches_the_network(self):
        """TC-JWK-032 | host 不在允许列表时不发起任何请求

        输入: allowlist="keys.example.com"，jku 指向 attacker.example.com
        预期输出: None，且 transport 未被调用
        断言点: 返回值；请求计数为 0
        防回归: 若允许列表校验被移到请求之后，SSRF 已发生，本用例失败
        """
        requests = []

        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, json={"keys": [EC_JWK]})

        fetcher = await _fetcher_with_client(handler)
        try:
            assert await fetcher.fetch_jwks("https://attacker.example.com/jwks.json") is None
            assert requests == []
        finally:
            await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_plain_http_is_rejected_even_for_allowed_host(self):
        """TC-JWK-033 | 允许列表通过后仍强制 HTTPS

        输入: jku="http://keys.example.com/jwks.json"
        预期输出: None，且 transport 未被调用
        断言点: 返回值；请求计数为 0
        防回归: 若 HTTPS 校验被删除，明文传输的密钥可被中间人替换，本用例失败
        """
        requests = []

        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, json={"keys": [EC_JWK]})

        fetcher = await _fetcher_with_client(handler)
        try:
            assert await fetcher.fetch_jwks("http://keys.example.com/jwks.json") is None
            assert requests == []
        finally:
            await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_chunked_body_over_limit_is_aborted(self):
        """TC-JWK-034 | 无 Content-Length 时按累计字节数中断超大响应

        输入: 分块返回 2 × 600 KiB（合计 1.2 MiB > 1 MiB 上限）
        预期输出: None
        断言点: 返回值为 None（累计字节校验先于 json 解析）
        防回归: 若只信 Content-Length，分块响应可绕过上限造成内存放大，本用例失败
        """
        class _Chunks(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b" " * 600_000
                yield b" " * 600_000

        fetcher = await _fetcher_with_client(
            lambda request: httpx.Response(200, stream=_Chunks()))
        try:
            assert await fetcher.fetch_jwks(JKU) is None
        finally:
            await fetcher.aclose()


class TestBuildJwks:
    def test_non_dict_payload_is_rejected(self):
        """TC-JWK-013 | 非对象载荷被判为非密钥集

        输入: _build_jwks(["not", "a", "set"]) 与 _build_jwks("text")
        预期输出: 均为 None
        断言点: 两次返回值 is None
        防回归: 若直接对字符串取 ["keys"]，会抛 TypeError 打断验签，本用例失败
        """
        assert JWKFetcher._build_jwks(["not", "a", "set"]) is None
        assert JWKFetcher._build_jwks("text") is None

    def test_keys_not_a_list_is_rejected(self):
        """TC-JWK-014 | keys 字段不是数组时判为非密钥集

        输入: _build_jwks({"keys": {"kty": "EC"}})
        预期输出: None
        断言点: 返回值为 None
        防回归: 若对 dict 迭代，会逐个遍历键名并静默产生空集合，本用例失败
        """
        assert JWKFetcher._build_jwks({"keys": {"kty": "EC"}}) is None

    def test_encryption_and_unsupported_keys_are_skipped(self):
        """TC-JWK-015 | 跳过加密用途与非对象条目，保留可用验签密钥

        输入: keys = [use="enc" 条目, "not-a-dict", EC_JWK]
        预期输出: JWKS 仅含 ec-key
        断言点: kid 列表 == ["ec-key"]
        防回归: 若单个不可用条目导致整集丢弃，混合发布的第三方 JWKS 无法验签，本用例失败
        """
        jwks = JWKFetcher._build_jwks({"keys": [
            {"kty": "RSA", "kid": "enc", "use": "enc", "n": "AAA", "e": "AQAB"},
            "not-a-dict",
            EC_JWK,
        ]})

        assert [key.kid for key in jwks.keys] == ["ec-key"]

    def test_no_usable_key_fails_closed(self):
        """TC-JWK-016 | 全部条目不可用时返回 None 而不是空密钥集

        输入: keys = [use="enc" 条目]
        预期输出: None
        断言点: 返回值为 None
        防回归: 若返回空 JWKS，调用方会走"键不存在"分支并掩盖配置错误，本用例失败
        """
        assert JWKFetcher._build_jwks({"keys": [
            {"kty": "RSA", "kid": "enc", "use": "enc", "n": "AAA", "e": "AQAB"},
        ]}) is None

    def test_model_validation_failures_are_skipped(self):
        """TC-JWK-035 | 通不过模型校验的条目（P-384/缺字段）被跳过，其余保留

        输入: keys = [EC P-384 条目, RSA 缺 n/e 条目, EC_JWK]
        预期输出: JWKS 仅含 ec-key（三条中有两条触发 ValidationError 分支）
        断言点: kid 列表 == ["ec-key"]
        防回归: 若 ValidationError 未被捕获，一个不合规条目会让整个密钥集失效，本用例失败
        """
        jwks = JWKFetcher._build_jwks({"keys": [
            {"kty": "EC", "kid": "p384", "use": "sig", "crv": "P-384", "x": "AAA", "y": "BBB"},
            {"kty": "RSA", "kid": "no-material", "use": "sig"},
            EC_JWK,
        ]})

        assert [key.kid for key in jwks.keys] == ["ec-key"]


class TestFindKeyById:
    def test_none_key_set_returns_none(self):
        """TC-JWK-017 | 传入 None 密钥集时返回 None

        输入: find_key_by_id(None, "kid")
        预期输出: None
        断言点: 返回值为 None（不抛 AttributeError）
        防回归: 若缺少 None 判断，取键失败路径会变成异常，本用例失败
        """
        assert JWKFetcher.find_key_by_id(None, "kid") is None

    def test_returns_matching_key(self):
        """TC-JWK-018 | 按键 ID 精确匹配返回对应 JWK

        输入: JWKS 含 ec-key 与 rsa-key，查询 "rsa-key"
        预期输出: kid == "rsa-key" 的 JWK 对象
        断言点: 返回对象的 kid 与 kty
        防回归: 若比较写成 startswith/前缀匹配，kid 前缀碰撞会选错密钥，本用例失败
        """
        jwks = JWKS(keys=[JWK(**EC_JWK), JWK(**{**_rsa_jwk(), "kid": "rsa-key"})])

        found = JWKFetcher.find_key_by_id(jwks, "rsa-key")

        assert found.kid == "rsa-key"
        assert found.kty == "RSA"

    def test_missing_kid_returns_none(self):
        """TC-JWK-019 | kid 不在密钥集中时返回 None

        输入: JWKS 含 ec-key，查询 "absent"
        预期输出: None
        断言点: 返回值为 None
        防回归: 若找不到时返回第一把密钥，会静默使用错误密钥验签，本用例失败
        """
        assert JWKFetcher.find_key_by_id(JWKS(keys=[JWK(**EC_JWK)]), "absent") is None

    def test_iteration_error_is_swallowed(self):
        """TC-JWK-020 | 遍历密钥集出错时返回 None 而不是抛异常

        输入: 传入 keys 属性抛 RuntimeError 的替身对象
        预期输出: None
        断言点: 返回值为 None
        防回归: 若 except 分支被删除，损坏的密钥集会中断验签流程，本用例失败
        """
        class _Broken:
            @property
            def keys(self):
                raise RuntimeError("corrupted key set")

        assert JWKFetcher.find_key_by_id(_Broken(), "kid") is None


class TestBackendKeyLookup:
    def test_convert_ec_and_rsa_keys(self):
        """TC-JWK-021 | JWK 转换为 PyJWK：EC 带 crv/x/y，RSA 带 n/e，可选 alg 透传

        输入: _convert_to_pyjwk(EC_JWK)（含 alg）与 _convert_to_pyjwk(rsa_jwk 去掉 alg)
        预期输出: PyJWK，key_id 分别为 ec-key / rsa-key
        断言点: 类型；key_id；algorithm_name（ES256 / RS256 由密钥推得）
        防回归: 若 x/y 或 n/e 未被带入 PyJWK 构造，PyJWK 会解析失败或得到错误公钥，本用例失败
        """
        rsa_payload = _rsa_jwk()
        ec_pyjwk = JWKFetcher._convert_to_pyjwk(JWK(**EC_JWK))
        rsa_pyjwk = JWKFetcher._convert_to_pyjwk(JWK(**{k: v for k, v in rsa_payload.items()
                                                       if k != "alg"}))

        assert isinstance(ec_pyjwk, PyJWK)
        assert ec_pyjwk.key_id == "ec-key"
        assert ec_pyjwk.algorithm_name == "ES256"
        assert isinstance(rsa_pyjwk, PyJWK)
        assert rsa_pyjwk.key_id == "rsa-key"
        assert rsa_pyjwk.algorithm_name == "RS256"

    def test_non_signature_key_is_refused(self):
        """TC-JWK-022 | use != "sig" 的密钥拒绝转换为验签公钥

        输入: _convert_to_pyjwk(JWK(kty="EC", use="enc", ...))
        预期输出: ValueError，消息含 "not intended for signature verification"
        断言点: 异常类型 + 消息关键字
        防回归: 若 use 校验被删除，加密密钥可被用于验签（算法混淆），本用例失败
        """
        with pytest.raises(ValueError, match="not intended for signature verification"):
            JWKFetcher._convert_to_pyjwk(JWK(**{**EC_JWK, "use": "enc"}))

    def test_invalid_key_material_is_reraised(self):
        """TC-JWK-023 | 非法密钥材料导致 PyJWK 解析失败时异常继续上抛

        输入: _convert_to_pyjwk(JWK(kty="EC", x/y 为非法 base64))
        预期输出: 异常（PyJWK 解码失败后被 except 记录并 re-raise）
        断言点: 抛出异常且类型不是 ValueError("not intended...")——即原异常被重新抛出
        防回归: 若 except 分支吞掉异常返回 None，调用方会误判"密钥不存在"，本用例失败
        """
        broken = {"kty": "EC", "kid": "broken", "use": "sig", "alg": "ES256",
                  "crv": "P-256", "x": "!!!", "y": "!!!"}

        with pytest.raises(Exception) as excinfo:
            JWKFetcher._convert_to_pyjwk(JWK(**broken))

        assert "not intended for signature verification" not in str(excinfo.value)

    def test_fetch_from_backend_without_manager_returns_none(self):
        """TC-JWK-024 | 未配置 PublicKeyManager 时后端取键返回 None

        输入: JWKFetcher().fetch_from_backend("kid", "org", "agent")
        预期输出: None
        断言点: 返回值为 None
        防回归: 若未判空直接调用，缺少公钥管理器的部署会在验签时抛 AttributeError，本用例失败
        """
        fetcher = JWKFetcher(jwk_allowlist=ALLOWED_HOST)

        assert fetcher.public_key_manager is None
        assert fetcher.fetch_from_backend("kid", "org", "agent") is None

    def test_fetch_from_backend_converts_found_key(self):
        """TC-JWK-025 | 后端命中公钥时转换为 PyJWK，查询参数原样传递

        输入: public_key_manager.get_public_key 返回 EC JWK，调用
              fetch_from_backend("ec-key", "org-1", "agent-1", "https://p.example")
        预期输出: PyJWK(kid="ec-key")；管理器收到四个位置参数
        断言点: 返回类型与 key_id；mock 的 call_args
        防回归: 若 organization/provider_url 传参错位，多租户会取到别人的密钥，本用例失败
        """
        from unittest.mock import MagicMock
        manager = MagicMock()
        manager.get_public_key.return_value = JWK(**EC_JWK)
        fetcher = JWKFetcher(public_key_manager=manager, jwk_allowlist=ALLOWED_HOST)

        result = fetcher.fetch_from_backend("ec-key", "org-1", "agent-1", "https://p.example")

        assert isinstance(result, PyJWK)
        assert result.key_id == "ec-key"
        manager.get_public_key.assert_called_once_with("org-1", "agent-1", "ec-key",
                                                      "https://p.example")

    def test_fetch_from_backend_miss_returns_none(self):
        """TC-JWK-026 | 后端未命中公钥时返回 None

        输入: public_key_manager.get_public_key 返回 None
        预期输出: None
        断言点: 返回值为 None
        防回归: 若未命中时改用 jku 兜底，会绕过后端信任边界，本用例失败
        """
        from unittest.mock import MagicMock
        manager = MagicMock()
        manager.get_public_key.return_value = None
        fetcher = JWKFetcher(public_key_manager=manager, jwk_allowlist=ALLOWED_HOST)

        assert fetcher.fetch_from_backend("kid", "org", "agent") is None

    def test_fetch_from_backend_error_returns_none(self):
        """TC-JWK-027 | 后端查询抛异常时返回 None 而不中断验签

        输入: public_key_manager.get_public_key 抛 RuntimeError
        预期输出: None
        断言点: 返回值为 None
        防回归: 若异常外抛，后端瞬时故障会让所有验签请求 500，本用例失败
        """
        from unittest.mock import MagicMock
        manager = MagicMock()
        manager.get_public_key.side_effect = RuntimeError("backend down")
        fetcher = JWKFetcher(public_key_manager=manager, jwk_allowlist=ALLOWED_HOST)

        assert fetcher.fetch_from_backend("kid", "org", "agent") is None

    def test_backend_key_fetcher_closure_binds_identity(self):
        """TC-JWK-028 | create_backend_key_fetcher 返回的闭包固定身份参数，只接受 kid

        输入: create_backend_key_fetcher("org-1", "agent-1")("kid-1", "https://jku")
        预期输出: 后端查询参数为 (org-1, agent-1, kid-1, None)
        断言点: mock 的 call_args（jku 不进入后端查询）
        防回归: 若闭包把 jku 当组织名传递，后端会查错租户，本用例失败
        """
        from unittest.mock import MagicMock
        manager = MagicMock()
        manager.get_public_key.return_value = None
        fetcher = JWKFetcher(public_key_manager=manager, jwk_allowlist=ALLOWED_HOST)
        closure = fetcher.create_backend_key_fetcher("org-1", "agent-1")

        assert closure("kid-1", "https://evil.example/keys") is None
        manager.get_public_key.assert_called_once_with("org-1", "agent-1", "kid-1", None)


class TestFetchJkuKey:
    @pytest.mark.asyncio
    async def test_returns_pyjwk_for_known_kid(self):
        """TC-JWK-029 | jku 取键成功：按 kid 找到并转换为 PyJWK

        输入: MockTransport 返回 {"keys": [EC_JWK]}，查询 kid="ec-key"
        预期输出: PyJWK，key_id="ec-key"，algorithm_name="ES256"
        断言点: 类型；key_id；算法名
        防回归: 若 fetch_jku_key 忘记转换（返回 JWK 而非 PyJWK），验签库拿不到可用密钥，本用例失败
        """
        fetcher = await _fetcher_with_client(
            lambda request: httpx.Response(200, json={"keys": [EC_JWK]}))
        try:
            result = await fetcher.fetch_jku_key("ec-key", JKU)
        finally:
            await fetcher.aclose()

        assert isinstance(result, PyJWK)
        assert result.key_id == "ec-key"
        assert result.algorithm_name == "ES256"

    @pytest.mark.asyncio
    async def test_unknown_kid_returns_none(self):
        """TC-JWK-030 | kid 不在 jku 密钥集中时返回 None

        输入: MockTransport 返回 {"keys": [EC_JWK]}，查询 kid="absent"
        预期输出: None
        断言点: 返回值为 None
        防回归: 若找不到 kid 时回退到第一把密钥，会验签到错误签名，本用例失败
        """
        fetcher = await _fetcher_with_client(
            lambda request: httpx.Response(200, json={"keys": [EC_JWK]}))
        try:
            assert await fetcher.fetch_jku_key("absent", JKU) is None
        finally:
            await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_failed_fetch_returns_none(self):
        """TC-JWK-031 | jku 拉取失败时不尝试匹配 kid，直接返回 None

        输入: MockTransport 返回 500，查询 kid="ec-key"
        预期输出: None
        断言点: 返回值为 None
        防回归: 若对 None 密钥集继续调用 find_key_by_id（未判空），会抛 AttributeError，本用例失败
        """
        fetcher = await _fetcher_with_client(lambda request: httpx.Response(500))
        try:
            assert await fetcher.fetch_jku_key("ec-key", JKU) is None
        finally:
            await fetcher.aclose()
