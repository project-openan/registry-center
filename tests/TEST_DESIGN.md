# 测试用例设计规范（registry-center）

本文件规定"什么算一条合格的测试用例"。CI 据此评审，评审人据此核对。

## 1. 三条基本要求

1. **用例是规格的可执行表达**：每条用例必须显式写明**输入**、**预期输出**、**断言点**。
2. **禁止弱用例**：只调用不校验（`assert True`、只有 `mock.assert_called` 而无结果断言）、
   只断言"不抛异常"，都不算合格用例。
3. **每条用例必须能拦截一类错误提交**：断言要落在"可被改坏的行为"上——返回值、异常类型与
   消息、HTTP 状态码、持久化结果、副作用、审计/日志记录、幂等性。如果某处代码被改错而用例
   仍然通过，这条用例就是无效的。

## 2. 用例模板（docstring 必须包含）

```python
def test_tag_empty_name_rejected():
    """TC-TAG-004 | 空标签名必须被拒绝

    输入: tag = {"name": "", "values": ["v1"]}
    预期输出: 抛出 TagValidationError，message 含 "empty"
    断言点: 异常类型 + 异常消息关键字 + 未写入存储
    防回归: 若校验被删除或提前 return，本用例失败
    """
```

用例编号规则：`TC-<模块>-<三位序号>`，模块取简称（CLI / TAG / KG / CERT / STORE / API / SEC …）。
新增用例必须在本文件 §9 的清单里登记一行。

## 3. 覆盖分层（每个模块至少覆盖前四层）

| 层次 | 要求 | 示例 |
|---|---|---|
| 正常路径 | 主流程返回预期值 | 注册 AgentCard → 返回 201 且可查询到 |
| 边界 | 空值/最小/最大/超长/分页越界/编码 | 分页 `page=0`、标签值 129 字符 |
| 异常 | 非法输入 → 具体异常类型与消息、4xx/5xx | 重复注册 → 409 且带冲突字段 |
| 状态 | 幂等、重复提交、事务回滚、并发 | 重复 PUT 同一资源不产生第二条记录 |
| 安全 | 未认证/越权/注入/证书校验失败 | 无 token 访问内部接口 → 401 |
| 并发 | 关键路径竞争与超时 | 连接池耗尽 → 503 而非挂死 |

## 4. 弱用例 vs 强用例

| 弱（不合格） | 强（合格） | 原因 |
|---|---|---|
| `storage.save(card)` 不校验 | `storage.save(card)`；再 `assert storage.get(id).name == card.name` | 只有读回才能发现"写入丢失/字段截断" |
| `assert result is not None` | `assert result == {"status": "ok", "count": 3}` | 非空断言无法发现内容错 |
| `with pytest.raises(Exception)` | `with pytest.raises(TagValidationError, match="empty")` | 宽泛异常会掩盖真实缺陷 |
| 只断言 `mock.called` | 断言入参 + 返回 + 调用次数 | 参数错位也能"通过" |
| 断言内部私有属性实现 | 断言对外可观察行为 | 重构即碎，且拦不住真实错误 |

## 5. 如何证明"能拦截错误提交"

覆盖率只证明"被执行过"，不证明"改错会被发现"。两层验证：

1. **变异测试（每季度或大改后跑一次）**
   ```bash
   pip install mutmut
   mutmut run --paths-to-mutate agent_registry/<关键模块>.py
   mutmut results
   ```
   通过标准：关键模块的变异体被杀率 ≥ 80%。未被杀死的变异体，说明对应用例断言太弱，需补强。
2. **手工变异快检（每次提交前，1 分钟）**
   把关键判定故意改错（如 `if not valid` → `if valid`），跑相关用例，**必须变红**，再改回。
   改错后用例仍绿 = 该路径没有有效断言。

## 6. 覆盖率要求与口径

