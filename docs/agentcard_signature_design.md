# AgentCard验签功能设计文档

## 1. 背景概述

AgentCard作为多个Agent之间交互的中转站，需要频繁接受各个Agent的请求。为确保请求的安全性和真实性，需要为AgentCard补充验签能力。

## 2. 功能需求

### 2.1 核心需求
1. **默认强制校验签名**，后续支持关闭校验
2. **后台配置公钥能力**：查询、新增、删除公钥（全局生效），支持多本公钥
3. **动态公钥获取**：验签时如果无证书公钥配置、或校验失败，则从签名链接中现获取公钥重试校验（每次注册都触发一下，不缓存）
4. **签名验证**：用公钥验证签名

### 2.2 签名格式要求

基于JWS (JSON Web Signature)格式，在开启验签能力时，请求体会多一个`signatures`字段：

```json
{
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
    ],
    "signatures": [
        {
            "protected": "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpPU0UiLCJraWQiOiJrZXktMSIsImprdSI6Imh0dHBzOi8vZXhhbXBsZS5jb20vYWdlbnQvandrcy5qc29uIn0",
            "signature": "QFdkNLNszlGj3z3u0YQGt_T9LixY3qtdQpZmsTdDHDe3fXV9y9-B3m2-XgCpzuhiLt8E0tV6HXoZKHv4GtHgKQ"
        }
    ]
}
```

### 2.3 签名字段说明

#### signatures 字段
- **类型**: 数组（支持密钥轮转场景，可能有多个签名字段）
- **位置**: 与"name"、"skills"等字段平级
- **可选**: 是（但在验签开启时必需）

#### 签名对象结构
```json
{
    "protected": "base64url编码的JSON字符串",
    "signature": "base64url编码的签名值"
}
```

#### protected 字段解码后格式
```json
{
    "alg": "ES256",           // 签名算法
    "typ": "JOSE",            // 类型标识
    "kid": "key-1",           // 密钥ID
    "jku": "https://10.10.10.10:26335/agent/jwks.json"  // JWK Set URL
}
```

### 2.4 JWS签名结构说明

#### JWS签名结构

在JWS (JSON Web Signature) 标准中，签名的生成遵循以下结构：

```
待签名的数据 = base64url(protected) + "." + base64url(payload)
signature = sign(待签名的数据， private_key)
```

#### 待签名数据（payload）的定义

**重要**：待签名的数据（payload）是整个AgentCard的JSON字符串，**但不包含signatures字段**。

这是为了防止循环引用，确保签名的完整性和一致性。

#### JWS签名结构总结

| 组件 | 说明 | 示例 |
|------|------|------|
| **protected** | base64url编码的头部 | `eyJhbGciOiJFUzI1NiIs...` |
| **payload** | AgentCard的JSON（除signatures） | `{"name":"TestAgent",...}` |
| **signature** | 对(protected.payload)的签名 | `QFdkNLNszlGj3z3u0YQGt_T9...` |
| **待签名数据** | `protected + "." + payload` | `eyJhbGci...`.`eyJuYW1lIj...` |

#### 重要注意事项

1. **payload不包含signatures字段**：防止循环引用和签名无限嵌套
2. **JSON序列化要一致**：客户端和服务端使用相同的序列化方式（如`sort_keys=True`）
3. **base64url编码**：使用URL安全的base64url编码，不是标准的base64
4. **字段顺序敏感**：JSON字段的顺序会影响签名结果

## 3. 验签流程设计

### 3.1 验签流程图

