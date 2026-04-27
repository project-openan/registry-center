# Agent注册中心 Owner隔离方案设计

## 0. 体系架构图

```mermaid
graph TB
    subgraph Client
        A[Agent Client<br/>携带TLS客户端证书]
    end

    subgraph "Agent Registry"
        M["TLS Middleware<br/>证书解析"]
        R["RegistryCore<br/>注册核心"]
        S["StorageRegistry<br/>存储注册表"]
        
        subgraph StorageBackends
            F["FileStorage<br/>按owner分文件存储"]
            P["PostgreSQLStorage<br/>owner字段隔离"]
        end
    end

    subgraph Database
        DB[(PostgreSQL<br/>owner字段索引)]
    end

    A -->|TLS握手+客户端证书| M
    M -->|解析CN作为owner| R
    R -->|存储时携带owner| S
    S -->|file模式| F
    S -->|postgresql模式| P
    P -->|owner字段| DB
```

---

## 1. 设计目标

### 1.1 核心需求

| 需求 | 描述 |
|------|------|
| 注册隔离 | 从TLS客户端证书提取CN作为owner入库保存，owner允许为空 |
| 操作鉴权 | 删除/修改时校验证书CN与库中owner匹配，owner为空的agent为公共agent，任何用户都可以修改和删除 |
| 多存储模式 | 文件模式和数据库模式均支持owner隔离 |

### 1.2 Owner定义

**Owner来源**: TLS客户端证书的 `Subject CN (Common Name)` 字段

证书Subject示例：
```
CN=agent-admin-001,OU=AgentOps,O=Huawei,L=Shenzhen,C=CN
```

提取逻辑：从 `subject` 字符串解析 `CN=xxx` 的值。

---

## 2. 数据模型变更

### 2.1 AgentCard扩展字段

由于AgentCard是protobuf定义的外部模型，建议采用**扩展存储**方式：

```python
# 存储时附加owner元数据
agent_record = {
    "agent_card": MessageToDict(agent, preserving_proto_field_name=True),
    "owner": "agent-admin-001",  # 新增字段
    "created_at": datetime.utcnow(),
    "updated_at": datetime.utcnow()
}
```

### 2.2 PostgreSQL表结构变更

```sql
-- 新增owner字段（允许为空，owner为空表示公共agent）
ALTER TABLE agent_card ADD COLUMN owner VARCHAR(100) NULL;

-- 复合唯一键：name + organization + owner
-- 允许同一agent被多个owner注册（视业务需求而定）
-- 方案A：全局唯一，一个agent只能被一个owner注册
DROP INDEX IF EXISTS agent_card_name_org_key;
CREATE UNIQUE INDEX idx_agent_unique ON agent_card(name, organization);

-- 方案B：owner隔离，同一agent可被不同owner分别注册
CREATE UNIQUE INDEX idx_agent_owner_unique ON agent_card(name, organization, owner);
```

**推荐方案A**：全局唯一，简化管理，owner仅用于权限校验。owner为空时表示公共agent。

---

## 3. 证书CN解析设计

### 3.1 CN提取工具

新增 `common/cert/cert_cn_parser.py`：

```python
"""
从X509证书Subject中提取CN字段
"""
import re
from typing import Optional

from common.cert.x509_obj import CertObj


def extract_cn_from_subject(subject: str) -> Optional[str]:
    """
    从证书Subject字符串中提取CN值
    
    Subject格式: CN=xxx,OU=yyy,O=zzz...
    支持多种格式:
    - CN=agent-admin-001,OU=...
    - CN=agent admin 001,OU=...  (带空格)
    
    Args:
        subject: RFC4514格式的Subject字符串
        
    Returns:
        CN值，若不存在返回None
    """
    if not subject:
        return None
    
    # RFC4514格式: 属性=值,属性=值
    # CN可能在任意位置，需要解析整个字符串
    pattern = r'CN=([^,]+)'
    match = re.search(pattern, subject)
    if match:
        cn_value = match.group(1).strip()
        # 处理特殊字符转义（RFC4514中逗号用\,转义）
        cn_value = cn_value.replace('\\,', ',')
        return cn_value
    
    return None


def extract_cn_from_cert(cert_obj: CertObj) -> Optional[str]:
    """
    从CertObj对象提取CN
    
    Args:
        cert_obj: CertObj实例
        
    Returns:
        CN值
    """
    return extract_cn_from_subject(cert_obj.subject)


def validate_cn(cn: str) -> bool:
    """
    校验CN是否合法
    
    规则:
    - 长度: 1-64字节（UTF-8编码）
    - 允许字符: 字母、数字、连字符、点
    - 禁止: 特殊符号、控制字符、空格、下划线
    
    Args:
        cn: CN值
        
    Returns:
        是否合法
    """
    if not cn:
        return False
    
    # 长度校验（UTF-8字节数）
    if len(cn.encode('utf-8')) > 64:
        return False
    
    # 允许的字符集
    import string
    allowed_chars = string.ascii_letters + string.digits + '-.'
    
    return all(c in allowed_chars for c in cn)
```

### 3.2 证书解析集成

