# Registry Center User Guide

## Feature Overview

The Registry Center is a service focused on unified Agent management, supporting users to centrally register and manage Agents from different vendors, enabling controlled access and maintenance of multi-source Agents.

### Application Scenarios

Applied to unified AgentCard registration and management in multi-vendor, multi-agent interaction scenarios in the A2A-T domain.

### Capability Scope

1. This project provides an Agent registry center module for customer system integration, used to manage AgentCards within the customer's internal system. It offers AgentCard registration, semantic search, and other capabilities, with security features such as TLS communication, log auditing, and access control.

2. This project is only a functional module, not a complete system. The module itself does not provide login authentication, authorization, user management, encryption/decryption, or key management capabilities; these security infrastructure components must be provided by the customer's system. Callback functions have been reserved in the source code for custom implementation.

### Design Constraints

1. This project must run on Linux systems and supports IPv4 environments.

2. It must be deployed as an internal system and cannot be exposed to the public internet or deployed as a cloud service; otherwise, the target system must simultaneously provide a firewall and a web server to implement security capabilities such as authentication and authorization.

3. AgentCards registered with this project must not contain personal data such as phone numbers, and must not contain sensitive information such as passwords or credentials; otherwise, there is a risk of information leakage.

4. AgentCards only support Chinese and English languages.

## Installation and Deployment

