# 知识图谱API实现说明

## 概述
知识图谱API提供RESTful接口用于图数据管理，包括节点和关系的CRUD操作、图查询、批量操作以及导入导出功能。

## 包结构

```
agent_registry/knowledge_graph_api/
├── __init__.py               # 导出knowledge_graph_router和相关的驱动管理函数
└── router.py                 # API路由器，定义所有端点
```

## API端点

所有端点路径前缀：`/rest/v1/registry-center/knowledge-graph`

### 节点操作 (Nodes)
- **GET /nodes** - 列出所有节点，支持分页和标签过滤
- **POST /nodes** - 创建节点
- **GET /nodes/{id}** - 通过elementId获取节点
- **PUT /nodes/{id}** - 更新节点属性
- **DELETE /nodes/{id}** - 删除节点（force=true时删除节点及其所有关系）

### 关系操作 (Relationships)
- **GET /relationships** - 列出所有关系，支持分页和类型过滤
- **POST /relationships** - 创建关系（起始节点和结束节点必须存在）
- **GET /relationships/{id}** - 通过elementId获取关系
- **PUT /relationships/{id}** - 更新关系属性
- **DELETE /relationships/{id}** - 删除关系

### 图操作 (Graph)
- **GET /graph** - 获取整个图的节点和关系

### 批量操作 (Bulk)
- **POST /bulk/nodes** - 批量创建节点（最多1000个，原子性操作）
- **POST /bulk/relationships** - 批量创建关系（最多1000个，原子性操作）

### 导入导出
- **POST /import** - 导入图数据
- **GET /export** - 导出图数据（支持按标签或属性过滤）

## 配置

### 数据库配置
```
database.uri=bolt://localhost:7687
database.username=neo4j
database.password=password
```

### 启动数据库服务
```bash
docker run -it --rm --name graph-db-server \
  --publish=7474:7474 --publish=7687:7687 \
  --env NEO4J_AUTH=neo4j/password \
  neo4j:2026.05.0
```

## 使用示例

### 创建节点
```bash
curl -X POST http://localhost:8080/rest/v1/registry-center/knowledge-graph/nodes \
  -H "Content-Type: application/json" \
  -d '{"labels": ["Person"], "properties": {"name": "张三", "age": 30}}'
```

### 创建关系
```bash
curl -X POST http://localhost:8080/rest/v1/registry-center/knowledge-graph/relationships \
  -H "Content-Type: application/json" \
  -d '{"type": "KNOWS", "startNodeId": "node-1-id", "endNodeId": "node-2-id", "properties": {"since": 2020}}'
```

### 批量创建节点
```bash
curl -X POST http://localhost:8080/rest/v1/registry-center/knowledge-graph/bulk/nodes \
  -H "Content-Type: application/json" \
  -d '{
    "nodes": [
      {"labels": ["Person"], "properties": {"name": "张三", "age": 25}},
      {"labels": ["Person"], "properties": {"name": "李四", "age": 30}}
    ]
  }'
```

## 测试

### 运行测试
```bash
python -m pytest tests/test_knowledge_graph_api.py -v
```

### 测试结果
- 18个单元测试，覆盖所有15个API端点
- 验证数据正确写入数据库
- 验证异常处理正确

## OpenAPI规范

文件：`knowledge-graph-openapi.yaml`

包含完整的API路径、参数和响应定义（共15个端点）。
