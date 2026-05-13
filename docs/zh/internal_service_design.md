# 注册中心内部交互服务设计文档

## 1. 功能概述

### 1.1 背景

注册中心系统(registry-center)作为多个Agent之间的中转站，需要与多个Agent进程进行交互。为了更好地管理Agent的发布流程和提供内部管理能力，需要补充实现内部交互服务。

### 1.2 核心需求

#### 需求1：审核开关配置

- 用户可通过`python -m agent_registry.init`命令配置审核开关的开启状态
- 审核开关配置写入`etc/conf/server.conf`文件
- 审核开关开启后可以关闭，但需检查是否存在"已注册"状态的Agent
- 若存在"已注册"状态的Agent，则报错提醒用户先发布或删除这些Agent
- 若不存在"已注册"状态的Agent，则成功关闭审核开关

#### 需求2：Agent状态管理

- **审核开关开启时**：
  - Agent注册后初始状态为"已注册"
  - 调用审核接口后状态更新为"已发布"
  
- **审核开关关闭时**：
  - Agent注册后直接设置为"已发布"状态

#### 需求3：内部交互服务

- 通过UDS(Unix Domain Socket)实现内部交互能力
- 统一的socket入口，支持多种内部操作
- 通过action字段区分不同操作类型
- 当前支持操作：审核(approval)、后续可扩展更多操作

### 1.3 设计原则

#### 1.3.1 统一Socket架构

- **单一socket文件**：所有内部交互操作共用一个socket
- **Handler模式**：不同操作由不同Handler处理
- **易于扩展**：新增操作只需添加新Handler
- **参考业界标准**：类似Docker的`/var/run/docker.sock`设计

#### 1.3.2 同进程部署

- **进程内线程**：UDS服务作为线程与HTTP服务在同一进程
- **数据共享**：共享RegistryCore实例，无需数据同步
- **配置统一**：所有配置在同一个配置文件
- **管理简单**：只需管理一个进程

## 2. 系统设计

### 2.1 审核开关配置

#### 2.1.1 配置项

在`etc/conf/server.conf`文件中新增配置项：

```ini
# Agent审核功能开关
agent_approval_enabled=true
```

**配置说明：**
- `true`：审核功能开启，Agent注册后需要审核才能发布
- `false`：审核功能关闭，Agent注册后直接发布

#### 2.1.2 配置流程

```
┌─────────────────────────────────┐
│  执行: python -m agent_registry.init │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  读取现有配置: agent_approval_enabled │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  提示用户输入审核开关配置         │
│  "是否开启审核功能 (y/n, 默认: true)" │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  用户输入: y/n                   │
└──────────┬──────────────────────┘
           │
      ┌────┴────┐
      │         │
  输入y      输入n
      │         │
      │         ▼
      │  ┌──────────────────────┐
      │  │ 检查现有配置           │
      │  │ agent_approval_enabled=? │
      │  └─────────┬────────────┘
      │       ┌────┴────┐
      │       │         │
      │    现有=true  现有=false
      │       │         │
      │       ▼         ▼
      │  ┌─────────────┐  ┌─────────┐
      │  │检查是否存在  │  │允许关闭 │
      │  │"已注册"Agent │  │→开启审核│
      │  └─────────┬───┘  └─────────┘
      │     ┌─────┴─────┐
      │     │           │
      │   存在        不存在
      │     │           │
      │     ▼           ▼
      │  ┌─────────┐  ┌─────────┐
      │  │报错：请先│  │成功关闭 │
      │  │发布Agent │  │审核开关 │
      │  └─────────┘  └─────────┘
      │
      ▼
┌─────────────────────────────────┐
│  写入配置到server.conf            │
│  agent_approval_enabled=true/false│
└─────────────────────────────────┘
```

#### 2.1.3 配置变更规则

**规则1：审核开关开启后可以关闭，但需检查已注册Agent**

```python
# 现有配置: agent_approval_enabled=true
# 用户输入: n (尝试关闭)

# 系统检查是否存在"已注册"状态的Agent:
if has_registered_agents():
    # 系统报错：
    错误：审核功能已开启，不能直接关闭！
    原因：存在"已注册"状态的Agent，关闭审核会导致状态不一致。
    
    建议：
    1. 先通过审核接口发布所有"已注册"状态的Agent
    2. 或通过注销接口删除不需要的Agent
    3. 处理完毕后再关闭审核功能
else:
    # 系统允许关闭：
    配置成功：审核功能已关闭
    注意：新注册的Agent将直接为"已发布"状态
```

**规则2：审核开关关闭后可以开启**

```python
# 现有配置: agent_approval_enabled=false
# 用户输入: y (尝试开启)

# 系统允许：
配置成功：审核功能已开启
注意：
- 新注册的Agent初始状态为"已注册"
- 已存在的"已发布"状态Agent保持不变
```

### 2.2 Agent状态模型

#### 2.2.1 状态定义

Agent状态分为两种：

| 状态 | 说明 | 可执行操作 |
|------|------|-----------|
| `registered` | 已注册 | 等待审核、可被审核接口调用 |
| `published` | 已发布 | 可被查询、可被调用、可被注销 |

#### 2.2.2 状态转换

```
┌─────────────────┐
│  Agent注册请求   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  检查审核开关配置                 │
│  agent_approval_enabled=?       │
└────────┬────────────────────────┘
         │
    ┌────┴────┐
    │         │
  true      false
    │         │
    ▼         ▼
┌──────────┐ ┌──────────┐
│状态=已注册│ │状态=已发布│
└─────┬────┘ └──────────┘
      │
      │ 审核接口调用
      ▼
┌──────────────┐
│ 检查审核开关  │
│ agent_approval_enabled=? │
└───────┬──────┘
    ┌───┴───┐
    │       │
  true    false
    │       │
    ▼       ▼
┌──────────┐ ┌──────────┐
│状态=已发布│ │报错：审核│
│(审核成功)│ │功能已关闭│
└──────────┘ └──────────┘
```

#### 2.2.3 数据模型变更

**修改AgentCard数据结构：**

在AgentCard中新增`status`字段：

```json
{
  "name": "TestAgent",
  "provider": {
    "organization": "TestOrg",
    "url": "https://test.org"
  },
  "description": "Test Description",
  "url": "https://agent.test",
  "version": "1.0.0",
  "status": "registered",  // 新增字段：registered 或 published
  ...
}
```