See: [Software Installation Guide (Quick Start)](https://gitcode.com/OpenAN/docs/blob/main/en/quick_start.md#2-software-installation-guide)

## Management Capabilities (CLI)

### Starting the CLI
CLI client startup example:
```bash
# CLI command client startup and entering the interface
[user@host registry-center-main]# python -m agent_registry.cli

agent-registry v1.0.0
Type 'cmds' for available commands, 'exit' to quit.

agent-registry>...
```

### Agent Management

Administrator: Agent query (list all, view details), Agent approval, Agent tag settings
Agent management command examples:
```bash
# List all agents
agent-registry> agent list
Agents List (1 total)
==================================================

Agent Name               Organization  Status      Tags  Created At           Updated At
-----------------------  ------------  ----------  ----  -------------------  -------------------
RAN Energy Saving Agent  Huawei        registered        2026-05-11T02:58:05  2026-05-11T02:58:05

# Set tags for an agent
agent-registry> agent set-tags -o Huawei -n "RAN Energy Saving Agent" -t tag1,tag2
Tags set successfully.
==================================================

Property      Value
------------  -----------------------
Agent Name    RAN Energy Saving Agent
Organization  Huawei
Tags          tag1, tag2

# Agent approval
agent-registry> agent approval -o Huawei -n "RAN Energy Saving Agent"
Approval Result
==================================================

Property      Value
------------  -----------------------
Agent Name    RAN Energy Saving Agent
Organization  Huawei
Status        published
Approved      Yes

# View agent details
agent-registry> agent get -o Huawei -n "RAN Energy Saving Agent"
Property      Value
------------  -----------------------
Agent Name    RAN Energy Saving Agent
Organization  Huawei
Status        registered
Tags          tag1, tag2
Created At    2026-05-11T02:58:05
Updated At    2026-05-11T09:44:34

Agent Card:
--------------------------------------------------
{
  "name": "RAN Energy Saving Agent",
  "description": "Autonomous closed-loop operation for RAN energy efficiency optimization, including intent exploration, intent implementation, effect evaluation, and reporting.",
  "supported_interfaces": [
    {
      "url": "http://127.0.0.1:5000/",
      "protocol_binding": "GRPC",
      "protocol_version": "1.0.0"
    },
    {
      "url": "http://127.0.0.1:5000/",
      "protocol_binding": "HTTP+JSON",
      "protocol_version": "1.0.0"
    }
  ],
  "provider": {
    "url": "https://www.huawei.com",
    "organization": "Huawei"
  },
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "push_notifications": false
  },
  "default_input_modes": [
    "text",
    "json"
  ],
  "default_output_modes": [
    "text",
    "json"
  ],
  "skills": [
    {
      "id": "ran-es-intent-exploration",
      "name": "RAN ES Intent Exploration",
      "description": "Evaluate and determine the best possibilities for specified RAN ES intent objectives, considering current resource conditions and system capabilities.",
      "tags": [
        "wireless",
        "energy-saving",
        "intent"
      ]
    },
    {
      "id": "ran-es-intent-lifecycle-management",
      "name": "RAN ES Intent Lifecycle Management",
      "description": "Manage the lifecycle of RAN energy-saving intents, including creating, modifying, deleting, activating, and deactivating intents, and performing data collection, analysis, solution formulation, and configuration.",
      "tags": [
        "wireless",
        "energy-saving",
        "intent"
      ]
    },
    {
      "id": "ran-es-intent-reporting",
      "name": "RAN ES Intent Reporting",
      "description": "Provide intent report query, subscription, and notification functions, reporting intent fulfillment status, achieved values, recommended values, and configuration modification information.",
      "tags": [
        "wireless",
        "energy-saving",
        "reporting"
      ]
    }
  ]
}
```

### Tag Management

Administrator: Create, read, update, and delete tags
```bash
# Create a tag
agent-registry> tag create --name mytag

==================================================
[OK] Tag created successfully
==================================================
Tag ID: 5946abd2-8862-4109-bbb9-6d62d2672bfd
Tag Name: mytag

# List all tags
agent-registry> tag list
Found 1 tags:
  5946abd2-8862-4109-bbb9-6d62d2672bfd: mytag (created: 2026-05-15T08:06:24)

# Update a tag
agent-registry> tag update --id 5946abd2-8862-4109-bbb9-6d62d2672bfd --name mytag1

==================================================
[OK] Tag updated successfully
==================================================
Tag ID: 5946abd2-8862-4109-bbb9-6d62d2672bfd
New Name: mytag1

# Query a tag
agent-registry> tag get --name mytag1
Tag ID: 5946abd2-8862-4109-bbb9-6d62d2672bfd
Tag Name: mytag1
Created: 2026-05-15T08:06:24.605982
Updated: 2026-05-15T08:06:52.766866

# Delete a tag
agent-registry> tag delete --id  5946abd2-8862-4109-bbb9-6d62d2672bfd

==================================================
[OK] Tag deleted successfully
==================================================
agent-registry> tag list
No tags found
agent-registry>
```

## API Capabilities

- **Register AgentCard**: Supports registering Agents from different vendors into the center for unified management. See [Registry Center API Reference](./Registry Center API Reference.md#register-agentcard).
- **Query AgentCard List**: Query a list of AgentCards matching specified criteria. See [Registry Center API Reference](./Registry Center API Reference.md#query-agentcard-list).
- **Get Specific AgentCard**: Precisely locate a unique AgentCard instance by AgentCard name and organization. See [Registry Center API Reference](./Registry Center API Reference.md#get-specific-agentcard).
- **Update Specific AgentCard**: Update the information of a specific AgentCard. See [Registry Center API Reference](./Registry Center API Reference.md#update-specific-agentcard).
- **Delete Specific AgentCard**: Delete an AgentCard that is no longer in use. See [Registry Center API Reference](./Registry Center API Reference.md#delete-specific-agentcard).
- **Semantic Search AgentCard**: Search for matching AgentCards based on natural language semantics. See [Registry Center API Reference](./Registry Center API Reference.md#semantic-search-agentcard).

## Appendix

## Configuration File Quick Reference

### Service Configuration (etc/conf/server.conf)

| Configuration Item | Description | Default |
|--------------------|-------------|---------|
| IP | Service listening IP | 127.0.0.1 |
| PORT | Service listening port | 5000 |
| enable_https | Enable HTTPS | true |
| ssl_certfile | Service certificate path | etc/ssl/server.cer |
| ssl_keyfile | Service private key path | etc/ssl/server_key.pem |
| signature_validation_enabled | Signature verification switch | true |
| agent_approval_enabled | Approval switch | false |
| use_vectordb | Enable vector database | false |

### Persistence Configuration (etc/conf/persistence.conf)

| Configuration Item | Description | Default |
|--------------------|-------------|---------|
| persistence.mode | Storage mode (file/postgresql) | file |
| postgresql.host | PostgreSQL host | 127.0.0.1 |
| postgresql.port | PostgreSQL port | 5432 |
| postgresql.name | Database name | registry_center |

### Advanced Configuration (etc/conf/server.properties)

| Configuration Item | Description | Default |
|--------------------|-------------|---------|
| agent.num.max | Maximum number of Agents | 100 |
| connection.max | Maximum connections | 500 |
| connection.timeout | Timeout (seconds) | 300 |

## Error Code Quick Reference

| Error Code | Description |
|------------|-------------|
| 400 | Parameter validation failed |
| 401 | Signature verification failed |
| 403 | Permission denied (owner mismatch) |
| 404 | Agent not found |
| 409 | Duplicate registration or quantity limit exceeded |
| 413 | Request body too large |
| 414 | URL too long |
| 422 | Data validation failed (blacklist, field restrictions, etc.) |
| 429 | Too many requests |
| 503 | Service busy |
| 504 | Request timeout |

## Data File Description

| File | Description |
|------|-------------|
| data/agentcard.json | AgentCard data (excluding status) |
| data/agentregistry.json | Agent metadata (status, owner, tags, etc.) |
| data/tags.json | Tag entity data |

## FAQ

### Q1: What should I do if "Duplicate Agent" is prompted when registering an Agent?

The (name, organization) combination for this Agent already exists. You need to:
1. Use a different name or organization
2. Or use the update API to modify the existing Agent
3. Or delete first and then register

### Q2: What should I do if signature verification fails?

Possible causes:
1. No signature verification public key configured
2. AgentCard does not include the signatures field
3. Signature algorithm mismatch (only RS256 and ES256 are supported)
4. JKU URL is inaccessible

### Q3: How to disable signature verification?

Modify `etc/conf/server.conf`:
```properties
signature_validation_enabled=false
```

### Q4: How to configure PostgreSQL storage?

1. Modify `etc/conf/persistence.conf`
2. Restart the service after creating the database

### Q5: Can it run in a Windows environment?

Yes. The Registry Center supports Windows environments for development and debugging. The unified entry point is: `python -m agent_registry.start`. On Windows, the built-in service uses the TCP protocol (127.0.0.1:1108).