修改 `common/cert/cert_parser.py`，在 `_extract_certificate_info` 中增加CN提取：

```python
def _extract_certificate_info(cert: x509.Certificate) -> CertObj:
    """从cryptography证书对象中提取信息"""
    info = {
        'subject': cert.subject.rfc4514_string(),
        'issuer': cert.issuer.rfc4514_string(),
        'serial_number': hex(cert.serial_number),
        'valid_from': cert.not_valid_before_utc.isoformat(),
        'valid_to': cert.not_valid_after_utc.isoformat(),
        'version': cert.version,
        'public_key': cert.public_key(),
        'org_cert': cert,
        'cn': extract_cn_from_subject(cert.subject.rfc4514_string())  # 新增
    }
    obj = CertObj.from_dict(info)
    return obj
```

修改 `common/cert/x509_obj.py`：

```python
class CertObj:
    subject = None
    issuer = None
    serial_number = None
    valid_from = None
    valid_to = None
    version = None
    public_key = None
    org_cert = None
    cn = None  # 新增

    @classmethod
    def from_dict(cls, cert_dict):
        obj = cls()
        obj.subject = cert_dict.get('subject', '')
        obj.issuer = cert_dict.get('issuer', '')
        obj.serial_number = cert_dict.get('serial_number', '')
        obj.valid_from = cert_dict.get('valid_from', '')
        obj.valid_to = cert_dict.get('valid_to', '')
        obj.version = cert_dict.get('version', '')
        obj.public_key = cert_dict.get('public_key', None)
        obj.org_cert = cert_dict.get('org_cert', None)
        obj.cn = cert_dict.get('cn', None)  # 新增
        return obj
```

---

## 4. REST接口改造设计

### 4.1 接口改造总览

| 接口 | 改造内容 |
|------|---------|
| POST /register | 从证书提取CN作为owner入库 |
| PUT /update | 校验证书CN与agent owner匹配 |
| DELETE /deregister | 校验证书CN与agent owner匹配 |
| GET /query | 无变更（可选：按owner过滤） |
| GET /retrieve | 无变更（可选：按owner过滤） |

### 4.2 证书获取方式

**方案选择**：通过TLS握手获取客户端证书

FastAPI中获取客户端证书：

```python
# 方案A：通过SSL context获取（推荐）
# 需要配置uvicorn SSL参数
ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain(server_cert, server_key)
ssl_context.load_verify_locations(ca_cert)
ssl_context.verify_mode = ssl.CERT_REQUIRED  # 强制客户端证书

# 启动命令
uvicorn.run(app, ssl=ssl_context)

# 接口中获取证书
@app.post("/register")
async def register_agent(request: Request):
    # 从request.scope获取SSL信息
    ssl_info = request.scope.get('ssl', {})
    # 或从transport获取
    transport = request.scope.get('transport')
    # 具体获取方式依赖服务器配置
```

**方案B：通过HTTP Header传递（代理场景）**

当Agent Registry部署在反向代理后（如Nginx），由代理解析证书并传递：

```nginx
# /etc/nginx/nginx.conf 或 /etc/nginx/conf.d/agent-registry.conf

# 定义upstream后端服务
upstream agent_registry_backend {
    server 127.0.0.1:8000;  # Agent Registry后端地址
    # 可配置多个后端实现负载均衡
    # server 127.0.0.1:8001;
    # server 127.0.0.1:8002;
}

server {
    listen 443 ssl;
    server_name agent-registry.example.com;

    # 服务端证书配置
    ssl_certificate /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # 客户端证书验证配置
    ssl_client_certificate /etc/nginx/ssl/ca.crt;  # CA证书，用于验证客户端
    ssl_verify_client on;  # 强制要求客户端证书
    ssl_verify_depth 2;    # 证书链验证深度

    # SSL安全配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    location / {
        proxy_pass http://agent_registry_backend;
        
        # 传递客户端证书信息到后端
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 传递客户端证书CN（关键配置）
        proxy_set_header X-SSL-Client-CN $ssl_client_s_dn_cn;
        
        # 可选：传递完整DN和其他证书信息
        proxy_set_header X-SSL-Client-DN $ssl_client_s_dn;
        proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
        proxy_set_header X-SSL-Client-Serial $ssl_client_serial;
        
        # 超时配置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}

# HTTP重定向到HTTPS（可选）
server {
    listen 80;
    server_name agent-registry.example.com;
    return 301 https://$server_name$request_uri;
}
```

**关键配置说明**：

| 配置项 | 说明 |
|--------|------|
| `ssl_client_certificate` | CA证书路径，用于验证客户端证书合法性 |
| `ssl_verify_client on` | 强制要求客户端提供证书 |
| `ssl_verify_depth` | 证书链验证深度，根据证书层级调整 |
| `$ssl_client_s_dn_cn` | Nginx变量，自动提取客户端证书的CN字段 |
| `X-SSL-Client-CN` | 自定义Header名，传递CN到后端应用 |

**后端应用配置**：

```python
# FastAPI获取
@app.post("/register")
async def register_agent(request: Request):
    owner = request.headers.get('X-SSL-Client-CN')
    if not owner:
        raise HTTPException(status_code=401, detail="Client certificate required")
```