```
┌─────────────────┐
│   Agent请求      │
└────────┬────────┘
         │
         │ 1. 接收AgentCard注册请求
         ▼
┌─────────────────────────────────┐
│   检查验签开关                  │
│   - 如果关闭：直接处理业务      │
│   - 如果开启：进入验签流程      │
└────────┬────────────────────────┘
         │
         │ 2. 提取signatures字段
         ▼
┌─────────────────────────────────┐
│   signatures字段存在？          │
└────────┬────────────────────────┘
         │
    ┌────┴────┐
    │         │
   否         是
    │         │
    │         │ 3. 遍历signatures数组
    │         ▼
    │  ┌─────────────────────────────────┐
    │  │   读取signatures[i].protected.kid│
    │  └────────┬────────────────────────┘
    │  ┌─────────┴─────────┐
    │  │                   │
    │  │ 4. 优先从后台存储的公钥中寻找
    │  │   根据kid查找是否存在该id
    │  │                   │
    │  │ 5. 存在该id的公钥？
    │  │  ┌─────────┴─────────┐
    │  │  │                   │
    │  │  是                  否
    │  │  │                   │
    │  │  │ 6. 使用后台公钥验签
    │  │  │   成功则通过
    │  │  │                   │
    │  │  │                   │ 7. 从protected.jku获取jwks.json
    │  │  │                   ▼
    │  │  │           ┌─────────────────────────────────┐
    │  │  │           │   成功获取JWKS？               │
    │  │  │           └────────┬────────────────────────┘
    │  │  │       ┌───────────┴───────────┐
    │  │  │       │                       │
    │  │  │      是                       否
    │  │  │       │                       │
    │  │  │       │ 8. 根据kid从JWKS中获取公钥
    │  │  │       │                       │
    │  │  │       │ 9. 使用临时公钥验签
    │  │  │       │                       │
    │  │  │       │ 10. 返回验签结果
    │  │  │       │                       │
    │  │  └───────┴───────────────────────┘
    │  │
    │  │ 11. 两次都未获取到公钥 → 验签失败
    │  │
    │  └──────────────────────────────────→ 返回错误
    │

    │ 12. 无signatures字段 → 验签失败
    │
    └──────────────────────────────────→ 返回错误
```

### 3.2 详细验签步骤

#### 步骤1：检查验签开关
- 检查配置文件中的验签开关状态
- 如果关闭，跳过验签直接处理业务逻辑
- 如果开启（默认），`进入验签流程

#### 步骤2：提取signatures字段
- 从请求体中提取`signatures`字段
- 如果不存在，返回验签失败错误

#### 步骤3：遍历signatures数组
- 对`signatures`数组中的每个签名对象进行处理
- 支持密钥轮转场景

#### 步骤4：读取kid
- 从`signatures[i].protected`中解码获取`kid`（密钥ID）
- `kid`用于标识和查找对应的公钥

#### 步骤5：优先从后台存储的公钥中寻找
- 根据从请求头中获取的`organization`和`agent-name`
- 构造文件路径：`/etc/sign_verify/jwks/{organization}/{agent-name}.json`
- 从该文件中查找是否存在对应`kid`的公钥

#### 步骤6：使用后台公钥验签
- 如果找到对应`kid`的公钥，使用该公钥进行验签
- 使用a2a-sdk提供的API进行验签
- 验签成功则视为验签通过

#### 步骤7：从jku获取临时公钥
- 如果后台未找到对应`kid`的公钥
- 从`protected`字段解码获取`jku` (JWK Set URL)
- 发送HTTP请求到`jku`获取JWKS (JSON Web Key Set)

#### 步骤8：从JWKS中获取公钥
- 从JWKS中根据`kid`查找对应的公钥
- 如果找不到，继续下一个签名对象

#### 步骤9：使用临时公钥验签
- 使用从`jku`获取的临时公钥验签
- 使用a2a-sdk提供的API进行验签
- **不缓存临时公钥**（每次都重新获取）

#### 步骤10：返回验签结果
- 验签成功：继续处理业务逻辑
- 验签失败：继续下一个签名对象

#### 步骤11：验签失败
- 如果所有签名对象都验签失败，返回验签失败错误

## 4. 数据模型设计

### 4.1 签名对象模型

```python
class SignatureObject(BaseModel):
    """签名对象模型"""
    protected: str = Field(..., description="base64url编码的protected头")
    signature: str = Field(..., description="base64url编码的签名值")
```

### 4.2 Protected头模型

```python
class ProtectedHeader(BaseModel):
    """Protected头模型（解码后）"""
    alg: str = Field(..., description="签名算法，如ES256, RS256")
    typ: str = Field(default="JOSE", description="类型标识")
    kid: str = Field(..., description="密钥ID")
    jku: str = Field(..., description="JWK Set URL")
```

### 4.3 JWK模型

```python
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
    
    @validator('kty')
    def validate_kty(cls, v):
        if v not in ['EC', 'RSA']:
            raise ValueError('密钥类型仅支持EC或RSA')
        return v
```

### 4.4 JWKS模型

```python
class JWKS(BaseModel):
    """JSON Web Key Set模型"""
    keys: List[JWK] = Field(..., description="公钥列表")
```

### 4.5 Agent公钥存储模型

```python
class AgentKeysStorage(BaseModel):
    """Agent公钥存储模型"""
    organization: str = Field(..., description="组织名称")
    agent_name: str = Field(..., description="Agent名称")
    keys: List[JWK] = Field(default_factory=list, description="公钥列表")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