- **语句覆盖率 ≥ 85%**（`.coveragerc` 中 `fail_under = 85`，CI 强制执行，不达标即失败）。
- 统计口径：`agent_registry` + `common` 全量 Python 代码（排除 tests/venv/__pycache__），
  即"全量后端代码"，当前分母约 12 700 条语句。
- 新增文件不得拉低整体：**单个被测文件覆盖 < 60% 即视为不合格**，需说明理由。
- 覆盖率报告：CI 产出 `coverage.xml` 工件；本地 `pytest --cov --cov-report=html`。

## 7. 本地运行

```bash
pip install -r requirements.txt -r requirements-dev.txt
export PYTHONPATH=.
pytest tests/ -q --cov --cov-report=term-missing        # 全量 + 覆盖率
pytest tests/ -q --cov --cov-report=html                # 生成 HTML 报告
```

数据库相关用例需要真实引擎（否则自动 skip）：

```bash
export PG_TEST_HOST=127.0.0.1 PG_TEST_PORT=5432 PG_TEST_DB=registry_center \
       PG_TEST_USER=opena2a_t PG_TEST_PASSWORD=openA2A_T
export MYSQL_TEST_HOST=127.0.0.1 MYSQL_TEST_PORT=3306 MYSQL_TEST_DB=registry_center \
       MYSQL_TEST_USER=root MYSQL_TEST_PASSWORD=root
```

> **注意 `--cov` 的写法**：请用不带模块名的 `--cov`（source 由 `.coveragerc` 提供）。
> 写成 `--cov=agent_registry.xxx` 会让 pytest-cov 在导入 `a2a`/`protobuf` 之前启动追踪，
> 在本机 venv 稳定触发 `KeyError: 'google.protobuf.*'` 导致 conftest 加载失败——这与用例无关，
> 换一种写法即可。若确实需要单模块统计，用 `coverage run -m pytest ...` + `coverage report --include=...`。

## 8. 现状与基线（2026-11-19）

| 项 | 数值 |
|---|---|
| 测试文件 / 测试函数 | 95 / 2451（含参数化） |
| 执行结果（本地含真实 PG16 + MySQL8） | **2451 passed, 8 skipped, 1 xfailed, 0 failed**，约 113 s |
| 语句覆盖率 | **93.2%**（11517 / 12352，未覆盖 835） |
| CI 门槛 | 85%（`.coveragerc` `fail_under`），不达标即失败 |
| 变异守卫 | `tests/mutation_check.py` 9 个变异体**全部被杀** |

覆盖率从 77.6% 提升到 93.2% 的主要来源：

| 模块 | before | after | 用例文件 |
|---|---|---|---|
| `agent_registry/cli/**` | 48.7% | 97.6%（base 99.4%、commands/agent 97.4%、commands/tag 96.9%、core 93.7%） | `test_cli_coverage.py`、`test_cli_commands_coverage.py` |
| `common/vector_db/**` | 28.7% | 100% | `test_vector_db_coverage.py` |
| `agent_registry/agent_to_graph/graph.py` | 14.0% | 100% | `test_graph_coverage.py` |
| `agent_registry/init.py` | 53.5% | 98.4% | `test_init_coverage.py` |
| `agent_registry/server.py` / `core.py` | 82.8% / 78.2% | 100% / 99.8% | `test_server_coverage.py`、`test_core_coverage.py` |
| `persistence/file_storage.py` | 78.7% | 99.8% | `test_file_storage_coverage.py` |
| `persistence/base.py` / `persistence/__init__.py` | 62.6% / 43.1% | 100% / 95.4% | `test_persistence_layer.py` |
| `health/store.py` | 61.9% | 100% | `test_health_store_coverage.py` |
| `cert/cert_parser.py` + `cert_validater.py` | 56.9% / 75.0% | 93.8% / 100% | `test_cert_coverage.py` |
| `signature/jwk_fetcher.py` | 71.0% | 100% | `test_jwk_fetcher_coverage.py` |
| `common/util/password_util.py` | 15% | 100% | `test_password_policy.py` |

