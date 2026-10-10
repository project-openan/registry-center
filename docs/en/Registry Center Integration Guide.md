# Registry Center Third-Party Integration Guide

Registry Center exposes the integration API on a dedicated HTTPS listener. OAuth 2.0 Client Credentials is the recommended integration: obtain an access token and send it using the RFC 6750 form:

```http
Authorization: Bearer <access-token>
```

Registry Center is an OAuth 2.0 Resource Server. It validates tokens; it does not issue tokens or implement interactive login flows. An optional acquisition endpoint delegates client authentication and token issuance to your IAM system.

Configuration boundary: `server.conf` holds switches, listener addresses, authentication modes, IAM endpoints and credential/certificate references; `server.properties` holds timeouts, caching, rate limits, bans and scope authorization policies. Examples below are split by file; define each key only once.

## Authentication modes

### OAuth 2.0 JWT

`etc/conf/server.conf`:

```properties
integration.auth.mode=oauth2_jwt
integration.auth.fingerprint_key=${INTEGRATION_FINGERPRINT_KEY}
integration.oauth2.issuer=https://iam.example.com
integration.oauth2.audience=registry-center
integration.oauth2.jwks_uri=https://iam.example.com/.well-known/jwks.json
```

`etc/conf/server.properties`:

```properties
integration.oauth2.algorithms=RS256
integration.auth.scope_role.registry.admin=nms_oss
integration.auth.scope_role.registry.vendor=vendor_agent
integration.auth.scope_role.registry.read=partner_service
integration.auth.scope_role.registry.audit=analytics_tool
```

The server validates the signature, algorithm, issuer, audience and time claims. JWKS `kid` rotation is supported. Its bounded key-set cache lasts up to 300 seconds; an unknown kid triggers a refresh, and a failed fetch does not extend that lifetime. Use introspection when per-request revocation checks are required. Unmapped scopes grant no role.

### OAuth 2.0 Token Introspection

`etc/conf/server.conf`:

```properties
integration.auth.mode=oauth2_introspection
integration.auth.fingerprint_key=${INTEGRATION_FINGERPRINT_KEY}
integration.oauth2.introspection_uri=https://iam.example.com/oauth2/introspect
integration.oauth2.client_id=${OAUTH_INTROSPECTION_CLIENT_ID}
integration.oauth2.client_secret=${OAUTH_INTROSPECTION_CLIENT_SECRET}
integration.oauth2.issuer=https://iam.example.com
integration.oauth2.audience=registry-center
integration.oauth2.ca_file=
```

`etc/conf/server.properties`:

```properties
integration.oauth2.cache_seconds=0
integration.oauth2.cache_max_entries=1024
integration.oauth2.timeout_seconds=3
```

Use this mode for opaque tokens or JWTs requiring online revocation checks. HTTPS certificate and hostname verification are mandatory. The default is **one IAM introspection per data request**, with no result cache. IAM determines validity, expiration and revocation; Registry Center also enforces issuer, audience, time claims and scope-to-role mapping. Set `integration.oauth2.ca_file` to a mounted private CA bundle if system roots do not trust IAM (also supported in JWT mode).

If an explicit revocation visibility delay is acceptable, enable a `1..60` second cache. Its LRU capacity defaults to 1024 entries and entries never outlive `exp`. Responses without `exp` are revalidated every time. JWT mode validates locally and cannot discover revocation before expiry/key changes; choose introspection when immediate remote revocation is required.

## Optional token acquisition endpoint

`POST /integration/v1/oauth2/token` exists only on the integration HTTPS listener and returns 404 unless enabled. Main-port APIs are unchanged. Configure the listener/TLS and the introspection settings above, including scope-role mappings, then add:

`etc/conf/server.conf`:

```properties
integration.enabled=true
integration.token.enabled=true
integration.token.provider=oauth2_client_credentials
integration.token.endpoint=https://iam.example.com/oauth2/token
integration.token.ca_file=
```

`etc/conf/server.properties`:

```properties
integration.token.allowed_scopes=registry.read registry.vendor
integration.token.default_scope=registry.read
integration.token.timeout_seconds=3
```

The caller supplies **its own** IAM `client_id` / `client_secret` using `client_secret_basic`. There is no Bearer prerequisite, no shared privileged issuance account and no client-controlled IAM URL. IAM must independently enforce each client's granted scopes and the `registry-center` audience; `allowed_scopes` is an additional gateway ceiling, not an IAM entitlement grant. Configure the token and introspection endpoints for the same issuer/resource. Choose scopes mapping to one role per token; conflicting roles are rejected.

The body is an `application/x-www-form-urlencoded` OAuth form containing only `grant_type=client_credentials` and optional `scope`. Credentials in body/query, duplicate parameters, other grant types and out-of-policy scopes are rejected. For identifiers/secrets with special characters, form-encode each component before Basic encoding (RFC 6749 §2.3.1); the simple curl example assumes unreserved credentials.

```bash
curl -u "$CLIENT_ID:$CLIENT_SECRET" \
  -d 'grant_type=client_credentials&scope=registry.read' \
  https://registry.example.com:5001/integration/v1/oauth2/token
```

Success is a standard OAuth JSON object (`access_token`, `token_type=Bearer`, `expires_in`, `scope`), with `Cache-Control: no-store` and `Pragma: no-cache`. IAM must return a positive integer `expires_in`; the proxy conservatively subtracts acquisition latency. Requested/granted scopes are bounded; unknown upstream fields and refresh tokens are discarded. Acquisition tokens and caller secrets are never persisted or cached. The caller reacquires a token after expiry—Registry Center does not auto-refresh credentials. When mTLS is required on the listener, token callers must also present a valid client certificate.

