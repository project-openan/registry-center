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