## 9. 新增用例清单（按文件登记）

| 文件 | 用例编号区间 | 条数 | 针对模块 |
|---|---|---|---|
| `test_password_policy.py` | TC-PWD-001…013 | 13 | 密码复杂度与交互确认 |
| `test_persistence_layer.py` | TC-STORE-001…021 | 21 | 持久化抽象层与后端分派 |
| `test_cli_coverage.py` | TC-CLI-001…053 | 53 | CLI 核心/上下文/日志/UDS |
| `test_cli_commands_coverage.py` | TC-CLI-101…148 | 48 | `cli/commands/agent.py`、`tag.py` |
| `test_server_coverage.py` | TC-API-001…077 | 77 | REST 路由与错误分支 |
| `test_core_coverage.py` | TC-CORE-001…052 | 52 | 注册/标签/状态机/检索 |
| `test_init_coverage.py` | TC-INIT-001…052 | 52 | 初始化向导与配置生成 |
| `test_file_storage_coverage.py` | TC-STORE-101…142 | 41 | 文件后端（含并发/损坏文件） |
| `test_health_store_coverage.py` | TC-STORE-001…030（内存心跳段） | 21 | 健康状态存储 |
| `test_cert_coverage.py` | TC-CERT-001…058 | 53 | 证书解析与链校验 |
| `test_jwk_fetcher_coverage.py` | TC-JWK-001…035 | 35 | JWK 拉取与缓存 |
| `test_vector_db_coverage.py` | TC-VEC-001…079 | 79 | Milvus 客户端全路径（mock） |
| `test_graph_coverage.py` | TC-GRAPH-001…035 | 35 | Neo4j 路由封装（mock） |
| `test_platform_coverage.py` | TC-DIGEST/CFG/CIPHER/CNCERT/PLUGIN/SSL/AUDQ/LLM/GRAPH-1xx/CARD-1xx | 60 | token_digest、config_reader、cipher_converter、cert_cn_parser、插件注册表、ssl_config、audit_query、llm 门面、图谱 agent、AgentCard 校验器全分支 |
| `test_logging_signing_coverage.py` | TC-LOGSET/AUDIT-1xx/JWKPROV/STG-1xx/PKM-1xx/SCM-1xx | 34 | logger_setup（含轮转压缩）、审计日志（含轮转/线程安全）、JWK 导出、签名存储路径、公钥管理器、签名证书管理器 |
| `test_backend_services_coverage.py` | TC-CONN/PG-2xx/GDB-2xx/MS-2xx/UDS-1xx/INT-1xx/SWEEP-1xx/BCAST-1xx | 41 | 连接助手、PG/GaussDB/MySQL 后端壳（替身）、UDS 客户端全路径、内部服务分发/请求处理、健康清扫器、广播装配 |
| `test_security_messaging_coverage.py` | TC-AUTHN/TOKEN/CRED/DBCFG/APPROVE/CSIGN/GLLM/STORE2/PRECHK/AUTHUTIL/HEALTH2/IDNT/EVBUS/SUBS/TCPI/MSRC/CERTCHK/CSPARSE/CONF | 62 | 认证提取器/提供商、token scope 与表单校验、凭证文件、数据库配置校验、审批状态机、签名校验循环守卫、LLM 模板替换、加载/预检、身份解析、事件总线消费、订阅存储 CRUD、TCP 内部服务、模型源校验、证书预检与解析 |
| `test_kg_router_coverage.py` | TC-KGG/KGD/KGS/KGN/KGR/KGB/KGI/KGE | 41 | 知识图谱 API：kg_guard 授权矩阵、Neo4j 驱动生命周期、节点/关系/批量/导入导出全分支（假驱动直调） |
| `test_broadcast_sql_coverage.py` | TC-DISP/MIG/SQLB/TAGH | 55 | Webhook 调度器（限流降级/重试/恢复/投递）、Milvus layer 迁移、SQL 后端 CRUD/事务分支、UDS tag handler 异常路径 |
| `test_audit_auth_coverage.py` | TC-ASINK/AUD-1xx/VR/LIST/INT2/MAUTH/PKM2/ALOG2/SSL2 | 20 | 审计 MySQL sink 降级/重连、审计镜像、监听器门面、内部服务 accept 循环、主端口 Token 授权矩阵、剩余部分分支 |
| `test_outbox_token_coverage.py` | TC-OBX/CLIC-1xx/START-1xx/TOKIAM-1xx/SMALL-1xx | 47 | outbox 三种持久化模式（聚合状态/剪枝/损坏行/唯一索引失败）、CLI 解析与补全/帮助格式化、启动内部服务与关停信号、IAM token 获取全分支、ban/jwks/signer/watcher/app_config/custom_handle/证书生成等零散缺口 |

