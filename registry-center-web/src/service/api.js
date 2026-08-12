// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0
//
//    Licensed under the Apache License, Version 2.0 (the "License"); you may
//    not use this file except in compliance with the License. You may obtain
//    a copy of the License at
//
//         http://www.apache.org/licenses/LICENSE-2.0
//
//    Unless required by applicable law or agreed to in writing, software
//    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
//    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
//    License for the specific language governing permissions and limitations
//    under the License.

// Registry Center API layer.
// Mirrors the workflow-designer axios wrapper conventions:
//  - dynamic baseURL resolved from localStorage 'server_config'
//  - response interceptor unwraps response.data, emits 'auth-expired' on 401/403
// Auth is mTLS (client certificate) handled by the browser; no bearer token.

import axios from 'axios'

const STORAGE_KEY = 'server_config'
export const defaultIp = '127.0.0.1'
export const defaultPort = '5000'
export const defaultProtocol = 'http://'
const API_PREFIX = '/rest/v1/registry-center'

export const getServerConfig = () => {
    try {
        const raw = localStorage.getItem(STORAGE_KEY)
        if (raw) return { ...JSON.parse(raw) }
    } catch (_e) {
        // ignore malformed config
    }
    return null
}

export const setServerConfig = (cfg) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg))
}

export const getBaseUrl = () => {
    // In dev, always use relative URLs so requests go through the Vite dev server
    // proxy (see vite.config.js). This avoids cross-origin (CORS) regardless of
    // any Direct IP config saved via Settings. To point dev at a different
    // backend, set VITE_BACKEND_TARGET and restart `npm run dev`.
    if (import.meta.env.DEV) {
        return ''
    }
    const cfg = getServerConfig()
    if (!cfg) {
        // Relative: same-origin in prod (serve the built app from the backend/nginx).
        return ''
    }
    if (cfg.mode === 'nginx') {
        const url = (cfg.nginxUrl || '').trim()
        return url || ''
    }
    // mode === 'ip' (default) — only meaningful for the production build.
    const protocol = 'http://'
    const ip = cfg.ip || defaultIp
    const port = cfg.port || defaultPort
    return `${protocol}${ip}:${port}`
}

const REGISTRY_BASE = () => `${getBaseUrl()}${API_PREFIX}`

const api = axios.create({ timeout: 120000 })

api.interceptors.request.use((config) => {
    // mTLS: the browser attaches the client certificate automatically.
    return config
})

api.interceptors.response.use(
    (response) => response.data,
    (error) => {
        const status = error.response && error.response.status
        if (status === 401 || status === 403) {
            window.dispatchEvent(new Event('auth-expired'))
        }
        return Promise.reject(error)
    },
)

// ---- Agent queries ----

export async function getAgentCards(name, organization) {
    const params = {}
    if (name) params.name = name
    if (organization) params.organization = organization
    return api.get(`${REGISTRY_BASE()}/agent-cards`, { params })
}

export async function getAgentCard(name, organization) {
    const encodedOrg = encodeURIComponent(organization)
    const encodedName = encodeURIComponent(name)
    return api.get(`${REGISTRY_BASE()}/agent-cards/${encodedOrg}/${encodedName}`)
}

export async function semanticQueryAgentCards(task, topN) {
    const body = { task }
    const query = topN ? `?top_n=${topN}` : ''
    return api.post(`${REGISTRY_BASE()}/agent-cards/semantic-query${query}`, body)
}

export async function getPublicKeys() {
    return api.get(`${REGISTRY_BASE()}/keys`)
}

export default api
