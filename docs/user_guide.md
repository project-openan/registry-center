# 注册中心功能简介

注册中心是一个专注于 Agent 统一管理的服务，支持用户将来自不同厂商的 Agent 进行集中注册与管理，实现多源 Agent
的可控接入与维护。主要功能包括：

- **Agent 注册**：支持将不同厂商的 Agent 注册到中心，统一纳管。
- **条件查询**：根据指定条件查询符合条件的 Agent 列表。
- **信息修改**：支持按名称修改已注册 Agent 的配置或元信息。
- **注销 Agent**：按名称注销不再使用的 Agent。
- **语义检索**：根据自然语言语义检索相匹配的 Agent，提升查找灵活性。
- **唯一查找**：按 Agent 名称精确查找唯一的 Agent 实例。

通过这些功能，注册中心帮助用户高效整合、维护与发现各类 Agent，为上层编排与协同提供基础能力。

# 组件交互接口定义

## 1. Agent注册

### 1.1 接口名称

注册新的Agent

### 1.2 接口描述

向A2A服务注册一个新的Agent，提交Agent的完整配置信息。

**✅ 响应模型：** bool - 注册成功返回 true

### 1.3 请求信息

#### 1.3.1 请求方法

POST

#### 1.3.2 请求路径

/rest/a2a-t/v1/agents/register

#### 1.3.3 请求头（Headers）

| 参数名          | 类型     | 必填 | 说明                   |
|--------------|--------|----|----------------------|
| Content-Type | string | 是  | 必须为 application/json |

#### 1.3.4 请求参数（Body）

**📋 AgentCard 结构说明：** AgentCard 是 A2A 协议中定义的标准 Agent 信息卡片，包含 Agent 的基本信息、能力、技能、接口等完整描述。

### 1.4 字段校验规则

以下为所有请求字段的详细校验规则，不符合规则的请求将返回 422 Unprocessable Content 错误。

#### 1.4.1 Agent 基本信息字段

| 字段名         | 类型     | 必填 | 限制说明                                                                                       |
|-------------|--------|----|--------------------------------------------------------------------------------------------|
| name        | string | 是  | **校验规则：** 最大长度：100 字符；格式要求：仅允许字母、数字、下划线（_）和空格；正则表达式：`^[a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*$` |
| description | string | 是  | **校验规则：** 最大长度：1000 字符                                                                     |
| version     | string | 是  | **校验规则：** 最大长度：50 字符                                                                       |

#### 1.4.2 Provider（提供商信息）字段

| 字段名                   | 类型     | 必填 | 限制说明                                                            |
|-----------------------|--------|----|-----------------------------------------------------------------|
| provider.organization | string | 是  | **校验规则：** 不能为空，必须提供非空字符串；最大长度：100 字符；禁止包含危险字符（见下方危险字符列表）        |
| provider.url          | string | 否  | **校验规则：** 最大长度：1024 字符；必须为有效的 Web URL 格式；示例：https://example.com |

#### 1.4.3 Skills（技能列表）字段

| 字段名    | 类型               | 必填 | 限制说明                                               |
|--------|------------------|----|----------------------------------------------------|
| skills | list[AgentSkill] | 否  | **校验规则：** 最大数量：100 个技能；每个技能的 JSON 序列化后最大长度：4096 字符 |

#### 1.4.4 Capabilities（能力配置）字段

| 字段名                     | 类型                   | 必填 | 限制说明                                             |
|-------------------------|----------------------|----|--------------------------------------------------|
| capabilities.extensions | list[AgentExtension] | 否  | **校验规则：** 最大数量：10 个扩展；每个扩展的 JSON 序列化后最大长度：512 字符 |

#### 1.4.5 Supported Interfaces（支持接口列表）字段

| 字段名                  | 类型                   | 必填 | 限制说明                                                         |
|----------------------|----------------------|----|--------------------------------------------------------------|
| supported_interfaces | list[AgentInterface] | 否  | **校验规则：** 每个接口的 URL 最大长度：1024 字符；每个接口的 URL 必须为有效的 Web URL 格式 |

