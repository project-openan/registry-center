#!/usr/bin/env python3
"""
AgentCard Signature Test Script

This script demonstrates how to:
1. Generate ECDSA key pair
2. Create backend public key file
3. Construct AgentCard data
4. Sign AgentCard
5. Test signature verification
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
    
    # Convert coordinates to base64url encoding
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
    Create AgentCard data (excluding signatures field)
    
    Returns:
        dict: AgentCard data
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
    Create protected header
    
    Args:
        kid: Key ID
        jku_url: JWK Set URL
    
    Returns:
        dict: protected header
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
    Base64URL encoding
    
    Args:
        data: String or bytes
    
    Returns:
        str: base64url encoded string
    """
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')


def sign_agent_card(private_key, agent_card, protected_header):
    """
    Sign AgentCard

    Args:
        private_key: Private key object
        agent_card: AgentCard data
        protected_header: protected header

    Returns:
        dict: signature object
    """
    # 1. Create signer
    signer = create_agent_card_signer(private_key, protected_header=protected_header)

    # 2. Use verifier to generate signed request
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

    # 3. Try direct signature verification
    organization = "TestOrg"
    agent_name = "TestAgent"
    kid = "test-key-1"
    public_key_manager = PublicKeyManager()
    jwk_fetcher = JWKFetcher(public_key_manager)
    backend_key_fetcher = jwk_fetcher.create_backend_key_fetcher(organization, agent_name)
    backend_key = backend_key_fetcher(kid, "")
    if backend_key:
        verifier = create_signature_verifier(backend_key_fetcher, ['ES256', 'RS256'])
        verifier(signed_card)


    return signed_card.model_dump().get("signatures")[0]


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
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    
    import os
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
        tuple: (agent_card_with_signature, private_key_pem, public_key_jwk)
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
    agent_card = create_agent_card()
    print(f"[OK] AgentCard data created")
    print(json.dumps(agent_card, indent=2))
    
    print("\n" + "=" * 60)
    print("Step 4: Create protected header")
    print("=" * 60)
    kid = "test-key-1"
    jku_url = "https://test.org/jwks.json"
    protected_header = create_protected_header(kid, jku_url)
    print(f"[OK] Protected header created")
    print(json.dumps(protected_header, indent=2))
    
    print("\n" + "=" * 60)
    print("Step 5: Sign AgentCard")
    print("=" * 60)
    signature_obj = sign_agent_card(private_key, agent_card, protected_header)
    print(f"[OK] Signature successful")
    print(json.dumps(signature_obj, indent=2))
    
    print("\n" + "=" * 60)
    print("Step 6: Construct complete AgentCard (with signatures)")
    print("=" * 60)
    agent_card_with_signature = agent_card.copy()
    agent_card_with_signature["signatures"] = [signature_obj]
    print(f"[OK] Complete AgentCard constructed")
    print(json.dumps(agent_card_with_signature, indent=2))
    
    return agent_card_with_signature, private_key_pem, public_key_jwk


def test_signature_verification():
    """
    Test signature verification
    """
    print("\n" + "=" * 60)
    print("Step 7: Test signature verification")
    print("=" * 60)
    
    agent_card_with_signature, private_key_pem, public_key_jwk = create_complete_agent_card_with_signature()
    
    print("\n" + "=" * 60)
    print("Test Instructions")
    print("=" * 60)
    print("""
Now you can use the following curl command to test the signature verification endpoint:

curl -X POST "http://localhost:8000/rest/a2a-t/v1/agents/register" \\
  -H "Content-Type: application/json" \\
  -d '""" + json.dumps(agent_card_with_signature) + """'

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
    """)


if __name__ == "__main__":
    test_signature_verification()