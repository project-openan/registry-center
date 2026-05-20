# 注册中心API参考

## 简介

注册中心是一个专注于Agent统一管理的服务，主要开放提供以下接口:
- **注册AgentCard**：支持将不同厂商的Agent注册到中心，统一纳管。
- **查询AgentCard列表**：根据指定条件查询符合条件的AgentCard列表。
- **查询指定AgentCard**：按AgentCard名称和组织精确查找唯一的AgentCard实例。
- **更新指定AgentCard**：更新指定AgentCard的信息。
- **删除指定AgentCard**：删除不再使用的AgentCard。
- **按语义检索AgentCard**：根据自然语言语义检索相匹配的AgentCard。
- **公钥管理**：提供注册中心签名公钥的获取接口。

## 注册AgentCard

- 典型场景

    运营商或设备厂商需要注册新AgentCard时，可通过调用该接口在注册中心组件中创建新的AgentCard信息。

- 功能描述

    注册指定AgentCard信息到注册中心。

- 接口约束

  - 单次注册AgentCard信息报文大小不得超过1024K。
  - 单实例上该接口最大并发数为50。

- 调用方法

    POST

- URI

    */rest/v1/registry-center/agent-cards*

- 请求参数

  <a id="表1-body参数列表"></a>**表1** body参数列表

    | 参数名称       | 是否必选 | 类型              | 值域                                            | 默认值 | 描述 |
    |------------|------|-----------------|-----------------------------------------------|-----|------|
    | agentCards | 是    | array_reference | 当前只支持单个AgentCard的注册，详细请参见[表2](#表2-agentcard对象的参数列表)。 | -   | -    |

  <a id="表2-agentcard对象的参数列表"></a>**表2** AgentCard对象的参数列表
    
    | 参数名称                | 是否必选 | 类型              | 值域                                                                 | 默认值 | 描述         |
    |---------------------|------|-----------------|--------------------------------------------------------------------|-----|--------------|
    | name                | 是    | string          | 1~100个字符。满足正则表达式`^[a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*$`。            | -   | AgentCard名称。  |
    | description         | 是    | string          | 1~1000个字符。                                                         | -   | AgentCard描述。  |
    | version             | 是    | string          | 1~50个字符。                                                           | -   | AgentCard版本。  |
    | provider            | 是    | reference       | 详细请参见[表4](#表4-agentprovider对象的参数列表)。                                       | -   | 提供商信息。        |
    | skills              | 是    | array_reference | 最大数量：100 个技能；每个技能的 JSON 序列化后最大长度：4096 字符；详细请参见[表7](#表7-agentskill对象的参数列表)。 | -   | 技能列表。         |
    | capabilities        | 是    | reference       | 详细请参见[表5](#表5-agentcapabilities对象的参数列表)。                                   | -   | AgentCard能力项。 |
    | supportedInterfaces | 是    | array_reference | 1~3个列表，详细请参见[表3](#表3-agentinterface对象的参数列表)。                               | -   | 支持的协议。        |

  <a id="表3-agentinterface对象的参数列表"></a>**表3** AgentInterface对象的参数列表

    | 参数名称            | 是否必选 | 类型     | 值域                        | 默认值 | 描述                        |
    |:----------------|:-----|:-------|:----------------------------|:----|:----------------------------|
    | url             | 是    | string | 1~1024个字符；必须为有效的 Web URL 格式。 | -   | 接口的基础 URL 地址，用于发送 A2A 请求。    |
    | protocolBinding | 是    | string | -                           | -   | 协议绑定标识，表示该接口使用的传输协议。         |
    | protocolVersion | 是    | string | -                           | -   | A2A 协议版本号，表示该接口支持的 A2A 协议版本。 |

  <a id="表4-agentprovider对象的参数列表"></a>**表4** AgentProvider对象的参数列表

    | 参数名称         | 是否必选 | 类型     | 值域                     | 默认值 | 描述                                 |
    |:-------------|:-----|:-------|:-------------------------|:----|:-------------------------------------|
    | organization | 是    | string | 1~100个字符；不能为空。           | -   | Agent 提供商的组织名称，用于标识 Agent 的来源组织或开发团队。 |
    | url          | 否    | string | 1~1024个字符；必须为有效的 Web URL。 | -   | Agent 提供商的官方网站链接，便于用户了解组织背景或获取技术支持。   |

  <a id="表5-agentcapabilities对象的参数列表"></a>**表5** AgentCapabilities对象的参数列表

    | 参数名称              | 是否必选 | 类型              | 值域                                                                | 默认值   | 描述                                                                                 |
    |:------------------|:-----|:----------------|:--------------------------------------------------------------------|:------|:-------------------------------------------------------------------------------------|
    | streaming         | 否    | boolean         | true 或 false。                                                        | false | 是否支持流式传输。如果为 true，Agent 能够通过 Server-Sent Events (SSE) 实时返回响应内容；如果为 false，则仅支持一次性同步响应。 |
    | pushNotifications | 否    | boolean         | true 或 false。                                                        | false | 是否支持推送通知。如果为 true，Agent 能够主动向客户端发送任务状态更新和产物通知；需要配合 PushNotificationConfig 进行配置。       |
    | extendedAgentCard | 否    | boolean         | true 或 false。                                                        | false | 声明 Agent 是否支持经过认证后提供扩展版的 Agent Card。                                                  |
    | extensions        | 否    | array_reference | 最大数量：10 个扩展；每个扩展的 JSON 序列化后最大长度：512 字符；详细请参见[表6](#表6-agentextension对象的参数列表)。 | -     | 支持的扩展能力列表，用于声明 Agent 实现的 A2A 协议扩展特性。                                                  |

  <a id="表6-agentextension对象的参数列表"></a>**表6** AgentExtension对象的参数列表

    | 参数名称        | 是否必选 | 类型      | 值域         | 默认值   | 描述                                                   |
    |:------------|:-----|:--------|:-------------|:------|:-------------------------------------------------------|
    | uri         | 是    | string  | -            | -     | 扩展的唯一标识符，必须是版本化的 URI 格式，用于全局唯一标识该扩展。                    |
    | description | 否    | string  | -            | -     | 扩展功能的人类可读说明，描述 Agent 如何使用此扩展。                           |
    | required    | 否    | boolean | true 或 false。 | false | 表示客户端是否必须支持此扩展。如果为 true，客户端必须理解并激活该扩展，否则 Agent 将拒绝处理请求。 |
    | params      | 否    | object  | -            | -     | 扩展的特定配置参数或发现参数，用于传递扩展初始化所需的额外信息。                        |

  <a id="表7-agentskill对象的参数列表"></a>**表7** AgentSkill对象的参数列表

    | 参数名称        | 是否必选 | 类型              | 值域 | 默认值 | 描述                           |
    |:------------|:-----|:----------------|:-----|:----|:-------------------------------|
    | id          | 是    | string          | -    | -   | 技能的唯一标识符，用于在 AgentCard 中区分不同技能。 |
    | name        | 是    | string          | -    | -   | 技能的人类可读名称，展示给最终用户的技能标题。         |
    | description | 是    | string          | -    | -   | 技能的详细功能说明，帮助客户理解该技能的具体作用和适用场景。  |
    | tags        | 否    | array of string | -    | -   | 用于分类和发现的关键词标签，便于客户端按类别检索和匹配技能。  |
    | inputMmodes | 否    | array of string | -    | -   | 支持的输入媒体类型列表（MIME 类型）。           |
    | outputModes | 否    | array of string | -    | -   | 支持的输出媒体类型列表（MIME 类型）。           |

- 请求示例

    ```json
    POST /rest/v1/registry-center/agent-cards HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    {
      "agentCards": [
        {
          "name": "RAN Energy Saving Agent",
          "description": "负责RAN能效优化的自主闭环运行，包括意图探索、意图实现、效果评估与报告。",
          "version": "1.0.0",
          "provider": {
            "organization": "Org",
            "url": "https://www.org.com"
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
            "streaming": true,
            "pushNotifications": false,
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
      ]
    }
    ```

- 响应参数

    无。

- 响应样例

    注册成功：无响应体。

- 状态码

  | 状态码 | 说明                   |
  |--------|----------------------|
  | 201 | 注册成功                 |
  | 422 | 注册失败，AgentCard参数校验失败 |
  | 409 | 注册失败，注册数量超出上限或重复注册   |

## 查询AgentCard列表

- 典型场景

    当用户需要查询Agent信息时，可以通过该接口来返回Agent列表。

- 功能描述

  - 根据Agent名称和组织机构进行精确匹配查询。
  - 支持多条件组合查询（AND逻辑）。
  - 所有查询参数均为可选，不提供任何参数时返回所有已注册的Agent列表。

- 接口约束

  - 当不提供任何参数时，返回系统中所有已注册的Agent列表（默认注册上限为100个）。
  - 提供参数时，按实际情况返回，最少返回0个。
  - 单实例上该接口最大并发数为100。

- 调用方法

    GET

- URI

    */rest/v1/registry-center/agent-cards*

- 请求参数

  <a id="表8-query参数列表"></a>**表8** query参数列表

    | 参数名          | 类型     | 必填 | 默认值 | 描述                           |
    |--------------|--------|----|-----|------------------------------|
    | name         | string | 否  | -   | Agent 名称，进行精确匹配查询。支持大小写敏感匹配。 |
    | organization | string | 否  | -   | 组织机构名称，进行精确匹配查询。支持大小写敏感匹配。   |

- 请求示例

  - 查询所有Agent

    ```json
    GET /rest/v1/registry-center/agent-cards HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    ```

  - 按名称查询

    ```json
    GET /rest/v1/registry-center/agent-cards?name=RAN%20Energy%20Saving%20Agent HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    ```

  - 按组织机构精确查询

    ```json
    GET /rest/v1/registry-center/agent-cards?organization=Org HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    ```

  - 组合条件查询（AND）

    ```json
    GET /rest/v1/registry-center/agent-cards?name=RAN%20Energy%20Saving%20Agent&organization=Org HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    ```

- 响应参数

    <a id="表9-响应参数列表"></a>**表9** 响应参数列表
    
    | 参数名称 | 类型              | 值域 | 默认值 | 描述         |
    |------|-----------------|----|-----|--------------|
    | agentCards | array_reference | -  | -   | 符合要求的Agent列表，详细请参见[表2](#表2-agentcard对象的参数列表)。 |

- 响应样例

    ```json
    {
      "agentCards": [
        {
          "name": "RAN Energy Saving Agent",
          "description": "负责RAN能效优化的自主闭环运行，包括意图探索、意图实现、效果评估与报告。",
          "version": "1.0.0",
          "provider": {
            "organization": "Org",
            "url": ""
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
            "streaming": true,
            "pushNotifications": false,
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
      ]
    }
    ```

- 状态码

  | 状态码 | 说明 |
  |--------|------|
  | 200 | 查询成功 |

## 查询指定AgentCard

- 典型场景

    根据用户输入的name和organization参数，精准查询name和organization对应的Agent。

- 功能描述

    根据Agent的name和organization的唯一组合，精确查询并返回单个Agent的完整详细信息，查不到返回null。

- 接口约束

    单实例上该接口最大并发数为100。

- 调用方法

    GET

- URI

    */rest/v1/registry-center/agent-cards/{organization}/{name}*

- 请求参数

  <a id="表10-path参数列表"></a>**表10** path参数列表

    | 参数名          | 类型     | 必填 | 描述                                          |
    |--------------|--------|----|---------------------------------------------|
    | name         | string | 是  | Agent名称，作为路径参数传递。用于唯一标识Agent的组成部分之一。        |
    | organization | string | 是  | Agent所属的组织机构名称，作为查询参数传递。与name共同唯一标识一个Agent。 |

- 请求示例

  ```json
  GET /rest/v1/registry-center/agent-cards/Org/RAN%20Energy%20Saving%20Agent HTTP/1.1
  Host: your-domain.com
  Content-Type: application/json
  ```

- 响应参数

    <a id="表11-响应参数列表"></a>**表11** 响应参数列表
    
    | 参数名称 | 类型    | 值域 | 默认值 | 描述           |
    |------|-------|----|-----|--------------|
    | agentCards    | array_reference | -  | -   | 符合要求的Agent列表，详细请参见[表2](#表2-agentcard对象的参数列表)。 |

- 响应样例

   ```json
   {
     "agentCards": [
       {
         "name": "RAN Energy Saving Agent",
        "description": "负责RAN能效优化的自主闭环运行，包括意图探索、意图实现、效果评估与报告。",
        "version": "1.0.0",
        "provider": {
          "organization": "Org",
          "url": ""
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
          "streaming": true,
          "pushNotifications": false,
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
    ]
  }
  ```

- 状态码

  | 状态码 | 说明 |
  |--------|------|
  | 200 | 查询成功 |

## 更新指定AgentCard

- 典型场景

    已注册的Agent的信息如果有变更，则需要用户调用该接口来进行Agent信息的更新。

- 功能描述

    完全替换一个已存在的Agent。该接口使用请求体中的完整AgentCard数据替换现有Agent的全部信息。请求体中的名称和组织机构必须与路径参数和查询参数匹配。

- 接口约束

    单实例上该接口最大并发数为100。

- 调用方法

    PUT

- URI

    */rest/v1/registry-center/agent-cards/{organization}/{name}*

- 请求参数

  <a id="表12-path参数列表"></a>**表12** path参数列表

    | 参数名          | 类型     | 必填 | 描述                                                  |
    |--------------|--------|----|-----------------------------------------------------|
    | name         | string | 是  | 待更新的Agent名称，作为路径参数传递。该值必须与请求体中的name字段匹配。            |
    | organization | string | 是  | 待更新Agent的组织机构名称。该值必须与请求体中provider.organization字段匹配。 |

- 请求示例

  ```json
  PUT /rest/v1/registry-center/agent-cards/Org/RAN%20Energy%20Saving%20Agent HTTP/1.1
  Host: your-domain.com
  Content-Type: application/json
  {
    "agentCards": [
      {
        "name": "RAN Energy Saving Agent",
        "description": "负责RAN能效优化的自主闭环运行，包括意图探索、意图实现、效果评估与报告。",
        "version": "1.0.0",
        "provider": {
          "organization": "Org",
          "url": ""
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
          "streaming": true,
          "pushNotifications": false,
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
    ]
  }
  ```

- 响应参数
    无。

- 响应样例

    修改成功：无响应体。

- 状态码

    | 状态码 | 说明                   |
    |--------|----------------------|
    | 200 | 修改成功                 |
    | 422 | 修改失败，AgentCard参数校验失败 |
    | 404 | 修改失败，Agent未找到             |

## 删除指定AgentCard

- 典型场景

    已注册的Agent的如果想要注销，需要用户调用该接口来进行Agent信息的注销。

- 功能描述

    从Agent注册中心中移除指定的Agent。该操作会彻底删除Agent的注册信息，删除后该Agent将无法被工作流调度使用。

- 接口约束

    单实例上该接口最大并发数为50。

- 调用方法

    DELETE

- URI

    */rest/v1/registry-center/agent-cards/{organization}/{name}*

- 请求参数

  <a id="表13-path参数列表"></a>**表13** path参数列表

    | 参数名          | 类型     | 必填 | 描述                                           |
    |--------------|--------|----|----------------------------------------------|
    | name         | string | 是  | 待注销的Agent名称，作为路径参数传递。用于唯一标识要删除的Agent。        |
    | organization | string | 是  | 待注销Agent的组织机构名称，作为查询参数传递。与name共同唯一标识一个Agent。 |

- 请求示例

  ```json
  DELETE /rest/v1/registry-center/agent-cards/Org/RAN%20Energy%20Saving%20Agent HTTP/1.1
  Host: your-domain.com
  Content-Type: application/json
  ```

- 响应参数
    无。

- 响应样例

    删除成功，无响应体。

- 状态码

  | 状态码 | 说明            |
  |--------|---------------|
  | 200 | 删除成功          |
  | 404 | 删除失败，Agent未找到 |

## 按语义检索AgentCard

- 典型场景

    用户输入一段自然语言描述的任务需求，系统可识别任务语义意图，并返回与任务最匹配的Agent列表，供用户选择调用。

- 功能描述

    该接口接收自然语言任务描述作为输入，通过语义理解能力分析任务意图，最终输出与任务最匹配的Agent列表。

- 接口约束

    单实例上该接口最大并发数为100。

- 调用方法

    POST

- URI

    */rest/v1/registry-center/agent-cards/semantic-query*

- 请求参数

  <a id="表14-body参数列表"></a>**表14** body参数列表

    | 参数名  | 类型     | 必填 | 默认值 | 描述                                     |
    |------|--------|----|-----|----------------------------------------|
    | task | string | 是  | -   | 自然语言任务描述，用于语义检索相关Agent。例如："需要查询意图报告"等。 |

- 请求示例

  - 基本检索

    ```json
    POST /rest/v1/registry-center/agent-cards/semantic-query HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    {
      "task": "需要查询意图报告"
    }
    ```

- 响应参数

    <a id="表15-响应参数列表"></a>**表15** 响应参数列表
    
    | 参数名称 | 类型    | 值域 | 默认值 | 描述         |
    |------|-------|---|-----|--------------|
    | agentCards    | array_reference | - | -   | 符合要求的Agent列表，详细请参见[表2](#表2-agentcard对象的参数列表)。 |

- 响应样例

   - 查询成功
      ```json
      {
        "agentCards": [
          {
            "name": "RAN Energy Saving Agent",
            "description": "负责RAN能效优化的自主闭环运行，包括意图探索、意图实现、效果评估与报告。",
            "version": "1.0.0",
            "provider": {
              "organization": "Org",
              "url": ""
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
              "streaming": true,
              "pushNotifications": false,
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
        ]
      }
      ```

- 状态码

  | 状态码 | 说明 |
  |--------|------|
  | 200 | 查询成功 |

## 获取公钥信息

- 典型场景

    运营商或设备厂商需要获取公钥信息时，可通过该接口获取。

- 功能描述

    提供注册中心签名证书的公钥JWK Set格式，用于验证AgentCard的注册中心签名。

- 接口约束

  - 接口流控：10次/秒；
  - 接口认证：不需要客户端证书认证，不需要用户认证。

- 调用方法

    GET

- URI

    */rest/v1/registry-center/keys*

- 请求参数

    无。

- 请求示例

  ```json
  GET /rest/v1/registry-center/keys HTTP/1.1
  Host: your-domain.com
  Content-Type： application/json
  ```

- 响应参数

  <a id="表16-jwk对象数组"></a>**表16** JWK对象数组

    | 参数名称 | 类型     | 值域 | 默认值 | 描述         |
    |------|--------|------|-----|--------------|
    | keys | array_reference  | -    | -   | JWK Set格式的公钥列表。 |

  <a id="表17-jwk对象"></a>**表17** JWK对象

    | 参数名称   | 是否必选 | 类型              | 值域             | 默认值 | 描述                        |
    |:---------|:-----|:----------------|:------------------|:----|:----------------------------|
    | kty      | 是    | string          | RSA               | -   | 密钥类型。                        |
    | n        | 是    | string          | base64url编码      | -   | RSA模数。                        |
    | e        | 是    | string          | base64url编码      | -   | RSA公钥指数。                     |
    | alg      | 是    | string          | RS256             | -   | 签名算法。                        |
    | use      | 是    | string          | sig               | -   | 密钥用途。                        |
    | kid      | 是    | string          | -                 | -   | 密钥标识符。                       |
    | key_ops  | 否    | array of string | ["verify"]        | -   | 密钥操作用途。                     |

- 响应样例

    ```json
    {
      "keys": [
        {
          "kty": "RSA",
          "n": "base64url-encoded-modules",
          "e": "AQAB",
          "alg": "RS256",
          "use": "sig",
          "kid": "test-key-1",
          "key_ops": ["verify"]
        }
      ]
    }
    ```

- 状态码

  | 状态码 | 说明          |
  |--------|-------------|
  | 200 | 获取成功        |
  | 429 | 获取失败，超过流控限制 |
  | 500 | 获取失败，服务内部错误 |
