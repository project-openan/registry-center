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

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Settings, X, Server, Network, Save } from 'lucide-react'
import {
    getServerConfig,
    setServerConfig,
    defaultIp,
    defaultPort,
} from '@/service/api.js'

const Setting = ({ open, onClose }) => {
    const { t } = useTranslation()
    const stored = getServerConfig() || {}
    const [mode, setMode] = useState(stored.mode || 'ip')
    const [ip, setIp] = useState(stored.ip || defaultIp)
    const [port, setPort] = useState(stored.port || defaultPort)
    const [https, setHttps] = useState(stored.https === true)
    const [nginxUrl, setNginxUrl] = useState(stored.nginxUrl || '')
    const [saved, setSaved] = useState(false)

    const handleSave = () => {
        setServerConfig({ mode, ip, port, https, nginxUrl })
        setSaved(true)
        setTimeout(() => window.location.reload(), 700)
    }

    return createPortal(
        <AnimatePresence>
            {open && (
                <motion.div
                    className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    onClick={onClose}
                >
                    <motion.div
                        className="bg-white dark:bg-zinc-900 rounded-[2rem] shadow-2xl w-full max-w-md p-8 animate-modal"
                        initial={{ scale: 0.96, y: 8 }}
                        animate={{ scale: 1, y: 0 }}
                        exit={{ scale: 0.96, y: 8 }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="flex items-center justify-between mb-6">
                            <div className="flex items-center gap-3">
                                <div className="p-3 bg-blue-500/10 text-blue-500 rounded-2xl">
                                    <Settings size={24} />
                                </div>
                                <div>
                                    <h3 className="text-xl font-black text-zinc-900 dark:text-white">
                                        {t('settings.title')}
                                    </h3>
                                    <p className="text-xs text-zinc-500 dark:text-zinc-400">
                                        {t('settings.subtitle')}
                                    </p>
                                </div>
                            </div>
                            <button
                                onClick={onClose}
                                className="p-2 rounded-full hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500 transition-colors"
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <div className="flex gap-2 mb-6 p-1 bg-zinc-100 dark:bg-zinc-800 rounded-2xl">
                            <button
                                onClick={() => setMode('ip')}
                                className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-bold transition-all ${
                                    mode === 'ip'
                                        ? 'bg-white dark:bg-zinc-700 text-blue-500 shadow'
                                        : 'text-zinc-500'
                                }`}
                            >
                                <Server size={14} /> {t('settings.mode_direct')}
                            </button>
                            <button
                                onClick={() => setMode('nginx')}
                                className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-bold transition-all ${
                                    mode === 'nginx'
                                        ? 'bg-white dark:bg-zinc-700 text-blue-500 shadow'
                                        : 'text-zinc-500'
                                }`}
                            >
                                <Network size={14} /> {t('settings.mode_gateway')}
                            </button>
                        </div>

                        {mode === 'ip' ? (
                            <div className="space-y-4">
                                <div>
                                    <label className="block text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400 mb-2">
                                        {t('settings.ip')}
                                    </label>
                                    <input
                                        value={ip}
                                        onChange={(e) => setIp(e.target.value)}
                                        className="w-full px-4 py-3 rounded-2xl bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400 mb-2">
                                        {t('settings.port')}
                                    </label>
                                    <input
                                        value={port}
                                        onChange={(e) => setPort(e.target.value)}
                                        className="w-full px-4 py-3 rounded-2xl bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    />
                                </div>
                                <label className="flex items-center gap-3 cursor-pointer select-none">
                                    <button
                                        type="button"
                                        onClick={() => setHttps((v) => !v)}
                                        className={`relative w-11 h-6 rounded-full transition-colors ${
                                            https ? 'bg-blue-500' : 'bg-zinc-300 dark:bg-zinc-700'
                                        }`}
                                    >
                                        <span
                                            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                                                https ? 'translate-x-5' : ''
                                            }`}
                                        />
                                    </button>
                                    <span className="text-sm text-zinc-700 dark:text-zinc-300">
                                        {t('settings.use_https')}
                                    </span>
                                </label>
                            </div>
                        ) : (
                            <div>
                                <label className="block text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400 mb-2">
                                    {t('settings.gateway_url')}
                                </label>
                                <input
                                    value={nginxUrl}
                                    onChange={(e) => setNginxUrl(e.target.value)}
                                    placeholder="/api/registry-center"
                                    className="w-full px-4 py-3 rounded-2xl bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                                />
                                <p className="text-xs text-zinc-400 mt-2">
                                    {t('settings.gateway_example', { url: '/api/registry-center' })}
                                </p>
                            </div>
                        )}

                        <button
                            onClick={handleSave}
                            className="mt-8 w-full flex items-center justify-center gap-2 py-3.5 rounded-2xl bg-blue-500 hover:bg-blue-600 text-white font-bold shadow-lg hover:shadow-xl transition-all duration-300 hover:-translate-y-0.5"
                        >
                            <Save size={18} />
                            {saved ? t('settings.saved') : t('settings.save')}
                        </button>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>,
        document.body,
    )
}

export default Setting
