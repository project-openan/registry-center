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

import { Fragment, cloneElement } from 'react'
import { useTranslation } from 'react-i18next'
import { History } from 'lucide-react'
import StatusBadge from './status_badge.jsx'
import HistoryTimeline from './history_timeline.jsx'
import { themeColor } from '../registry_center/index.jsx'

// Online first: healthy, then suspect, then offline (incl. never-reported).
const RISK_ORDER = { healthy: 0, suspect: 1, offline: 2, unknown: 2 }

export const formatRelative = (ms, t) => {
    if (!Number.isFinite(ms) || ms < 0) return '-'
    const s = Math.floor(ms / 1000)
    if (s < 60) return t('heartbeat.seconds_ago', { count: s })
    const m = Math.floor(s / 60)
    if (m < 60) return t('heartbeat.minutes_ago', { count: m })
    const h = Math.floor(m / 60)
    if (h < 24) return t('heartbeat.hours_ago', { count: h })
    return t('heartbeat.days_ago', { count: Math.floor(h / 24) })
}

export const formatAbsolute = (iso) => {
    if (!iso) return '-'
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString()
}

const HealthTable = ({ agents, now, onSelect, onToggleHistory, historyAgent, history, historyLoading }) => {
    const { t } = useTranslation()
    const expandedKey = historyAgent ? `${historyAgent.organization}/${historyAgent.name}` : null
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
                        <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/50">
                            <th className="px-4 py-3 text-left text-[11px] font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                                {t('registry.col_name')}
                            </th>
                            <th className="px-4 py-3 text-left text-[11px] font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                                {t('heartbeat.col_status')}
                            </th>
                            <th className="px-4 py-3 text-left text-[11px] font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                                {t('heartbeat.col_last_heartbeat')}
                            </th>
                            <th className="px-4 py-3 text-left text-[11px] font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                                {t('heartbeat.col_changed_at')}
                            </th>
                            <th className="px-4 py-3 text-left text-[11px] font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                                {t('registry.col_actions')}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {sorted.map((agent) => {
                            const key = `${agent.organization}/${agent.name}`
                            const expanded = key === expandedKey
                            return (
                                <Fragment key={key}>
                                    <tr
                                        onClick={() => onSelect(agent)}
                                        className="border-b border-zinc-100 dark:border-zinc-800 last:border-0 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
                                    >
                                        <td className="px-4 py-3">
                                            <div
                                                className="flex items-center gap-3"
                                                title={`${t('registry.col_name')}: ${agent.name}\n${t('registry.col_org')}: ${agent.organization}\n${t('heartbeat.col_description')}: ${agent.description || '-'}`}
                                            >
                                                {agent.icon && (
                                                    <div
                                                        className={`p-2 rounded-lg text-white shadow-sm shrink-0 ${
                                                            agent.layer === 'network' ? 'bg-emerald-500' : themeColor(agent.theme)
                                                        }`}
                                                    >
                                                        {cloneElement(agent.icon, { size: 14 })}
                                                    </div>
                                                )}
                                                <div className="leading-tight min-w-0">
                                                    <div className="text-sm font-black text-zinc-900 dark:text-white truncate">
                                                        {agent.name}
                                                    </div>
                                                    <div className="text-[11px] text-zinc-400 dark:text-zinc-500 truncate max-w-[280px]">
                                                        {agent.description}
                                                    </div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-4 py-3">
                                            <StatusBadge
                                                status={agent.health_status}
                                                pulse={agent.health_status === 'suspect'}
                                            />
                                        </td>
                                        <td className="px-4 py-3 text-xs font-bold text-zinc-500 dark:text-zinc-400 whitespace-nowrap">
                                            {formatRelative(agent.last_heartbeat_at ? now - new Date(agent.last_heartbeat_at).getTime() : NaN, t)}
                                        </td>
                                        <td className="px-4 py-3 text-[11px] font-bold text-zinc-400 dark:text-zinc-500 whitespace-nowrap">
                                            {formatAbsolute(agent.status_changed_at)}
                                        </td>
                                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                                            <button
                                                onClick={() => onToggleHistory(agent)}
                                                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-black border transition-colors ${
                                                    expanded
                                                        ? 'bg-blue-600 hover:bg-blue-500 border-blue-600 text-white'
                                                        : 'bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-300 border-zinc-200 dark:border-zinc-700'
                                                }`}
                                            >
                                                <History size={12} />
                                                {t('heartbeat.switch_to_history')}
                                            </button>
                                        </td>
                                    </tr>
                                    {expanded && (
                                        <tr className="border-b border-zinc-100 dark:border-zinc-800 last:border-0">
                                            <td colSpan={5} className="px-4 py-3 bg-zinc-50/50 dark:bg-zinc-900/40">
                                                {historyLoading ? (
                                                    <div className="h-24 flex items-center justify-center">
                                                        <div className="w-6 h-6 border-2 border-zinc-300 dark:border-zinc-600 border-t-blue-500 rounded-full animate-spin" />
                                                    </div>
                                                ) : (
                                                    <HistoryTimeline history={history} />
                                                )}
                                            </td>
                                        </tr>
                                    )}
                                </Fragment>
                            )
                        })}
                        {sorted.length === 0 && (
                            <tr>
                                <td colSpan={5} className="py-16 text-center text-zinc-400 text-sm font-bold">
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
