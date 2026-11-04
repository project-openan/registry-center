<!--
Copyright (c) 2026 Huawei Technologies Co., Ltd.
All Rights Reserved.

SPDX-License-Identifier: Apache-2.0

   Licensed under the Apache License, Version 2.0 (the "License"); you may
   not use this file except in compliance with the License. You may obtain
   a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
   License for the specific language governing permissions and limitations
   under the License.
-->
# Registry Center API Reference

## Before You Begin

### Introduction

  The Registry Center is a service focused on unified Agent management. It provides the following APIs:
  - **Register AgentCard**: Register Agents from different vendors into the center for unified management.
  - **Query AgentCard List**: Query the list of AgentCards matching specified conditions.
  - **Query Specific AgentCard**: Precisely look up a unique AgentCard instance by AgentCard name and organization.
  - **Update Specific AgentCard**: Update information of a specified AgentCard.
  - **Delete Specific AgentCard**: Delete an AgentCard that is no longer needed.
  - **Semantic Query AgentCard**: Search for matching AgentCards based on natural language semantics.
  - **Public Key Management**: Provide an API to retrieve the Registry Center's signing public key.
  - **Agent Heartbeat Reporting**: Agents periodically report liveness; the Registry Center maintains health status based on heartbeats.
  - **Agent Health Query**: Query the health status list of heartbeat-monitored Agents.
  - **Change Subscription Management**: Create, query, and delete registry change broadcast subscriptions.
  - **Change Reconciliation**: Pull registry change events by version number so subscribers can catch up.

### Constraints and Limitations

  For details, see the interface constraints of each API.

  For AgentCard registration/update, `agentCards` must be a non-empty list of
  objects conforming to the AgentCard schema. PUT requires each Card's `name`
  and `provider.organization` to match the URL; it never renames an identity or
  rewrites signed payloads. A malformed item returns 422; if earlier items in
  the batch succeeded, `registeredAgents` / `updatedAgents` records that partial
  success. The batch is not an all-or-nothing transaction.

### Transport, Caller Identity and Permissions

HTTP/HTTPS, incoming client certificates, caller Token authentication, owner authorization and
AgentCard JWS signatures are independent. Disabling peer-certificate verification does not disable authentication.

| Listener | Caller identity | Operation boundary |
| --- | --- | --- |
| Main `/rest/v1/registry-center/*` | `owner.identity.mode=token`: Bearer validated by the configured `integration.auth.*` provider | Ordinary roles discover public cards; `vendor_agent` additionally writes/heartbeats its own cards; `nms_oss` has administrative access. Existing owner guards still apply. |
| Main, certificate/proxy identity | Existing certificate or trusted proxy identity policy | Certificate identity requires HTTPS with client verification; only trust explicitly configured proxies. |
| Integration `/integration/*` | Independently configured Token/mTLS provider | Role/operation-specific policy; this is not the main API port. Token acquisition is available only when the integration API/provider supports it. |

Example main-port discovery (`REGISTRY_API_TOKEN` comes from your configured identity provider):

```bash
curl --cacert /secure/trust.cer \
  -H "Authorization: Bearer ${REGISTRY_API_TOKEN}" \
  https://registry.example/rest/v1/registry-center/agent-cards
```

401 means missing/invalid/expired credentials (or an independently failed card-signature check);
403 means verified identity without role/owner permission; 503 means required authentication,
signing or storage capability is unavailable. Provider failure does not become anonymous access.
This service is not the orchestration center's web-account login server.

The JWKS `/rest/v1/registry-center/keys` route is exempt from application Token authentication.
That exemption cannot bypass TLS: when `verify_client=true`, every HTTPS connection, including JWKS,
must present a valid client certificate. See [current transport details](../transport-runtime.md).

## Register AgentCard

- Typical Scenario

    When operators or device vendors need to register a new AgentCard, they can call this API to create a new AgentCard record in the Registry Center component.

- Description

    Register a specified AgentCard with the Registry Center.

- Interface Constraints

  - The size of a single AgentCard registration request body must not exceed 1024 KB.
  - The maximum concurrency for this API on a single instance is 50.

- Method

    POST

- URI

    */rest/v1/registry-center/agent-cards*