#### 1.4.6 Input/Output Modes（输入输出模式）字段

| 字段名                  | 类型        | 必填 | 限制说明                 |
|----------------------|-----------|----|----------------------|
| default_input_modes  | list[str] | 否  | **校验规则：** 最大数量：100 个 |
| default_output_modes | list[str] | 否  | **校验规则：** 最大数量：100 个 |

#### 1.4.7 危险字符列表

以下字符在 provider.organization 字段中被禁止使用：

| 字符/范围             | 说明               |
|-------------------|------------------|
| `[\x00-\x1F]`     | 控制字符（ASCII 0-31） |
| `\x7F`            | DEL 删除字符         |
| `[\x80-\x9F]`     | C1 控制字符          |
| `\u2028`          | 行分隔符             |
| `\u2029`          | 段落分隔符            |
| `\u202D`          | 从左到右覆盖           |
| `\u202E`          | 从右到左覆盖           |
| `\u200B`          | 零宽空格             |
| `\u200C`          | 零宽非连接符           |
| `\u200D`          | 零宽连接符            |
| `\uFEFF`          | 零宽无中断空格          |
| `[\u2066-\u2069]` | 方向性格式化字符         |

### 1.5 请求示例

#### 1.5.1 完整请求示例

```json
{
  "name": "TestAgent",
  "description": "这是一个TestAgent",
  "version": "1.0.0",
  "provider": {
    "organization": "AI Solutions Inc.",
    "url": "https://test.example.com"
  },
  "skills": [
    {
      "name": "Test1",
      "description": "Test1"
    },
    {
      "name": "Test2",
      "description": "Test2"
    }
  ],
  "capabilities": {
    "streaming": true,
    "push_notifications": false,
    "extensions": []
  },
  "default_input_modes": [
    "text",
    "json"
  ],
  "default_output_modes": [
    "text",
    "json"
  ],
  "supported_interfaces": [
    {
      "protocol_binding": "GPRC",
      "protocol_version": "1.0.0",
      "url": "http://127.0.0.1:5000/"
    },
    {
      "protocol_binding": "HTTP+JSON",
      "protocol_version": "1.0.0",
      "url": "http://127.0.0.1:5000/"
    }
  ]
}
```

### 1.6 响应信息

#### 1.6.1 成功响应

**状态码：** 201 Created

**响应类型：** boolean

true

#### 1.6.2 错误响应示例

**名称格式错误（422）**

```json
{
  "detail": "The name can contain only letters, digits, underscores (_), spaces."
}
```

**名称超长（422）**

```json
{
  "detail": "The agent name can contain a maximum of 100 characters."
}
```

**描述超长（422）**

```json
{
  "detail": "The agent description can contain a maximum of 1000 characters."
}
```

**Provider 组织名称为空（422）**

```json
{
  "detail": "Agent provider organization is required and cannot be empty."
}
```

**Provider URL 格式无效（422）**

```json
{
  "detail": "Provider URL must be a valid web URL."
}
```

**技能数量超限（422）**

```json
{
  "detail": "The agent can contain a maximum of 100 skills"
}
```

**扩展数量超限（422）**

```json
{
  "detail": "The number of supported protocol extensions of the agent can not exceed 10."
}
```

**输入模式数量超限（422）**

```json
{
  "detail": "The agent default_input_modes can contain a maximum of 100 params."
}
```

**URL 超长（422）**

```json
{
  "detail": "The agent url can contain a maximum of 1024 characters."
}
```

**组织名称包含危险字符（422）**

```json
{
  "detail": "Agent provider organization contains invalid or dangerous characters."
}
```

## 2. Agent查询

### 2.1 接口名称

查询符合条件的Agent

### 2.2 接口描述

根据Agent名称和组织机构进行**精确匹配查询**，支持多条件组合查询（AND逻辑）。所有查询参数均为可选，不提供任何参数时返回所有已注册的Agent。

### 2.3 请求信息

#### 2.3.1 请求方法

GET

#### 2.3.2 请求路径