**状态字段说明：**
- `status`：字符串类型，枚举值为 `"registered"` 或 `"published"`
- 默认值：根据审核开关配置决定
- 必填字段

### 2.3 注册接口变更

#### 2.3.1 接口定义

**接口路径：** `/rest/a2a-t/v1/agents/register`

**请求体：** Agent Card格式

**响应：**

```json
{
  "success": true,
  "message": "Agent registered successfully",
  "status": "registered",  // 或 "published"
  "agent": {
    "name": "TestAgent",
    "provider": {
      "organization": "TestOrg",
      "url": "https://test.org"
    },
    ...
  }
}
```

#### 2.3.2 注册流程

```python
async def register_agent(agent_card: ValidatedAgentCard):
    # 步骤1：验签（如果验签开关开启）
    if signature_validation_enabled:
        # 验签逻辑...
    
    # 步骤2：读取审核开关配置
    approval_enabled = config.get('agent_approval_enabled', 'false')
    
    # 步骤3：设置Agent初始状态
    if approval_enabled == 'true':
        agent_card.status = 'registered'  # 已注册，等待审核
    else:
        agent_card.status = 'published'   # 已发布，无需审核
    
    # 步骤4：保存Agent
    registry.register(agent_card)
    
    # 步骤5：返回响应
    return {
        "success": true,
        "status": agent_card.status,
        "message": f"Agent registered as {agent_card.status}"
    }
```

### 2.3 查询接口变更

#### 2.3.1 接口说明

系统提供两个HTTP查询接口，用于查询Agent信息：

**接口1：** `/rest/a2a-t/v1/agents/{name}` - 按名称和组织查询单个Agent

**接口2：** `/rest/a2a-t/v1/agents/query` - 按条件查询Agent列表

#### 2.3.2 查询逻辑变更

**变更规则：只查询处于"已发布"状态的Agent**

- 查询接口只返回`status=published`的Agent
- 处于`status=registered`状态的Agent不会出现在查询结果中
- 这样可以确保外部调用者只能看到已经审核通过的Agent

**实现要点：**

修改`agent_registry/server.py`中的查询接口逻辑：

1. `/rest/a2a-t/v1/agents/{name}`接口：
   - 调用`find_by_key()`方法时，检查Agent的status字段
   - 如果Agent存在但status为`registered`，返回404或空结果
   - 只有status为`published`的Agent才会返回

2. `/rest/a2a-t/v1/agents/query`接口：
   - 调用`find_by_name()`、`find_by_organization()`等方法时，过滤掉status为`registered`的Agent
   - 只返回status为`published`的Agent列表

**代码示例：**

```python
@app.get("/rest/a2a-t/v1/agents/{name}")
async def get_agent(name: str, organization: str):
    """查询单个Agent（只返回已发布状态）"""
    agent = registry.find_by_key(name, organization)
    
    # 检查Agent状态，只返回已发布的Agent
    if agent and agent.status != 'published':
        return None  # 或抛出404异常
    
    return agent

@app.get("/rest/a2a-t/v1/agents/query")
async def list_agents(name: Optional[str] = None, organization: Optional[str] = None):
    """查询Agent列表（只返回已发布状态）"""
    agents = registry.find_all()
    
    # 过滤条件
    if name:
        agents = [a for a in agents if a.name == name]
    if organization:
        agents = [a for a in agents if a.provider.organization == organization]
    
    # 只返回已发布状态的Agent
    agents = [a for a in agents if a.status == 'published']
    
    return agents
```

### 2.4 UDS内部交互服务设计

#### 2.4.1 统一Socket架构

**设计理念：**

采用统一socket + Handler分发模式，类似Docker的设计：

- 单一socket入口：socket文件存放在项目目录下
- Socket路径：`run/registry-center/internal.sock`（项目根目录下的相对路径）
- 所有内部操作通过action字段区分
- Handler模式处理不同操作
- 易于扩展新功能

**架构图：**

```
┌─────────────────────────────────────────┐
│ RegistryCenterService (统一服务)          │
│                                         │
│  监听：run/registry-center/internal.sock │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │ 请求分发器        │   │
│  │ 根据action分发到不同handler         │   │
│  └─────────────┬───────────────────┘   │
│                │                        │
│      ┌─────────┴─────────┬──────┬─────┐│
│      │                   │      │     ││
│      ▼                   ▼      ▼     ▼│
│  ┌────────┐  ┌────────┐ ┌────┐ ┌────┐ │
│  │审核    │  │配置    │ │统计│ │查询│ │
│  │Handler │  │Handler │ │Hdlr│ │Hdlr│ │
│  └────────┘  └────────┘ └────┘ └────┘ │
│                                         │
│  后续扩充时只需添加新Handler              │
└─────────────────────────────────────────┘

                    ↓ UDS连接

┌──────────────────┐
│ 客户端            │
│                  │
│ 发送请求：         │
│ {                │
│  "action":"approval",│ ← action字段区分操作
│  "params": {     │ ← params封装请求参数
│    "agent_name":"X",│
│    "organization":"Y"│
│  }               │
│ }                │
└──────────────────┘
```

#### 2.4.2 协议设计

**UDS Socket路径：** `run/registry-center/internal.sock`

**Socket路径说明：**
- socket文件存放在项目根目录下的`run/registry-center/`目录
- 启动时自动创建该目录（如果不存在）
- socket文件权限设置为`0o660`（rw-rw----）

**接口协议：** JSON over UDS

**请求格式：**

```json
{
  "action": "approval",        // 操作类型
  "params": {                  // 请求参数（不同操作有不同的参数）
    "agent_name": "TestAgent", // Agent名称
    "organization": "TestOrg"  // 组织名称
  }
}
```

**响应格式：**

```json
{
  "success": true,
  "message": "Agent approval successful",
  "agent": {
    "name": "TestAgent",
    "organization": "TestOrg",
    "status": "published"
  }
}
```

**支持的操作类型（action）：**

| action | 说明 | 参数 |
|--------|------|------|
| `approval` | 审核Agent | agent_name, organization |
| `get_agent` | 查询单个Agent元数据 | agent_name, organization |
| `list_agents` | 查询全量Agent元数据 | 无参数 |
| `set_tag` | 设置Agent标签（全量覆盖） | agent_name, organization, tags(数组) |
| `config` | 配置管理 | config_key, config_value |
| `stats` | 统计查询 | type |
| `query` | Agent查询 | agent_name, organization |

