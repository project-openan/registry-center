from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


class SignatureObject(BaseModel):
    """Signature object model"""
    protected: str = Field(..., description="base64url-encoded protected header")
    signature: str = Field(..., description="base64url-encoded signature value")


class ProtectedHeader(BaseModel):
    """Protected header model (decoded)"""
    alg: str = Field(..., description="Signature algorithm, e.g., ES256, RS256")
    typ: str = Field(default="JOSE", description="Type identifier")
    kid: str = Field(..., description="Key ID")
    jku: str = Field(..., description="JWK Set URL")


class JWK(BaseModel):
    """JSON Web Key model"""
    kty: str = Field(..., description="Key type, supports EC or RSA only")
    kid: str = Field(..., description="Key ID")
    use: str = Field(default="sig", description="Key usage")
    alg: str = Field(..., description="Algorithm, e.g., ES256, RS256")
    crv: Optional[str] = Field(None, description="Curve, e.g., P-256")
    x: str = Field(..., description="X coordinate (ECDSA) or modulus (RSA)")
    y: Optional[str] = Field(None, description="Y coordinate (ECDSA)")
    n: Optional[str] = Field(None, description="Modulus (RSA)")
    e: Optional[str] = Field(None, description="Exponent (RSA)")

    @field_validator('kty')
    @classmethod
    def validate_kty(cls, v):
        if v not in ['EC', 'RSA']:
            raise ValueError('Key type only supports EC or RSA')
        return v


class JWKS(BaseModel):
    """JSON Web Key Set model"""
    keys: List[JWK] = Field(..., description="List of public keys")


class AgentKeysStorage(BaseModel):
    """Agent public key storage model"""
    organization: Optional[str] = Field(None, description="Organization name")
    agent_name: str = Field(..., description="Agent name")
    keys: List[JWK] = Field(default_factory=list, description="List of public keys")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")