/rest/a2a-t/v1/agents/query

#### 2.3.3 请求头（Headers）

| 参数名          | 类型     | 必填 | 说明                |
|--------------|--------|----|-------------------|
| Content-Type | string | 否  | 通常无需设置，响应格式为 JSON |

#### 2.3.4 请求参数（Query Parameters）

请求参数通过 URL 查询字符串传递，所有参数均为可选。

| 参数名          | 类型     | 必填 | 默认值 | 说明                           |
|--------------|--------|----|-----|------------------------------|
| name         | string | 否  | -   | Agent 名称，进行精确匹配查询。支持大小写敏感匹配。 |
| organization | string | 否  | -   | 组织机构名称，进行精确匹配查询。支持大小写敏感匹配。   |

**📌 查询说明：**

- 当同时提供 name 和 organization 参数时，返回同时满足两个条件的 Agent。
- 当仅提供其中一个参数时，返回满足该条件的所有 Agent。
- 当不提供任何参数时，返回系统中所有已注册的 Agent。
- 查询为**精确匹配**，不支持模糊搜索或通配符。

#### 2.3.5 请求示例

**示例2.1：查询所有Agent**
GET /rest/a2a-t/v1/agents/query HTTP/1.1
Host: your-domain.com

**示例2.2：按名称查询**
GET /rest/a2a-t/v1/agents/query?name=TestAgent HTTP/1.1
Host: your-domain.com

**示例2.3：按组织机构精确查询**
GET /rest/a2a-t/v1/agents/query?organization=HUAWEI HTTP/1.1
Host: your-domain.com

**示例2.4：组合条件查询（AND）**
GET /rest/a2a-t/v1/agents/query?name=TestAgent&organization=HUAWEI HTTP/1.1
Host: your-domain.com

### 2.4 响应信息

#### 2.4.1 响应模型

**响应类型：** List[AgentCard]（JSON数组）

每个 AgentCard 包含以下主要字段：

| 字段名                  | 类型     | 说明                        |
|----------------------|--------|---------------------------|
| name                 | string | Agent名称                   |
| description          | string | Agent描述                   |
| version              | string | 版本号                       |
| provider             | object | 提供商信息（包含organization和url） |
| skills               | array  | 技能列表                      |
| capabilities         | object | 能力配置                      |
| default_input_modes  | array  | 默认输入模式                    |
| default_output_modes | array  | 默认输出模式                    |
| supported_interfaces | array  | 支持的接口列表                   |

#### 2.4.2 成功响应示例（200 OK）

```json
[
  {
    "name": "TestAgent",
    "description": "这是一个TestAgent",
    "version": "1.0.0",
    "provider": {
      "organization": "AI Solutions Inc.",
      "url": "https://test.example.com"
    },
    "skills": [
      {
        "name": "Test1",
        "description": "Test1"
      },
      {
        "name": "Test2",
        "description": "Test2"
      }
    ],
    "capabilities": {
      "streaming": true,
      "push_notifications": false,
      "extensions": []
    },
    "default_input_modes": [
      "text",
      "json"
    ],
    "default_output_modes": [
      "text",
      "json"
    ],
    "supported_interfaces": [
      {
        "protocol_binding": "GPRC",
        "protocol_version": "1.0.0",
        "url": "http://127.0.0.1:5000/"
      },
      {
        "protocol_binding": "HTTP+JSON",
        "protocol_version": "1.0.0",
        "url": "http://127.0.0.1:5000/"
      }
    ]
  }
]
```

空结果（未找到匹配Agent）

```json
[]
```

### 2.5 状态码总结

| 状态码                       | 说明                     |
|---------------------------|------------------------|
| 200 OK                    | 请求成功，返回Agent列表（可能为空数组） |
| 429 Too Many Requests     | 请求过于频繁，触发限流            |
| 503 Service Unavailable   | 服务器繁忙，并发请求超过处理能力       |
| 500 Internal Server Error | 服务器内部错误                |

## 3. 全量更新Agent

### 3.1 接口名称

全量更新Agent（Full Update / Replace）