#### 2.4.3 进程架构

**部署方案：同进程多线程**

```
┌─────────────────────────────────────────┐
│ Registry Center 进程（单个进程）          │
│ PID: 12345                              │
│                                         │
│ 主线程：HTTP服务                         │
│ ├─ uvicorn.run()                        │
│ ├─ 监听：127.0.0.1:9301                  │
│ ├─ /rest/a2a-t/v1/agents/register       │
│ ├─ /rest/a2a-t/v1/agents/query          │
│ └─ ...其他HTTP接口                       │
│                                         │
│ 子线程：UDS服务                          │
│ ├─ RegistryCenterService.start()        │
│ ├─ 监听：run/registry-center/internal.sock │
│ └─ 处理内部交互请求                       │
│                                         │
│ 共享资源：                                │
│ ├─ RegistryCore实例（共享Agent数据）      │
│ ├─ 配置文件（共享etc/conf/server.conf）  │
│ └─ 持久化存储（根据persistence.mode配置） │
└─────────────────────────────────────────┘
```

**关键特点：**

1. **数据共享**：UDS和HTTP服务共享RegistryCore实例
2. **无数据同步**：直接访问共享内存，无需IPC
3. **配置统一**：所有配置在同一文件
4. **管理简单**：只需启动/停止一个进程
5. **Socket路径在项目目录**：`run/registry-center/internal.sock`

#### 2.4.4 文件结构

```
agent_registry/
├── internal/                     # 内部交互服务
│   ├── __init__.py
│   ├── registry_center_internal_service.py  # UDS服务端
│   │
│   ├── handlers/                 # 操作处理器
│   │   ├── __init__.py
│   │   ├── base_handler.py       # Handler基类
│   │   ├── approval_handler.py   # 审核处理器
│   │   ├── get_agent_handler.py  # 单Agent查询处理器
│   │   ├── list_agents_handler.py # 全量Agent查询处理器
│   │   └── set_tags_handler.py   # 设置标签处理器（全量覆盖）
│   │
│   └── protocols/                # 协议定义
│       ├── __init__.py
│       ├── request.py            # 请求协议
│       ├── response.py           # 响应协议
│       └── actions.py            # action定义
│
├── cli/                          # CLI工具
│   ├── __init__.py
│   ├── __main__.py               # CLI入口
│   ├── core.py                   # CLI核心引擎
│   ├── base.py                   # 命令基类
│   ├── registry.py               # 命令注册
│   ├── client.py                 # HTTP客户端
│   ├── uds_client.py             # UDS客户端（内部服务）
│   └── commands/                 # 命令实现
│       ├── __init__.py
│       ├── agent.py              # Agent管理命令
│       ├── status.py             # 状态查询命令
│       └── approval.py           # 审核命令
```

**服务端代码结构：**

```python
class RegistryCenterService:
    """注册中心内部交互UDS服务（统一入口）"""
    
    SOCKET_PATH = "run/registry-center/internal.sock"
    
    def __init__(self):
        self.socket_path = self.SOCKET_PATH
        self.registry = get_registry()
        self.config = get_conf()
        self.dispatcher = RequestDispatcher()
    
    def start(self):
        """启动UDS服务"""
        # 创建UDS socket
        server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        
        # 删除旧socket文件
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        
        # 绑定socket
        server_socket.bind(self.socket_path)
        
        # 设置权限：只有特定组可以访问
        os.chmod(self.socket_path, 0o660)  # rw-rw----
        os.chown(self.socket_path, 0, 1000)  # root:registry_group
        
        # 监听连接
        server_socket.listen(5)
        
        # 处理请求
        while True:
            conn, _ = server_socket.accept()
            self._handle_request(conn)
    
    def _handle_request(self, conn):
        """处理请求并分发到对应Handler"""
        try:
            # 接收请求
            data = conn.recv(4096)
            request = json.loads(data)
            
            # 获取action
            action = request.get('action', '')
            params = request.get('params', {})
            
            # 分发到对应Handler
            handler = self.dispatcher.get_handler(action)
            if not handler:
                response = {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
            else:
                response = handler.handle(params, self.registry, self.config)
            
            conn.send(json.dumps(response).encode())
        finally:
            conn.close()
```

#### 2.4.5 客户端设计

**客户端代码：**

```python
class RegistryClient:
    """注册中心内部交互客户端"""
    
    SOCKET_PATH = "run/registry-center/internal.sock"
    
    def __init__(self):
        self.socket_path = self.SOCKET_PATH
    
    def _send_request(self, request: dict) -> dict:
        """发送请求到UDS服务"""
        client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        
        try:
            client_socket.connect(self.socket_path)
        except PermissionError:
            return {
                "success": False,
                "error": "Permission denied",
                "message": "You don't have permission to access registry center"
            }
        
        # 发送请求
        client_socket.send(json.dumps(request).encode())
        
        # 接收响应
        response = client_socket.recv(4096)
        result = json.loads(response.decode())
        
        client_socket.close()
        return result
    
    def approval_agent(self, agent_name: str, organization: str) -> dict:
        """审核Agent"""
        request = {
            "action": "approval",
            "params": {
                "agent_name": agent_name,
                "organization": organization
            }
        }
        return self._send_request(request)
    
    def get_config(self, config_key: str) -> dict:
        """获取配置"""
        request = {
            "action": "config",
            "params": {
                "config_key": config_key
            }
        }
        return self._send_request(request)
    
    def get_stats(self, stat_type: str) -> dict:
        """获取统计信息"""
        request = {
            "action": "stats",
            "params": {
                "type": stat_type
            }
        }
        return self._send_request(request)
    
    def query_agent(self, agent_name: str, organization: str) -> dict:
        """查询Agent"""
        request = {
            "action": "query",
            "params": {
                "agent_name": agent_name,
                "organization": organization
            }
        }
        return self._send_request(request)
```

#### 2.4.6 UDS访问控制

**权限设计：**

```bash
# Socket文件权限
ls -la run/registry-center/internal.sock

# 输出：
srw-rw---- 1 root registry_group 0 Jan 1 12:00 run/registry-center/internal.sock
```

