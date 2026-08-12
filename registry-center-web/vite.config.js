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

import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'
import qiankun from 'vite-plugin-qiankun'

// Dev-only: on startup, POST this sub-app's descriptor to the portal so it
// appears in the portal sidebar automatically. Inert under `vite build`
// (configureServer only runs for the dev server).
function portalPublish(descriptor) {
    return {
        name: 'portal-publish',
        configureServer(server) {
            const portalUrl = process.env.PORTAL_URL || 'http://localhost:3000'
            let stopped = false
            let current = null
            const post = async (path, body) => {
                try {
                    await fetch(`${portalUrl}${path}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body),
                    })
                    return true
                } catch (_e) {
                    return false
                }
            }
            const register = async (retries = 0) => {
                if (stopped || !current) return
                if (await post('/__portal__/register', current)) return
                if (retries < 20) setTimeout(() => register(retries + 1), 2000)
            }
            server.httpServer?.on('listening', () => {
                const addr = server.httpServer.address()
                const port = typeof addr === 'object' && addr ? addr.port : descriptor.port
                const { port: _omit, ...rest } = descriptor
                current = { ...rest, entry: `http://localhost:${port}` }
                register()
            })
            const deregister = () => {
                stopped = true
                if (current) post('/__portal__/unregister', { name: current.name }).catch(() => {})
            }
            process.on('SIGINT', () => { deregister(); process.exit(0) })
            process.on('SIGTERM', () => { deregister(); process.exit(0) })
        },
    }
}

// The app can run standalone (base '/') or as a qiankun sub-app (base '/registry-center/').
// base is driven by VITE_BASE so the unified web frontend framework can mount assets under a sub-path.
export default ({ mode }) => {
    const env = loadEnv(mode, import.meta.dirname, '')
    const isHttps = mode === 'https'
    return defineConfig({
        base: env.VITE_BASE || (mode === 'qiankun' ? '/registry-center/' : '/'),
        server: {
            port: 3004,
            // Allow the qiankun host app to fetch this sub-app's entry/assets cross-origin.
            cors: true,
            headers: {
                'Access-Control-Allow-Origin': '*',
            },
            // Dev: proxy same-origin API calls to the registry backend so the browser
            // avoids cross-origin (CORS) and self-signed-certificate issues.
            // Override the target via VITE_BACKEND_TARGET (env) if needed.
            proxy: {
                '/rest/v1/registry-center': {
                    target: env.VITE_BACKEND_TARGET || 'http://127.0.0.1:5000',
                    changeOrigin: true,
                    secure: false,
                },
            },
        },
        plugins: [
            react(),
            qiankun('registry-center', { useDevMode: true }),
            portalPublish({ name: 'registry-center', port: 3004, activeRule: '/registry-center', title: { zh: '注册中心', en: 'Registry Center' }, icon: 'Boxes' }),
            ...(isHttps ? [basicSsl()] : []),
            visualizer({ open: false, filename: 'stats.html', gzipSize: true, brotliSize: true }),
        ],
        resolve: {
            alias: { '@': path.resolve(import.meta.dirname, 'src') },
        },
        build: {
            minify: 'esbuild',
            rollupOptions: {
                output: {
                    manualChunks: (id) => {
                        if (id.includes('node_modules')) {
                            return 'vendor'
                        }
                    },
                },
            },
        },
    })
}
