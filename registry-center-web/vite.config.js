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

// STANDALONE dev/build config — the website runs by itself with its own
// shell (Header / theme / i18n) via src/main.jsx.
//
// Portal-plugin integration does NOT use this file — it uses
// vite.bundle.config.js (UMD artifact for the OpenAN Portal).
//
// Dev: proxy same-origin API calls to the registry backend so the browser
// avoids cross-origin (CORS) and self-signed-certificate issues. Override
// the target via VITE_BACKEND_TARGET if needed.
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'

export default ({ mode }) => {
    const env = loadEnv(mode, import.meta.dirname, '')
    const isHttps = mode === 'https'
    return defineConfig({
        base: env.VITE_BASE || '/',
        server: {
            port: 3004,
            cors: true,
            headers: {
                'Access-Control-Allow-Origin': '*',
            },
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