**权限说明：**
- 所有者：root（可读写）
- 组：registry_group（可读写）
- 其他用户：无权限

**访问控制逻辑：**
1. 只有registry_group组成员可以调用内部交互接口
2. 普通用户无法访问UDS socket
3. 通过文件权限自动实现访问控制

#### 2.4.7 审核接口流程图

```
┌─────────────────────────────────┐
│  客户端调用内部交互接口           │
│  client.approval_agent("TestAgent", "TestOrg") │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  连接UDS Socket                  │
│  run/registry-center/internal.sock │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  检查文件权限                     │
│  (registry_group组成员?)          │
└──────────┬──────────────────────┘
           │
      ┌────┴────┐
      │         │
    有权限    无权限
      │         │
      │         ▼
      │  ┌──────────────────────┐
      │  │ 返回错误：Permission │
      │  │ denied               │
      │  └──────────────────────┘
      │
      ▼
┌─────────────────────────────────┐
│  发送请求                         │
│  {"action":"approval", "params":{...}} │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  UDS服务端接收请求                │
│  RequestDispatcher分发           │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  ApprovalHandler处理请求           │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  检查审核开关                     │
│  agent_approval_enabled=?       │
└──────────┬──────────────────────┘
           │
      ┌────┴────┐
      │         │
    true      false
      │         │
      │         ▼
      │  ┌──────────────────────┐
      │  │ 返回错误：Approval   │
      │  │ function is disabled │
      │  └──────────────────────┘
      │
      ▼
┌─────────────────────────────────┐
│  查找Agent                       │
│  get_by_key(agent_name, org)     │
└──────────┬──────────────────────┘
           │
      ┌────┴────┐
      │         │
    找到      未找到
      │         │
      │         ▼
      │  ┌──────────────────────┐
      │  │ 返回错误：Agent not │
      │  │ found                │
      │  └──────────────────────┘
      │
      ▼
┌─────────────────────────────────┐
│  检查Agent状态                   │
│  status == "registered"?         │
└──────────┬──────────────────────┘
           │
      ┌────┴────┐
      │         │
  registered  published
      │         │
      │         ▼
      │  ┌──────────────────────┐
      │  │ 返回错误：Already    │
      │  │ published            │
      │  └──────────────────────┘
      │
      ▼
┌─────────────────────────────────┐
│  更新Agent状态                   │
│  status = "published"            │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  保存Agent                       │
│  registry.update(...)            │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  返回成功响应                     │
│  {"success":true, ...}           │
└─────────────────────────────────┘
```

## 3. 实现方案

### 3.1 文件修改清单

#### 3.1.1 新增文件

```
agent_registry/
├── internal/                     # 内部交互服务
│   ├── __init__.py
│   ├── registry_center_internal_service.py  # UDS服务端
│   │
│   ├── handlers/                 # 操作处理器
│   │   ├── __init__.py
│   │   ├── base_handler.py       # Handler基类
│   │   ├── approval_handler.py   # 审核处理器
│   │   ├── get_agent_handler.py  # 单Agent查询处理器
│   │   ├── list_agents_handler.py # 全量Agent查询处理器
│   │   └── set_tags_handler.py   # 设置标签处理器（全量覆盖）
│   │
│   └── protocols/                # 协议定义
│       ├── __init__.py
│       ├── request.py            # 请求协议
│       ├── response.py           # 响应协议
│       └── actions.py            # action定义
│
├── cli/                          # CLI工具
│   ├── uds_client.py             # UDS客户端（内部服务）
```

#### 3.1.2 修改文件

```
agent_registry/
├── init.py                   # 新增审核开关配置提示
├── server.py                 # 修改注册接口和查询接口逻辑
├── core.py                   # 新增状态管理、标签管理方法
├── start.py                  # 启动UDS内部交互服务线程
├── persistence/
│   ├── file_storage.py       # 新增双文件存储处理
│   ├── postgresql_storage.py # 新增status、tag字段处理
│   └── sql_queries.py        # 新增status、tag字段SQL
├── model/
│   └── validated_agentcard.py  # 新增status字段验证
├── internal/
│   ├── handlers/             # 新增get_agent、list_agents、add_tags处理器
│   └── protocols/            # 新增action定义
├── cli/
│   ├── uds_client.py         # 新增UDS客户端方法
│   └── commands/agent.py     # 新增CLI命令
```

### 3.2 代码实现要点

#### 3.2.1 init.py修改

在`init_command()`方法中新增审核开关配置：

```python
# 新增代码片段
default_approval_enabled = self.existing_config.get('agent_approval_enabled', 'false')
current_approval_enabled = default_approval_enabled

# 提示用户输入
approval_input = input(
    f"是否开启审核功能 agent_approval_enabled (y/n, 默认: {default_approval_enabled}): "
).strip().lower()

# 处理用户输入
if approval_input == 'n':
    if current_approval_enabled == 'true':
        # 检查是否存在"已注册"状态的Agent
        registered_agents = registry.get_agents_by_status('registered')
        if registered_agents:
            print("❌ 错误：审核功能已开启，不能直接关闭！")
            print(f"   原因：存在 {len(registered_agents)} 个'已注册'状态的Agent")
            print("   建议：")
            print("   1. 先通过审核接口发布这些Agent")
            print("   2. 或通过注销接口删除这些Agent")
            print("   3. 处理完毕后再关闭审核功能")
            sys.exit(1)
        else:
            # 不存在已注册Agent，允许关闭
            config['agent_approval_enabled'] = 'false'
            print("✓ 审核功能已关闭")
elif approval_input == 'y':
    config['agent_approval_enabled'] = 'true'
    print("✓ 审核功能已开启")
else:
    config['agent_approval_enabled'] = default_approval_enabled
```

#### 3.2.2 server.py修改

修改`register_agent`接口，添加状态设置逻辑：

```python
@app.post("/rest/a2a-t/v1/agents/register")
async def register_agent(agent: ValidatedAgentCard, request: Request):
    # 验签逻辑（如果开启）...
    
    # 读取审核开关配置
    approval_enabled = config.get('agent_approval_enabled', 'false')
    
    # 设置Agent初始状态
    if approval_enabled == 'true':
        agent.status = 'registered'
        status_message = "Agent registered, waiting for approval"
    else:
        agent.status = 'published'
        status_message = "Agent registered and published"
    
    # 注册Agent
    result = await _perform_registration(agent, registry, client_ip, details)
    
    # 返回响应
    return JSONResponse(
        content={
            "success": result,
            "status": agent.status,
            "message": status_message
        },
        status_code=status.HTTP_201_CREATED
    )
```