## 10. 缺陷修复记录（2026-11-20）

首轮补测发现的 5 个产品缺陷已全部修复，原 `xfail(strict=True)` 用例已转为**强断言回归用例**；
每个修复点同时加入 `tests/mutation_check.py`，改坏即变红。

| 编号 | 位置 | 缺陷 | 修复 |
|---|---|---|---|
| DEFECT-INIT-1 | `agent_registry/init.py` `validate_certificate` | `cert.public_key()` 把属性当方法调用，且 RSA 类型取自不存在的 `x509.RSAPublicKey`，证书校验对任何证书都恒失败 | 改读 `cert.public_key` 属性，补 `None` 守卫（返回 "Certificate has no public key"），RSA 类型改用 `cryptography...asymmetric.rsa.RSAPublicKey`；新增 TC-INIT-021/022/023/026/052 强断言 |
| DEFECT-STORE-1 | `persistence/file_storage.py` `update` | 先 `Parse()` 整个载荷再判断 `status`，proto 无该字段 → 带 status 的更新必然抛 ParseError，分支不可达 | 先剥离 `status` 再 `Parse`，随后写入 `_status_map`；TC-STORE-142 转正 |
| DEFECT-VEC-1 | `milvus_client.py` | 连接失败后 `self.client` 不存在，检索路径抛 `AttributeError`，与其它方法返回 False/[] 不一致 | `__init__` 显式置 `self.client = None`，新增 `_client_ready()` 守卫，9 个公开方法统一降级为空结果；新增 TC-VEC-077/079 |
| DEFECT-VEC-2 | `milvus_client.py` `insert_entity` | 自抛的维度 `ValueError` 被通用 `except` 吞成 False | 新增 `VectorDimensionError(ValueError)` 并 `except ...: raise`；TC-VEC-011/012/078 转正 |
| DEFECT-CLI-1 | `cli/uds_client.py` `send_request` | `connect()` 失败直接 return，socket 只在后面的 finally 关闭 → fd 泄漏 | 失败分支统一 `close()` 后再返回，并补 `OSError` 兜底分支；TC-CLI-043/053 |
| DEFECT-CLI-2 | `cli/__main__.py` | Windows 无 pyreadline3 时的 `FakeReadline` 缺 `set_completer_delims`/`read_history_file` 等，`InteractiveCLI` 构造即崩 | 两处重复桩合并为一个完整 `FakeReadline`（补 4 个方法 + 历史接口）；TC-CLI-046/051 |

回归保护：`tests/mutation_check.py` 覆盖 9 个变异点（MUT-001…009），其中 MUT-006…009 对应上述修复。

已知存量 lint（非本次引入，未处理）：`init.py` 未使用的 `getpass`/`logger` 导入、
`cli/__main__.py` 未使用的 `CLI` 导入与 `except ImportError as e`、`file_storage.py` 两处 B007。

## 11. 覆盖率提升记录（2026-11-25）

