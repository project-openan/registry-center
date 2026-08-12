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

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Header from '@/components/common/header/index.jsx'
import Setting from '@/components/common/setting/index.jsx'
import { ErrorBoundary } from '@/components/common/error_boundary/index.jsx'
import AgentRegistry from '@/components/registry_center/index.jsx'

const MainContainer = () => {
    const { i18n } = useTranslation()
    const [isDark, setIsDark] = useState(() => localStorage.getItem('theme') !== 'light')
    const [lang, setLang] = useState(() => localStorage.getItem('lang') || i18n.language || 'zh')
    const [settingsOpen, setSettingsOpen] = useState(false)
    const isEmbedded = typeof window !== 'undefined' && window.self !== window.top

    useEffect(() => {
        const root = document.documentElement
        if (isDark) {
            root.classList.add('dark')
            root.style.colorScheme = 'dark'
        } else {
            root.classList.remove('dark')
            root.style.colorScheme = 'light'
        }
        if (!isEmbedded) localStorage.setItem('theme', isDark ? 'dark' : 'light')
    }, [isDark, isEmbedded])

    useEffect(() => {
        i18n.changeLanguage(lang)
        if (!isEmbedded) localStorage.setItem('lang', lang)
    }, [lang, i18n, isEmbedded])

    useEffect(() => {
        const onAuthExpired = () => setSettingsOpen(true)
        window.addEventListener('auth-expired', onAuthExpired)
        return () => window.removeEventListener('auth-expired', onAuthExpired)
    }, [])

    // When embedded in the portal, sync theme/lang from the portal (applied via
    // the effects above, which skip localStorage while embedded).
    useEffect(() => {
        const handler = (e) => {
            const d = e.data
            if (d && d.type === 'portal-prefs') {
                setIsDark(d.theme === 'dark')
                setLang(d.lang)
            }
        }
        window.addEventListener('message', handler)
        if (isEmbedded) {
            window.parent.postMessage({ type: 'portal-prefs-request' }, '*')
        }
        return () => window.removeEventListener('message', handler)
    }, [isEmbedded])

    return (
        <div className="h-screen flex flex-col bg-zinc-50 dark:bg-[#09090B] overflow-hidden font-sans transition-colors duration-500">
            {!isEmbedded && (
                <Header
                    isDark={isDark}
                    setIsDark={setIsDark}
                    lang={lang}
                    onLangChange={setLang}
                    onOpenSettings={() => setSettingsOpen(true)}
                />
            )}
            <main className="flex-1 min-h-0 relative overflow-hidden">
                <div className="h-full w-full relative z-10 visible animate-in">
                    <ErrorBoundary>
                        <AgentRegistry isDark={isDark} />
                    </ErrorBoundary>
                </div>
            </main>
            <Setting open={settingsOpen} onClose={() => setSettingsOpen(false)} />
        </div>
    )
}

export default MainContainer