### 3.2 接口描述

完全替换一个已存在的Agent。该接口执行**全量更新**操作，使用请求体中的完整AgentCard数据替换现有Agent的全部信息。请求体中的名称和组织机构必须与路径参数和查询参数匹配。

**🔄 更新模式：** 全量替换（Full Replace）

**✅ 返回类型：** boolean - 更新成功返回 true，未找到Agent返回 false

**⚠️ 重要提示：** 该接口执行全量替换操作，请求体中未提供的字段将被清除。

### 3.3 请求信息

#### 3.3.1 请求方法

PUT

#### 3.3.2 请求路径

/rest/a2a-t/v1/update_agent/{name}

#### 3.3.3 路径参数（Path Parameters）

| 参数名  | 类型     | 必填 | 说明                                         |
|------|--------|----|--------------------------------------------|
| name | string | 是  | 待更新的Agent名称，作为路径参数传递。该值必须与请求体中的 name 字段匹配。 |

#### 3.3.4 查询参数（Query Parameters）

| 参数名          | 类型     | 必填 | 说明                                                    |
|--------------|--------|----|-------------------------------------------------------|
| organization | string | 是  | 待更新Agent的组织机构名称。该值必须与请求体中 provider.organization 字段匹配。 |

**📌 匹配要求：**

- 路径参数 name 必须与请求体中的 name 字段完全一致。
- 查询参数 organization 必须与请求体中的 provider.organization 字段完全一致。
- 如果匹配失败，Agent将不会被更新。

#### 3.3.5 请求头（Headers）

| 参数名          | 类型     | 必填 | 说明                   |
|--------------|--------|----|----------------------|
| Content-Type | string | 是  | 必须为 application/json |

#### 3.3.6 请求参数（Body）

必须提供完整的AgentCard对象，所有字段校验规则与注册接口一致。

#### 3.3.7 请求示例

PUT /rest/a2a-t/v1/update_agent/TestAgent?organization=HUAWEI HTTP/1.1
Host: your-domain.com
Content-Type: application/json

```json
{
  "name": "TestAgent",
  "description": "这是一个TestAgent",
  "version": "1.0.0",
  "provider": {
    "organization": "AI Solutions Inc.",
    "url": "https://test.example.com"
  },
  "skills": [
    {
      "name": "Test1",
      "description": "Test1"
    },
    {
      "name": "Test2",
      "description": "Test2"
    }
  ],
  "capabilities": {
    "streaming": true,
    "push_notifications": false,
    "extensions": []
  },
  "default_input_modes": [
    "text",
    "json"
  ],
  "default_output_modes": [
    "text",
    "json"
  ],
  "supported_interfaces": [
    {
      "protocol_binding": "GPRC",
      "protocol_version": "1.0.0",
      "url": "http://127.0.0.1:5000/"
    },
    {
      "protocol_binding": "HTTP+JSON",
      "protocol_version": "1.0.0",
      "url": "http://127.0.0.1:5000/"
    }
  ]
}
```

### 3.4 响应信息

#### 3.4.1 成功响应

状态码： 200 OK

响应类型： boolean

```json
true
```

#### 3.4.2 错误响应示例

Agent未找到（404 Not Found）

```json
{
  "detail": "Agent not found"
}
```

### 3.5 技术特性

#### 3.5.1 数据校验

请求体中的AgentCard会经过完整的校验流程，包括字段长度、格式、数量限制等，校验规则与注册接口一致。

#### 3.5.2 数量限制检查

更新前会检查客户端IP的Agent数量限制（_check_agent_limit），确保不超过允许的最大数量。

### 3.6 与注册接口的区别

| 特性    | 注册接口（POST）                     | 更新接口（PUT）                          |
|-------|--------------------------------|------------------------------------|
| 请求方法  | POST                           | PUT                                |
| 路径    | /rest/a2a-t/v1/agents/register | /rest/a2a-t/v1/update_agent/{name} |
| 路径参数  | 无                              | name（必填）                           |
| 查询参数  | 无                              | organization（必填）                   |
| 目标    | 创建新Agent                       | 替换已存在的Agent                        |
| 重复处理  | 返回409冲突                        | 替换现有数据                             |
| 成功状态码 | 201 Created                    | 200 OK                             |

