#!/usr/bin/env python3
"""
AgentCard签名测试脚本

这个脚本演示如何：
1. 生成ECDSA密钥对
2. 创建后台公钥文件
3. 构造AgentCard数据
4. 对AgentCard进行签名
5. 测试验签能力
"""

import json
import base64
from a2a.types import AgentCard
from a2a.utils.helpers import canonicalize_agent_card
from a2a.utils.signing import create_agent_card_signer, create_signature_verifier
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from datetime import datetime

from agent_registry.signature.jwk_fetcher import JWKFetcher
from agent_registry.signature.public_key_manager import PublicKeyManager


def generate_ecdsa_key_pair():
    """
    生成ECDSA P-256密钥对
    
    Returns:
        tuple: (private_key, public_key)
    """
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key = private_key.public_key()
    return private_key, public_key


def private_key_to_pem(private_key):
    """
    将私钥转换为PEM格式
    
    Args:
        private_key: 私钥对象
    
    Returns:
        str: PEM格式的私钥
    """
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    return pem.decode('utf-8')


def public_key_to_jwk(public_key, kid="test-key-1"):
    """
    将公钥转换为JWK格式
    
    Args:
        public_key: 公钥对象
        kid: 密钥ID
    
    Returns:
        dict: JWK格式的公钥
    """
    public_numbers = public_key.public_numbers()
    
    # 将坐标转换为base64url编码
    x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
    y_bytes = public_numbers.y.to_bytes(32, byteorder='big')
    
    x_b64url = base64.urlsafe_b64encode(x_bytes).decode('utf-8').rstrip('=')
    y_b64url = base64.urlsafe_b64encode(y_bytes).decode('utf-8').rstrip('=')
    
    jwk = {
        "kty": "EC",
        "kid": kid,
        "use": "sig",
        "alg": "ES256",
        "crv": "P-256",
        "x": x_b64url,
        "y": y_b64url
    }
    return jwk


def create_agent_card():
    """
    创建AgentCard数据（不含signatures字段）
    
    Returns:
        dict: AgentCard数据
    """
    agent_card = {
        "name": "TestAgent",
        "provider": {
            "organization": "TestOrg",
            "url": "https://test.org"
        },
        "description": "Test Description",
        "capabilities": {
            "skills": ["text-generation", "code-generation"],
            "input_modes": ["text/plain", "application/json"],
            "output_modes": ["text/plain", "application/json"]
        },
        "default_input_modes": ["text/plain"],
        "default_output_modes": ["text/plain"],
        "url": "https://agent.test",
        "version": "1.0.0",
        "skills": [
            {
                "id": "skill-1",
                "name": "TestSkill",
                "description": "Test Skill Description",
                "tags": ["test", "skill"],
                "input_modes": ["text/plain"],
                "output_modes": ["text/plain"]
            }
        ]
    }
    return agent_card


def create_protected_header(kid, jku_url):
    """
    创建protected头
    
    Args:
        kid: 密钥ID
        jku_url: JWK Set URL
    
    Returns:
        dict: protected头
    """
    protected = {
        "alg": "ES256",
        "typ": "JOSE",
        "kid": kid,
        "jku": jku_url
    }
    return protected


def base64url_encode(data):
    """
    Base64URL编码
    
    Args:
        data: 字符串或字节
    
    Returns:
        str: base64url编码的字符串
    """
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')


def sign_agent_card(private_key, agent_card, protected_header):
    """
    对AgentCard进行签名

    Args:
        private_key: 私钥对象
        agent_card: AgentCard数据
        protected_header: protected头

    Returns:
        dict: 签名对象
    """
    # 1. 创建签名器
    signer = create_agent_card_signer(private_key, protected_header=protected_header)

    # 2. 使用验签器生成带签名的请求
    agent_card_obj = AgentCard(**agent_card)
    signed_card = signer(agent_card_obj)

    canonical_payload = canonicalize_agent_card(agent_card_obj)
    protected_b64url = signed_card.model_dump().get("signatures")[0].get('protected')
    payload_b64url = base64url_encode(canonical_payload.encode('utf-8'))
    sign_input = f"{protected_b64url}.{payload_b64url}"
    print('=' * 100)
    print('sign_input:')
    print(sign_input)
    print('=' * 100)

    # 3. 此处尝试直接验签，确保直接验签是可以成功的
    organization = "TestOrg"
    agent_name = "TestAgent"
    kid = "test-key-1"
    public_key_manager = PublicKeyManager()
    jwk_fetcher = JWKFetcher(public_key_manager)
    backend_key_fetcher = jwk_fetcher.create_backend_key_fetcher(organization, agent_name)
    backend_key = backend_key_fetcher(kid, "")  # 这里第二个参数代表jku，由于后台公钥无需jku，这里给空字符串
    if backend_key:
        verifier = create_signature_verifier(backend_key_fetcher, ['ES256', 'RS256'])
        verifier(signed_card)


    return signed_card.model_dump().get("signatures")[0]