**Nginx变量参考**：

| Nginx变量 | 说明 | 示例值 |
|----------|------|--------|
| `$ssl_client_s_dn` | 客户端证书Subject完整DN | `CN=admin-001,OU=Ops,O=Company` |
| `$ssl_client_s_dn_cn` | 客户端证书CN字段 | `admin-001` |
| `$ssl_client_i_dn` | 客户端证书Issuer DN | `CN=MyCA,O=Company` |
| `$ssl_client_verify` | 客户端证书验证结果 | `SUCCESS` 或 `FAILED:reason` |
| `$ssl_client_serial` | 客户端证书序列号 | `0123456789ABCDEF` |

**部署步骤**：

1. 生成CA证书和客户端证书（或使用现有证书）
2. 配置Nginx SSL参数
3. 重启Nginx：`nginx -s reload`
4. 验证证书传递：`curl -k --cert client.crt --key client.key https://agent-registry.example.com`

**推荐方案B**：更灵活，支持代理场景。

### 4.3 注册接口改造

```python
@app.post("/rest/a2a-t/v1/agents/register")
async def register_agent(request: Request):
    """注册Agent，从证书提取owner，owner可为空"""
    
    # 1. 获取owner（从Header或SSL）
    owner = request.headers.get('X-SSL-Client-CN')
    
    # 2. 校验CN格式（如果有CN）
    if owner:
        from common.cert.cert_cn_parser import validate_cn
        if not validate_cn(owner):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid CN format: {owner}"
            )
    # owner为空表示公共agent，任何用户都可以修改和删除
    
    # 3. 解析AgentCard
    body = await request.body()
    agent = Parse(body, AgentCard())
    
    # 4. 注册（携带owner，可以为空）
    save_handle = HandlerRegistry.get_handler(InterfaceType.INSERT)
    success = await save_handle.handle(agent, owner=owner)
    
    return JSONResponse(content=success, status_code=status.HTTP_201_CREATED)
```

### 4.4 更新/删除接口改造

```python
async def _verify_owner_permission(
    request: Request, 
    name: str, 
    organization: str
) -> str:
    """
    校验owner权限
    
    流程:
    1. 从证书获取CN作为current_owner
    2. 查询agent获取stored_owner
    3. 比对是否匹配（owner为空时表示公共agent，任何用户都可以操作）
    
    Returns:
        current_owner (校验成功)
        
    Raises:
        HTTPException: 权限不匹配
    """
    # 1. 获取当前证书CN
    current_owner = request.headers.get('X-SSL-Client-CN')
    
    # 2. 查询agent
    query_handle = HandlerRegistry.get_handler(InterfaceType.GET)
    agent = await query_handle.handle(name, organization)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent ({name}, {organization}) not found"
        )
    
    # 3. 获取存储的owner
    stored_owner = agent.get('owner')  # 可能为None
    
    # 4. 权限校验
    # owner为空表示公共agent，任何用户都可以修改和删除
    if stored_owner is None or stored_owner == '':
        # 公共agent，允许任何用户操作
        return current_owner
    
    # 非公共agent，需要校验owner匹配
    if current_owner != stored_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: agent belongs to {stored_owner}"
        )
    
    return current_owner


@app.put("/rest/a2a-t/v1/update_agent/{name}")
async def update_agent(request: Request, name: str, organization: str):
    """更新Agent，校验owner权限"""
    
    # 1. 权限校验
    owner = await _verify_owner_permission(request, name, organization)
    
    # 2. 执行更新
    body = await request.body()
    agent_data = Parse(body, AgentCard())
    
    update_handle = HandlerRegistry.get_handler(InterfaceType.UPDATE)
    success = await update_handle.handle(name, organization, agent_data, owner=owner)
    
    return success


@app.delete("/rest/a2a-t/v1/deregister_agent/{name}")
async def deregister_agent(request: Request, name: str, organization: str):
    """注销Agent，校验owner权限"""
    
    # 1. 权限校验
    owner = await _verify_owner_permission(request, name, organization)
    
    # 2. 执行删除
    deregister_handle = HandlerRegistry.get_handler(InterfaceType.DEREGISTER)
    success = await deregister_handle.handle(name, organization, owner=owner)
    
    return success
```

---

## 5. 存储层改造设计

### 5.1 StorageBackend接口扩展

```python
# agent_registry/persistence/base.py
class StorageBackend(ABC):
    @abstractmethod
    def create(self, agent: AgentCard, owner: str) -> bool:
        """注册Agent，携带owner"""
        pass
    
    @abstractmethod
    def find_by_key(self, name: str, organization: str) -> Optional[Dict]:
        """查询Agent，返回包含owner的完整记录"""
        pass
    
    @abstractmethod
    def find_by_owner(self, owner: str) -> List[AgentCard]:
        """按owner查询（新增）"""
        pass
    
    @abstractmethod
    def update(self, name: str, organization: str, agent_data: Dict, owner: str) -> bool:
        """更新Agent，携带owner校验"""
        pass
    
    @abstractmethod
    def delete(self, name: str, organization: str, owner: str) -> bool:
        """删除Agent，携带owner校验"""
        pass
```

