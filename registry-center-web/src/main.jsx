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

import { createRoot } from 'react-dom/client'
import { BrowserRouter, MemoryRouter, Routes, Route } from 'react-router-dom'
import { renderWithQiankun, qiankunWindow } from 'vite-plugin-qiankun/es/helper'
import './index.css'
import './i18n'
import App from './App.jsx'

let root = null

// Single render entry. Under qiankun, props.container is provided by the host
// and a MemoryRouter avoids history conflicts with the portal shell.
function render(props) {
    const container =
        props && props.container
            ? props.container.querySelector('#root') || props.container
            : document.getElementById('root')
    const Router = qiankunWindow.__POWERED_BY_QIANKUN__ ? MemoryRouter : BrowserRouter
    root = createRoot(container)
    root.render(
        <Router>
            <Routes>
                <Route path="/" element={<App />} />
            </Routes>
        </Router>,
    )
}

renderWithQiankun({
    bootstrap() {
        // no global side effects
    },
    mount(props) {
        render(props)
    },
    unmount() {
        if (root) {
            root.unmount()
            root = null
        }
    },
    update() {
        // no-op
    },
})

// Standalone (dev / independent deploy) when not running inside qiankun.
if (!qiankunWindow.__POWERED_BY_QIANKUN__) {
    render({})
}