修改查询接口，只返回已发布状态的Agent（响应体不包含status字段）：

```python
@app.get("/rest/a2a-t/v1/agents/{name}")
async def get_agent(name: str, organization: str):
    agent = registry.find_by_key(name, organization)
    
    # 只返回已发布状态的Agent
    if agent and agent.status != 'published':
        raise HTTPException(status_code=404, detail="Agent not found or not published")
    
    # 返回Agent数据，不包含status字段（保持业界标准）
    return MessageToDict(agent, preserving_proto_field_name=True)

@app.get("/rest/a2a-t/v1/agents/query")
async def list_agents(name: Optional[str] = None, organization: Optional[str] = None):
    agents = registry.find_all()
    
    # 过滤条件
    if name:
        agents = [a for a in agents if a.name == name]
    if organization:
        agents = [a for a in agents if a.provider.organization == organization]
    
    # 只返回已发布状态的Agent
    agents = [a for a in agents if a.status == 'published']
    
    # 返回Agent数据列表，不包含status字段（保持业界标准）
    return [MessageToDict(a, preserving_proto_field_name=True) for a in agents]
```

#### 3.2.3 core.py修改

新增状态管理方法：

```python
def update_status(self, name: str, organization: str, new_status: str) -> bool:
    """
    更新Agent状态
    
    Args:
        name: Agent名称
        organization: 组织名称
        new_status: 新状态 (registered/published)
    
    Returns:
        bool: 是否成功更新
    """
    key = self._make_key(name, organization)
    agent = self._agents.get(key)
    
    if not agent:
        logger.warning(f"Agent not found: {name} ({organization})")
        return False
    
    # 更新状态
    agent.status = new_status
    self._agents[key] = agent
    self._save()
    
    logger.info(f"Agent status updated: {name} -> {new_status}")
    return True

def get_agents_by_status(self, status: str) -> List[AgentCard]:
    """
    根据状态查询Agent
    
    Args:
        status: Agent状态
    
    Returns:
        List[AgentCard]: Agent列表
    """
    return [agent for agent in self._agents.values() if agent.status == status]
```

#### 3.2.4 validated_agentcard.py修改

新增status字段验证函数（用于验证agentregistry.json中的状态值）：

```python
def validate_agent_card(agent: AgentCard):
    """验证AgentCard数据（不含status字段，保持业界标准）"""
    validate_name(agent.name)
    validate_description(agent.description)
    validate_version(agent.version)
    validate_default_input_modes(agent.default_input_modes)
    validate_default_output_modes(agent.default_output_modes)
    validate_skills(agent.skills)
    validate_capabilities(agent.capabilities)
    validate_provider(agent.provider)
    validate_supported_interfaces(agent.supported_interfaces)


def validate_status(status: str):
    """验证status字段值（用于agentregistry.json）"""
    if status not in ['registered', 'published']:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Agent status must be either "registered" or "published"')
```

**说明：**
- AgentCard本身不包含status字段，保持业界标准数据结构
- status信息存储在独立的agentregistry.json文件中
- `validate_status`函数用于验证agentregistry.json中的状态值
- `validate_agent_card`函数不验证status（AgentCard不包含此字段）

#### 3.2.5 core.py修改

新增register_with_status方法和双文件加载/保存逻辑：

```python
def register_with_status(self, agent: AgentCard, initial_status: str = 'published') -> bool:
    """注册Agent并设置初始状态"""
    with self._lock:
        if self.persistence_mode == 'postgresql':
            agent.status = initial_status
            return self.storage.create(agent)
        else:
            key = self._make_key(agent.name, agent.provider.organization)
            self._agents[key] = agent
            self._status_map[key] = initial_status
            self._save()
            return True

def _save(self) -> None:
    """双文件保存"""
    self._save_agents()      # agentcard.json（不含status）
    self._save_registry()    # agentregistry.json（状态映射）

def _load(self) -> None:
    """双文件加载"""
    self._load_agents()      # 加载agentcard.json
    self._load_registry()    # 加载agentregistry.json并关联状态
```

**关键点：**
- `_status_map`: Dict[(name, org), status] 存储状态映射
- AgentCard存储不含status字段
- 状态通过_status_map关联

#### 3.2.5 start.py修改

启动UDS内部交互服务：

```python
def main():
    server_config = get_conf()
    
    # 启动UDS内部交互服务（作为子线程运行）
    from agent_registry.internal.registry_service import RegistryCenterService
    
    # 创建内部交互服务线程
    internal_service = RegistryCenterService()
    internal_thread = threading.Thread(target=internal_service.start, daemon=True)
    internal_thread.start()
    
    logger.info("Internal service started on UDS socket: run/registry-center/internal.sock")
    
    # 启动HTTP服务
    ...
```

### 3.3 配置变更示例

#### 3.3.1 审核功能开启后的配置

```ini
# etc/conf/server.conf
agent_approval_enabled=true
```

**影响：**
- 新注册的Agent状态为`registered`
- 需要调用审核接口才能变为`published`
- UDS内部交互服务启动并监听，可通过`approval` action审核Agent

#### 3.3.2 审核功能关闭时的配置

```ini
# etc/conf/server.conf
agent_approval_enabled=false
```

**影响：**
- 新注册的Agent直接为`published`状态
- UDS内部交互服务仍然启动
- 调用`approval` action会报错（审核功能关闭）

### 3.4 数据持久化

系统支持两种持久化存储模式，由`etc/conf/persistence.conf`中的`persistence.mode`配置控制：

```ini
# etc/conf/persistence.conf
# 持久化模式：file / postgresql / sqlite / gauss
persistence.mode=postgresql
```

#### 3.4.1 文件存储模式（persistence.mode=file）

**双文件方案说明：**

为保持业界AgentCard数据结构标准，防止后续业界更新status字段后与项目本身的status字段冲突，采用双文件存储方案：

**存储文件1：`data/agentcard.json`** - 存放不带status字段的AgentCard数据（符合业界标准）

