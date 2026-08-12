# Registry Center Web

Registry Center frontend - Agent CRUD management UI (register / deregister / modify / query), built to match the `workflow-designer` visual style, and publishable as a **qiankun micro-frontend (PIU)** for integration into the unified web frontend framework.

## Tech Stack

React 18 + Vite + Tailwind CSS + lucide-react + framer-motion + i18next + axios. JavaScript/JSX (no TypeScript).

## Develop

```bash
npm install
npm run dev            # standalone at http://localhost:3004
npm run dev:https      # https dev (mTLS backend)
```

Open the Settings (gear icon) to point at the Registry Center backend. Default: `https://127.0.0.1:5000` with API prefix `/rest/v1/registry-center`.

### Backend assumptions (dev)

The backend validates AgentCard signatures by default. For unsigned register/update to succeed in development, set in `etc/conf/server.conf`:

```
signature_validation_enabled=false
owner.isolation.enabled=false
```

Client-certificate (mTLS) auth is handled by the browser; the SPA calls the HTTPS endpoint directly.

## Build

```bash
npm run build          # standalone SPA, base "/"
npm run build:qiankun  # qiankun sub-app, base "/registry-center/"
```

## Lint

```bash
npm run lint
```

## Qiankun (PIU) Integration

`src/main.jsx` exports the qiankun lifecycle (`bootstrap` / `mount` / `unmount`) and auto-detects `window.__POWERED_BY_QIANKUN__`. In standalone mode it mounts into `#root` with a `BrowserRouter`; under qiankun it mounts into the host-provided `props.container` with a `MemoryRouter`.

Register the sub-app in the unified host framework:

```js
import { registerMicroApps } from 'qiankun'

registerMicroApps([
  {
    name: 'registry-center',
    entry: '//host/registry-center/',      // serves web/dist at base '/registry-center/'
    container: '#subapp-container',
    activeRule: '/registry-center',
  },
])
```

Build with `npm run build:qiankun` (sets `VITE_BASE=/registry-center/`) and serve `dist/` under that sub-path.

## Project Structure

```
web/
├─ src/
│  ├─ main.jsx                 # dual-mode entry + qiankun lifecycle
│  ├─ App.jsx                  # theme + header + content + ErrorBoundary
│  ├─ index.css                # Tailwind directives + keyframes
│  ├─ i18n.js · locales/{en,zh}.json
│  ├─ service/api.js           # axios wrapper + agent CRUD
│  └─ components/
│     ├─ common/{header,setting,error_boundary}/index.jsx
│     └─ registry_center/{index,agent_card_form,agent_detail,delete_confirm}/index.jsx
└─ ...
```