def create_backend_key_file(organization, agent_name, jwk):
    """
    创建后台公钥文件
    
    Args:
        organization: 组织名称
        agent_name: Agent名称
        jwk: JWK格式的公钥
    """
    base_dir = "etc/sign_verify/jwks"
    org_dir = f"{base_dir}/{organization}"
    file_path = f"{org_dir}/{agent_name}.json"
    
    # 构造存储对象
    storage_obj = {
        "organization": organization,
        "agent_name": agent_name,
        "keys": [jwk],
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    
    # 创建目录
    import os
    os.makedirs(org_dir, exist_ok=True)
    
    # 写入文件
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(storage_obj, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 后台公钥文件已创建: {file_path}")
    print(f"   文件内容:")
    print(json.dumps(storage_obj, indent=2, ensure_ascii=False))


def create_complete_agent_card_with_signature():
    """
    创建完整的带签名的AgentCard
    
    Returns:
        tuple: (agent_card_with_signature, private_key_pem, public_key_jwk)
    """
    print("=" * 60)
    print("步骤1: 生成ECDSA密钥对")
    print("=" * 60)
    private_key, public_key = generate_ecdsa_key_pair()
    private_key_pem = private_key_to_pem(private_key)
    public_key_jwk = public_key_to_jwk(public_key, kid="test-key-1")
    
    print(f"✅ 密钥对生成成功")
    print(f"   kid: {public_key_jwk['kid']}")
    print(f"   私钥(PEM):")
    print(private_key_pem)
    print(f"   公钥(JWK):")
    print(json.dumps(public_key_jwk, indent=2))

    print("\n" + "=" * 60)
    print("步骤2: 创建后台公钥文件")
    print("=" * 60)
    organization = "TestOrg"
    agent_name = "TestAgent"
    create_backend_key_file(organization, agent_name, public_key_jwk)
    
    print("\n" + "=" * 60)
    print("步骤3: 创建AgentCard数据")
    print("=" * 60)
    agent_card = create_agent_card()
    print(f"✅ AgentCard数据创建成功")
    print(json.dumps(agent_card, indent=2))
    
    print("\n" + "=" * 60)
    print("步骤4: 创建protected头")
    print("=" * 60)
    kid = "test-key-1"
    jku_url = "https://test.org/jwks.json"
    protected_header = create_protected_header(kid, jku_url)
    print(f"✅ Protected头创建成功")
    print(json.dumps(protected_header, indent=2))
    
    print("\n" + "=" * 60)
    print("步骤5: 对AgentCard进行签名")
    print("=" * 60)
    signature_obj = sign_agent_card(private_key, agent_card, protected_header)
    print(f"✅ 签名成功")
    print(json.dumps(signature_obj, indent=2))
    
    print("\n" + "=" * 60)
    print("步骤6: 构造完整的AgentCard（包含signatures）")
    print("=" * 60)
    agent_card_with_signature = agent_card.copy()
    agent_card_with_signature["signatures"] = [signature_obj]
    print(f"✅ 完整AgentCard构造成功")
    print(json.dumps(agent_card_with_signature, indent=2))
    
    return agent_card_with_signature, private_key_pem, public_key_jwk


def test_signature_verification():
    """
    测试签名验证
    """
    print("\n" + "=" * 60)
    print("步骤7: 测试签名验证")
    print("=" * 60)
    
    # 创建带签名的AgentCard
    agent_card_with_signature, private_key_pem, public_key_jwk = create_complete_agent_card_with_signature()
    
    print("\n" + "=" * 60)
    print("测试说明")
    print("=" * 60)
    print("""
现在你可以使用以下curl命令测试验签接口：

curl -X POST "http://localhost:8000/rest/a2a-t/v1/agents/register" \\
  -H "Content-Type: application/json" \\
  -d '""" + json.dumps(agent_card_with_signature) + """'

预期结果：
- 如果验签成功：返回201 Created和true
- 如果验签失败：返回401 Unauthorized和错误信息

验签流程：
1. 服务端接收AgentCard注册请求
2. 从AgentCard中提取signatures字段
3. 解码protected头，获取kid和jku
4. 优先从后台公钥文件中查找对应kid的公钥
5. 如果找到后台公钥，使用该公钥验签
6. 如果后台公钥验签失败或未找到，从jku URL获取公钥
7. 使用获取的公钥验签
8. 验签通过后继续注册流程
    """)


if __name__ == "__main__":
    test_signature_verification()