Private issuance protocols use `TokenAcquisitionProvider` with `register_token_acquisition_provider(id, factory)`, independently of `AuthenticationProvider`. Register the factory in deployment bootstrap code before starting the listener. Adapters authenticate the current caller at IAM, map safe OAuth errors and return `AcquiredToken` with explicit expiry and granted scopes; they must not substitute a shared service token. Clients use the same REST and Bearer contracts regardless of the upstream protocol.

For standalone configuration use `etc/conf/server.conf.example`. Secret `${ENV_VAR}` placeholders are resolved in authentication/acquisition configuration. No real credentials should be committed.

### Static Bearer Token

For deployments without an OAuth 2.0 server, store only an HMAC-SHA-256 token digest:

```properties
credential.operations.identity=operations-service
credential.operations.token_hash=<64-lowercase-hex-digest>
credential.operations.role=nms_oss
```

```properties
integration.auth.mode=static_bearer
integration.auth.fingerprint_key=${INTEGRATION_FINGERPRINT_KEY}
integration.auth.static.hmac_key=${INTEGRATION_TOKEN_HMAC_KEY}
integration.credential.file=etc/conf/integration_credentials.conf
```

Run `python -m agent_registry.integration.token_digest` to generate a digest interactively. Never place a plaintext token in configuration, command lines, logs, or audit records.

### mTLS

```properties
integration.auth.mode=mtls
integration.client_cert=true
```

Identity is derived from the verified TLS peer certificate, never from a client-supplied HTTP header. Map certificate CN values in the credential file:

```properties
credential.vendor.identity=vendor-service
credential.vendor.cn=vendor-service.example
credential.vendor.role=vendor_agent
```

## Client Credentials example

```bash
curl -u "$CLIENT_ID:$CLIENT_SECRET" \
  -d 'grant_type=client_credentials&scope=registry.read' \
  https://iam.example.com/oauth2/token

curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  https://registry.example.com:5001/integration/v1/agent-cards
```

## Error and security semantics

- `401`: missing, malformed, invalid, expired or revoked credential (`invalid_client` on acquisition).
- `403`: authenticated identity lacks the mapped permission.
- `429`: IP pre-authentication, acquisition credential-budget or authenticated-identity rate limit exceeded. Acquisition admission runs before IAM issuance: a private HMAC of the submitted credential isolates attempts, while only IAM-authenticated calls debit identity buckets. Limits are per process and reset on restart; multi-replica deployments need a shared limiter or gateway.
- `503`: IAM timeout, network/TLS failure, unusable acquisition response or provider outage. These do not increment authentication bans; requests still fail closed.
- Only successful acquisition responses contain a complete token. Errors, logs and audit records never do. Shared Uvicorn access logs redact URL queries, including unknown routes and proxy path prefixes, even after main-listener logging reconfiguration. Path logs remain available; use the structured audit trail for authenticated operations.
- JWT, introspection, and static-token validation all fail closed.

Acquisition errors use OAuth `{"error": "..."}`; resource errors retain the existing Registry Center envelope. Bearer 401/403 responses include `WWW-Authenticate`; acquisition 401 challenges Basic authentication. Tokens/credentials must never be placed in URLs. A trusted configured IAM endpoint may contain fixed, non-sensitive query parameters such as `api-version`; client input cannot change the destination. Token request bodies are bounded to 8 KiB and ten seconds (oversized requests return 413, slow bodies 408). Acquisition/introspection/JWKS responses are bounded to 64 KiB; all built-in IAM transports validate TLS and disable redirects and environment proxies. Acquisition's total deadline also covers custom async providers, which must cooperate with cancellation. No automatic retries of issuance requests occur. TLS is preflighted before provider allocation; startup failures propagate, and listener-owned resources are closed on both failed startup and shutdown.

Validation: `python -m pytest -q tests/test_token_acquisition.py tests/test_introspection_lifecycle.py tests/test_integration_oauth_review_regressions.py`, then `python tests/integration_oauth_smoke.py`. The smoke starts the real service with isolated SQLite and a synthetic HTTPS IAM and verifies acquisition, fixed endpoint queries, data access, expiration/revocation, authorization, outage recovery and query-redacted path logs. It does not certify a particular production IAM implementation.

## Private authentication protocols

Private headers are not part of the core contract. Inject them through `CredentialExtractor` and `AuthenticationProvider`; see `samples/custom_auth_provider.py`. Extensions return the same `Principal`, so authorization, throttling, bans, and auditing do not inspect private request fields.

`register_authentication_provider(provider, extractor)` registers shared, business-owned instances, not factories. Main-port and integration-port handlers may invoke them concurrently from different event loops; handlers do not close custom authentication providers. Keep these extensions stateless or safe across threads/event loops, and do not share a loop-bound async client between listeners. The business composition root owns their resource allocation and cleanup. Built-in authentication providers are created separately per listener. This ownership rule concerns authentication providers, not the separate token-acquisition provider lifecycle described above.

Raise `AuthenticationError` with a specific invalid-credential reason only when caller credentials are actually invalid. Unclassified network/internal exceptions and invalid provider return values fail closed with 503 without incrementing bans. Custom acquisition providers must be async, cancellation-cooperative and release owned clients in `aclose()`; synchronous blocking work must not run on the event loop.

## Migration

The former private two-header scheme is no longer built into the core. Prefer OAuth 2.0 Client Credentials. A deployment that cannot migrate immediately can package its old protocol as a business-owned extractor/provider. Integration API paths and the four-role authorization matrix remain unchanged.