```

## 5. 核心组件设计

### 5.1 签名验证器 (AgentCardValidator)

**职责**：
- 协调整个验签流程
- 集成配置公钥和临时公钥验签
- 提供统一的验签接口

**主要方法**：
```python
class AgentCardValidator:
    def validate_agent_card(
        self,
        agent_card_data: dict,
        organization: str,
        agent_name: str
    ) -> ValidationResult:
        """验证AgentCard的签名"""
        
    def _extract_signatures(self, agent_card_data: dict) -> List[SignatureObject]:
        """提取signatures字段"""
        
    def _validate_single_signature(
        self,
        signature: SignatureObject,
        agent_card_data: dict,
        organization: str,
        agent_name: str
    ) -> bool:
        """验证单个签名"""
        
    def _try_backend_key(
        self,
        kid: str,
        organization: str,
        agent_name: str
    ) -> Optional[JWK]:
        """尝试从后台获取公钥"""
        
    def _try_temporary_key(
        self,
        jku: str,
        kid: str
    ) -> Optional[JWK]:
        """尝试从jku获取临时公钥"""
```

### 5.2 公钥管理器 (PublicKeyManager)

**职责**：
- 管理后台配置的公钥
- 提供公钥的CRUD操作
- 支持多本公钥
- 基于文件存储

**主要方法**：
```python
class PublicKeyManager:
    def add_public_keys(
        self,
        organization: str,
        agent_name: str,
        jwks: JWKS
    ) -> List[str]:
        """批量添加公钥配置"""
        
    def remove_public_key(
        self,
        organization: str,
        agent_name: str,
        kid: str
    ) -> bool:
        """删除公钥配置"""
        
    def get_all_public_keys(
        self,
        organization: str,
        agent_name: str
    ) -> JWKS:
        """获取所有配置的公钥"""
        
    def get_public_key(
        self,
        organization: str,
        agent_name: str,
        kid: str
    ) -> Optional[JWK]:
        """根据kid获取公钥"""
        
    def _get_storage_path(
        self,
        organization: str,
        agent_name: str
    ) -> str:
        """获取存储路径"""
```

### 5.3 JWK获取器 (JWKFetcher)

**职责**：
- 从jku URL获取JWKS
- 解析JWKS提取公钥
- 不缓存获取的公钥

**主要方法**：
```python
class JWKFetcher:
    def fetch_jwks(self, jku: str) -> JWKS:
        """从URL获取JWKS"""
        
    def find_key_by_kid(self, jwks: JWKS, kid: str) -> Optional[JWK]:
        """根据kid从JWKS中查找公钥"""
```

## 6. API接口设计

### 6.1 公钥管理API

#### 批量添加公钥配置
```
POST /rest/a2a-t/v1/keys/config
Headers:
  - organization: TestOrg
  - agent-name: TestAgent

Request Body:
{
    "keys": [
        {
            "kty": "EC",
            "kid": "key-1",
            "use": "sig",
            "alg": "ES256",
            "crv": "P-256",
            "x": "MKBCTNIcKUSDii11ySs3526iDz8ETo7ct6KogEvTkH0",
            "y": "4Etl6SRW2YiLUrN5vfvAfHh7nStpGMT9y3JQtmD1LYA"
        },
        {
            "kty": "RSA",
            "kid": "rsa-key-1",
            "use": "sig",
            "alg": "RS256",
            "n": "0vx7agoebGcQSuuCxLzdtZ...)",
            "e": "AQAB"
        }
    ]
}

Response:
{
    "success": true,
    "added_keys": ["key-1", "rsa-key-1"],
    "message": "Public keys added successfully"
}
```

**校验规则**：
- 一次最多添加5个公钥
- 每个JWK的密钥类型约束只支持EC或RSA公钥
- 若kid相同则视为重复添加，直接覆盖

#### 删除公钥配置
```
DELETE /rest/a2a-t/v1/keys/config/{kid}
Headers:
  - organization: TestOrg
  - agent-name: TestAgent

Response:
{
    "success": true,
    "message": "Public key removed successfully"
}
```

#### 查询所有公钥配置
```
GET /rest/a2a-t/v1/keys/config
Headers:
  - organization: TestOrg
  - agent-name: TestAgent

Response:
{
    "keys": [
        {
            "kty": "EC",
            "kid": "key-1",
            "use": "sig",
            "alg": "ES256",
            "crv": "P-256",
            "x": "MKBCTNIcKUSDii11ySs3526iDz8ETo7ct6KogEvTkH0",
            "y": "4Etl6SRW2YiLUrN5vfvAfHh7nStpGMT9y3JQtmD1LYA"
        }
    ],
    "total": 1
}
```

#### 查询单个公钥配置
```
GET /rest/a2a-t/v1/keys/config/{kid}
Headers:
  - organization: TestOrg
  - agent-name: TestAgent