```json
[
  {
    "name": "TestAgent",
    "provider": {
      "organization": "TestOrg",
      "url": "https://test.org"
    },
    "description": "Test Description",
    "url": "https://agent.test",
    "version": "1.0.0",
    "skills": [...],
    ...
    // 不包含status字段，保持业界标准
  },
  {
    "name": "AnotherAgent",
    "provider": {
      "organization": "AnotherOrg",
      "url": "https://another.org"
    },
    ...
    // 不包含status字段
  }
]
```

**存储文件2：`data/agentregistry.json`** - 存放Agent元数据（status、tag等）

```json
[
  {
    "organization": "TestOrg",
    "agent_name": "TestAgent",
    "status": "registered",
    "tag": ["label1", "label2"]
  },
  {
    "organization": "AnotherOrg",
    "agent_name": "AnotherAgent",
    "status": "published",
    "tag": []
  }
]
```

**文件用途说明：**
- `agentcard.json`：存储完整的AgentCard数据，不包含status和tag字段，保持业界标准格式
- `agentregistry.json`：存储Agent的组织名、Agent名、状态和标签等元数据
- 两个文件通过`(organization, agent_name)`组合进行关联

**FileStorage修改要点：**

需要修改`agent_registry/persistence/file_storage.py`：

1. 新增`agentregistry.json`文件的处理逻辑
2. `_save()`方法：分别保存AgentCard数据（不含status）到agentcard.json，状态信息到agentregistry.json
3. `_load()`方法：加载时合并两个文件的数据，恢复Agent的完整状态信息
4. 注册Agent时：同时更新两个文件
5. 审核Agent时：只更新agentregistry.json中的status字段

**实现示例：**

```python
class FileStorage(StorageBackend):
    def __init__(self, file_path: str, registry_file: str = "data/agentregistry.json"):
        self.file_path = file_path          # agentcard.json
        self.registry_file = registry_file  # agentregistry.json
        self._agents: Dict[tuple, AgentCard] = {}
        self._status_map: Dict[tuple, str] = {}  # {(name, org): status}
        self._load()
    
    def create(self, agent: AgentCard) -> bool:
        key = (agent.name.strip(), agent.provider.organization.strip())
        self._agents[key] = agent
        self._status_map[key] = agent.status
        self._save()
        return True
    
    def _save(self) -> None:
        # 保存agentcard.json（不含status）
        agent_cards = []
        for agent in self._agents.values():
            agent_dict = MessageToDict(agent, preserving_proto_field_name=True)
            agent_dict.pop('status', None)  # 移除status字段
            agent_cards.append(agent_dict)
        
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(agent_cards, f, ensure_ascii=False, indent=2)
        
        # 保存agentregistry.json
        registry_data = []
        for key, status in self._status_map.items():
            registry_data.append({
                "organization": key[1],
                "agent_name": key[0],
                "status": status
            })
        
        with open(self.registry_file, 'w', encoding='utf-8') as f:
            json.dump(registry_data, f, ensure_ascii=False, indent=2)
    
    def _load(self) -> None:
        # 加载agentcard.json
        if os.path.exists(self.file_path):
            with open(self.file_path, 'r', encoding='utf-8') as f:
                agent_cards = json.load(f)
            for item in agent_cards:
                agent = AgentCard(**item)
                key = (agent.name.strip(), agent.provider.organization.strip())
                self._agents[key] = agent
        
        # 加载agentregistry.json并合并状态
        if os.path.exists(self.registry_file):
            with open(self.registry_file, 'r', encoding='utf-8') as f:
                registry_data = json.load(f)
            for item in registry_data:
                key = (item['agent_name'], item['organization'])
                self._status_map[key] = item['status']
                # 将状态合并到Agent对象
                if key in self._agents:
                    self._agents[key].status = item['status']
        else:
            # 兼容处理：如果没有agentregistry.json，默认所有Agent为published
            for key in self._agents.keys():
                self._status_map[key] = 'published'
```

#### 3.4.2 数据库存储模式（persistence.mode=postgresql/sqlite/gauss）

**数据库表结构变更：**

需要修改`agent_registry/persistence/sql_queries.py`，在agent_card表中新增status字段：

```sql
CREATE TABLE IF NOT EXISTS agent_card (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    organization    VARCHAR(100) NOT NULL,
    description     VARCHAR(1000),
    url             VARCHAR(1024),
    version         VARCHAR(50),
    status          VARCHAR(20) DEFAULT 'published',  -- 新增字段
    provider_json   JSONB        NOT NULL,
    capabilities_json JSONB,
    skills_json     JSONB,
    default_input_modes  JSONB,
    default_output_modes JSONB,
    agent_card_json JSONB        NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, organization)
)
```

**新增索引：**

```sql
CREATE INDEX IF NOT EXISTS idx_agent_status ON agent_card(status)
```

**PostgreSQLStorage修改要点：**

需要修改`agent_registry/persistence/postgresql_storage.py`：

1. `_get_agent_fields()`方法：新增status字段
2. `create()`方法：插入时包含status字段
3. `update()`方法：更新时支持status字段变更
4. 新增`find_by_status()`方法：按状态查询Agent
5. 新增`count_by_status()`方法：按状态统计Agent数量

## 4. 测试方案

### 4.1 单元测试

#### 4.1.1 审核开关配置测试

```python
def test_approval_config():
    """测试审核开关配置"""
    
    # 测试1：默认配置
    init_cmd = InitCommand()
    assert init_cmd.existing_config.get('agent_approval_enabled') == 'false'
    
    # 测试2：开启审核
    config = {'agent_approval_enabled': 'true'}
    init_cmd.save_config_to_file(config)
    assert get_conf()['agent_approval_enabled'] == 'true'
    
    # 测试3：尝试关闭已开启的审核（存在已注册Agent时应报错）
    # 模拟存在已注册Agent的场景
    registry.register(AgentCard(name="Test", status='registered'))
    # 模拟用户输入'n'
    # 预期：报错，提示先发布已注册Agent
    
    # 测试4：尝试关闭已开启的审核（不存在已注册Agent时应成功）
    registry.update_status("Test", "Org", 'published')
    # 模拟用户输入'n'
    # 预期：成功关闭
```

#### 4.1.2 Agent状态测试