- Request Parameters

  <a id="table-1-body-parameters"></a>**Table 1** body parameters

    | Parameter Name | Required | Type              | Value Range                                                          | Default | Description |
    |------------|------|-----------------|---------------------------------------------------------------|-----|------|
    | agentCards | Yes    | array_reference | Supports single or batch registration; must be a non-empty list. Batch registration processes cards in order and stops at the first failure (fail-fast); cards already registered are reported in the registeredAgents field of the error response. See [Table 2](#table-2-agentcard-object-parameters) for details. | -   | -    |

  <a id="table-2-agentcard-object-parameters"></a>**Table 2** AgentCard object parameters
    
    | Parameter Name      | Required | Type              | Value Range                                                                                         | Default | Description               |
    |---------------------|------|-----------------|-----------------------------------------------------------------------------------------------------|-----|---------------------------|
    | name                | Yes    | string          | 1–100 characters. Must match the regular expression `^[a-zA-Z0-9_-]+(?:\s+[a-zA-Z0-9_-]+)*$`.         | -   | AgentCard name.           |
    | description         | Yes    | string          | 1–1000 characters.                                                                                  | -   | AgentCard description.    |
    | version             | Yes    | string          | 1–50 characters.                                                                                    | -   | AgentCard version.        |
    | provider            | Yes    | reference       | See [Table 4](#table-4-agentprovider-object-parameters) for details.                                | -   | Provider information.     |
    | skills              | Yes    | array_reference | Maximum: 100 skills; maximum JSON serialized length per skill: 4096 characters. See [Table 7](#table-7-agentskill-object-parameters) for details. | -   | Skill list.               |
    | capabilities        | Yes    | reference       | See [Table 5](#table-5-agentcapabilities-object-parameters) for details.                            | -   | AgentCard capabilities.   |
    | supportedInterfaces | Yes    | array_reference | 1–3 interfaces. See [Table 3](#table-3-agentinterface-object-parameters) for details.              | -   | Supported protocols.      |
    | signatures          | No    | array            | List of signatures for AgentCard integrity verification.                                           | -   | Digital signatures.       |
    | defaultInputModes   | No    | array of string  | List of supported default input media types (MIME types).                                          | -   | Default input modes.      |
    | defaultOutputModes  | No    | array of string  | List of supported default output media types (MIME types).                                         | -   | Default output modes.     |

  <a id="table-3-agentinterface-object-parameters"></a>**Table 3** AgentInterface object parameters

    | Parameter Name   | Required | Type     | Value Range                                | Default | Description                                                       |
    |:----------------|:-----|:-------|:--------------------------------------------|:----|:-------------------------------------------------------------------|
    | url             | Yes    | string | 1–1024 characters; must be a valid Web URL.  | -   | The base URL of the interface, used for sending A2A requests.     |
    | protocolBinding | Yes    | string | -                                           | -   | Protocol binding identifier, indicating the transport protocol used by this interface. |
    | protocolVersion | Yes    | string | -                                           | -   | A2A protocol version number, indicating the A2A protocol version supported by this interface. |

  <a id="table-4-agentprovider-object-parameters"></a>**Table 4** AgentProvider object parameters

    | Parameter Name | Required | Type     | Value Range                              | Default | Description                                                                 |
    |:-------------|:-----|:-------|:------------------------------------------|:----|:-----------------------------------------------------------------------------|
    | organization | Yes    | string | 1–100 characters; must not be empty.       | -   | The organization name of the Agent provider, used to identify the source organization or development team of the Agent. |
    | url          | No    | string | 1–1024 characters; must be a valid Web URL. | -   | The official website link of the Agent provider, for users to learn about the organization background or obtain technical support. |

  <a id="table-5-agentcapabilities-object-parameters"></a>**Table 5** AgentCapabilities object parameters

    | Parameter Name     | Required | Type              | Value Range                                                                                                                               | Default | Description                                                                                                                                                                              |
    |:------------------|:-----|:----------------|:-------------------------------------------------------------------------------------------------------------------------------------------|:------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
    | streaming         | No    | boolean         | true or false.                                                                                                                             | false | Whether streaming is supported. If true, the Agent can return response content in real time via Server-Sent Events (SSE); if false, only one-shot synchronous responses are supported. |
    | pushNotifications | No    | boolean         | true or false.                                                                                                                             | false | Whether push notifications are supported. If true, the Agent can proactively send task status updates and artifact notifications to the client; requires PushNotificationConfig configuration. |
    | extendedAgentCard | No    | boolean         | true or false.                                                                                                                             | false | Declares whether the Agent supports providing an extended version of the Agent Card after authentication.                                                                           |
    | extensions        | No    | array_reference | Maximum: 10 extensions; maximum JSON serialized length per extension: 512 characters. See [Table 6](#table-6-agentextension-object-parameters) for details. | -     | List of supported extension capabilities, used to declare A2A protocol extension features implemented by the Agent.                                                           |

  <a id="table-6-agentextension-object-parameters"></a>**Table 6** AgentExtension object parameters

    | Parameter Name | Required | Type      | Value Range     | Default | Description                                                                                       |
    |:------------|:-----|:--------|:-----------------|:------|:-------------------------------------------------------------------------------------------|
    | uri         | Yes    | string  | -                | -     | The unique identifier of the extension; must be a versioned URI format for globally unique identification.      |
    | description | No    | string  | -                | -     | Human-readable description of the extension feature, describing how the Agent uses this extension.        |
    | required    | No    | boolean | true or false.    | false | Indicates whether the client must support this extension. If true, the client must understand and activate this extension, otherwise the Agent will reject the request. |
    | params      | No    | object  | -                | -     | Extension-specific configuration or discovery parameters, used to pass additional information needed for extension initialization.        |

  <a id="table-7-agentskill-object-parameters"></a>**Table 7** AgentSkill object parameters

    | Parameter Name | Required | Type              | Value Range | Default | Description                                              |
    |:------------|:-----|:----------------|:-------------|:----|:--------------------------------------------------|
    | id          | Yes    | string          | -            | -   | The unique identifier of the skill, used to distinguish different skills within the AgentCard. |
    | name        | Yes    | string          | -            | -   | The human-readable name of the skill, the skill title displayed to end users.                |
    | description | Yes    | string          | -            | -   | Detailed functional description of the skill, helping clients understand the specific role and applicable scenarios of this skill. |
    | tags        | No    | array of string | -            | -   | Keyword tags for categorization and discovery, facilitating client-side retrieval and matching of skills by category.     |
    | inputModes | No    | array of string | -            | -   | List of supported input media types (MIME types).                                           |
    | outputModes | No    | array of string | -            | -   | List of supported output media types (MIME types).                                          |

- Request Example

    ```json
    POST /rest/v1/registry-center/agent-cards HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    {
      "agentCards": [
        {
          "name": "RAN Energy Saving Agent",
          "description": "RAN Energy Saving Agent for autonomous closed-loop energy efficiency optimization, including intent exploration, fulfillment, effect evaluation and reporting.",
          "version": "1.0.0",
          "provider": {
            "organization": "Org",
            "url": "https://example.com"
          },
          "skills": [
            {
              "id": "ran-es-intent-exploration",
              "name": "RAN ES Intent Exploration",
              "description": "Evaluate and determine best possible values for RAN ES intent targets, considering current resource conditions and system capabilities.",
              "tags": [
                "wireless",
                "energy-saving",
                "intent"
              ]
            },
            {
              "id": "ran-es-intent-lifecycle-management",
              "name": "RAN ES Intent Lifecycle Management",
              "description": "Manage RAN ES intent lifecycle including creation, modification, deletion, activation, deactivation, and perform data collection, analysis, solution formulation and configuration.",
              "tags": [
                "wireless",
                "energy-saving",
                "intent"
              ]
            },
            {
              "id": "ran-es-intent-reporting",
              "name": "RAN ES Intent Reporting",
              "description": "Provide intent report query, subscription and notification capabilities, reporting intent fulfillment status, achieved values, recommended values and configuration changes.",
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
              "protocolBinding": "GRPC",
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

- Response Parameters

    Registration successful returns a results array with one entry per card, in the same order as the request agentCards.

    | Parameter | Type | Description |
    |------|----|------|
    | results[].name           | string  | AgentCard name. |
    | results[].organization   | string  | Provider organization. |
    | results[].status         | string  | Status after registration: published (searchable) or registered (pending approval when agent_approval_enabled=true). |
    | results[].registrySigned | boolean | Whether the registry center has countersigned the card. |

- Response Example

    Registration successful:

    ```json
    HTTP/1.1 201 Created
    {
      "results": [
        {
          "name": "RAN Energy Saving Agent",
          "organization": "Org",
          "status": "published",
          "registrySigned": false
        }
      ]
    }
    ```

    In batch registration, the first failed card aborts the request (fail-fast). The error response additionally carries a registeredAgents field listing the cards already registered by this request, so the client can determine the retry scope:

    ```json
    {
      "errors": {"error": [{"errorMessage": "Card 2/2 (Bad Agent!): ..."}]},
      "registeredAgents": [
        {"name": "RAN Energy Saving Agent", "organization": "Org", "status": "published", "registrySigned": false}
      ]
    }
    ```

- Status Codes

| Status Code | Description                          |
|--------|--------------------------------------|
| 201 | Registration successful.             |
| 401 | Caller authentication or card signature verification failed.       |
| 413 | Request body too large.              |
| 422 | Registration failed, AgentCard parameter validation failed. |
| 409 | Registration failed, registration count exceeds limit or duplicate registration. |
| 503 | Service busy.                        |

## Query AgentCard List

- Typical Scenario

    When users need to query Agent information, they can call this API to retrieve the Agent list.

- Description

  - Performs fuzzy match (substring) queries by Agent name and exact-match queries by organization.
  - Supports multi-condition combined queries (AND logic).
  - All query parameters are optional; when no parameters are provided, all registered Agents are returned.

- Interface Constraints

  - When no parameters are provided, all registered Agents in the system are returned (default registration limit is 100).
  - When parameters are provided, results are returned based on actual matches, with a minimum of 0 results.
  - The maximum concurrency for this API on a single instance is 100.

- Method

    GET

- URI

    */rest/v1/registry-center/agent-cards*

- Request Parameters

  <a id="table-8-query-parameters"></a>**Table 8** query parameters

    | Parameter Name | Type     | Required | Default | Description                                           |
    |--------------|--------|----|-----|------------------------------------------------|
    | name         | string | No  | -   | Agent name for fuzzy match (substring) query. Case-insensitive matching is supported. |
    | organization | string | No  | -   | Organization name for exact-match query. Case-sensitive matching is supported. |

- Request Example

  - Query all Agents

    ```json
    GET /rest/v1/registry-center/agent-cards HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    ```

  - Query by name

    ```json
    GET /rest/v1/registry-center/agent-cards?name=RAN%20Energy%20Saving%20Agent HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    ```

  - Query by organization

    ```json
    GET /rest/v1/registry-center/agent-cards?organization=Org HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    ```

  - Combined query (AND)

    ```json
    GET /rest/v1/registry-center/agent-cards?name=RAN%20Energy%20Saving%20Agent&organization=Org HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    ```

- Response Parameters

    <a id="table-9-response-parameters"></a>**Table 9** response parameters
    
    | Parameter Name | Type              | Value Range | Default | Description               |
    |------|-----------------|----|-----|--------------------|
    | agentCards | array_reference | -  | -   | List of matching Agents. See [Table 2](#table-2-agentcard-object-parameters) for details. |

- Response Example

    ```json
    {
      "agentCards": [
        {
          "name": "RAN Energy Saving Agent",
          "description": "RAN Energy Saving Agent for autonomous closed-loop energy efficiency optimization, including intent exploration, fulfillment, effect evaluation and reporting.",
          "version": "1.0.0",
          "provider": {
            "organization": "Org",
            "url": ""
          },
          "skills": [
            {
              "id": "ran-es-intent-exploration",
              "name": "RAN ES Intent Exploration",
              "description": "Evaluate and determine best possible values for RAN ES intent targets, considering current resource conditions and system capabilities.",
              "tags": [
                "wireless",
                "energy-saving",
                "intent"
              ]
            },
            {
              "id": "ran-es-intent-lifecycle-management",
              "name": "RAN ES Intent Lifecycle Management",
              "description": "Manage RAN ES intent lifecycle including creation, modification, deletion, activation, deactivation, and perform data collection, analysis, solution formulation and configuration.",
              "tags": [
                "wireless",
                "energy-saving",
                "intent"
              ]
            },
            {
              "id": "ran-es-intent-reporting",
              "name": "RAN ES Intent Reporting",
              "description": "Provide intent report query, subscription and notification capabilities, reporting intent fulfillment status, achieved values, recommended values and configuration changes.",
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
              "protocolBinding": "GRPC",
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

- Status Codes

  | Status Code | Description               |
  |--------|----------------------|
  | 200 | Query successful, returns matching agents (empty list if none found). |
  | 500 | Query failed, internal service error. |
  | 503 | Service busy.             |

## Query Specific AgentCard

- Typical Scenario

    Based on the name and organization parameters provided by the user, precisely query the Agent corresponding to the name and organization.

- Description

    Based on the unique combination of Agent name and organization, precisely query and return the complete details of a single Agent. Only agents in published status are returned; if the agent does not exist or exists but is not published, the API returns 200 with an empty agentCards list, without distinguishing the two cases.

- Interface Constraints

    The maximum concurrency for this API on a single instance is 100.

- Method

    GET

- URI

    */rest/v1/registry-center/agent-cards/{organization}/{name}*

- Request Parameters

  <a id="table-10-path-parameters"></a>**Table 10** path parameters

    | Parameter Name | Type     | Required | Description                                                         |
    |--------------|--------|----|--------------------------------------------------------------|
    | name         | string | Yes  | Agent name, passed as a path parameter. The name of the Agent to query.        |
    | organization | string | Yes  | The organization name to which the Agent belongs, passed as a path parameter. Together with name, it uniquely identifies an Agent. |

- Request Example

  ```json
  GET /rest/v1/registry-center/agent-cards/Org/RAN%20Energy%20Saving%20Agent HTTP/1.1
  Host: your-domain.com
  Content-Type: application/json
  ```

- Response Parameters

    <a id="table-11-response-parameters"></a>**Table 11** response parameters
    
    | Parameter Name | Type    | Value Range | Default | Description                 |
    |------|-------|----|-----|----------------------|
    | agentCards    | array_reference | -  | -   | List of matching Agents. See [Table 2](#table-2-agentcard-object-parameters) for details. |

- Response Example

   ```json
   {
     "agentCards": [
       {
         "name": "RAN Energy Saving Agent",
        "description": "RAN Energy Saving Agent for autonomous closed-loop energy efficiency optimization, including intent exploration, fulfillment, effect evaluation and reporting.",
        "version": "1.0.0",
        "provider": {
          "organization": "Org",
          "url": ""
        },
        "skills": [
          {
            "id": "ran-es-intent-exploration",
            "name": "RAN ES Intent Exploration",
            "description": "Evaluate and determine best possible values for RAN ES intent targets, considering current resource conditions and system capabilities.",
            "tags": [
              "wireless",
              "energy-saving",
              "intent"
            ]
          },
          {
            "id": "ran-es-intent-lifecycle-management",
            "name": "RAN ES Intent Lifecycle Management",
            "description": "Manage RAN ES intent lifecycle including creation, modification, deletion, activation, deactivation, and perform data collection, analysis, solution formulation and configuration.",
            "tags": [
              "wireless",
              "energy-saving",
              "intent"
            ]
          },
          {
            "id": "ran-es-intent-reporting",
            "name": "RAN ES Intent Reporting",
            "description": "Provide intent report query, subscription and notification capabilities, reporting intent fulfillment status, achieved values, recommended values and configuration changes.",
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
            "protocolBinding": "GRPC",
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

- Status Codes

  | Status Code | Description                      |
  |--------|----------------------------|
  | 200 | Query successful (returns an empty agentCards list if the agent does not exist or is not published). |
  | 500 | Query failed, internal service error.         |
  | 503 | Service busy.                          |

## Update Specific AgentCard

- Typical Scenario

    If the information of a registered Agent has changed, the user needs to call this API to update the Agent information.

- Description

    Completely replace an existing Agent. This API uses the complete AgentCard data in the request body to replace all information of the existing Agent. The name and organization in the request body must match the path parameters and query parameters. The agentCards list in the request body must be non-empty; an empty list returns 422.

- Interface Constraints

    The maximum concurrency for this API on a single instance is 100.

- Method

    PUT

- URI

    */rest/v1/registry-center/agent-cards/{organization}/{name}*

- Request Parameters

  <a id="table-12-path-parameters"></a>**Table 12** path parameters

    | Parameter Name | Type     | Required | Description                                                                     |
    |--------------|--------|----|--------------------------------------------------------------------------|
    | name         | string | Yes  | The name of the Agent to be updated, passed as a path parameter. This value must match the name field in the request body.         |
    | organization | string | Yes  | The organization name of the Agent to be updated. This value must match the provider.organization field in the request body. |

- Request Example

  ```json
  PUT /rest/v1/registry-center/agent-cards/Org/RAN%20Energy%20Saving%20Agent HTTP/1.1
  Host: your-domain.com
  Content-Type: application/json
  {
    "agentCards": [
      {
        "name": "RAN Energy Saving Agent",
        "description": "RAN Energy Saving Agent for autonomous closed-loop energy efficiency optimization, including intent exploration, fulfillment, effect evaluation and reporting.",
        "version": "1.0.0",
        "provider": {
          "organization": "Org",
          "url": ""
        },
        "skills": [
          {
            "id": "ran-es-intent-exploration",
            "name": "RAN ES Intent Exploration",
            "description": "Evaluate and determine best possible values for RAN ES intent targets, considering current resource conditions and system capabilities.",
            "tags": [
              "wireless",
              "energy-saving",
              "intent"
            ]
          },
          {
            "id": "ran-es-intent-lifecycle-management",
            "name": "RAN ES Intent Lifecycle Management",
            "description": "Manage RAN ES intent lifecycle including creation, modification, deletion, activation, deactivation, and perform data collection, analysis, solution formulation and configuration.",
            "tags": [
              "wireless",
              "energy-saving",
              "intent"
            ]
          },
          {
            "id": "ran-es-intent-reporting",
            "name": "RAN ES Intent Reporting",
            "description": "Provide intent report query, subscription and notification capabilities, reporting intent fulfillment status, achieved values, recommended values and configuration changes.",
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
            "protocolBinding": "GRPC",
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

- Response Parameters

    Update successful returns a results array with one entry per card, in the same order as the request agentCards.

    | Parameter | Type | Description |
    |------|----|------|
    | results[].name           | string  | AgentCard name. |
    | results[].organization   | string  | Provider organization. |
    | results[].registrySigned | boolean | Whether the registry center has countersigned the card. |

- Response Example

    Update successful:

    ```json
    HTTP/1.1 200 OK
    {
      "results": [
        {
          "name": "RAN Energy Saving Agent",
          "organization": "Org",
          "registrySigned": false
        }
      ]
    }
    ```

    In batch update, the first failed card aborts the request (fail-fast). The error response additionally carries an updatedAgents field listing the cards already updated by this request.

- Status Codes

    | Status Code | Description                          |
    |--------|--------------------------------------|
    | 200 | Update successful.                   |
    | 400 | Parameter validation failed.         |
    | 401 | Caller authentication or card signature verification failed.       |
    | 403 | Permission denied.                   |
| 404 | Query failed, Agent not found.      |
    | 422 | Update failed, AgentCard parameter validation failed. |
    | 503 | Service busy.                        |

## Delete Specific AgentCard

- Typical Scenario

    If a registered Agent needs to be unregistered, the user needs to call this API to deregister the Agent information.

- Description

    Remove the specified Agent from the Agent Registry Center. This operation completely deletes the Agent's registration information, after which the Agent can no longer be scheduled and used by workflows.

- Interface Constraints

    The maximum concurrency for this API on a single instance is 50.

- Method

    DELETE

- URI

    */rest/v1/registry-center/agent-cards/{organization}/{name}*

- Request Parameters

  <a id="table-13-path-parameters"></a>**Table 13** path parameters

    | Parameter Name | Type     | Required | Description                                                           |
    |--------------|--------|----|----------------------------------------------------------------|
    | name         | string | Yes  | The name of the Agent to be unregistered, passed as a path parameter. Used to uniquely identify the Agent to be deleted.       |
    | organization | string | Yes  | The organization name of the Agent to be unregistered, passed as a path parameter. Together with name, it uniquely identifies an Agent. |

- Request Example

  ```json
  DELETE /rest/v1/registry-center/agent-cards/Org/RAN%20Energy%20Saving%20Agent HTTP/1.1
  Host: your-domain.com
  Content-Type: application/json
  ```

- Response Parameters

    | Parameter | Type | Description |
    |------|----|------|
    | name         | string  | Name of the deleted Agent. |
    | organization | string  | Provider organization. |
    | deleted      | boolean | Always true, indicating successful deletion. |

- Response Example

    Deletion successful:

    ```json
    HTTP/1.1 200 OK
    {
      "name": "RAN Energy Saving Agent",
      "organization": "Org",
      "deleted": true
    }
    ```

- Status Codes

  | Status Code | Description                      |
  |--------|----------------------------|
  | 200 | Deletion successful.                 |
  | 403 | Permission denied.                   |
  | 404 | Deletion failed, Agent not found.        |
  | 503 | Service busy.                          |

## Semantic Query AgentCard

- Typical Scenario

    The user inputs a task description in natural language, and the system identifies the semantic intent of the task and returns the list of Agents best matching the task for the user to select and invoke.

- Description

    This API receives a natural language task description and selects matching published Agents. Pending cards are excluded before the selection model is called. Semantic retrieval depends on the `chat` capability defined in `etc/config/models.yaml` — the entry names its secret through `api_key_env`, and the value comes from the process environment or `.env`. Missing model configuration, model invocation failure, or invalid model output returns 503; a successful search with no matches returns 200 with an empty agentCards list.

- Interface Constraints

    The maximum concurrency for this API on a single instance is 100.

- Method

    POST

- URI

    */rest/v1/registry-center/agent-cards/semantic-query*

- Request Parameters

  <a id="table-14-body-parameters"></a>**Table 14** body parameters

    | Parameter Name | Type     | Required | Default | Description                                                              |
    |------|--------|----|-----|-------------------------------------------------------------------|
    | task | string | Yes  | -   | Non-blank natural language task description, at most 10,000 characters. |

  The main port accepts the query parameter `top_n` (default 10, integer 1–50).
  The integration port accepts the JSON field `topN` with the same default and
  bounds; it rejects booleans, fractions and numeric strings rather than
  coercing or clamping them. Invalid task/count input returns 422 before any
  model call.

- Request Example

  - Basic query

    ```json
    POST /rest/v1/registry-center/agent-cards/semantic-query HTTP/1.1
    Host: your-domain.com
    Content-Type: application/json
    {
      "task": "Need to query intent report"
    }
    ```

- Response Parameters

    <a id="table-15-response-parameters"></a>**Table 15** response parameters
    
    | Parameter Name | Type    | Value Range | Default | Description               |
    |------|-------|---|-----|--------------------|
    | agentCards    | array_reference | - | -   | List of matching Agents. See [Table 2](#table-2-agentcard-object-parameters) for details. |

- Response Example

   - Query successful
      ```json
      {
        "agentCards": [
          {
            "name": "RAN Energy Saving Agent",
            "description": "RAN Energy Saving Agent for autonomous closed-loop energy efficiency optimization, including intent exploration, fulfillment, effect evaluation and reporting.",
            "version": "1.0.0",
            "provider": {
              "organization": "Org",
              "url": ""
            },
            "skills": [
              {
                "id": "ran-es-intent-exploration",
                "name": "RAN ES Intent Exploration",
                "description": "Evaluate and determine best possible values for RAN ES intent targets, considering current resource conditions and system capabilities.",
                "tags": [
                  "wireless",
                  "energy-saving",
                  "intent"
                ]
              },
              {
                "id": "ran-es-intent-lifecycle-management",
                "name": "RAN ES Intent Lifecycle Management",
                "description": "Manage RAN ES intent lifecycle including creation, modification, deletion, activation, deactivation, and perform data collection, analysis, solution formulation and configuration.",
                "tags": [
                  "wireless",
                  "energy-saving",
                  "intent"
                ]
              },
              {
                "id": "ran-es-intent-reporting",
                "name": "RAN ES Intent Reporting",
                "description": "Provide intent report query, subscription and notification capabilities, reporting intent fulfillment status, achieved values, recommended values and configuration changes.",
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
                "protocolBinding": "GRPC",
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

- Status Codes

  | Status Code | Description                      |
  |--------|----------------------------|
  | 200 | Query successful (returns an empty agentCards list if no agent matches). |
  | 500 | Query failed, internal service error.      |
  | 503 | Service busy.                          |

## Registration layer and layer-aware discovery

Layer is registration metadata, not a signed AgentCard field. `agentCards` accepts either an ordinary AgentCard or a wrapper `{"agentCard": <complete signed card>, "layer": "OMC"}`. A declared layer must be a non-empty string after trimming, at most 64 characters. Missing layer for a new registration uses `unknown`; an update omitting layer preserves existing metadata. Do not alter the signed card when adding the wrapper.

The ordinary `GET /rest/v1/registry-center/agent-cards` accepts an optional `layer` query filter, including with organization/name filters. `POST /agent-cards/semantic-query` also accepts `layer` and `topN` (1–50, default 10). Ordinary responses remain `agentCards`, without layer metadata.

The following routes return registration metadata. In main-port Token mode they require an `nms_oss` administrator credential; ordinary discovery/vendor roles are not sufficient. Other identity modes continue to use their configured authentication policies. Application Token authorization never bypasses required mTLS.

| Method | Path (under `/rest/v1/registry-center`) | Input | Result |
| --- | --- | --- | --- |
| POST | `/agent-cards-with-layer` | Optional layer; limit 1–1000 (default 100), offset >=0 (default 0); no task | agents, count, hasMore |
| GET | `/agent-cards-with-layer/{organization}/{name}` | URL-encoded organization and name | agentCard, layer; 404 when not visible |
| POST | `/agent-cards-with-layer/semantic-query` | Required non-empty task; optional layer, topN 1–50 (default 10) | agents, count |

Only published records are visible; unhealthy records are additionally hidden when the health-hiding policy is enabled. Semantic queries require usable model configuration; layer metadata may require storage migration. Invalid JSON/parameters return 422, role denial 403, rate limiting 429, unavailable storage/migration or concurrency 503. General failures return 500; authentication may fail before request validation.

Example (an existing administrative token, trusted HTTPS deployment):

```http
POST /rest/v1/registry-center/agent-cards-with-layer HTTP/1.1
Host: registry.example.test
Authorization: Bearer <nms-oss-token>
Content-Type: application/json

{"layer":"OMC","limit":20,"offset":0}
```

```json
{"agents":[],"count":0,"hasMore":false}
```

Non-empty `agents` items have `{"agentCard": <complete card>, "layer": "OMC"}`. The detail route returns one such item rather than an array. The semantic route has no `hasMore` field. Do not substitute a truncated response card as a registration request.

## Get Public Key Information

- Typical Scenario

    When operators or device vendors need to obtain public key information, they can call this API to retrieve it.

- Description

    Provides the public key in JWK Set format from the Registry Center's signing certificate, used to verify the Registry Center's signature on AgentCards.

- Interface Constraints

  - Rate limiting: 10 requests/second.
  - Authentication: exempt from application Token authentication; HTTPS with `verify_client=true` still requires a client certificate at the TLS handshake.

- Method

    GET

- URI

    */rest/v1/registry-center/keys*

- Request Parameters

    None.

- Request Example

  ```json
  GET /rest/v1/registry-center/keys HTTP/1.1
  Host: your-domain.com
  Content-Type: application/json
  ```

- Response Parameters

  <a id="table-16-jwk-object-array"></a>**Table 16** JWK object array

    | Parameter Name | Type     | Value Range | Default | Description              |
    |------|--------|------|-----|-------------------|
    | keys | array_reference  | -    | -   | List of public keys in JWK Set format. |

  <a id="table-17-jwk-object"></a>**Table 17** JWK object

    | Parameter Name | Required | Type              | Value Range         | Default | Description                        |
    |:---------|:-----|:----------------|:----------------------|:----|:----------------------------|
    | kty      | Yes    | string          | RSA                   | -   | Key type.                        |
    | n        | Yes    | string          | base64url-encoded     | -   | RSA modulus.                        |
    | e        | Yes    | string          | base64url-encoded     | -   | RSA public exponent.                     |
    | alg      | Yes    | string          | RS256                 | -   | Signature algorithm.                        |
    | use      | Yes    | string          | sig                   | -   | Key usage.                        |
    | kid      | Yes    | string          | -                     | -   | Key identifier.                       |
    | key_ops  | No    | array of string | ["verify"]            | -   | Key operations.                     |

- Response Example

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

- Status Codes

  | Status Code | Description                     |
  |--------|---------------------------|
  | 200 | Retrieval successful.              |
  | 429 | Retrieval failed, rate limit exceeded. |
  | 500 | Retrieval failed, internal service error. |
  | 503 | Signing is disabled, signer unavailable or certificate loading failed. |

## Report Agent Heartbeat

- Typical Scenario

    After deployment, an Agent periodically calls this API to report liveness. When heartbeat detection is enabled, the Registry Center maintains Agent health status based on heartbeat times and the failure threshold.

- Description

    Records the server-side receive time of the Agent's most recent heartbeat. If the Agent was previously suspect or offline, receiving a heartbeat immediately restores it to healthy and publishes a health change event.

- Constraints

  - Health tracking takes effect only when `heartbeat.enabled=true`; when disabled, the API returns 200 with `heartbeat_enabled` set to false and records nothing.
  - With `owner.isolation.enabled=true` only the card's owner may report a heartbeat: an unverifiable caller gets 401 and a non-owner gets 403 (the claim drives health hiding, the offline TTL and public health events).
  - The Agent must be registered; unregistered Agents receive 404.
  - Rate limit: 100 requests/second/IP by default, configurable via `flowcontrol.ratelimit.heartbeat`.
  - The heartbeat time is always the server-side receive time; timestamps provided by the request are not trusted.

- Method

    POST

- URI

    */rest/v1/registry-center/agent-cards/{organization}/{name}/heartbeat*

- Request Parameters

  <a id="table-18-heartbeat-path-parameters"></a>**Table 18** Path parameters

    | Parameter    | Mandatory | Type   | Value Range | Default | Description                        |
    |--------------|-----------|--------|-------------|---------|------------------------------------|
    | organization | Yes       | string | 1~100 chars | -       | Agent organization, same as registered. |
    | name         | Yes       | string | 1~100 chars | -       | Agent name, same as registered.         |

    The request body may be empty.

- Example Request

    ```http
    POST /rest/v1/registry-center/agent-cards/TestOrg/DemoAgent/heartbeat HTTP/1.1
    Host: your-domain.com
    ```

- Response Parameters

  <a id="table-19-heartbeat-response-parameters"></a>**Table 19** Response parameters

    | Parameter         | Type    | Description                                                              |
    |-------------------|---------|--------------------------------------------------------------------------|
    | heartbeat_enabled | boolean | Whether heartbeat detection is enabled.                                   |
    | interval          | int     | Expected heartbeat period (seconds). Agents should report with this period plus ±10% random jitter. |
    | failure_threshold | int     | An Agent is marked offline after missing this many consecutive periods.    |
    | grace_period      | int     | Suspect-state buffer duration (seconds).                                   |
    | server_time       | string  | Current server time (ISO 8601) for Agent clock alignment.                  |
    | health_status     | string  | Current health status: healthy/suspect/offline/unknown.                    |

- Example Response

    ```json
    {
      "heartbeat_enabled": true,
      "interval": 30,
      "failure_threshold": 3,
      "grace_period": 10,
      "server_time": "2026-09-17T12:00:00.123456+00:00",
      "health_status": "healthy"
    }
    ```

- Status Codes

  | Status Code | Description                          |
  |--------|--------------------------------------|
  | 200 | Report successful.                   |
  | 401 | Authentication failed.               |
  | 404 | Agent not registered.                |
  | 429 | Report failed, rate limit exceeded.  |
  | 500 | Report failed, internal service error. |
  | 503 | Server busy.                         |

## Query Agent Health Status List

- Typical Scenario

    A system administrator queries the health status of all heartbeat-monitored Agents from an observability dashboard to identify offline Agents promptly.

- Description

    Returns the health status list of all heartbeat-monitored Agents with optional status filtering.

- Constraints

  - Returns data only when `heartbeat.enabled=true`; otherwise returns an empty list.
  - The status filter value must be one of healthy/suspect/offline/unknown.

- Method

    GET

- URI

    */rest/v1/registry-center/agents/health*

- Request Parameters

  <a id="table-20-health-query-parameters"></a>**Table 20** Query parameters

    | Parameter | Mandatory | Type   | Value Range                    | Default | Description           |
    |-----------|-----------|--------|--------------------------------|---------|-----------------------|
    | status    | No        | string | healthy/suspect/offline/unknown | -       | Filter by health status. |

- Example Request

    ```http
    GET /rest/v1/registry-center/agents/health?status=offline HTTP/1.1
    Host: your-domain.com
    ```

- Response Parameters

  <a id="table-21-health-status-object"></a>**Table 21** Health status object

    | Parameter          | Type   | Description                                     |
    |--------------------|--------|-------------------------------------------------|
    | name               | string | Agent name.                                     |
    | organization       | string | Agent organization.                             |
    | health_status      | string | Health status.                                  |
    | last_heartbeat_at  | string | Server-side receive time of the last heartbeat. |
    | status_changed_at  | string | Time of the last health status transition.       |

- Example Response

    ```json
    {
      "agents": [
        {
          "name": "DemoAgent",
          "organization": "TestOrg",
          "health_status": "offline",
          "last_heartbeat_at": "2026-09-17T11:07:00.056845+00:00",
          "status_changed_at": "2026-09-17T11:07:07.595837+00:00"
        }
      ]
    }
    ```

- Status Codes

  | Status Code | Description                        |
  |--------|------------------------------------|
  | 200 | Query successful.                  |
  | 400 | Invalid status filter value.       |
  | 500 | Query failed, internal service error. |

## Create Change Subscription

- Typical Scenario

    A service operator wants real-time notifications when registry data changes (registration, update, deregistration, health changes), and first registers a callback URL through this API.

- Description

    Creates a change broadcast subscription. When matching change events occur, the Registry Center pushes events in batches to the subscriber via HTTPS callback, signed with HMAC-SHA256 for verification.

- Constraints

  - Available only when `broadcast.enabled=true`; otherwise 503.
  - callback_url must be HTTPS; HTTP can be allowed in development via `broadcast.allow.http.callbacks=true`.
  - `broadcast.callback.allowlist` is mandatory: an empty allowlist rejects the request (422) and no delivery is attempted.
  - Rate limit: 50 requests/second/IP by default.

- Method

    POST

- URI

    */rest/v1/registry-center/subscriptions*

- Request Parameters

  <a id="table-22-subscription-body-parameters"></a>**Table 22** Body parameters

    | Parameter    | Mandatory | Type            | Value Range                                                          | Default     | Description                                              |
    |--------------|-----------|-----------------|----------------------------------------------------------------------|-------------|----------------------------------------------------------|
    | callback_url | Yes       | string          | 1~2048 chars, HTTPS URL                                              | -           | Event callback URL.                                       |
    | event_types  | No        | array of string | AGENT_REGISTERED/AGENT_UPDATED/AGENT_DEREGISTERED/AGENT_HEALTH_CHANGED | All types   | Event type whitelist to subscribe to.                     |
    | filters      | No        | reference       | -                                                                    | -           | Filter conditions. See [Table 23](#table-23-subscription-filters). |
    | secret       | No        | string          | 1~256 chars                                                          | -           | HMAC-SHA256 signing secret, recommended; events are unsigned if omitted. |

  <a id="table-23-subscription-filters"></a>**Table 23** Subscription filters

    | Parameter     | Mandatory | Type            | Description              |
    |---------------|-----------|-----------------|--------------------------|
    | organizations | No        | array of string | Filter by Agent organization. |
    | tags          | No        | array of string | Filter by Agent tags.         |

- Example Request

    ```json
    {
      "callback_url": "https://operator.example.com/registry-events",
      "event_types": ["AGENT_REGISTERED", "AGENT_UPDATED", "AGENT_DEREGISTERED", "AGENT_HEALTH_CHANGED"],
      "filters": {"organizations": ["acme"]},
      "secret": "whsec-demo"
    }
    ```

- Response Parameters

  <a id="table-24-subscription-object"></a>**Table 24** Subscription object

    | Parameter       | Type   | Description                          |
    |-----------------|--------|--------------------------------------|
    | subscription_id | string | Unique subscription ID for query and deletion. |
    | callback_url    | string | Callback URL.                        |
    | event_types     | array  | Subscribed event types.              |
    | filters         | object | Filter conditions.                   |
    | created_at      | string | Creation time.                       |

- Example Response

    ```json
    {
      "subscription_id": "sub_6133a2d93b32459990bf",
      "callback_url": "https://operator.example.com/registry-events",
      "event_types": ["AGENT_REGISTERED", "AGENT_UPDATED"],
      "filters": {"organizations": ["acme"], "tags": null},
      "created_at": "2026-09-17T11:07:14.009321+00:00"
    }
    ```

- Status Codes

  | Status Code | Description                                 |
  |--------|---------------------------------------------|
  | 201 | Created successfully.                       |
  | 422 | Invalid request parameters (callback URL, event types, etc.). |
  | 429 | Creation failed, rate limit exceeded.       |
  | 500 | Creation failed, internal service error.    |
  | 503 | Change broadcast is disabled.               |

## Query Subscription List

- Typical Scenario

    An administrator views active change subscriptions and their callback configurations.

- Description

    Returns all change subscriptions. The response does not include the secret.

- Constraints

  - Available only when `broadcast.enabled=true`; otherwise 503.

- Method

    GET

- URI

    */rest/v1/registry-center/subscriptions*

- Request Parameters

    None.

- Example Response

    ```json
    {
      "subscriptions": [
        {
          "subscription_id": "sub_6133a2d93b32459990bf",
          "callback_url": "https://operator.example.com/registry-events",
          "event_types": null,
          "filters": {"organizations": null, "tags": null},
          "created_at": "2026-09-17T11:07:14.009321+00:00"
        }
      ]
    }
    ```

- Status Codes

  | Status Code | Description                        |
  |--------|------------------------------------|
  | 200 | Query successful.                  |
  | 500 | Query failed, internal service error. |
  | 503 | Change broadcast is disabled.      |

## Delete Subscription

- Typical Scenario

    A subscriber cancels the subscription when it no longer needs change notifications.

- Description

    Deletes a change subscription by ID. The Registry Center stops pushing events to the callback URL afterwards.

- Constraints

  - Available only when `broadcast.enabled=true`; otherwise 503.

- Method

    DELETE

- URI

    */rest/v1/registry-center/subscriptions/{subscription_id}*

- Request Parameters

  <a id="table-25-delete-subscription-path-parameters"></a>**Table 25** Path parameters

    | Parameter       | Mandatory | Type   | Description            |
    |-----------------|-----------|--------|------------------------|
    | subscription_id | Yes       | string | Unique subscription ID. |

- Example Response

    ```json
    {
      "subscription_id": "sub_6133a2d93b32459990bf",
      "deleted": true
    }
    ```

- Status Codes

  | Status Code | Description                        |
  |--------|------------------------------------|
  | 200 | Deletion successful.               |
  | 404 | Subscription not found.            |
  | 500 | Deletion failed, internal service error. |
  | 503 | Change broadcast is disabled.      |

## Change Reconciliation Query

- Typical Scenario

    A subscriber uses this API to incrementally pull change events by version when it receives a `SYNC_REQUIRED` summary event, suspects missed events, or performs periodic verification.

- Description

    Returns events whose `registry_version` is greater than the given since value (ascending), which together with the full AgentCard query supports initial synchronization and missed-event recovery.

- Constraints

  - Events are retained for `broadcast.outbox.retention.days` (7 days by default); expired events cannot be retrieved.
  - Maximum 1000 events per page.

- Method

    GET

- URI

    */rest/v1/registry-center/changes*

- Request Parameters

  <a id="table-26-reconciliation-query-parameters"></a>**Table 26** Query parameters

    | Parameter | Mandatory | Type | Value Range | Default | Description                           |
    |-----------|-----------|------|-------------|---------|---------------------------------------|
    | since     | No        | int  | >=0         | 0       | Last known registry_version.          |
    | limit     | No        | int  | 1~1000      | 100     | Maximum events per page.              |

- Response Parameters

  <a id="table-27-change-event-object"></a>**Table 27** Change event object

    | Parameter        | Type   | Description                                                            |
    |------------------|--------|------------------------------------------------------------------------|
    | event_id         | string | Unique event ID (UUID) for subscriber-side idempotent deduplication.    |
    | event_type       | string | Event type; see the event_types description in [Table 22](#table-22-subscription-body-parameters). |
    | timestamp        | string | Event creation time (server clock).                                     |
    | registry_version | int    | Globally monotonic version number of the Registry Center.               |
    | data             | object | Event payload: card events contain name/organization/agent_card/tags; health events contain health_status/previous_health_status. |
    | has_more         | boolean | Whether more pages exist.                                               |
    | next_since       | int    | Starting point for the next page (registry_version of the last event on this page). |

- Example Response

    ```json
    {
      "changes": [
        {
          "event_id": "0198f6a2-7c1d-7cc2-9a3b-4f2e1d0c9b8a",
          "event_type": "AGENT_REGISTERED",
          "timestamp": "2026-09-17T12:00:00.123456+00:00",
          "registry_version": 1,
          "data": {"name": "DemoAgent", "organization": "TestOrg"}
        }
      ],
      "has_more": false,
      "next_since": 1
    }
    ```

- Status Codes

  | Status Code | Description                        |
  |--------|------------------------------------|
  | 200 | Query successful.                  |
  | 429 | Query failed, rate limit exceeded. |
  | 500 | Query failed, internal service error. |

## Management list registration metadata

`GET /rest/v1/registry-center/agent-cards/manage` returns all review states (or the requested `status`), with `publishStatus` and `registration.layer` on each card. `statusCounts` remains the unfiltered review-state totals. `registration.layer` is the stored vendor-defined string; legacy registrations without a declared layer return `unknown`. The management response is an envelope for the UI, not a signed AgentCard registration payload. Public AgentCard discovery responses remain unchanged.

The native frontend groups only explicit service/service-layer and network/network-layer labels (case/separator variants included) into its two standard tabs. Other declared values retain their original label under Other / Unspecified; missing metadata is shown as Unspecified. Organization/vendor names are never used to infer a layer. Upgrade the backend and frontend together to display existing stored layers; a new frontend against an older management API displays missing metadata as Unspecified.