### 5.2 PostgreSQL存储改造

```python
# agent_registry/persistence/sql_queries.py 新增
class PostgreSQLQueries(str, Enum):
    # ... 现有语句 ...
    
    # 新增owner相关
    CREATE_AGENT_WITH_OWNER = """
        INSERT INTO agent_card (name, organization, owner, agent_card_json, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (name, organization) DO NOTHING
    """
    
    FIND_BY_OWNER = """
        SELECT agent_card_json, owner FROM agent_card WHERE owner = $1
    """
    
    UPDATE_AGENT_WITH_OWNER_CHECK = """
        UPDATE agent_card 
        SET agent_card_json = $3, updated_at = $4
        WHERE name = $1 AND organization = $2 AND owner = $5
    """
    
    DELETE_AGENT_WITH_OWNER_CHECK = """
        DELETE FROM agent_card 
        WHERE name = $1 AND organization = $2 AND owner = $3
    """
```

```python
# agent_registry/persistence/postgresql_storage.py 改造
class PostgreSQLStorage(StorageBackend):
    
    def create(self, agent: AgentCard, owner: str) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
                now = datetime.utcnow()
                cur.execute(
                    PostgreSQLQueries.CREATE_AGENT_WITH_OWNER.value,
                    (agent.name, agent.provider.organization, owner, 
                     json.dumps(agent_dict), now, now)
                )
                conn.commit()
            return cur.rowcount > 0
        finally:
            self.pool.putconn(conn)
    
    def find_by_key(self, name: str, organization: str) -> Optional[Dict]:
        """返回包含owner的完整记录"""
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.FIND_BY_KEY.value,
                    (name, organization)
                )
                row = cur.fetchone()
            if row:
                data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                owner = row[1] if len(row) > 1 else 'system'
                return {"agent_card": AgentCard(**data), "owner": owner}
            return None
        finally:
            self.pool.putconn(conn)
    
    def update(self, name: str, organization: str, agent_data: Dict, owner: str) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                now = datetime.utcnow()
                cur.execute(
                    PostgreSQLQueries.UPDATE_AGENT_WITH_OWNER_CHECK.value,
                    (name, organization, json.dumps(agent_data), now, owner)
                )
                conn.commit()
                affected = cur.rowcount
            return affected > 0
        finally:
            self.pool.putconn(conn)
    
    def delete(self, name: str, organization: str, owner: str) -> bool:
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    PostgreSQLQueries.DELETE_AGENT_WITH_OWNER_CHECK.value,
                    (name, organization, owner)
                )
                conn.commit()
                affected = cur.rowcount
            return affected > 0
        finally:
            self.pool.putconn(conn)
```

### 5.3 文件存储改造（推荐方案）

#### 方案A：双文件存储模式

**设计思路**：
- **原始逻辑不变**：agent数据保存在agentcard.json文件中
- **新增元数据文件**：专门存储agent的name、organization、owner、时间等元数据
- **一一对应**：新文件的name、organization和agentcard.json文件中的name、organization一一对应

**文件结构**：
```
data/
├── agentcard.json              # Agent Card数据文件
│   [
│     {"name": "agent-001", "organization": "org-A", ...},
│     {"name": "agent-002", "organization": "org-B", ...}
│   ]
└── agent_metadata.json         # 元数据文件
    [
      {
        "name": "agent-001",
        "organization": "org-A",
        "owner": "admin-001",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z"
      },
      {
        "name": "agent-002",
        "organization": "org-B",
        "owner": null,          # owner为空表示公共agent
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z"
      }
    ]
```

**优点**：
- agentcard.json保持原始格式，兼容现有逻辑
- 元数据独立管理，易于扩展
- 一一对应关系清晰，便于查询

**缺点**：
- 需要维护两个文件的一致性
- 元数据查询需要额外的文件读取

