#!/usr/bin/env python3
"""
AgentCard Signature Test Script

This script demonstrates how to:
1. Generate ECDSA key pair
2. Create backend public key file
3. Construct AgentCard data
4. Sign AgentCard
5. Test signature verification

Adapted for a2a-sdk 1.0.0+ (protobuf-based AgentCard)
"""

import json
import base64
import os
from datetime import datetime, timezone
from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict, MessageToDict
from a2a.utils.signing import (
    create_agent_card_signer,
    create_signature_verifier,
    ProtectedHeader,
    InvalidSignaturesError,
    NoSignatureError
)
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from datetime import datetime

from agent_registry.signature.jwk_fetcher import JWKFetcher
from agent_registry.signature.public_key_manager import PublicKeyManager


def generate_ecdsa_key_pair():
    """
    Generate ECDSA P-256 key pair
    
    Returns:
        tuple: (private_key, public_key)
    """
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key = private_key.public_key()
    return private_key, public_key


def private_key_to_pem(private_key):
    """
    Convert private key to PEM format
    
    Args:
        private_key: Private key object
    
    Returns:
        str: PEM format private key
    """
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    return pem.decode('utf-8')


def public_key_to_jwk(public_key, kid="test-key-1"):
    """
    Convert public key to JWK format
    
    Args:
        public_key: Public key object
        kid: Key ID
    
    Returns:
        dict: JWK format public key
    """
    public_numbers = public_key.public_numbers()
    
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


def create_agent_card_dict():
    """
    Create AgentCard data dict (excluding signatures field)
    
    Note: JSON field names must use camelCase for protobuf ParseDict
    
    Returns:
        dict: AgentCard data
    """
    agent_card_dict = {
      "name": "TestAgent",
      "description": "负责RAN能效优化的自主闭环运行，包括意图探索、意图实现、效果评估与报告。",
      "version": "1.0.0",
      "provider": {
        "organization": "TestOrg",
        "url": "https://www.huawei.com"
      },
      "skills": [
        {
          "id": "ran-es-intent-exploration",
          "name": "RAN ES Intent Exploration",
          "description": "评估并确定指定RAN ES意图目标的最佳可能性，考虑当前资源状况和系统能力。",
          "tags": [
            "wireless",
            "energy-saving",
            "intent"
          ]
        },
        {
          "id": "ran-es-intent-lifecycle-management",
          "name": "RAN ES Intent Lifecycle Management",
          "description": "管理RAN节能意图的生命周期，包括创建、修改、删除、激活、去激活意图，并执行数据采集、分析、解决方案制定与配置。",
          "tags": [
            "wireless",
            "energy-saving",
            "intent"
          ]
        },
        {
          "id": "ran-es-intent-reporting",
          "name": "RAN ES Intent Reporting",
          "description": "提供意图报告查询、订阅、通知功能，报告意图实现状态、达成值、推荐值及配置修改信息。",
          "tags": [
            "wireless",
            "energy-saving",
            "reporting"
          ]
        }
      ],
      "capabilities": {
        "streaming": True,
        "pushNotifications": False,
        "extensions": []
      },
      "defaultInputModes": [
        "text",
        "json"
      ],
      "defaultOutputModes": [
        "text",
        "json"
      ],
      "supportedInterfaces": [
        {
          "protocolBinding": "GPRC",
          "protocolVersion": "1.0.0",
          "url": "http://127.0.0.1:5000/"
        },
        {
          "protocolBinding": "HTTP+JSON",
          "protocolVersion": "1.0.0",
          "url": "http://127.0.0.1:5000/"
        }
      ]
    }
    return agent_card_dict


def create_protected_header(kid, jku_url) -> ProtectedHeader:
    """
    Create protected header
    
    Args:
        kid: Key ID
        jku_url: JWK Set URL
    
    Returns:
        ProtectedHeader: protected header
    """
    protected: ProtectedHeader = {
        "alg": "ES256",
        "typ": "JOSE",
        "kid": kid,
        "jku": jku_url
    }
    return protected


def base64url_encode(data):
    """
    Base64URL encoding
    
    Args:
        data: String or bytes
    
    Returns:
        str: base64url encoded string
    """
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')


def base64url_decode(data):
    """
    Base64URL decoding
    
    Args:
        data: String
    
    Returns:
        bytes: decoded bytes
    """
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)


def sign_agent_card(private_key_pem: str, agent_card: AgentCard, protected_header: ProtectedHeader) -> dict:
    """
    Sign AgentCard

    Args:
        private_key_pem: PEM format private key string
        agent_card: AgentCard protobuf object
        protected_header: protected header

    Returns:
        dict: signature object (for compatibility with existing code)
    """
    signer = create_agent_card_signer(private_key_pem, protected_header=protected_header)

    signed_card = signer(agent_card)

    signature = signed_card.signatures[0]
    
    protected_json = base64url_decode(signature.protected).decode('utf-8')
    print('=' * 100)
    print('Protected header decoded:')
    print(protected_json)
    print('=' * 100)

    organization = "TestOrg"
    agent_name = "TestAgent"
    kid = "test-key-1"
    public_key_manager = PublicKeyManager()
    jwk_fetcher = JWKFetcher(public_key_manager)
    backend_key_fetcher = jwk_fetcher.create_backend_key_fetcher(organization, agent_name)
    backend_key = backend_key_fetcher(kid, "")
    if backend_key:
        verifier = create_signature_verifier(backend_key_fetcher, ['ES256', 'RS256'])
        try:
            verifier(signed_card)
            print('[OK] Signature verification passed with backend key')
        except (NoSignatureError, InvalidSignaturesError) as e:
            print(f'[WARN] Backend key verification failed: {e}')

    return {
        "protected": signature.protected,
        "signature": signature.signature
    }