```python
def test_agent_status():
    """测试Agent状态管理"""
    
    registry = RegistryCore()
    
    # 测试1：审核功能开启时注册
    agent = AgentCard(name="Test", provider=Provider(...), status='registered')
    registry.register(agent)
    assert registry.get_by_key("Test", "Org").status == 'registered'
    
    # 测试2：审核通过
    registry.update_status("Test", "Org", 'published')
    assert registry.get_by_key("Test", "Org").status == 'published'
    
    # 测试3：审核功能关闭时注册
    agent2 = AgentCard(name="Test2", provider=Provider(...), status='published')
    registry.register(agent2)
    assert registry.get_by_key("Test2", "Org").status == 'published'
```

#### 4.1.3 查询接口测试

```python
def test_query_interface():
    """测试查询接口只返回已发布Agent"""
    
    registry = RegistryCore()
    
    # 注册一个已发布Agent
    agent_published = AgentCard(name="PublishedAgent", status='published')
    registry.register(agent_published)
    
    # 注册一个已注册Agent
    agent_registered = AgentCard(name="RegisteredAgent", status='registered')
    registry.register(agent_registered)
    
    # 测试1：查询所有Agent，只返回已发布Agent
    result = list_agents()
    assert len(result) == 1
    assert result[0].name == "PublishedAgent"
    
    # 测试2：按名称查询已注册Agent，返回空
    result = get_agent("RegisteredAgent", "Org")
    assert result is None  # 或抛出404异常
    
    # 测试3：按名称查询已发布Agent，正常返回
    result = get_agent("PublishedAgent", "Org")
    assert result.status == 'published'
```

#### 4.1.4 UDS接口测试

```python
def test_approval_uds_interface():
    """测试UDS审核接口"""
    
    # 启动审核服务
    internal_service = RegistryCenterService()
    internal_thread = threading.Thread(target=internal_service.start, daemon=True)
    internal_thread.start()
    
    # 创建客户端
    client = RegistryClient()
    
    # 测试1：审核功能开启时调用
    result = client.approval_agent("TestAgent", "TestOrg")
    assert result['success'] == True
    assert result['agent']['status'] == 'published'
    
    # 测试2：审核功能关闭时调用（应报错）
    # 修改配置：agent_approval_enabled=false
    result = client.approval_agent("TestAgent", "TestOrg")
    assert result['success'] == False
    assert result['error'] == "Approval function is disabled"
```

### 4.2 成成测试

#### 4.2.1 完整流程测试

**测试场景：**

1. **审核功能开启场景**
   ```bash
   # 步骤1：配置审核功能开启
   python -m agent_registry.init
   # 输入：y
   
   # 步骤2：注册Agent
   curl -X POST http://localhost:5000/rest/a2a-t/v1/agents/register \
     -H "Content-Type: application/json" \
     -d '{"name":"TestAgent", ...}'
   
   # 预期响应：
   {"success":true, "status":"registered", "message":"Agent registered, waiting for approval"}
   
   # 步骤3：调用审核接口
   python -m agent_registry.cli approval -n TestAgent -o TestOrg
   
   # 预期响应：
   {"success":true, "status":"published", "message":"Agent approval successful"}
   
   # 步骤4：查询Agent
   curl http://localhost:5000/rest/a2a-t/v1/agents/query?name=TestAgent
   
   # 预期：status="published"，Agent可以被查询到
   ```

2. **审核功能关闭场景**
   ```bash
   # 步骤1：配置审核功能关闭（需确保不存在已注册Agent）
   python -m agent_registry.init
   # 输入：n
   
   # 步骤2：注册Agent
   curl -X POST http://localhost:5000/rest/a2a-t/v1/agents/register \
     -H "Content-Type: application/json" \
     -d '{"name":"TestAgent", ...}'
   
   # 预期响应：
   {"success":true, "status":"published", "message":"Agent registered and published"}
   
   # 步骤3：尝试调用审核接口（应报错）
   python -m agent_registry.cli approval -n TestAgent -o TestOrg
   
   # 预期响应：
   {"success":false, "error":"Approval function is disabled"}
   
   # 步骤4：查询Agent（已发布状态可被查询）
   curl http://localhost:5000/rest/a2a-t/v1/agents/query?name=TestAgent
   
   # 预期：Agent可以被查询到，status="published"
   ```

3. **审核功能从关闭到开启场景**
   ```bash
   # 步骤1：审核功能关闭时注册Agent1
   # 预期：status="published"
   
   # 步骤2：开启审核功能
   python -m agent_registry.init
   # 输入：y
   
   # 步骤3：注册Agent2
   # 预期：status="registered"
   
   # 步骤4：查询Agent1
   # 预期：status仍为"published"（保持原状），可被查询
   
   # 步骤5：查询Agent2
   # 预期：status为"registered"，不会被查询接口返回
   
   # 步骤6：审核Agent2
   # 预期：status变为"published"，可被查询
   ```

4. **审核功能从开启到关闭场景**
   ```bash
   # 步骤1：审核功能开启时注册Agent1
   # 预期：status="registered"
   
   # 步骤2：尝试关闭审核功能（存在已注册Agent）
   python -m agent_registry.init
   # 输入：n
   
   # 预期：报错，提示先发布已注册Agent
   
   # 步骤3：审核Agent1
   python -m agent_registry.cli approval -n Agent1 -o Org
   
   # 预期：status变为"published"
   
   # 步骤4：再次尝试关闭审核功能（不存在已注册Agent）
   python -m agent_registry.init
   # 输入：n
   
   # 预期：成功关闭审核功能
   ```

### 4.3 安全测试

#### 4.3.1 UDS权限测试

```bash
# 测试1：普通用户无法访问内部交互接口
python -m agent_registry.cli approval -n TestAgent -o TestOrg

# 预期：
Permission denied: You don't have permission to access registry center

# 测试2：registry_group组成员可以访问
sudo usermod -aG registry_group $USER
python -m agent_registry.cli approval -n TestAgent -o TestOrg

# 预期：成功调用审核接口
```

#### 4.3.2 配置安全测试

```bash
# 测试1：尝试关闭已开启的审核功能（存在已注册Agent）
python -m agent_registry.init
# 当前配置：agent_approval_enabled=true
# 存在已注册Agent
# 输入：n

# 预期：
错误：审核功能已开启，不能直接关闭！
原因：存在"已注册"状态的Agent

# 测试2：尝试关闭已开启的审核功能（不存在已注册Agent）
python -m agent_registry.init
# 当前配置：agent_approval_enabled=true
# 不存在已注册Agent（全部已发布）
# 输入：n

# 预期：成功关闭审核功能
```