```python
# agent_registry/persistence/file_storage.py 改造
class FileStorage(StorageBackend):
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.agent_card_file = self.data_dir / "agentcard.json"
        self.metadata_file = self.data_dir / "agent_metadata.json"
        self._agents: Dict[tuple, dict] = {}  # (name, org) -> agent_card
        self._metadata: Dict[tuple, dict] = {}  # (name, org) -> metadata
        self._load()
    
    def _load(self):
        """加载两个文件"""
        # 加载agent card
        if self.agent_card_file.exists():
            with open(self.agent_card_file, 'r', encoding='utf-8') as f:
                agent_list = json.load(f)
                for agent_data in agent_list:
                    key = (agent_data.get('name', '').strip(), 
                           agent_data.get('provider', {}).get('organization', '').strip())
                    self._agents[key] = agent_data
        
        # 加载metadata
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                metadata_list = json.load(f)
                for meta in metadata_list:
                    key = (meta.get('name', '').strip(), 
                           meta.get('organization', '').strip())
                    self._metadata[key] = meta
    
    def _save(self):
        """保存两个文件"""
        # 保存agent card
        agent_list = list(self._agents.values())
        with open(self.agent_card_file, 'w', encoding='utf-8') as f:
            json.dump(agent_list, f, ensure_ascii=False, indent=2)
        
        # 保存metadata
        metadata_list = list(self._metadata.values())
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata_list, f, ensure_ascii=False, indent=2)
    
    def create(self, agent: AgentCard, owner: str = None) -> bool:
        """注册Agent，owner可为空"""
        key = (agent.name.strip(), agent.provider.organization.strip())
        
        # 检查是否已存在
        if key in self._agents:
            return False
        
        # 保存agent card
        agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
        self._agents[key] = agent_dict
        
        # 保存metadata
        now = datetime.utcnow().isoformat()
        self._metadata[key] = {
            "name": agent.name,
            "organization": agent.provider.organization,
            "owner": owner,  # 可以为None
            "created_at": now,
            "updated_at": now
        }
        
        self._save()
        return True
    
    def find_by_key(self, name: str, organization: str) -> Optional[Dict]:
        """查询Agent，返回包含owner的记录"""
        key = (name.strip(), organization.strip())
        
        if key not in self._agents:
            return None
        
        agent_data = self._agents[key]
        metadata = self._metadata.get(key, {})
        
        return {
            "agent_card": AgentCard(**agent_data),
            "owner": metadata.get("owner")  # 可能为None
        }
    
    def update(self, name: str, organization: str, agent_data: Dict, owner: str = None) -> bool:
        """更新Agent，校验owner权限"""
        key = (name.strip(), organization.strip())
        
        if key not in self._agents:
            return False
        
        metadata = self._metadata.get(key, {})
        stored_owner = metadata.get("owner")
        
        # 权限校验：owner为空表示公共agent，任何用户都可以修改
        # owner不为空时，需要校验owner匹配
        if stored_owner is not None and stored_owner != '':
            if owner != stored_owner:
                raise PermissionError(f"Agent belongs to {stored_owner}")
        
        # 更新agent card
        self._agents[key] = agent_data
        
        # 更新metadata
        self._metadata[key]["updated_at"] = datetime.utcnow().isoformat()
        # 注意：不更新owner，保持原有owner
        
        self._save()
        return True
    
    def delete(self, name: str, organization: str, owner: str = None) -> bool:
        """删除Agent，校验owner权限"""
        key = (name.strip(), organization.strip())
        
        if key not in self._agents:
            return False
        
        metadata = self._metadata.get(key, {})
        stored_owner = metadata.get("owner")
        
        # 权限校验：owner为空表示公共agent，任何用户都可以删除
        # owner不为空时，需要校验owner匹配
        if stored_owner is not None and stored_owner != '':
            if owner != stored_owner:
                raise PermissionError(f"Agent belongs to {stored_owner}")
        
        del self._agents[key]
        del self._metadata[key]
        self._save()
        return True
```

#### 方案B：单文件存储模式（备选）

**结构**：单个JSON文件，每条记录携带owner字段

```json
// data/agents.json
[
    {
        "name": "agent-001",
        "organization": "org-A",
        "owner": "admin-001",
        "agent_card": {...},
        "created_at": "2026-01-01T00:00:00Z"
    },
    {
        "name": "agent-002",
        "organization": "org-B",
        "owner": null,
        "agent_card": {...}
    }
]
```

**优点**：
- 实现简单，改动小
- 跨owner查询方便
- 数据迁移平滑

**缺点**：
- 大文件性能问题（已有max_file_size限制）
- 无物理隔离
- 与原始agentcard.json格式不兼容

```python
# agent_registry/persistence/file_storage.py 改造
class FileStorage(StorageBackend):
    
    def create(self, agent: AgentCard, owner: str = None) -> bool:
        key = (agent.name.strip(), agent.provider.organization.strip())
        agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
        
        # 存储结构：包含owner元数据
        record = {
            "name": agent.name,
            "organization": agent.provider.organization,
            "owner": owner,  # 可以为None
            "agent_card": agent_dict,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        self._agents[key] = record
        self._save()
        return True
    
    def find_by_key(self, name: str, organization: str) -> Optional[Dict]:
        key = (name.strip(), organization.strip())
        record = self._agents.get(key)
        if record:
            return {
                "agent_card": AgentCard(**record["agent_card"]),
                "owner": record.get("owner")  # 可能为None
            }
        return None
    
    def update(self, name: str, organization: str, agent_data: Dict, owner: str = None) -> bool:
        key = (name.strip(), organization.strip())
        record = self._agents.get(key)
        if not record:
            return False
        
        # 权限校验：owner为空表示公共agent
        stored_owner = record.get("owner")
        if stored_owner is not None and stored_owner != '':
            if owner != stored_owner:
                raise PermissionError(f"Agent belongs to {stored_owner}")
        
        record["agent_card"] = agent_data
        record["updated_at"] = datetime.utcnow().isoformat()
        self._agents[key] = record
        self._save()
        return True
    
    def delete(self, name: str, organization: str, owner: str = None) -> bool:
        key = (name.strip(), organization.strip())
        record = self._agents.get(key)
        if not record:
            return False
        
        # 权限校验：owner为空表示公共agent
        stored_owner = record.get("owner")
        if stored_owner is not None and stored_owner != '':
            if owner != stored_owner:
                raise PermissionError(f"Agent belongs to {stored_owner}")
        
        del self._agents[key]
        self._save()
        return True
    
    def _save(self) -> None:
        # 保存完整记录（包含owner）
        records = []
        for record in self._agents.values():
            records.append(record)
        
        json_str = json.dumps(records, ensure_ascii=False, indent=2)
        # ... 大小检查和写入逻辑 ...
```