def create_backend_key_file(organization, agent_name, jwk):
    """
    Create backend public key file
    
    Args:
        organization: Organization name
        agent_name: Agent name
        jwk: JWK format public key
    """
    base_dir = "etc/sign_verify/jwks"
    org_dir = f"{base_dir}/{organization}"
    file_path = f"{org_dir}/{agent_name}.json"
    
    storage_obj = {
        "organization": organization,
        "agent_name": agent_name,
        "keys": [jwk],
        "updated_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    }
    
    os.makedirs(org_dir, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(storage_obj, f, ensure_ascii=False, indent=2)
    
    print(f"[OK] Backend public key file created: {file_path}")
    print(f"   File content:")
    print(json.dumps(storage_obj, indent=2, ensure_ascii=False))


def create_complete_agent_card_with_signature():
    """
    Create complete AgentCard with signature
    
    Returns:
        tuple: (agent_card_with_signature_dict, private_key_pem, public_key_jwk)
    """
    print("=" * 60)
    print("Step 1: Generate ECDSA key pair")
    print("=" * 60)
    private_key, public_key = generate_ecdsa_key_pair()
    private_key_pem = private_key_to_pem(private_key)
    public_key_jwk = public_key_to_jwk(public_key, kid="test-key-1")
    
    print(f"[OK] Key pair generated successfully")
    print(f"   kid: {public_key_jwk['kid']}")
    print(f"   Private key (PEM):")
    print(private_key_pem)
    print(f"   Public key (JWK):")
    print(json.dumps(public_key_jwk, indent=2))

    print("\n" + "=" * 60)
    print("Step 2: Create backend public key file")
    print("=" * 60)
    organization = "TestOrg"
    agent_name = "TestAgent"
    create_backend_key_file(organization, agent_name, public_key_jwk)
    
    print("\n" + "=" * 60)
    print("Step 3: Create AgentCard data")
    print("=" * 60)
    agent_card_dict = create_agent_card_dict()
    print(f"[OK] AgentCard data created")
    print(json.dumps(agent_card_dict, indent=2))
    
    print("\n" + "=" * 60)
    print("Step 4: Create protobuf AgentCard from dict")
    print("=" * 60)
    agent_card = ParseDict(agent_card_dict, AgentCard())
    print(f"[OK] AgentCard protobuf created")
    print(f"   name: {agent_card.name}")
    print(f"   provider.organization: {agent_card.provider.organization}")
    
    print("\n" + "=" * 60)
    print("Step 5: Create protected header")
    print("=" * 60)
    kid = "test-key-1"
    jku_url = "https://test.org/jwks.json"
    protected_header = create_protected_header(kid, jku_url)
    print(f"[OK] Protected header created")
    print(json.dumps(protected_header, indent=2))
    
    print("\n" + "=" * 60)
    print("Step 6: Sign AgentCard")
    print("=" * 60)
    signature_dict = sign_agent_card(private_key_pem, agent_card, protected_header)
    print(f"[OK] Signature successful")
    print(json.dumps(signature_dict, indent=2))
    
    print("\n" + "=" * 60)
    print("Step 7: Construct complete AgentCard (with signatures)")
    print("=" * 60)
    agent_card_with_signature_dict = agent_card_dict.copy()
    agent_card_with_signature_dict["signatures"] = [signature_dict]
    print(f"[OK] Complete AgentCard constructed")
    print(json.dumps(agent_card_with_signature_dict, indent=2))
    
    return agent_card_with_signature_dict, private_key_pem, public_key_jwk


def test_signature_verification():
    """
    Test signature verification
    """
    print("\n" + "=" * 60)
    print("Step 8: Test signature verification")
    print("=" * 60)
    
    agent_card_with_signature_dict, private_key_pem, public_key_jwk = create_complete_agent_card_with_signature()
    
    print("\n" + "=" * 60)
    print("Test Instructions")
    print("=" * 60)
    print("""
Now you can use the following curl command to test the signature verification endpoint:

curl -X POST "http://localhost:8000/rest/a2a-t/v1/agents/register" \\
  -H "Content-Type: application/json" \\
  -d '""" + json.dumps(agent_card_with_signature_dict) + """'

Expected results:
- If signature verification succeeds: Returns 201 Created and true
- If signature verification fails: Returns 401 Unauthorized and error message

Signature verification flow:
1. Server receives AgentCard registration request
2. Extract signatures field from AgentCard
3. Decode protected header, get kid and jku
4. First look for corresponding public key in backend public key file
5. If backend public key found, use it for verification
6. If backend public key verification fails or not found, fetch public key from jku URL
7. Use fetched public key for verification
8. After verification passes, continue registration process

API Changes for a2a-sdk 1.0.0+:
- AgentCard is now a protobuf message (not pydantic)
- Use ParseDict/MessageToDict for conversion
- ProtectedHeader is a TypedDict
- create_agent_card_signer returns a callable that modifies the AgentCard directly
    """)


if __name__ == "__main__":
    test_signature_verification()