### 3.7 状态码总结

| 状态码                       | 说明                     |
|---------------------------|------------------------|
| 200 OK                    | 更新成功，返回 true           |
| 400 Bad Request           | 请求参数错误，如名称/组织不匹配、校验失败等 |
| 404 Not Found             | 指定的Agent不存在            |
| 422 Unprocessable Content | 字段校验失败（长度、格式、数量超限等）    |
| 429 Too Many Requests     | 请求过于频繁，触发限流            |
| 500 Internal Server Error | 服务器内部错误                |
| 503 Service Unavailable   | 服务器繁忙，并发请求超过处理能力       |

## 4. 注销Agent

### 4.1 接口名称

注销Agent（Deregister Agent）

### 4.2 接口描述

从Agent注册中心中移除指定的Agent。该操作会彻底删除Agent的注册信息，删除后该Agent将无法被工作流调度使用。

**⚠️ 危险操作警告：** 此接口执行删除操作，删除后数据无法恢复。请谨慎使用，建议在删除前进行确认。

**🗑️ 操作类型：** 物理删除（Physical Delete）

**✅ 返回类型：** boolean - 删除成功返回 true，未找到Agent返回 false

### 4.3 请求信息

#### 4.3.1 请求方法

DELETE

#### 4.3.2 请求路径

/rest/a2a-t/v1/deregister_agent/{name}

#### 4.3.3 路径参数（Path Parameters）

| 参数名  | 类型     | 必填 | 说明                                    |
|------|--------|----|---------------------------------------|
| name | string | 是  | 待注销的Agent名称，作为路径参数传递。用于唯一标识要删除的Agent。 |

#### 4.3.4 查询参数（Query Parameters）

| 参数名          | 类型     | 必填 | 默认值 | 说明                                           |
|--------------|--------|----|-----|----------------------------------------------|
| organization | string | 是  | -   | 待注销Agent的组织机构名称，作为查询参数传递。与name共同唯一标识一个Agent。 |

**📌 标识说明：** Agent通过 name 和 organization 组合唯一标识。两个参数必须同时提供才能准确定位要删除的Agent。

#### 4.3.5 请求头（Headers）

| 参数名          | 类型     | 必填 | 说明     |
|--------------|--------|----|--------|
| Content-Type | string | 否  | 通常无需设置 |

#### 4.3.6 请求示例

DELETE /rest/a2a-t/v1/deregister_agent/TestAgent?organization=HUAWEI HTTP/1.1
Host: your-domain.com

### 4.4 响应信息

#### 4.4.1 成功响应

**状态码：** 200 OK

**响应类型：** boolean

```json
true
```

#### 4.4.2 错误响应示例

Agent未找到（404 Not Found）

```json
{
  "detail": "Agent not found"
}
```

服务器繁忙（503 Service Unavailable）

```json
{
  "detail": "Server is busy"
}
```

服务器内部错误（500 Internal Server Error）

```json
{
  "detail": "Internal server error"
}
```

限流限制（429 Too Many Requests）

```json
{
  "detail": "Rate limit exceeded"
}
```

### 4.5 状态码总结

| 状态码                       | 说明               |
|---------------------------|------------------|
| 200 OK                    | 注销成功，返回 true     |
| 404 Not Found             | 指定的Agent不存在      |
| 429 Too Many Requests     | 请求过于频繁，触发限流      |
| 500 Internal Server Error | 服务器内部错误          |
| 503 Service Unavailable   | 服务器繁忙，并发请求超过处理能力 |

## 5. 基于任务语义检索Agent

### 5.1 接口名称

基于任务语义检索Agent

### 5.2 接口描述

使用大语言模型（LLM）根据自然语言任务描述，语义检索与之相关的Agent。该接口能够理解任务的语义意图，返回与任务最匹配的Agent列表，按相关性排序。