### 5.4 文件存储方案推荐

| 场景 | 推荐方案 |
|------|---------|
| 少量owner (<10) | 方案B：单文件+owner字段，简单高效 |
| 需要保持原始数据格式 | 方案A：双文件模式，agentcard.json不变 |
| 需要平滑迁移 | 方案A：双文件模式，兼容现有agentcard.json |
| 多owner + 物理隔离需求 | 方案B：单文件+owner字段 |

**默认推荐方案A（双文件模式）**，保持agentcard.json原始格式，兼容现有架构。

**重要说明**：
- owner可以为空，owner为空表示公共agent
- 公共agent可以被任何用户修改和删除

---

## 6. Handler改造设计

### 6.1 InsertHandler改造

```python
# common/custom/custom_handle.py
class InsertHandler(Handler):
    async def handle(self, agent: AgentCard, owner: str = None) -> bool:
        """注册Agent，携带owner，owner可以为空"""
        registry = get_registry()
        return registry.register(agent, owner=owner)
```

### 6.2 UpdateHandler改造

```python
class UpdateHandler(Handler):
    async def handle(self, name: str, organization: str, 
                     agent_data: dict, owner: str = None) -> bool:
        """更新Agent，携带owner校验，owner可以为空"""
        registry = get_registry()
        return registry.update(name, organization, agent_data, owner=owner)
```

### 6.3 DeregisterHandler改造

```python
class DeregisterHandler(Handler):
    async def handle(self, name: str, organization: str, 
                     owner: str = None) -> bool:
        """注销Agent，携带owner校验，owner可以为空"""
        registry = get_registry()
        return registry.deregister(name, organization, owner=owner)
```

### 6.4 GetHandler改造

```python
class GetHandler(Handler):
    async def handle(self, name: str, organization: str) -> Optional[Dict]:
        """查询Agent，返回包含owner的记录"""
        registry = get_registry()
        return registry.get_by_key(name, organization)
```

---

## 7. RegistryCore改造

```python
# agent_registry/core.py
class RegistryCore:
    
    def register(self, agent: AgentCard, owner: str = None, 
                 use_vectordb: bool = USE_VECTORDB) -> bool:
        """注册Agent，携带owner，owner可以为空"""
        with self._lock:
            if use_vectordb:
                # vectordb模式：存储时包含owner
                entity_str = json.dumps(MessageToDict(agent, preserving_proto_field_name=True))
                embedding = self.embedding_tool.get_embedding_vector(agent.description)
                id = self._make_id(agent.name, agent.provider.organization)
                insert_entity = {
                    "embedding": embedding,
                    "id": id,
                    "name": agent.name,
                    "description": agent.description,
                    "organization": agent.provider.organization,
                    "agent_card": entity_str,
                    "owner": owner  # 新增，可以为None
                }
                insert_data = {"collection_name": COLLECTION_NAME, "entity": insert_entity}
                return self.vectordb.insert_entity(insert_data)
            elif self.persistence_mode == 'postgresql':
                return self.storage.create(agent, owner)
            else:
                return self.storage.create(agent, owner)
    
    def get_by_key(self, name: str, organization: str, 
                   use_vectordb: bool = USE_VECTORDB) -> Optional[Dict]:
        """查询Agent，返回包含owner的记录"""
        if use_vectordb:
            query_data = {"collection_name": COLLECTION_NAME, "key": "id", 
                          "value": self._make_id(name, organization)}
            results = self.vectordb.query_by_key(query_data)
            if results:
                result = results[0]
                return {
                    "agent_card": AgentCard(**result.get("agent_card", {})),
                    "owner": result.get("owner")  # 可能为None
                }
            return None
        elif self.persistence_mode == 'postgresql':
            return self.storage.find_by_key(name, organization)
        else:
            return self.storage.find_by_key(name, organization)
    
    def update(self, name: str, organization: str, agent_data: Dict, 
               owner: str = None, use_vectordb: bool = USE_VECTORDB) -> bool:
        """更新Agent，携带owner校验，owner为空表示公共agent"""
        if use_vectordb:
            # vectordb更新时校验owner
            existing = self.get_by_key(name, organization)
            if not existing:
                return False
            stored_owner = existing.get("owner")
            # owner为空表示公共agent，任何用户都可以修改
            if stored_owner is not None and stored_owner != '':
                if owner != stored_owner:
                    raise PermissionError(f"Permission denied")
            # ... vectordb更新逻辑 ...
        elif self.persistence_mode == 'postgresql':
            return self.storage.update(name, organization, agent_data, owner)
        else:
            return self.storage.update(name, organization, agent_data, owner)
    
    def deregister(self, name: str, organization: str, owner: str = None,
                   use_vectordb: bool = USE_VECTORDB) -> bool:
        """注销Agent，携带owner校验，owner为空表示公共agent"""
        if use_vectordb:
            existing = self.get_by_key(name, organization)
            if not existing:
                return False
            stored_owner = existing.get("owner")
            # owner为空表示公共agent，任何用户都可以删除
            if stored_owner is not None and stored_owner != '':
                if owner != stored_owner:
                    raise PermissionError(f"Permission denied")
            # ... vectordb删除逻辑 ...
        elif self.persistence_mode == 'postgresql':
            return self.storage.delete(name, organization, owner)
        else:
            return self.storage.delete(name, organization, owner)
```