Response:
{
    "kty": "EC",
    "kid": "key-1",
    "use": "sig",
    "alg": "ES256",
    "crv": "P-256",
    "x": "MKBCTNIcKUSDii11ySs3526iDz8ETo7ct6KogEvTkH0",
    "y": "4Etl6SRW2YiLUrN5vfvAfHh7nStpGMTGMT9y3JQtmD1LYA"
}
```

### 6.2 验签开关配置

验签能力开关配置在`/etc/conf/server.conf`中：

```ini
# 验签开关
signature_validation_enabled=true
```

## 7. 文件存储设计

### 7.1 存储目录结构

```
/etc/sign_verify/jwks/
├── TestOrg/
│   ├── TestAgent.json
│   ├── AnotherAgent.json
│   └── ...
├── AnotherOrg/
│   ├── Agent1.json
│   └── Agent2.json
└── ...
```

### 7.2 存储文件格式

每个Agent的公钥存储在独立的JSON文件中：

```json
{
    "organization": "TestOrg",
    "agent_name": "TestAgent",
    "keys": [
        {
            "kty": "EC",
            "kid": "key-1",
            "use": "sig",
            "alg": "ES256",
            "crv": "P-256",
            "x": "MKBCTNIcKUSDii11ySs3526iDz8ETo7ct6KogEvTkH0",
            "y": "4Etl6SRW2YiLUrN5vfvAfHh7nStpGMT9y3JQtmD1LYA"
        }
    ],
    "updated_at": "2024-01-01T00:00:00Z"
}
```

### 7.3 存储路径构造

```python
def get_storage_path(organization: str, agent_name: str) -> str:
    """
    构造存储路径
    
    Args:
        organization: 组织名称
        agent_name: Agent名称
    
    Returns:
        str: 存储文件路径
    """
    base_dir = "/etc/sign_verify/jwks"
    org_dir = os.path.join(base_dir, organization)
    return os.path.join(org_dir, f"{agent_name}.json")
```

## 8. 签名验证集成设计

### 8.1 使用a2a-sdk进行签名验证

```python
from a2a_sdk import signature as a2a_signature

def verify_signature_with_sdk(
    protected: str,
    payload: str,
    signature: str,
    public_key: JWK
) -> bool:
    """
    使用a2a-sdk进行签名验证
    
    Args:
        protected: base64url编码的protected头
        payload: AgentCard的JSON字符串（不包含signatures）
        signature: base64url编码的签名值
        public_key: JWK格式的公钥
    
    Returns:
        bool: 验证结果
    """
    try:
        # 构造JWS对象
        jws = {
            "protected": protected,
            "payload": payload,
            "signature": signature
        }
        
        # 使用a2a-sdk验证签名
        result = a2a_signature.verify_jws(jws, public_key)
        
        return result.is_valid
    except Exception as e:
        logger.error(f"签名验证失败: {e}")
        return False
```

### 8.2 完整验签流程实现

```python
class AgentCardValidator:
    def validate_agent_card(
        self,
        agent_card_data: dict,
        organization: str,
        agent_name: str
    ) -> ValidationResult:
        """
        验证AgentCard的签名
        
        Args:
            agent_card_data: AgentCard数据
            organization: 组织名称
            agent_name: Agent名称
        
        Returns:
            ValidationResult: 验证结果
        """
        # 步骤1：提取signatures字段
        signatures = self._extract_signatures(agent_card_data)
        if not signatures:
            return ValidationResult(
                is_valid=False,
                error_code="SIG001",
                error_message="Signatures field is required"
            )
        
        # 步骤2：构造payload（不包含signatures）
        agent_card_copy = agent_card_data.copy()
        del agent_card_copy["signatures"]
        payload = json.dumps(agent_card_copy, sort_keys=True)
        
        # 步骤3：遍历signatures数组
        for sig_obj in signatures:
            # 解码protected头
            protected_header = self._decode_protected(sig_obj.protected)
            kid = protected_header.kid
            
            # 步骤4：优先从后台获取公钥
            backend_key = self._try_backend_key(kid, organization, agent_name)
            if backend_key:
                # 使用后台公钥验签
                if self._verify_with_sdk(
                    sig_obj.protected,
                    payload,
                    sig_obj.signature,
                    backend_key
                ):
                    return ValidationResult(is_valid=True)
            
            # 步骤5：从jku获取临时公钥
            if hasattr(protected_header, 'jku'):
                temporary_key = self._try_temporary_key(
                    protected_header.jku,
                    kid
                )
                if temporary_key:
                    # 使用临时公钥验签
                    if self._verify_with_sdk(
                        sig_obj.protected,
                        payload,
                        sig_obj.signature,
                        temporary_key
                    ):
                        return ValidationResult(is_valid=True)
        
        # 所有签名都验证失败
        return ValidationResult(
            is_valid=False,
            error_code="SIG005",
            error_message="All signature validations failed"
        )