语句覆盖率 **93.2% → 98.5%**（12163 / 12353，未覆盖 190）；分支覆盖率（branch 模式）
**91.5% → 93.7%**（3262 / 3482），语句+分支合并 **96.5%**。新增 8 个用例文件、360 条用例
（登记见 §9），全部遵循本文件模板；在无 PG/MySQL 的机器上同样可运行（数据库/socket 路径
全部以替身驱动，并读回持久化结果断言）。

语句覆盖第三轮（`test_outbox_token_coverage.py`，47 条）补齐：outbox 三种模式全路径（含损坏行容错、
版本唯一索引 fail-loud、计数器播种竞态）、CLI 解析/补全/帮助格式化、启动内部服务与关停
信号、IAM token 获取全部校验分支（畸形响应/过期/非对象体/重复注册/并发播种）及 20 个
小文件的零散缺口。

分支覆盖提升主要来源（2026-11-25 第二轮，`test_branch_*.py` 三个文件、116 条用例）：

| 模块 | 分支覆盖 before → after |
|---|---|
| `knowledge_graph_api/router.py` | 75.5% → 99%+（kg_guard 授权矩阵 + 全部端点分支） |
| `broadcast/dispatcher.py` | 83.5% → 97%+（限流降级/重试/恢复/投递异常） |
| `persistence/milvus_layer_migration.py` | 85.3% → 98%+ |
| `internal/handlers/tag_handler.py` | 82.8% → 98%+（5 个 handler 异常路径） |
| `persistence/sql_backend.py` | 93.5% → 97%+（update/delete owner 回退、tag 唯一冲突、事务 rollback-only） |
| `internal/tcp_internal_service.py`、`registry_center_internal_service.py` | accept 循环异常/正常路径 |
| `main_auth.py`、`health/sweeper.py`、`identity.py`、`event_bus.py`、`subscriptions.py` | → 100% |

主要提升来源：

| 模块 | before | after |
|---|---|---|
| `agent_registry/integration/token_digest.py` | 0% | 100% |
| `common/llm/config/config_reader.py` | 0% | 100% |
| `agent_registry/agent_to_graph/agent.py` | 36.4% | 100% |
| `agent_registry/persistence/connection.py` | 21.9% | 100% |
| `agent_registry/persistence/mysql_storage.py` | 34.7% | 98.7% |
| `agent_registry/persistence/gaussdb_storage.py` / `postgresql_storage.py` | 45.8% | 100% |
| `common/llm/llm.py` | 47.1% | 100% |
| `agent_registry/cli/uds_client.py` | 52.4% | 100% |
| `agent_registry/agent_registry/jwk_provider.py` | 60.9% | 96.9% |
| `agent_registry/health/sweeper.py` | 71.2% | 100% |
| `agent_registry/internal/handlers/approval_handler.py` | 92.3% | 100% |
| `agent_registry/broadcast/event_bus.py` | 90.1% | 100% |
| `agent_registry/identity.py` | 91.9% | 100% |
| `agent_registry/model/validated_agentcard.py` | 76.1% | 100% |
| `common/plugin_framework/registry.py` | 75.0% | 100% |
| `common/util/conf_obj.py` / `authenticate_util.py` | 92.2% / 94.5% | 100% / 100% |
| `agent_registry/internal/tcp_internal_service.py` | 87.0% | 98.7% |
| `common/llm/config/model_sources.py` | 89.3% | 99.3% |
| `common/cert/cert_cn_parser.py` | 78.3% | 100% |

### 缺陷修复记录（2026-11-25）