---

## 8. 配置变更

### 8.1 新增配置项

```properties
# etc/conf/server.conf 新增

# Owner隔离开关（默认关闭）
owner.isolation.enabled=false

# Owner校验严格模式
# strict: 严格校验，CN必须合法格式
# relaxed: 宽松模式，CN可以为空
owner.validation.mode=strict

# 文件存储owner隔离模式
# dual_file: 双文件模式（推荐）
# single_file: 单文件+owner字段
file.storage.owner.mode=dual_file
```

**注意**：
- `owner.isolation.enabled` 默认为 `false`，可根据需要开启
- `owner` 可以为空，不需要配置默认owner
- owner为空时表示公共agent，任何用户都可以修改和删除

### 8.2 init配置命令支持

```python
# 新增init命令对owner配置的支持
# init配置命令新增以下参数

def init_config(args):
    """
    初始化配置，支持owner相关配置
    
    参数:
    --owner-isolation-enabled: 是否启用owner隔离，默认false
    --owner-validation-mode: owner校验模式，默认strict
    --file-storage-owner-mode: 文件存储模式，默认dual_file
    """
    config = {
        "owner.isolation.enabled": args.owner_isolation_enabled or "false",
        "owner.validation.mode": args.owner_validation_mode or "strict",
        "file.storage.owner.mode": args.file_storage_owner_mode or "dual_file"
    }
    
    # 写入配置文件
    write_config(config)
```

**使用示例**：

```bash
# 初始化配置，启用owner隔离
init --owner-isolation-enabled=true --owner-validation-mode=strict --file-storage-owner-mode=dual_file

# 初始化配置，使用默认值（owner隔离关闭）
init

# 初始化配置，指定文件存储模式
init --file-storage-owner-mode=single_file
```

### 8.3 配置加载

```python
# agent_registry/config.py 新增
OWNER_ISOLATION_ENABLED = get_conf().get('owner.isolation.enabled', 'false').lower() == 'true'
OWNER_VALIDATION_MODE = get_conf().get('owner.validation.mode', 'strict')
FILE_STORAGE_OWNER_MODE = get_conf().get('file.storage.owner.mode', 'dual_file')
```

---

## 9. 向量数据库改造（可选）

若使用Milvus向量数据库，需扩展collection schema：

```python
# collection定义增加owner字段
fields = [
    FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=256, is_primary=True),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024),
    FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=100),
    FieldSchema(name="organization", dtype=DataType.VARCHAR, max_length=100),
    FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=1000),
    FieldSchema(name="agent_card", dtype=DataType.VARCHAR, max_length=65535),
    FieldSchema(name="owner", dtype=DataType.VARCHAR, max_length=100),  # 新增
]

# 创建owner索引
index_params = {
    "field_name": "owner",
    "index_type": "Trie",
    "metric_type": "UNKNOWN"
}
collection.create_index("owner", index_params)
```

---

## 10. 流程图

### 10.1 注册流程

```mermaid
sequenceDiagram
    participant Client as Agent Client
    participant Proxy as Nginx/Proxy
    participant API as FastAPI
    participant Handler as InsertHandler
    participant Storage as FileStorage/PostgreSQL
    
    Client->>Proxy: HTTPS + Client Cert
    Proxy->>Proxy: 解析证书CN
    Proxy->>API: POST /register<br/>Header: X-SSL-Client-CN=admin-001
    API->>API: 校验CN格式
    API->>API: 解析AgentCard
    API->>Handler: handle(agent, owner=admin-001)
    Handler->>Storage: create(agent, owner)
    
    alt PostgreSQL
        Storage->>Storage: INSERT with owner
    else FileStorage
        Storage->>Storage: 写入记录+owner字段
    end
    
    Storage-->>Handler: success
    Handler-->>API: success
    API-->>Client: 201 Created
```

### 10.2 更新/删除流程

```mermaid
sequenceDiagram
    participant Client as Agent Client
    participant API as FastAPI
    participant Query as GetHandler
    participant Storage as StorageBackend
    
    Client->>API: PUT /update<br/>Header: X-SSL-Client-CN=admin-001
    API->>Query: find_by_key(name, org)
    Query->>Storage: 查询agent
    Storage-->>Query: {agent_card, owner: admin-001}
    Query-->>API: agent_record
    
    API->>API: 检查owner是否为空
    API->>API: 非空则校验 CN(admin-001) == owner(admin-001)
    
    alt owner为空（公共agent）
        API->>API: 允许任何用户操作
        API->>Storage: update(name, org, data, owner)
        Storage-->>API: success
        API-->>Client: 200 OK
    else 匹配成功
        API->>Storage: update(name, org, data, owner)
        Storage-->>API: success
        API-->>Client: 200 OK
    else 匹配失败
        API-->>Client: 403 Forbidden<br/>Agent belongs to admin-002
    end
```

