from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


class SignatureObject(BaseModel):
    """签名对象模型"""
    protected: str = Field(..., description="base64url编码的protected头")
    signature: str = Field(..., description="base64url编码的签名值")


class ProtectedHeader(BaseModel):
    """Protected头模型（解码后）"""
    alg: str = Field(..., description="签名算法，如ES256, RS256")
    typ: str = Field(default="JOSE", description="类型标识")
    kid: str = Field(..., description="密钥ID")
    jku: str = Field(..., description="JWK Set URL")


class JWK(BaseModel):
    """JSON Web Key模型"""
    kty: str = Field(..., description="密钥类型，仅支持EC或RSA")
    kid: str = Field(..., description="密钥ID")
    use: str = Field(default="sig", description="密钥用途")
    alg: str = Field(..., description="算法，如ES256, RS256")
    crv: Optional[str] = Field(None, description="曲线，如P-256")
    x: str = Field(..., description="X坐标（ECDSA）或模数（RSA）")
    y: Optional[str] = Field(None, description="Y坐标（ECDSA）")
    n: Optional[str] = Field(None, description="模数（RSA）")
    e: Optional[str] = Field(None, description="指数（RSA）")

    @field_validator('kty')
    @classmethod
    def validate_kty(cls, v):
        if v not in ['EC', 'RSA']:
            raise ValueError('密钥类型仅支持EC或RSA')
        return v


class JWKS(BaseModel):
    """JSON Web Key Set模型"""
    keys: List[JWK] = Field(..., description="公钥列表")


class AgentKeysStorage(BaseModel):
    """Agent公钥存储模型"""
    organization: Optional[str] = Field(None, description="组织名称")
    agent_name: str = Field(..., description="Agent名称")
    keys: List[JWK] = Field(default_factory=list, description="公钥列表")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")