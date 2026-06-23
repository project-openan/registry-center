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

### Constraints and Limitations

  For details, see the interface constraints of each API.

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
    | agentCards | Yes    | array_reference | Currently only supports registration of a single AgentCard. See [Table 2](#table-2-agentcard-object-parameters) for details. | -   | -    |

  <a id="table-2-agentcard-object-parameters"></a>**Table 2** AgentCard object parameters
    
    | Parameter Name      | Required | Type              | Value Range                                                                                         | Default | Description               |
    |---------------------|------|-----------------|-----------------------------------------------------------------------------------------------------|-----|---------------------------|
    | name                | Yes    | string          | 1–100 characters. Must match the regular expression `^[a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*$`.         | -   | AgentCard name.           |
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

    None.

- Response Example

    Registration successful: No response body.

- Status Codes

| Status Code | Description                          |
|--------|--------------------------------------|
| 201 | Registration successful.             |
| 401 | Signature verification failed.       |
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
  | 404 | Update failed, Agent not found.      |
  | 500 | Query failed, internal service error. |
  | 503 | Service busy.             |

## Query Specific AgentCard

- Typical Scenario

    Based on the name and organization parameters provided by the user, precisely query the Agent corresponding to the name and organization.

- Description

    Based on the unique combination of Agent name and organization, precisely query and return the complete details of a single Agent. Returns 404 status code with error message if not found.

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
  | 200 | Query successful.                   |
  | 404 | Query failed, Agent not found.          |
  | 500 | Query failed, internal service error.         |
  | 503 | Service busy.                          |

## Update Specific AgentCard

- Typical Scenario

    If the information of a registered Agent has changed, the user needs to call this API to update the Agent information.

- Description

    Completely replace an existing Agent. This API uses the complete AgentCard data in the request body to replace all information of the existing Agent. The name and organization in the request body must match the path parameters and query parameters.

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

    None.

- Response Example

    Update successful: No response body.

- Status Codes

    | Status Code | Description                          |
    |--------|--------------------------------------|
    | 200 | Update successful.                   |
    | 400 | Parameter validation failed.         |
    | 401 | Signature verification failed.       |
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

    None.

- Response Example

    Deletion successful: No response body.

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

    This API receives a natural language task description as input, analyzes the task intent through semantic understanding capabilities, and ultimately outputs the list of Agents best matching the task.

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
    | task | string | Yes  | -   | Natural language task description for semantically searching related Agents. For example: "Need to query intent reports", etc. |

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
  | 200 | Query successful.                   |
  | 404 | Query failed, Agent not found.          |
  | 500 | Query failed, internal service error.      |
  | 503 | Service busy.                          |

## Get Public Key Information

- Typical Scenario

    When operators or device vendors need to obtain public key information, they can call this API to retrieve it.

- Description

    Provides the public key in JWK Set format from the Registry Center's signing certificate, used to verify the Registry Center's signature on AgentCards.

- Interface Constraints

  - Rate limiting: 10 requests/second.
  - Authentication: No client certificate authentication or user authentication required.

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