**💡 功能特点：**

- 支持自然语言任务描述，无需精确关键词匹配
- 基于语义理解，能够识别同义词和相关概念
- 返回结果按与任务的相关性降序排列
- 支持限制返回结果数量

### 5.3 请求信息

#### 5.3.1 请求方法

GET

#### 5.3.2 请求路径

/rest/a2a-t/v1/agents/retrieve

#### 5.3.3 请求头（Headers）

| 参数名          | 类型     | 必填 | 说明                |
|--------------|--------|----|-------------------|
| Content-Type | string | 否  | 通常无需设置，响应格式为 JSON |

#### 5.3.4 请求参数（Query Parameters）

请求参数通过 URL 查询字符串传递。

| 参数名   | 类型      | 必填 | 默认值 | 说明                                                     |
|-------|---------|----|-----|--------------------------------------------------------|
| task  | string  | 是  | -   | 自然语言任务描述，用于语义检索相关Agent。例如："需要处理数据清洗和分析"、"需要部署机器学习模型"等。 |
| top_n | integer | 否  | 10  | 返回最相关的前 N 个Agent。                                      |

**📌 参数说明：**

- task 为必填参数，应提供清晰、完整的任务描述以获得最佳检索效果。
- top_n 参数限制返回结果数量。

#### 5.3.5 请求示例

**示例5.1：基本检索**
GET /rest/a2a-t/v1/agents/retrieve?task=Test HTTP/1.1
Host: your-domain.com

**示例5.2：指定返回数量**
GET /rest/a2a-t/v1/agents/retrieve?task=Test&top_n=5 HTTP/1.1
Host: your-domain.com

### 5.4 响应信息

#### 5.4.1 响应模型

**响应类型：** List[AgentCard]（JSON数组）

返回与任务语义相关的Agent列表。每个 AgentCard 包含以下主要字段：

| 字段名                  | 类型     | 说明                          |
|----------------------|--------|-----------------------------|
| name                 | string | Agent名称                     |
| description          | string | Agent描述，用于语义匹配              |
| version              | string | 版本号                         |
| provider             | object | 提供商信息（包含organization和url）   |
| skills               | array  | 技能列表，每个技能包含name和description |
| capabilities         | object | 能力配置                        |
| default_input_modes  | array  | 默认输入模式                      |
| default_output_modes | array  | 默认输出模式                      |
| supported_interfaces | array  | 支持的接口列表                     |

#### 5.4.2 成功响应示例（200 OK）

**检索结果示例：**

```json
[
  {
    "name": "TestAgent",
    "description": "这是一个TestAgent",
    "version": "1.0.0",
    "provider": {
      "organization": "AI Solutions Inc.",
      "url": "https://test.example.com"
    },
    "skills": [
      {
        "name": "Test1",
        "description": "Test1"
      },
      {
        "name": "Test2",
        "description": "Test2"
      }
    ],
    "capabilities": {
      "streaming": true,
      "push_notifications": false,
      "extensions": []
    },
    "default_input_modes": [
      "text",
      "json"
    ],
    "default_output_modes": [
      "text",
      "json"
    ],
    "supported_interfaces": [
      {
        "protocol_binding": "GPRC",
        "protocol_version": "1.0.0",
        "url": "http://127.0.0.1:5000/"
      },
      {
        "protocol_binding": "HTTP+JSON",
        "protocol_version": "1.0.0",
        "url": "http://127.0.0.1:5000/"
      }
    ]
  }
]
```
空结果示例（未找到相关Agent）：
```json
[]
```
#### 5.4.3 错误响应示例
服务器繁忙（503 Service Unavailable）
```json
{
  "detail": "Server is busy"
}
```
服务器内部错误（500 Internal Server Error）
```json
{
  "detail": "Internal server error"
}
```
限流限制（429 Too Many Requests）
```json
{
  "detail": "Rate limit exceeded"
}
```
### 5.5 状态码总结
| 状态码                       | 说明               |
|---------------------------|------------------|
| 200 OK                    | 注销成功，返回 true     |
| 429 Too Many Requests     | 请求过于频繁，触发限流      |
| 500 Internal Server Error | 服务器内部错误          |
| 503 Service Unavailable   | 服务器繁忙，并发请求超过处理能力 |

