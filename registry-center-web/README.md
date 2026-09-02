# Registry Center Web

注册中心前端 — **可独立运行，也可作为 OpenAN Portal 插件集成**。

## 两种运行形态

### 1. 独立运行(自带完整壳)

```bash
npm install
npm run dev
# → http://localhost:3004 (自带 Header/主题/语言切换)
```

后端代理:同源 `/rest/v1/registry-center/*` → `VITE_BACKEND_TARGET`(默认 `http://127.0.0.1:5000`)。

### 2. 作为 OpenAN Portal 插件(纯内容组件)

```bash
npm run build:plugin
# → dist-plugin/
#   ├── index.js              UMD,挂 window.__OPENAN_PLUGIN__registry_center
#   ├── index.css             编译后样式
#   └── plugin.manifest.json  运行时元数据
```

Portal 侧集成(二选一):

**本地加载** — 产物复制到 Portal:
```bash
cp dist-plugin/* <Portal>/portal/public/plugins/registry-center/
```
Portal `plugins.config.js`:
```js
{ id: 'registry-center', mode: 'bundle', entry: '/plugins/registry-center', enabled: true }
```

**远程加载** — 产物部署在本仓库服务器(nginx + CORS):
```nginx
location /plugins/registry-center/ {
    alias /usr/share/nginx/html/plugins/registry-center/;
    add_header Access-Control-Allow-Origin *;
}
```
```js
{ id: 'registry-center', mode: 'bundle',
  entry: 'http://registry-center:5000/plugins/registry-center', enabled: true }
```

## 架构

```
src/
├── main.jsx                        ← 独立运行入口(自带壳:Header/主题/i18n)
├── index.jsx                       ← Portal 插件入口(纯内容组件,消费 PortalContext)
├── App.jsx                         ← 独立模式应用壳
├── components/
│   ├── registry_center/            ← 业务组件(AgentRegistry,接受注入的 api)
│   └── common/                     ← 独立模式的壳组件(header/setting/error_boundary)
├── service/api.js                  ← API 层(可注入 Portal 的 axios 实例)
├── i18n.js + locales/              ← 国际化(en/zh)
plugin.manifest.js                  ← Portal 插件声明(id/menu/routes/i18n/backend)
vite.config.js                      ← 独立模式 dev/build 配置
vite.bundle.config.js               ← 插件 UMD 打包配置
portal-sdk/                         ← @openan/portal-sdk 本地副本(自包含)
```

### 关键设计

- **单一业务组件**: `AgentRegistry` 同时服务两种形态 — 独立模式由 App.jsx 传 `isDark`,插件模式由 `src/index.jsx` 传 `PortalContext.theme/api`
- **API 可注入**: `getAgentCards(name, org, injectedApi)` — 插件模式注入 Portal 的 axios(走 Portal 网关),独立模式用本地实例(同源代理)
- **React external**: 插件产物不打包 react/react-dom/react-i18next/portal-sdk,由 Portal 运行时全局提供(单一 React 实例)

## API

后端真实路径(见 `agent_registry/server.py`):

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rest/v1/registry-center/agent-cards` | 查询 Agent 列表,响应 `{ agentCards: [...] }` |
| POST | `/rest/v1/registry-center/agent-cards` | 注册 Agent(批量) |
| PUT | `/rest/v1/registry-center/agent-cards/{org}/{name}` | 全量更新 |
| DELETE | `/rest/v1/registry-center/agent-cards/{org}/{name}` | 注销 |
| POST | `/rest/v1/registry-center/agent-cards/semantic-query` | 语义检索 |

认证:mTLS(浏览器自动携带客户端证书),无 token。
