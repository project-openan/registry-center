// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0
//
//    Licensed under the Apache License, Version 2.0 (the "License"); you may
//    use this file except in compliance with the License. You may obtain a
//    copy of the License at
//
//         http://www.apache.org/licenses/LICENSE-2.0
//
//    Unless required by applicable law or agreed to in writing, software
//    distributed under the License is distributed on an "AS IS" BASIS,
//    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//    See the License for the specific language governing permissions and
//    limitations under the License.

import { useTranslation } from 'react-i18next'
import StatusBadge from './status_badge.jsx'

// Online first: healthy, then suspect, then offline (incl. never-reported).
const RISK_ORDER = { healthy: 0, suspect: 1, offline: 2, unknown: 2 }

const formatRelative = (ms, t) => {
    if (!Number.isFinite(ms) || ms < 0) return '-'
    const s = Math.floor(ms / 1000)
    if (s < 60) return t('heartbeat.seconds_ago', { count: s })
    const m = Math.floor(s / 60)
    if (m < 60) return t('heartbeat.minutes_ago', { count: m })
    const h = Math.floor(m / 60)
    if (h < 24) return t('heartbeat.hours_ago', { count: h })
    return t('heartbeat.days_ago', { count: Math.floor(h / 24) })
}

const formatAbsolute = (iso) => {
    if (!iso) return '-'
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString()
}

const HealthTable = ({ agents, now, onSelect }) => {
    const { t } = useTranslation()
    const sorted = [...agents].sort((a, b) => {
        const risk = (RISK_ORDER[a.health_status || 'offline'] ?? 2)
            - (RISK_ORDER[b.health_status || 'offline'] ?? 2)
        if (risk !== 0) return risk
        return (a.name || '').localeCompare(b.name || '')
    })

    return (
        <div className="rounded-2xl border bg-white dark:bg-zinc-900 border-zinc-100 dark:border-zinc-800 overflow-hidden animate-in fade-in duration-300">
            <div className="overflow-x-auto custom-scrollbar">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="border-b border-zinc-100 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50">
                            <th className="px-5 py-3 text-left text-sm font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                                {t('heartbeat.col_status')}
                            </th>
                            <th className="px-5 py-3 text-left text-sm font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                                {t('heartbeat.col_agent')}
                            </th>
                            <th className="px-5 py-3 text-left text-sm font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                                {t('heartbeat.col_last_heartbeat')}
                            </th>
                            <th className="px-5 py-3 text-left text-sm font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                                {t('heartbeat.col_changed_at')}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {sorted.map((agent) => (
                            <tr
                                key={`${agent.organization}/${agent.name}`}
                                onClick={() => onSelect(agent)}
                                className="border-b border-zinc-50 dark:border-zinc-800/50 last:border-0 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/40 transition-colors"
                            >
                                <td className="px-5 py-3.5">
                                    <StatusBadge
                                        status={agent.health_status}
                                        pulse={agent.health_status === 'suspect'}
                                    />
                                </td>
                                <td className="px-5 py-3.5">
                                    <div className="font-black text-zinc-900 dark:text-white">
                                        {agent.name}
                                    </div>
                                    <div className="text-sm font-bold text-zinc-400 dark:text-zinc-500">
                                        {agent.organization}
                                    </div>
                                </td>
                                <td className="px-5 py-3.5 font-bold text-zinc-600 dark:text-zinc-300 whitespace-nowrap">
                                    {formatRelative(agent.last_heartbeat_at ? now - new Date(agent.last_heartbeat_at).getTime() : NaN, t)}
                                </td>
                                <td className="px-5 py-3.5 text-sm font-bold text-zinc-400 dark:text-zinc-500 whitespace-nowrap">
                                    {formatAbsolute(agent.status_changed_at)}
                                </td>
                            </tr>
                        ))}
                        {sorted.length === 0 && (
                            <tr>
                                <td colSpan={4} className="h-40 text-center text-zinc-400 text-sm font-bold">
                                    {t('heartbeat.no_agents')}
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

export default HealthTable