## 5. 运维方案

### 5.1 配置管理

#### 5.1.1 查看当前配置

```bash
# 查看审核开关配置
cat etc/conf/server.conf | grep agent_approval_enabled

# 输出：
agent_approval_enabled=true
```

#### 5.1.2 修改配置

```bash
# 开启审核功能
python -m agent_registry.init
# 输入：y

# 关闭审核功能（需确保不存在已注册Agent）
python -m agent_registry.init
# 输入：n

# 注意：关闭审核功能前需先发布所有已注册状态的Agent
```

### 5.2 Agent状态查询

```bash
# 查询所有"已发布"状态的Agent（HTTP接口只返回已发布Agent）
curl http://localhost:5000/rest/a2a-t/v1/agents/query

# 查询Agent状态通过HTTP接口（仅返回published状态）
```

### 5.3 UDS接口使用

#### 5.3.1 CLI命令

```bash
# 查询全量Agent元数据
python -m agent_registry.cli
agent-registry> agent uds-list

# 查询单个Agent元数据
agent-registry> agent uds-get -n TestAgent -o TestOrg

# 审核Agent
agent-registry> agent approval -n TestAgent -o TestOrg

# 添加标签
agent-registry> agent add-tags -n TestAgent -o TestOrg --tags label1,label2
```

#### 5.3.2 UDS响应示例

**查询单个Agent：**
```json
{
  "success": true,
  "message": "Agent retrieved successfully",
  "data": {
    "agentcard": {
      "name": "TestAgent",
      "provider": {...},
      "description": "...",
      ...
    },
    "status": "published",
    "tag": ["label1", "label2"]
  }
}
```

**查询全量Agent：**
```json
{
  "success": true,
  "message": "Agents retrieved successfully",
  "data": {
    "agents": [
      {
        "agent_name": "TestAgent",
        "organization": "TestOrg",
        "status": "published",
        "tag": ["label1"],
        "created_at": "2026-01-01T10:00:00",
        "updated_at": "2026-01-02T15:30:00"
      },
      {
        "agent_name": "AnotherAgent",
        "organization": "AnotherOrg",
        "status": "registered",
        "tag": [],
        "created_at": "2026-01-03T08:00:00",
        "updated_at": "2026-01-03T08:00:00"
      }
    ],
    "count": 2
  }
}
```

### 5.5 批量审核

```python
# 批量审核所有"已注册"状态的Agent
from agent_registry.cli.uds_client import get_uds_client

client = get_uds_client()

# 获取所有"已注册"Agent
registered_agents = registry.get_agents_by_status('registered')

# 批量审核
for agent in registered_agents:
    result = client.approval_agent(agent.name, agent.provider.organization)
    print(f"{agent.name}: {result.get('message', 'approved')}")
```

### 5.6 监控和日志

#### 5.4.1 审核日志

```python
# 记录审核操作日志
await approval_handle.handle({
    "operation_name": OperationName.APPROVAL_AGENT,
    "level": LogLevel.MINOR,
    "result": OperationResult.SUCCESS,
    "object_name": OperatorObject.AGENT,
    "details": {
        "agent_name": "TestAgent",
        "organization": "TestOrg",
        "status": "registered -> published"
    },
    "user_name": "admin"
})
```

## 6. 总结

### 6.1 功能要点

1. **审核开关配置**
   - 通过`init.py`交互式配置
   - 配置写入`server.conf`文件
   - 配置项名称：`agent_approval_enabled`
   - 开启后可以关闭，但需检查是否存在已注册Agent
   - 存在已注册Agent时关闭需先发布这些Agent

2. **Agent状态管理**
   - 新增`status`字段：registered/published
   - 审核开启：注册后为registered，审核后为published
   - 审核关闭：注册后直接为published
   - HTTP查询接口只返回已发布状态的Agent

3. **UDS内部交互接口**
   - Socket路径：`run/registry-center/internal.sock`（项目目录）
   - 统一入口，通过action字段区分操作类型
   - 请求格式：`{"action": "...", "params": {...}}`
   - 支持approval、get_agent、list_agents、add_tags等操作
   - 文件权限实现访问控制（registry_group组）
   - 审核关闭时approval action报错
   - UDS查询返回(agent_name, organization, status, tag)

4. **Agent标签管理**
   - 新增`tag`字段（数组类型）
   - 通过UDS接口添加标签（追加、去重）
   - 文件模式：存储在agentregistry.json
   - 数据库模式：新增tag字段（JSONB类型）

5. **持久化存储**
   - 支持文件存储和数据库存储两种模式
   - 由`persistence.conf`中的`persistence.mode`配置控制
   - 文件存储采用双文件方案：agentcard.json（不含status/tag）+ agentregistry.json（元数据）
   - 双文件方案保持业界AgentCard数据标准，避免status/tag字段冲突
   - 数据库存储需新增status、tag字段

### 6.2 安全要点

1. **配置安全**
   - 关闭审核功能时需检查是否存在已注册Agent
   - 若存在已注册Agent，需先发布或删除这些Agent后再关闭
   - 防止配置不一致导致状态混乱

2. **访问控制**
   - UDS socket文件权限控制访问
   - 只有registry_group组成员可以访问内部交互服务

3. **状态一致性**
   - 配置变更时保持已存在Agent状态不变
   - 新Agent按新配置设置状态

### 6.3 扩展性

1. **状态扩展**
   - 可扩展更多状态（如：审核中、审核失败等）

2. **标签扩展**
   - 标签可扩展更多元数据字段
   - 支持标签搜索、分类等功能

3. **审核流程扩展**
   - 可增加多级审核
   - 可增加审核日志和审计

4. **接口扩展**
   - 可增加批量审核接口
   - 可增加审核历史查询接口
   - Handler模式易于添加新操作类型

5. **CLI扩展**
   - 可通过UDS接口扩展更多CLI命令
   - CLI与UDS统一入口，易于维护

该设计文档详细说明了注册中心内部交互服务的实现方案，包括审核开关配置、Agent状态管理、标签管理、统一UDS内部交互服务设计等，为后续实现提供了完整的设计蓝图。