## 6. 获取单个Agent详情

### 6.1 接口名称

根据名称和组织机构获取Agent详情

### 6.2 接口描述

根据Agent名称和组织机构的唯一组合，精确查询并返回单个Agent的完整详细信息。该接口用于获取特定Agent的配置、技能、能力等完整信息。

### 6.3 请求信息

#### 6.3.1 请求方法

GET

#### 6.3.2 请求路径

/rest/a2a-t/v1/agents/{name}

#### 6.3.3 路径参数（Path Parameters）

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 是 | Agent名称，作为路径参数传递。用于唯一标识Agent的组成部分之一。 |

#### 6.3.4 查询参数（Query Parameters）

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| organization | string | 是 | - | Agent所属的组织机构名称，作为查询参数传递。与name共同唯一标识一个Agent。 |

**📌 标识说明：** Agent通过 name（路径参数）和 organization（查询参数）组合唯一标识。两个参数必须同时提供才能准确定位要查询的Agent。

#### 6.3.5 请求头（Headers）

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| Content-Type | string | 否 | 通常无需设置，响应格式为 JSON |

#### 6.3.6 请求示例
GET /rest/a2a-t/v1/agents/TestAgent?organization=HUAWEI HTTP/1.1
Host: your-domain.com

### 6.4 响应信息

#### 6.4.1 响应模型

**响应类型：** AgentCard（JSON对象）

成功时返回完整的AgentCard对象，包含以下主要字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| name | string | Agent名称，最大100字符，仅字母/数字/下划线/空格 |
| description | string | Agent描述，最大1000字符 |
| version | string | 版本号，最大50字符 |
| provider | object | 提供商信息，包含organization和url |
| skills | array | 技能列表，最多100个技能 |
| capabilities | object | 能力配置，包含streaming、push_notifications、extensions |
| default_input_modes | array | 默认输入模式列表，如["text", "json"] |
| default_output_modes | array | 默认输出模式列表，如["text", "json"] |
| supported_interfaces | array | 支持的接口列表，包含url、protocol_binding和protocol_version |

#### 6.4.2 成功响应示例（200 OK）

**完整Agent信息响应：**

```json
{
    "name": "TestAgent",
    "description": "这是一个TestAgent",
    "version": "1.0.0",
    "provider": {
      "organization": "AI Solutions Inc.",
      "url": "https://test.example.com"
    },
    "skills": [
      {
        "name": "Test1",
        "description": "Test1"
      },
      {
        "name": "Test2",
        "description": "Test2"
      }
    ],
    "capabilities": {
      "streaming": true,
      "push_notifications": false,
      "extensions": []
    },
    "default_input_modes": [
      "text",
      "json"
    ],
    "default_output_modes": [
      "text",
      "json"
    ],
    "supported_interfaces": [
      {
        "protocol_binding": "GPRC",
        "protocol_version": "1.0.0",
        "url": "http://127.0.0.1:5000/"
      },
      {
        "protocol_binding": "HTTP+JSON",
        "protocol_version": "1.0.0",
        "url": "http://127.0.0.1:5000/"
      }
    ]
}
```
#### 6.4.3 错误响应示例
服务器繁忙（503 Service Unavailable）
```json
{
  "detail": "Server is busy"
}
```
服务器内部错误（500 Internal Server Error）
```json
{
  "detail": "Internal server error"
}
```
限流限制（429 Too Many Requests）
```json
{
  "detail": "Rate limit exceeded"
}
```
### 6.5 状态码总结
| 状态码                       | 说明               |
|---------------------------|------------------|
| 200 OK                    | 注销成功，返回 true     |
| 429 Too Many Requests     | 请求过于频繁，触发限流      |
| 500 Internal Server Error | 服务器内部错误          |
| 503 Service Unavailable   | 服务器繁忙，并发请求超过处理能力 |