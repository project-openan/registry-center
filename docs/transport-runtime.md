# 容器传输与认证配置

HTTP、HTTPS、是否验证客户端证书、业务认证与 AgentCard 签名是独立职责。模板没有秘密；.env 与实际 server.conf/PKI 不作为镜像输入。Python 直接解析环境覆盖，不改写挂载的配置文件。

## 注册中心

- SQL 模式使用 PERSISTENCE_MODE=mysql/postgresql 和 DB_HOST/PORT/NAME/USERNAME/PASSWORD；连接职责配置仍在 etc/conf/db，不能混作运行认证配置。
- HTTP 或 HTTPS-no-mTLS 推荐 REGISTRY_OWNER_IDENTITY_MODE=token，复用 integration.auth.* 的标准 Token provider；静态模式要求凭据文件+HMAC/审计指纹 key，OAuth2 使用现有 JWT/introspection 配置。验证后的 Principal.identity 是所有权锚点，owner 只是归属说明。
- 第三方接入端口可独立设置 integration.enable_https=false，但不能与 client_cert=true 或 auth.mode=mtls 组合。默认仍是 HTTPS。
- REGISTRY_ENABLE_HTTPS 和 REGISTRY_VERIFY_CLIENT 分开；关闭客户端校验不会关闭 Token 认证、所有者隔离或签名校验。
- registry.sign.enabled=true 时缺/错签名材料拒绝服务，不再静默返回 unsigned。签名使用 SDK 标准 JWS；未加密签名 key 的空口令归一为 None。既有非标准签名卡片需重新注册/更新后获取标准 JWS。
- JWKS 依据签名准备状态可用，非依据监听协议。registry.public.base_url 指公开入口；通配 bind 不生成 jku。HTTP 消费方使用预置可信公钥，远程 JWKS 仍要求 HTTPS/信任白名单。
- 主端口 Token 的普通角色仅可发现公开卡片，vendor_agent 可写自己的卡片；管理/订阅等使用已授权 integration 操作或管理身份，原有业务所有者检查保留。


## 镜像与挂载

模型使用完整 etc/config/models.yaml，api_key_env/auth.*_env 引用 .env 或 Secret。LLM_CONFIG_FILE 可选择其他挂载；挂载优先于 chat-only 的环境生成，显式选择不存在的文件会拒绝。Compose 使用长格式 bind 并禁止自动创建缺失的模型/凭据文件为目录。

TLS bundle：server.cer、server_key.pem、cert_pwd、trust.cer。验证客户端时还需 CA/可选 CRL；关闭客户端校验时不会因缺 CA/CRL 阻止监听，但 HTTPS 健康探针仍必须有可校验的服务端 CA。服务原有密钥强度/口令规则不变。生产使用企业 CA，开发可使用 generate_selfsign_cert.py。

Linux 应用 UID=10001；只读挂载目录推荐 0700、文件 0600 或组内只读 0440/0640，不得世界可读或组可写。Kubernetes 模板以 subPath 挂载文件到受限镜像目录，Secret 更新需滚动重启。探针必须匹配证书 SAN；mTLS 探针另需客户端证书/私钥。/health 只报告最小健康，不返回业务列表，不能当作真实数据库/模型的持续业务验收。

完整 MySQL/HTTP/HTTPS/Helm 配置见 openan-installation 的 containerized/TRANSPORT_DEPLOYMENT.md。上线前运行真正的镜像、数据库和代理链路验收，不以单元测试通过代替环境验证。
