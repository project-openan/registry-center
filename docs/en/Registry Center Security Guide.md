# Registry Center Security Guide

The Registry Center security capabilities are as follows:

- **Secure Communication**: Inter-system interactions use the HTTPS protocol by default, with secure TLS protocol versions and cipher suites.
- **Access Control**: Provides an authentication callback function for custom implementation. AgentCard operation isolation is enforced based on the agent owner, allowing only the agent owner to modify or delete their own AgentCard.
- **Storage Security**: Provides encryption/decryption callback functions for custom implementation to protect sensitive data; sensitive parameters in backend CLI commands use interactive input to prevent sensitive parameters from being logged by the system.
- **Audit Logging**: Default logging to a dedicated log file, recording six key elements of critical operations; also provides an audit log callback function for custom implementation.
- **AgentCard Content Security**: Identifies and blocks AgentCard registrations with malicious intent during the registration phase; validates AgentCard integrity by default and provides registry center signing; provides manual AgentCard review capability.
- **Certificate Generation Tool**: Provides a standalone tool for generating self-signed certificates for debugging scenarios.
- **Signature Verification Public Key Download**: Provides an interface to download the registry center's signature verification public key.

## Secure Communication (Inter-System TLS Communication)

The Registry Center provides REST interfaces such as AgentCard registration, modification, and deletion (refer to the [Registry Center User Guide "API Capabilities" section](https://gitcode.com/OpenAN/registry-center/blob/main/docs/en/Registry%20Center%20User%20Guide.md#api-capabilities)). These interfaces use the HTTPS protocol by default to ensure communication channel security, with secure TLS protocol versions and cipher suites.<br>
- TLS protocol versions: TLSv1.3, TLSv1.2<br>
- Cipher suites: TLS_AES_256_GCM_SHA384,TLS_AES_128_GCM_SHA256,TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384,TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384,TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,TLS_DHE_RSA_WITH_AES_256_GCM_SHA384,TLS_DHE_DSS_WITH_AES_256_GCM_SHA384,TLS_DHE_RSA_WITH_AES_128_GCM_SHA256,TLS_DHE_DSS_WITH_AES_128_GCM_SHA256<br>
> **Note**: Protocol versions and cipher suites do not support modification<br>

The Registry Center's certificates must be prepared by the user in advance. Certificate requirements:<br>
- Identity certificate server.cer:
Required, only PEM encoding format supported<br>
Certificate format: X.509v3<br>
Certificate key algorithm, key length: RSA (>= 3072 bits), ECDSA (>= 256 bits)<br>
Validity period: valid at the current time<br>
Certificate key usage: digital signature, key encipherment<br>
Extended key usage: server authentication<br>

- Private key file server_key.pem:
Required, only PEM encoding format supported<br>
Private key and public key matching: must match the public key in server.cer<br>
The private key file must be protected by a private key password. The private key password must meet complexity requirements: at least 8 characters, containing at least two character types (digits, uppercase letters, lowercase letters, special characters `` `~!@#$%^&*()-_=+ | [{}]);:'",<.>/? `` and spaces)<br>

For debugging scenarios, the [Self-Signed Certificate Generation Tool](#self-signed-certificate-generation-tool) can be used to generate the two certificate files that meet the above requirements. Note that such certificates must not be used in production environments.<br>

- Trust certificate trust.cer:
Required by default, only PEM encoding format supported, only .cer files supported. If multiple certificates are involved, they must be merged into one.<br>
In scenarios where client certificate verification is enabled, this file must exist.<br>
Certificate format verification: X.509v3<br>
Validity period verification: valid at the current time<br>
Key algorithm, length: RSA (>= 3072 bits), ECDSA (>= 256 bits)<br>

- Certificate revocation list revocationlist.crl:
Optional, only PEM encoding format supported, only .crl files supported. If multiple certificates are involved, they must be merged into one. May not exist.<br>
Certificate format verification: X.509v2<br>
Validity period verification: valid at the current time<br>
National cipher (Guomi) certificates are not supported<br>

Minimize permissions for certificate files and their directories (e.g., file permissions 400/600, directory permissions 700), and ensure that the project process has read permission for the files<br>

Configure certificates for the Registry Center using the init command. This command configures relevant certificate paths and interactively inputs the private key password
```bash
# init command client starts and enters the interface
[user@host registry-center-main]# python -m agent_registry.init
Enable HTTPS (y/n, default: true):  y

Configure server TLS certificate (RSA only):
# Supports specifying relative and absolute paths. Relative paths are based on the project root path
Enter server certificate path ssl_certfile: (current: etc/ssl/server.cer): /testdir/test_server.cer
Enter server private key path ssl_keyfile: (current: etc/ssl/serve_key.pem): /testdir/test_key.pem
Enter server trust certificate path ssl_ca_certs: (current: etc/ssl/trust.cer): /testdir/trust.cer
# Certificate revocation list, can be left blank
Enter server CRL file path ssl_cert_certs:
# The password is only required when the ssl_keyfile location is changed from the default
Enter server private key password:
# A prompt appears if the password does not meet complexity requirements
Private key password complexity is low (Include at least two character types), continue using this password? (y/n):  y

# Enable client certificate verification
Enable client certificate verification verify_client (y/n, default: false): y
```

This project only reads and uses these certificates and does not provide certificate management capabilities such as certificate expiration alerts, backup and recovery, etc.<br>
Configuration takes effect after restart<br>

The Registry Center also provides HTTP communication capability. HTTPS can be disabled and HTTP enabled through the initialization configuration command line
```bash
# init command client starts and enters the interface
[user@host registry-center-main]# python -m agent_registry.init
Enable HTTPS (y/n, default: true):  n
```
Configuration takes effect after restart<br>

## Access Control

### Authentication

Provides an authentication callback function for on-demand custom implementation, with no default authentication mechanism. For custom implementation, refer to the [Registry Center Development Guide "Custom Handler Usage" section](./Registry%20Center%20Development%20Guide.md#custom-handler-usage).

### AgentCard Operation Isolation

When the Registry Center has HTTPS communication enabled and client certificate verification enabled, the AgentCard operation isolation feature is enabled by default and can be disabled.<br>
The Registry Center uses the CN field of the client TLS identity certificate as the operator identity, and the operator of the AgentCard registration REST interface as the agent owner.<br>
In the AgentCard modification and deletion REST interfaces, the system checks whether the operator is the agent owner, and only allows the agent owner to modify or delete the AgentCard.<br>

Configuration scenarios where operation isolation is not enabled:<br>
- HTTP communication, or HTTPS communication without client certificate verification;<br>
- HTTPS communication with client certificate verification enabled, but the operation isolation switch is turned off (owner.isolation.enabled is configured as false).<br>
- HTTPS communication with client certificate verification enabled, the operation isolation switch is turned on, the validation mode is relaxed (owner.validation.mode=relaxed), and the operator identity was empty during AgentCard registration.<br>
<br>
In these scenarios, operation isolation is not enforced, and all clients can perform modification and deletion operations on any AgentCard. This mechanism is only suitable for interactions within a trusted domain; otherwise, there is a risk of AgentCard tampering.<br>
```properties
# server.conf configuration file

# Whether to enable owner validation logic
owner.isolation.enabled=true

# Owner validation mode
# strict: Strict mode, CN cannot be empty. If CN is empty, the registration request will be rejected
# relaxed: Relaxed mode, CN can be empty. If CN is empty, operation isolation is not enforced
owner.validation.mode=relaxed
```

## Storage Security

1. Provides encryption/decryption callback functions for custom implementation to protect sensitive data. For custom implementation, refer to the [Registry Center Development Guide "Custom Handler Usage" section](./Registry%20Center%20Development%20Guide.md#custom-handler-usage).

2. Sensitive parameters in backend CLI commands use interactive input to prevent sensitive parameters from being logged by the system. For example, the private key password parameter in the self-signed certificate generation tool, the private key password parameter and database password parameter in the init command.<br>

## Audit Logging

Audit logs are recorded for critical operations and system state changes. The auditable critical operations are:<br>
- Registry Center initialization configuration
- Registry Center service start
- Registry Center service stop
- AgentCard registration
- AgentCard modification
- AgentCard deletion
- AgentCard review
- AgentCard tag setting
- Tag creation
- Tag modification
- Tag deletion

Six key elements of critical operations are recorded: time, client IP, user name, operation name, operation target, and operation result.<br>

There are two recording methods:
1. Default logging to a dedicated log file<br>
File path: log/audit/audit.log<br>
Maximum file size: 5 MB. When the limit is reached, existing log files are renamed in descending order by incrementing their numbers by 1, e.g., audit.log.1 -> audit.log.2, audit.log -> audit.log.1<br>
When the number exceeds 4, the file is aged out and deleted. Smaller numbers correspond to newer logs, and the latest logs are always recorded in audit.log<br>
Maximum number of files: 5: audit.log, audit.log.1, audit.log.2, audit.log.3, audit.log.4<br>
The file size and maximum file count are configurable. The configuration file path is etc/conf/log_config.conf, with the following configuration items:
```properties
audit_log_max_file_size_mb=5
audit_log_backup_count=4
```

The recording format is a JSON string, with examples as follows:<br>
- Service start operation:
```json
{"time": "2026-05-11T13:03:54Z", "clientIP": "", "userName": "root", "level": "Critical", "operationName": "Start Service", "object": "Service", "result": "Success", "details": {"ip": "10.244.183.56", "port": "1107"}}
```
- AgentCard registration operation:<br>
Success scenario:
```json
{"time": "2026-05-06T06:39:05Z", "clientIP": "127.0.0.1", "userName": "", "level": "General", "operationName": "Register Agent", "object": "Agent", "result": "Success", "details": {"agentName": "RAN Energy Saving Agent", "organization": "Huawei", "url": "https://www.huawei.com"}}
```
Failure scenario:
```json
{"time": "2026-05-12T01:43:26Z", "clientIP": "10.25.131.91", "userName": "", "level": "General", "operationName": "Register Agent", "object": "Agent", "result": "Failure", "details": {"agentName": "RAN Energy Saving Agent", "organization": "Huawei", "url": "https://www.huawei.com", "message": "Registration skipped: duplicate agent."}}
```
- AgentCard update operation:<br>
Success scenario:
```json
{"time": "2026-05-08T01:14:44Z", "clientIP": "127.0.0.1", "userName": "", "level": "General", "operationName": "Update Agent", "object": "Agent", "result": "Success", "details": {"name": "RAN Energy Saving Agent", "provider": {"organization": "Huawei", "url": "https://www.huawei.com"}, "description": "Responsible for autonomous closed-loop operation of RAN energy efficiency optimization, including intent exploration, intent implementation, effect evaluation and reporting.", "capabilities": {"streaming": true, "pushNotifications": false}, "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"], "version": "1.0.0", "skills": [{"id": "skill-1", "name": "TestSkill", "description": "Test Skill Description", "tags": ["test", "skill"], "input_modes": ["text/plain"], "output_modes": ["text/plain"]}], "supportedInterfaces": [{"protocolBinding": "GRPC", "protocolVersion": "1.0.0", "url": "http://127.0.0.1:5000/"}]}}
```
Failure scenario:
```json
{"time": "2026-05-08T00:44:48Z", "clientIP": "127.0.0.1", "userName": "", "level": "General", "operationName": "Update Agent", "object": "Agent", "result": "Failure", "details": {"agentName": "RAN Energy Saving Agent", "organization": "Huawei", "url": "https://www.huawei.com", "message": "Invalid agent data: Protocol message AgentCapabilities has no \"pushNotifications\" field."}}
```

- AgentCard deletion operation:
```json
{"time": "2026-05-06T06:45:08Z", "clientIP": "127.0.0.1", "userName": "", "level": "General", "operationName": "Deregister Agent", "object": "Agent", "result": "Failure", "details": {"agentName": "RAN Energy Saving Agent", "organization": "Huawei"}}
```


2. An audit log callback function is also provided for custom implementation.<br>
For custom implementation, refer to the [Registry Center Development Guide "Custom Handler Usage" section](./Registry%20Center%20Development%20Guide.md#custom-handler-usage).

## AgentCard Content Security

AgentCard only supports Chinese and English. AgentCard must not carry sensitive/confidential data or personal information; otherwise, there is a risk of information leakage.<br>

### Blocking AgentCard Registration with Malicious Intent

In the AgentCard registration REST interface, the following fields in the AgentCard are subject to prompt injection validation and high-risk skill checks:<br>
- description
- skill.name
- skill.description
- skill.tags

Registrations containing description keywords from the following blacklist will be rejected. This mechanism is enabled by default and cannot be disabled.<br>

> For the complete blacklist of prompt injection keywords and high-risk skill description keywords, see: [AgentCard Security Registration Specification - Appendix: Complete Blacklist](../../design/AgentCard_Security_Specification.md#7-appendix-complete-blacklist)


### AgentCard Integrity Validation

Checks whether the AgentCard has been tampered with based on the signature field in the AgentCard.<br>
Example of an AgentCard signature, as shown in the signatures field below:<br>
```json
{
  "name": "Energy Saving Agent",
  "description": "Responsible for autonomous closed-loop operation of energy efficiency optimization, including intent exploration, intent implementation, effect evaluation and reporting.",
  ...
  "signatures": [
    {
      "protected": "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpPU0UiLCJraWQiOiJrZXktMSIsImprdSI6Imh0dHBzOi8vZXhhbXBsZS5jb20vYWdlbnQvandrcy5qc29uIn0",
      "signature": "QFdkNLNszlGj3z3u0YQGt_T9LixY3qtdQpZmsTdDHDe3fXV9y9-B3m2-XgCpzuhiLt8E0tV6HXoZKHv4GtHgKQ"
    }
  ]
}
```
The protected field can be decoded to<br>
```json
{"alg":"ES256","typ":"JOSE","kid":"key-1","jku":"https://example.com/agent/jwks.json"}
```
The Registry Center performs signature verification according to the mechanism in https://a2a-protocol.org/latest/specification/#84-agent-card-signing<br>
As long as one signature verification passes, the integrity validation is considered successful.<br>

Signature algorithms supported: RS256, ES256<br>
The signature verification public key can be configured in the backend file: etc/sign_verify/jwks/{organization}/{agentname}.json<br>
The file content is in standard JWKS format, with an example as follows:<br>
```json
{
  "keys": [
    {
      "kty": "RSA",
      "use": "sig",
      "kid": "rsa-key-01",
      "alg": "RS256",
      "n": "0vx7agoebGcQSuu********JzKnqDKgw",
      "e": "AQAB"
    },
    {
      "kty": "EC",
      "use": "sig",
      "kid": "ec-key-01",
      "alg": "ES256",
      "crv": "P-256",
      "x": "MKBCTNIcKUS******KPAqv7D4",
      "y": "4Etl6SRW2Y******tmWWlbbM4IFyM"
    }
  ]
}
```

Alternatively, it can be carried in the jku field of the signature's protected field. The Registry Center will automatically call the interface via the GET method to query the signature public key for verification. Public keys obtained in this way are not cached.<br>

This integrity validation feature is enabled by default and can be disabled.<br>
Disabling method:<br>
init command<br>
```bash
# Start the Registry Center init configuration
[user@host registry-center-main]# python -m agent_registry.init
# Disable AgentCard signature verification
Enable signature validation (y/n, default: true): n
Signature validation disabled
```


### Providing Registry Center Signature

After successful AgentCard registration or modification, a Registry Center signature can be computed for the AgentCard.<br>
The Registry Center performs the signing using the Registry Center's signing key according to the mechanism in https://a2a-protocol.org/latest/specification/#84-agent-card-signing.<br>
The AgentCard signature field queried by the agent client from the Registry Center will include both the original AgentCard signature and the Registry Center signature.<br>

Configure whether to enable this feature in the init command, command example:<br>
Enable registry signing registry.sign.enabled (y/n, default: false): y
<br>

```bash
# init command client starts and enters the interface
[user@host registry-center-main]# python -m agent_registry.init
# Other configuration items

# Enable Registry Center signing
Enable registry signing registry.sign.enabled (y/n, default: false): y

Configure signing certificate (RSA only):
Enter signing certificate path sign_certfile:  /testdir/test_client.cer
# The password is only required when the sign_keyfile location is changed from the default
Enter signing private key path sign_keyfile: /testdir/test_client_key.pem
Enter signing private key password:
# A prompt appears if the password does not meet complexity requirements. You can continue to use this low-complexity password private key after accepting the risk
Private key password complexity is low (At least 8 characters), continue using this password? (y/n):  y
```

This signing feature is enabled by default and requires configuring the Registry Center signing certificate when enabled. Certificate requirements:<br>
- server.cer:
Required, identity certificate, only PEM encoding format supported<br>
Certificate format: X.509v3<br>
Certificate key algorithm, key length: RSA (>= 3072 bits), ECDSA (>= 256 bits)<br>
Validity period: valid at the current time<br>
Certificate key usage: digital signature, key encipherment<br>
Extended key usage: server authentication<br>

- server_key.pem:
Required, private key file, only PEM encoding format supported<br>
Private key and public key matching: must match the public key in server.cer<br>
The private key file must be protected by a private key password. The private key password must meet complexity requirements: at least 8 characters, containing at least two character types (digits, uppercase letters, lowercase letters, special characters `` `~!@#$%^&*()-_=+ | [{}]);:'",<.>/? `` and spaces)<br>

The signature verification public key can be obtained via the GET /rest/v1/registry-center/keys interface. This interface has no request parameters and returns the public key content from the signing public key certificate sign_certfile configured in the init command in standard JWKS format. For the interface definition, refer to the [Registry Center API Reference](./Registry%20Center%20API%20Reference.md#get-public-key-information)<br>

For debugging scenarios, the [Self-Signed Certificate Generation Tool](#self-signed-certificate-generation-tool) can be used to generate the two certificate files that meet the above requirements. Note that such certificates must not be used in production environments.<br>


### AgentCard Manual Review

The Registry Center provides a manual review capability, allowing administrators to review registered Agents from dimensions such as legal and data compliance, business logic and quality, resources and cost.<br>
Disabled by default. Enabling method:<br>
init command line<br>
```bash
# Start the Registry Center init configuration
python -m agent_registry.init
# Configure whether to enable the review switch
Enable agent approval (y/n, default: false): y
Approval function enabled
```
The modification takes effect after restart. If there are agents pending review, the agents must be approved or deleted before the review feature can be disabled.<br>

Agent states include registered and published. In the AgentCard query and semantic search interfaces, only AgentCards in the published state can be queried.<br>
When this feature is not enabled, registered Agents are in the published state by default.<br>
When the review feature is enabled, registered Agents are in the registered state by default, and administrators can query all agent information (including agents whose state is not published) via the CLI command line.<br>
Administrators can further query AgentCards in the registered state via the CLI command line for manual review.<br>
After the administrator approves the agent, they can execute the CLI command to approve the agent, and the agent's state will change to published.<br>
For CLI command line usage, refer to the [Registry Center User Guide "Management Capabilities (CLI)" section](./Registry%20Center%20User%20Guide.md#cli-management), which includes operations such as Agent management and tag management.

## Self-Signed Certificate Generation Tool

Provides a standalone tool for generating self-signed certificates for debugging scenarios. Note that such certificates must not be used in production environments.<br>
When executing the tool from the command line, you must specify the certificate path, private key password, and certificate purpose.<br>
Where:<br>
- The certificate path supports relative path input, relative to the directory where generate_selfsign_cert.py is located<br>
- The private key password is entered interactively<br>

Two certificate purposes are supported: serverAuth and dataSigning. The generated certificates differ in key usage and extended key usage:<br>
1. serverAuth: Generates a TLS communication certificate<br>
Certificate key usage: digital signature, key encipherment<br>
Extended key usage: server authentication<br>
Command line example:<br>
```bash
# python generate_selfsign_cert.py {certificate directory} {certificate type}
python generate_selfsign_cert.py testDir serverAuth
```

2. dataSigning: Generates a signing certificate<br>
Certificate key usage: digital signature, non-repudiation<br>
Command line example:
```bash
mkdir testDir
# python generate_selfsign_cert.py {certificate directory} {certificate type}
python generate_selfsign_cert.py testDir dataSigning
Enter private key password:
Private key password complexity is low (At least 8 characters), continue using this password? (y/n):  y
Successfully generated self-signed certificates in testDir
```

Upon successful execution, a PEM-encoded X.509v3 self-signed certificate will be generated in the specified path:<br>
The certificate key algorithm is RSA, with a key length of 3072, a certificate validity period of 99 years, issuer and subject (CN field of both issuer and subject) are both agent-registry, SAN is not set. Certificate file permissions are 600, and the directory permissions are 700.<br>