---

## 11. 测试设计

| 测试用例 | 描述 |
|---------|------|
| test_cn_extraction | CN字段解析正确性 |
| test_cn_validation | CN格式校验（长度64字节，无空格和下划线） |
| test_register_with_owner | 注册携带owner |
| test_register_without_owner | 注册时owner为空（公共agent） |
| test_update_owner_match | 更新时owner匹配成功 |
| test_update_owner_mismatch | 更新时owner不匹配拒绝 |
| test_update_public_agent | 更新公共agent（owner为空）成功 |
| test_delete_owner_match | 删除时owner匹配成功 |
| test_delete_owner_mismatch | 删除时owner不匹配拒绝 |
| test_delete_public_agent | 删除公共agent（owner为空）成功 |
| test_file_storage_owner | 文件存储owner隔离 |
| test_file_storage_public_agent | 文件存储公共agent |
| test_postgresql_storage_owner | PostgreSQL存储owner隔离 |
| test_postgresql_storage_public_agent | PostgreSQL存储公共agent |
| test_dual_file_storage | 双文件模式存储正确性 |
| test_dual_file_consistency | 双文件模式数据一致性 |

---

## 12. 文件清单

### 新增文件

| 文件路径 | 说明 |
|---------|------|
| `common/cert/cert_cn_parser.py` | CN解析工具 |
| `data/agent_metadata.json` | Agent元数据文件（双文件模式） |

### 修改文件

| 文件 | 改动 |
|------|------|
| `common/cert/cert_parser.py` | `_extract_certificate_info`增加CN提取 |
| `common/cert/x509_obj.py` | `CertObj`增加cn属性 |
| `agent_registry/persistence/base.py` | 接口增加owner参数（可为None） |
| `agent_registry/persistence/file_storage.py` | 实现双文件模式owner隔离 |
| `agent_registry/persistence/postgresql_storage.py` | 实现owner隔离（owner可为NULL） |
| `agent_registry/persistence/sql_queries.py` | 新增owner相关SQL |
| `agent_registry/core.py` | 方法增加owner参数（可为None） |
| `agent_registry/server.py` | 接口改造，提取和校验owner，支持公共agent |
| `common/custom/custom_handle.py` | Handler增加owner参数（可为None） |
| `agent_registry/config.py` | 新增owner相关配置 |

---

## 13. 实现计划

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| 1 | CN解析工具 `cert_cn_parser.py` | P0 |
| 2 | 证书解析集成（cert_parser/x509_obj） | P0 |
| 3 | PostgreSQL表结构变更 | P0 |
| 4 | StorageBackend接口扩展 | P0 |
| 5 | PostgreSQL存储owner实现 | P0 |
| 6 | 文件存储owner实现（方案A） | P0 |
| 7 | Handler改造 | P0 |
| 8 | RegistryCore改造 | P0 |
| 9 | REST接口改造 | P0 |
| 10 | 配置项新增 | P1 |
| 11 | 文件存储方案B实现（可选） | P2 |
| 12 | 向量数据库owner扩展（可选） | P2 |
| 13 | 单元测试 | P0 |

---

## 14. 文件存储方案选择建议

### 场景分析

| 场景 | agent数量 | owner数量 | 推荐方案 |
|------|----------|----------|---------|
| 开发/测试环境 | <100 | <5 | 方案B：单文件 |
| 小规模生产 | <1000 | <20 | 方案A：双文件 |
| 需保持原始格式 | - | - | 方案A：双文件 |
| 大规模生产 | >1000 | >50 | 方案B：单文件 |

### 方案A详细说明

**适用场景**：
- 需要保持agentcard.json原始格式的系统
- 需要平滑迁移的存量系统
- 元数据需要独立管理的场景

**实现要点**：
- agentcard.json保持原始格式不变
- 新增agent_metadata.json存储owner等元数据
- 两个文件一一对应，通过name+organization关联

### 方案B详细说明

**适用场景**：
- 新系统，不需要保持原始格式
- 查询性能要求高的场景（单文件索引更快）
- 实现简单的场景

**实现要点**：
- 每条记录增加 `owner` 字段
- owner可以为空，表示公共agent
- 权限校验在业务层完成

### 公共agent说明

- **定义**：owner为空（null或空字符串）的agent为公共agent
- **权限**：任何用户都可以修改和删除公共agent
- **适用场景**：共享的公共工具agent、系统级agent等

---

## 15. 安全注意事项

1. **CN校验**：严格校验CN格式，防止注入
2. **目录权限**：owner目录设置0o700，文件设置0o600
3. **日志脱敏**：审计日志中owner脱敏处理
4. **公共agent管理**：owner为空的agent为公共agent，任何用户都可以修改和删除，需要谨慎管理
5. **代理信任**：X-SSL-Client-CN Header来源可信
6. **owner为空的处理**：注册时owner可以为空，表示创建公共agent；操作时需要明确区分公共agent和私有agent的权限