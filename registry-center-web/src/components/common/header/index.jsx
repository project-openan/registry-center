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

import { useTranslation } from 'react-i18next'
import { Sun, Moon, Settings, Boxes } from 'lucide-react'

const Header = ({ isDark, setIsDark, lang, onLangChange, onOpenSettings }) => {
    const { t } = useTranslation()
    return (
        <header className="h-16 flex items-center justify-between px-6 border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-950/80 backdrop-blur-md z-50 relative">
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg">
                    <Boxes className="text-white" size={22} />
                </div>
                <div className="leading-tight">
                    <h1 className="text-lg font-black text-zinc-900 dark:text-white">
                        Open<span className="text-blue-500">AN</span> {t('nav.title')}
                    </h1>
                    <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-400">
                        {t('nav.subtitle')}
                    </p>
                </div>
            </div>

            <div className="flex items-center gap-2">
                <div className="flex bg-zinc-100 dark:bg-zinc-800 p-1 rounded-full border border-zinc-200 dark:border-zinc-700 shadow-inner">
                    <button
                        onClick={() => onLangChange('zh')}
                        className={`px-4 py-1.5 rounded-full text-xs font-black transition-all ${lang === 'zh' ? 'bg-white dark:bg-zinc-600 text-blue-600 dark:text-white shadow-sm' : 'text-zinc-400'}`}
                    >
                        中
                    </button>
                    <button
                        onClick={() => onLangChange('en')}
                        className={`px-4 py-1.5 rounded-full text-xs font-black transition-all ${lang === 'en' ? 'bg-white dark:bg-zinc-600 text-blue-600 dark:text-white shadow-sm' : 'text-zinc-400'}`}
                    >
                        EN
                    </button>
                </div>
                <button
                    onClick={() => setIsDark(!isDark)}
                    className="w-9 h-9 rounded-full flex items-center justify-center bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
                    title={isDark ? t('header.theme_light') : t('header.theme_dark')}
                >
                    {isDark ? <Sun size={16} /> : <Moon size={16} />}
                </button>
                <button
                    onClick={onOpenSettings}
                    className="w-9 h-9 rounded-full flex items-center justify-center bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
                    title={t('header.settings')}
                >
                    <Settings size={16} />
                </button>
            </div>
        </header>
    )
}

export default Header
