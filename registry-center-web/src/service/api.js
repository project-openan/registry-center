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
import { resolveBaseUrl } from './base_url.js'

const STORAGE_KEY = 'server_config'
export const defaultIp = '127.0.0.1'
export const defaultPort = '5000'
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
    return resolveBaseUrl(getServerConfig(), {
        development: import.meta.env.DEV,
        pageProtocol: window.location.protocol,
    })
}

const REGISTRY_BASE = (injectedApi) => `${injectedApi ? '' : getBaseUrl()}${API_PREFIX}`

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
// All queries accept an optional injected axios instance (Portal plugin mode
// passes PortalContext.api). Falls back to this module's own instance for
// standalone / legacy qiankun mode.

export async function getAgentCards(name, organization, injectedApi) {
    const params = {}
    if (name) params.name = name
    if (organization) params.organization = organization
    const client = injectedApi || api
    return client.get(`${REGISTRY_BASE(injectedApi)}/agent-cards`, { params })
}

// Management view: ALL agent cards (published + registered) with publishStatus
export async function getAgentCardsManage(injectedApi) {
    const client = injectedApi || api
    return client.get(`${REGISTRY_BASE(injectedApi)}/agent-cards/manage`)
}

// Review/approve an agent: registered (unpublished) -> published.
// remark (review reason) is required by the backend and recorded in the
// operation audit log.
export async function publishAgentCard(organization, name, remark, injectedApi) {
    const encodedOrg = encodeURIComponent(organization)
    const encodedName = encodeURIComponent(name)
    const client = injectedApi || api
    return client.post(`${REGISTRY_BASE(injectedApi)}/agent-cards/${encodedOrg}/${encodedName}/publish`, { remark })
}

// Review state machine trail: current status + newest-first transition
// history (from/to status, reason, operator, timestamp) per agent card.
export async function getAgentReviewStatus(organization, name, injectedApi) {
    const encodedOrg = encodeURIComponent(organization)
    const encodedName = encodeURIComponent(name)
    const client = injectedApi || api
    return client.get(`${REGISTRY_BASE(injectedApi)}/agent-cards/${encodedOrg}/${encodedName}/review-status`)
}

// Operation audit log (review/publish actions)
export async function getOperationLogs(limit, injectedApi) {
    const client = injectedApi || api
    const query = limit ? `?limit=${limit}` : ''
    return client.get(`${REGISTRY_BASE(injectedApi)}/operation-logs${query}`)
}

export async function getAgentCard(name, organization, injectedApi) {
    const encodedOrg = encodeURIComponent(organization)
    const encodedName = encodeURIComponent(name)
    const client = injectedApi || api
    return client.get(`${REGISTRY_BASE(injectedApi)}/agent-cards/${encodedOrg}/${encodedName}`)
}

export async function semanticQueryAgentCards(task, topN) {
    const body = { task }
    const query = topN ? `?top_n=${topN}` : ''
    return api.post(`${REGISTRY_BASE()}/agent-cards/semantic-query${query}`, body)
}

export async function getPublicKeys() {
    return api.get(`${REGISTRY_BASE()}/keys`)
}

// ---- Heartbeat & health ----

export async function getAgentsHealth(status, injectedApi) {
    const params = {}
    if (status) params.status = status
    const client = injectedApi || api
    return client.get(`${REGISTRY_BASE(injectedApi)}/agents/health`, { params })
}

export async function getAgentsHealthHistory(name, organization, limit = 50, injectedApi) {
    const params = { limit }
    if (name) params.name = name
    if (organization) params.organization = organization
    const client = injectedApi || api
    return client.get(`${REGISTRY_BASE(injectedApi)}/agents/health/history`, { params })
}

// SSE cannot go through axios — build the absolute URL for native EventSource.
export function getHealthStreamUrl(injectedApi) {
    const url = `${REGISTRY_BASE(injectedApi)}/agents/health/stream`
    return injectedApi?.getUri ? injectedApi.getUri({url}) : url
}

export default api