```

## 9. 错误处理

### 9.1 错误码定义

| 错误码 | 说明 | HTTP状态码 |
|--------|------|-----------|
| SIG001 | 验签已启用但signatures字段缺失 | 400 |
| SIG002 | signatures字段格式错误 | 400 |
| SIG003 | protected字段解码失败 | 400 |
| SIG004 | 无法从jku获取公钥 | 400 |
| SIG005 | 所有公钥验签失败 | 401 |
| SIG006 | 不支持的签名算法 | 400 |
| SIG007 | JWKS格式错误 | 400 |
| SIG008 | 公钥配置不存在 | 404 |
| SIG009 | 公钥数量超过限制（最多5个） | 400 |
| SIG010 | 不支持的密钥类型（仅支持EC或RSA） | 400 |

### 9.2 错误响应格式

```json
{
    "error_code": "SIG001",
    "error_message": "Signatures field is required when signature validation is enabled",
    "details": {
        "validation_enabled": true,
        "signatures_found": false
    }
}
```

## 10. 安全考虑

### 10.1 公钥安全
- **配置公钥**：存储在后台文件系统，权限控制
- **临时公钥**：不缓存，每次重新获取
- **公钥验证**：验证公钥格式和算法

### 10.2 网络安全
- **HTTPS传输**：jku URL必须使用HTTPS
- **超时控制**：防止长时间等待
- **重试限制**：限制重试次数

### 10.3 算法安全
- **算法白名单**：只允许安全的签名算法
- **密钥类型约束**：仅支持EC或RSA公钥
- **密钥长度验证**：验证密钥长度符合要求

## 11. 性能优化

### 11.1 缓存策略
- **配置公钥**：可以缓存（因为配置不常变化）
- **临时公钥**：不缓存（每次重新获取）

### 11.2 并发处理
- **多签名并行验签**：提高验签速度
- **超时控制**：防止单个公钥验签时间过长

## 12. 测试计划

### 12.1 单元测试
- 公钥管理器测试
- JWK获取器测试
- AgentCard验证器测试

### 12.2 集成测试
- 完整验签流程测试
- 配置公钥验签测试
- 临时公钥验签测试
- 混合验签测试

### 12.3 安全测试
- 签名伪造测试
- 公钥替换测试
- jku篡改测试
- 算法降级测试

## 13. 实现优先级

### Phase 1: 核心功能
1. 实现公钥管理器（文件存储）
2. 实现JWK获取器
3. 实现AgentCard验证器
4. 集成a2a-sdk签名验证

### Phase 2: API接口
1. 实现公钥管理API
2. 集成到现有Agent注册接口

### Phase 3: 优化和测试
1. 性能优化
2. 完整测试覆盖
3. 文档完善

## 14. 兼容性考虑

### 14.1 向后兼容
- **验签关闭时**：兼容无signatures字段的请求
- **渐进式启用**：支持先启用验签，再配置公钥

### 14.2 前向兼容
- **多签名支持**：支持密钥轮转场景
- **算法扩展**：易于添加新的签名算法

## 15. 监控和日志

### 15.1 监控指标
- 验签成功率
- 验签失败原因分布
- jku获取成功率
- 配置公钥使用率

### 15.2 日志记录
- 验签请求日志
- 公钥使用日志
- jku获取日志
- 错误日志

## 16. 总结

本设计方案基于JWS (JSON Web Signature)标准，实现了AgentCard的验签功能，主要特点：

1. **灵活的验签策略**：支持配置公钥和临时公钥双重验签
2. **密钥轮转支持**：支持多签名字段，平滑密钥轮转
3. **安全优先**：默认强制验签，支持动态公钥获取
4. **易于集成**：使用a2a-sdk进行签名验证
5. **可扩展性**：支持多种签名算法和公钥来源
6. **文件存储**：基于文件系统的公钥管理
7. **Agent隔离**：通过organization和agent-name实现Agent级别的公钥隔离

该设计满足所有需求，并考虑了安全性、性能和可维护性。