| 编号 | 位置 | 缺陷 | 修复 |
|---|---|---|---|
| DEFECT-JWK-1 | `agent_registry/agent_registry/jwk_provider.py` `_public_key_to_jwk_dict` | 按 `__class__.__name__ == 'EllipticCurvePublicKey'` 分派；cryptography rust 后端的具体类名是 `ECPublicKey`，EC 证书恒被拒（"Unsupported key type: ECPublicKey"），与 DEFECT-INIT-1 同类 | 改为 `isinstance` 分派（`rsa.RSAPublicKey` / `ec.EllipticCurvePublicKey`）；TC-JWKPROV-002（EC P-256）与 TC-JWKPROV-006（Ed25519/secp256k1）转为强断言回归用例 |
| DEFECT-CRED-1 | `agent_registry/integration/credentials.py` `load_credentials` | 凭证文件经 `load_conf_as_dict` 解析，configparser strict 模式下同 id 重复条目抛 DuplicateOptionError 后被吞成 `{}`——**整个凭证文件被静默丢弃**（安全相关：一行笔误移除全部集成凭证），"Duplicate credential id; keeping first" 守卫为死代码 | credentials.py 改用专用 `_load_conf_first_wins` 解析（first-wins + 重复告警），不动全局 load_conf_as_dict 语义；`test_duplicate_credential_id_keeps_first_entry` 由 xfail(strict) 转为强断言回归用例；新增变异守卫 MUT-010 |

> 说明：本轮基线环境无真实 PG16/MySQL8（端口 5432/3306 未开放），存量 DB 集成用例按设计自动
> skip；36 个存量失败（`test_isolated_service_startup.py`、`test_persistence_layer.py` 等）
> 在本轮改动前后完全一致，属环境性失败，非本轮引入。


## 12. Windows 实机环境引入记录（2026-11-25）

本机（Windows 企业版 Python 3.11.9）从「36 failed」修复到「0 failed」，共 5 项环境变更：

| # | 变更 | 解决的失败 | 说明 |
|---|---|---|---|
| 1 | 禁用 Python311\\python311._pth（重命名为 .disabled-by-ut-env，可回滚） | 25 个子进程类失败的总根源 | 该文件使解释器进入隔离模式：忽略 PYTHONPATH 与 cwd，导致 test_container_entrypoint / test_isolated_service_startup / test_integration_access_logging 的子进程全部 ModuleNotFoundError |
| 2 | site-packages\\_registry_center_dev.pth 指向仓库根 | 同上 | 等价 pip install -e .（工程无打包配置），使仓库包在任何 cwd/子进程可导入 |
| 3 | test_cli_coverage.py 10 个 UDS/POSIX readline 用例 + test_persistence_layer.py 1 个 0600 权限用例加 win32 skip 标记 | 11 个物理不可运行用例 | AF_UNIX 与 POSIX 0600 权限在 Windows 不存在；Linux CI 仍全量执行 |
| 4 | test_container_entrypoint.py 换行环境变量参数加 win32 skip | 1 个 | Windows 环境变量值不允许换行符；._pth 禁用后该用例在此平台触发解释器崩溃 |
| 5 | Cloud Run 预检用例改用 -Command 捕获原始异常消息 | 1 个 | PowerShell 5.1 渲染 Write-Error 时按控制台宽度省略截断，完整消息无法到达 stderr |

### 运行器稳定性问题与分块运行器

环境修复后，单进程长跑（超过约 700 条测试且频繁 spawn bash/服务子进程）会触发企业版
Python 3.11.9 的解释器级静默 exit(1)：无 traceback、无 WER 事件、faulthandler 无输出、
崩溃点随机移动。同样测试拆成不超过 636 条的 pytest 进程则稳定全绿。

因此新增 scripts/run_tests_windows.ps1：按整文件贪心分块（默认每块不超过 500 条）、
每块独立 pytest 进程 + junitxml 报告、崩溃自动重试一次、聚合总数。实测：

    TOTAL: passed=2708 skipped=112 failed=0 errors=0   （2820 条全覆盖）

Linux CI 不受影响，仍按 ci.yml 的单进程方式运行。

> 更新（同日）：DEFECT-CRED-1 修复后，原 113 个跳过中的 1 个 xfail 转为常规回归用例，
> 跳过数降为 112；变异守卫增至 10 个（MUT-010）。
