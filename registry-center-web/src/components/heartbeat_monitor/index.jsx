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

// Heartbeat monitor: live agent health states built on the registry-center
// heartbeat detection backend. Polls /agents/health and upgrades to SSE
// (/agents/health/stream) when available; polling continues as a fallback.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AnimatePresence, motion } from 'framer-motion'
import {
    Search,
    HeartPulse,
    RefreshCw,
    Radio,
    X,
    XCircle,
    LayoutDashboard,
    History,
    Activity,
} from 'lucide-react'
import { getAgentsHealth, getAgentsHealthHistory, getAgentCards, getHealthStreamUrl } from '@/service/api.js'
import { useHealthPolling } from '@/hooks/use_health_polling.js'
import StatusBadge from './status_badge.jsx'
import StatCards from './stat_cards.jsx'
import HealthTable from './health_table.jsx'
import HistoryTimeline from './history_timeline.jsx'
import AgentCard from '../registry_center/agentcard_visualization/index.jsx'
import CodeInspector from '../registry_center/code_inspector/index.jsx'

const TABS = ['all', 'healthy', 'suspect', 'offline']
const POLL_INTERVAL_MS = 5000
const SSE_FALLBACK_POLL_MS = 60000

const HeartbeatMonitor = ({ isDark, api }) => {
    const { t } = useTranslation()
    const [searchTerm, setSearchTerm] = useState('')
    const [activeTab, setActiveTab] = useState('all')
    const [selected, setSelected] = useState(null)
    const [detailTab, setDetailTab] = useState('card')
    const [cardData, setCardData] = useState(null)
    const [history, setHistory] = useState(null)
    const [now, setNow] = useState(Date.now())
    const [sseConnected, setSseConnected] = useState(false)

    // Local 1s tick drives relative timestamps and freshness bars without
    // waiting for the next poll.
    useEffect(() => {
        const timer = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(timer)
    }, [])

    // Merge the full registered agent list with heartbeat states: every
    // registered agent is listed here; agents that never reported a
    // heartbeat show as "unknown". Health-only entries (deregistered
    // moments ago) are kept until the sweeper cleans them up.
    const fetchHealth = useCallback(async () => {
        const [healthResp, cardsResp] = await Promise.all([
            getAgentsHealth(undefined, api),
            getAgentCards(undefined, undefined, api),
        ])
        const healthAgents = healthResp?.agents || []
        const byKey = {}
        healthAgents.forEach((a) => {
            byKey[`${a.organization}/${a.name}`] = a
        })
        const cards = cardsResp?.agentCards || []
        const cardKeys = new Set()
        const merged = cards.map((c) => {
            const organization = c.provider?.organization || ''
            cardKeys.add(`${organization}/${c.name}`)
            const h = byKey[`${organization}/${c.name}`]
            return {
                name: c.name,
                organization,
                // Agents that never reported are treated as offline.
                health_status: h ? h.health_status : 'offline',
                last_heartbeat_at: h ? h.last_heartbeat_at : null,
                status_changed_at: h ? h.status_changed_at : null,
            }
        })
        healthAgents.forEach((a) => {
            if (!cardKeys.has(`${a.organization}/${a.name}`)) merged.push(a)
        })
        return { agents: merged, config: healthResp?.config || null }
    }, [api])
    const { data, error, loading, refresh } = useHealthPolling(
        fetchHealth,
        sseConnected ? SSE_FALLBACK_POLL_MS : POLL_INTERVAL_MS,
    )

    const agents = useMemo(() => data?.agents || [], [data])
    const config = data?.config || null
    const enabled = config ? config.enabled !== false : true

    // SSE upgrade: push-triggered refresh with polling as fallback. The
    // effect depends only on the `enabled` boolean — never on the config
    // object (whose identity changes every poll) — otherwise the stream is
    // torn down and reopened on every fetch. Errors retry with a backoff.
    useEffect(() => {
        if (!enabled) return undefined
        let source = null
        let retryTimer = null
        let stopped = false
        const connect = () => {
            if (stopped) return
            source = new EventSource(getHealthStreamUrl(api))
            source.onopen = () => setSseConnected(true)
            source.addEventListener('health_changed', () => refresh())
            source.onerror = () => {
                setSseConnected(false)
                if (source) source.close()
                if (!stopped) retryTimer = setTimeout(connect, 15000)
            }
        }
        connect()
        return () => {
            stopped = true
            clearTimeout(retryTimer)
            if (source) source.close()
            setSseConnected(false)
        }
    }, [enabled, refresh, api])

    const openDetail = useCallback(async (agent) => {
        setSelected(agent)
        setDetailTab('card')
        setCardData(null)
        setHistory(null)
        try {
            const [cardResp, historyResp] = await Promise.all([
                getAgentCards(agent.name, agent.organization, api),
                getAgentsHealthHistory(agent.name, agent.organization, 50, api),
            ])
            const raw = (cardResp?.agentCards || []).find(
                (c) => c.name === agent.name && c.provider?.organization === agent.organization,
            ) || (cardResp?.agentCards || [])[0]
            if (raw) {
                const modifiedSkills = (raw.skills || []).map(({ inputs, outputs, ...rest }) => rest)
                setCardData({ ...raw, skills: modifiedSkills })
            }
            setHistory(historyResp?.history || [])
        } catch (_e) {
            setHistory([])
        }
    }, [api])

    const tabCounts = useMemo(
        () => ({
            all: agents.length,
            healthy: agents.filter((a) => a.health_status === 'healthy').length,
            suspect: agents.filter((a) => a.health_status === 'suspect').length,
            offline: agents.filter((a) => a.health_status !== 'healthy' && a.health_status !== 'suspect').length,
        }),
        [agents],
    )

    const filteredAgents = useMemo(() => {
        let result = agents
        if (activeTab !== 'all') {
            result = result.filter((a) => (a.health_status || 'offline') === activeTab)
        }
        if (searchTerm) {
            const term = searchTerm.toLowerCase()
            result = result.filter(
                (a) =>
                    a.name?.toLowerCase().includes(term) ||
                    a.organization?.toLowerCase().includes(term),
            )
        }
        return result
    }, [agents, activeTab, searchTerm])

    return (
        <div className="h-full p-6 flex flex-col w-full transition-all animate-in fade-in duration-500 overflow-hidden font-sans">
            <div className="shrink-0 flex flex-wrap items-center gap-3 mb-6 px-2">
                <div className="relative w-72">
                    <input
                        type="text"
                        placeholder={t('heartbeat.search_placeholder')}
                        className="w-full pl-10 pr-4 py-2.5 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-bold focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 outline-none transition-all dark:text-white"
                        onChange={(e) => setSearchTerm(e.target.value)}
                        value={searchTerm}
                    />
                    <Search className="absolute left-3.5 top-3 text-zinc-400" size={14} />
                </div>
                <div className="flex-1" />
                <div className="flex items-center gap-2 text-sm font-black uppercase tracking-wider">
                    <span
                        className={`w-2 h-2 rounded-full ${
                            sseConnected ? 'bg-emerald-500 shadow-[0_0_6px_#10b981]' : 'bg-zinc-400'
                        } animate-pulse-soft`}
                    />
                    <span className="text-zinc-400 dark:text-zinc-500">
                        {sseConnected ? t('heartbeat.live_sse') : t('heartbeat.live_polling')}
                    </span>
                </div>
                <button
                    onClick={() => refresh()}
                    className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-black uppercase bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-300 transition-all"
                >
                    <RefreshCw size={13} />
                    {t('heartbeat.refresh')}
                </button>
            </div>

            {!enabled ? (
                <div className="flex-1 flex items-center justify-center">
                    <div className="max-w-md p-8 rounded-2xl border bg-white dark:bg-zinc-900 border-zinc-100 dark:border-zinc-800 text-center animate-in fade-in duration-300">
                        <div className="inline-flex p-4 rounded-2xl bg-amber-50 dark:bg-amber-900/20 text-amber-500 mb-4">
                            <HeartPulse size={28} />
                        </div>
                        <h2 className="text-lg font-black text-zinc-900 dark:text-white mb-2">
                            {t('heartbeat.disabled_title')}
                        </h2>
                        <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                            {t('heartbeat.disabled_hint')}
                        </p>
                        <code className="mt-4 inline-block px-4 py-2 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-sm font-bold text-zinc-700 dark:text-zinc-300">
                            heartbeat.enabled=true
                        </code>
                    </div>
                </div>
            ) : (
                <>
                    {config && (
                        <div className="shrink-0 flex flex-wrap items-center gap-x-5 gap-y-1 mb-4 px-2 text-sm font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                            <span className="flex items-center gap-1.5">
                                <Activity size={12} />
                                {t('heartbeat.config_interval')}: {config.interval}s
                            </span>
                            <span>
                                {t('heartbeat.config_threshold')}: {config.failure_threshold}
                            </span>
                            <span>
                                {t('heartbeat.config_grace')}: {config.grace_period}s
                            </span>
                            <span>
                                {t('heartbeat.config_sweep')}: {config.sweep_interval}s
                            </span>
                        </div>
                    )}

                    <div className="shrink-0">
                        <StatCards agents={agents} />
                    </div>

                    <div className="shrink-0 flex items-center gap-1 mb-4 px-2">
                        {TABS.map((tab) => (
                            <button
                                key={tab}
                                onClick={() => setActiveTab(tab)}
                                className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-black uppercase tracking-wide transition-all duration-300 ${
                                    activeTab === tab
                                        ? 'bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 shadow-md'
                                        : 'text-zinc-400 dark:text-zinc-500 hover:text-zinc-600 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800'
                                }`}
                            >
                                {tab === 'all' && <Radio size={14} />}
                                {tab !== 'all' && (
                                    <span
                                        className={`w-2 h-2 rounded-full ${
                                            tab === 'healthy' ? 'bg-emerald-500'
                                                : tab === 'suspect' ? 'bg-amber-500'
                                                    : 'bg-rose-500'
                                        }`}
                                    />
                                )}
                                    {t(tab === 'all' ? 'heartbeat.tab_all' : `heartbeat.status_${tab}`)}
                                <span
                                        className={`px-1.5 py-0.5 rounded-md text-sm font-black ${
                                        activeTab === tab
                                            ? 'bg-white/20 dark:bg-zinc-900/20'
                                            : 'bg-zinc-100 dark:bg-zinc-800'
                                    }`}
                                >
                                    {tabCounts[tab]}
                                </span>
                            </button>
                        ))}
                    </div>

                    <div className="flex-1 overflow-y-auto custom-scrollbar min-h-0 px-2 pb-4">
                        {loading && agents.length === 0 ? (
                            <div className="h-full flex items-center justify-center">
                                <div className="flex flex-col items-center gap-3 text-zinc-400">
                                    <div className="w-8 h-8 border-2 border-zinc-300 dark:border-zinc-600 border-t-blue-500 rounded-full animate-spin" />
                                    <span className="text-sm font-bold uppercase tracking-wider">
                                        {t('heartbeat.loading')}
                                    </span>
                                </div>
                            </div>
                        ) : error && agents.length === 0 ? (
                            <div className="h-full flex items-center justify-center text-zinc-400 text-sm font-bold">
                                {t('heartbeat.load_failed')}
                            </div>
                        ) : (
                            <HealthTable
                                agents={filteredAgents}
                                now={now}
                                onSelect={openDetail}
                            />
                        )}
                    </div>
                </>
            )}

            {selected && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center p-6 bg-black/40 dark:bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
                    <div className="bg-white dark:bg-zinc-950 w-full max-w-5xl h-[85vh] rounded-[2rem] shadow-2xl border border-zinc-200 dark:border-zinc-800 flex flex-col overflow-hidden animate-in zoom-in-95 duration-300">
                        <div className="p-5 border-b border-zinc-100 dark:border-zinc-800 flex justify-between items-center bg-zinc-50/50 dark:bg-zinc-900/50 shrink-0">
                            <div className="flex items-center gap-4">
                                <div className="p-3 rounded-xl text-white shadow-lg bg-blue-600">
                                    <HeartPulse size={24} />
                                </div>
                                <div>
                                    <h2 className="text-lg font-black dark:text-white leading-none">
                                        {selected.name}
                                    </h2>
                                    <div className="flex items-center gap-2 mt-1.5">
                                        <span className="text-sm font-bold text-zinc-400 uppercase">
                                            {selected.organization}
                                        </span>
                                        <StatusBadge status={selected.health_status} pulse={selected.health_status === 'suspect'} />
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-3">
                                <button
                                    onClick={() => setDetailTab(detailTab === 'card' ? 'history' : 'card')}
                                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all text-sm font-black uppercase shadow-sm ${
                                        isDark
                                            ? 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300'
                                            : 'bg-zinc-100 hover:bg-zinc-200 text-zinc-600'
                                    }`}
                                >
                                    {detailTab === 'card' ? <History size={14} /> : <LayoutDashboard size={14} />}
                                    {detailTab === 'card' ? t('heartbeat.switch_to_history') : t('heartbeat.switch_to_card')}
                                </button>
                                <button
                                    onClick={() => setSelected(null)}
                                    className="p-2 rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                                >
                                    <X size={20} className="text-zinc-400" />
                                </button>
                            </div>
                        </div>
                        <div className="flex-1 overflow-y-auto custom-scrollbar">
                            {detailTab === 'card' ? (
                                cardData ? (
                                    <AgentCard agent={cardData} isDark={isDark} />
                                ) : (
                                    <div className="h-40 flex items-center justify-center text-zinc-400 text-sm font-bold">
                                        {t('heartbeat.no_card')}
                                    </div>
                                )
                            ) : (
                                <HistoryTimeline history={history} />
                            )}
                        </div>
                    </div>
                </div>
            )}

            <AnimatePresence>
                {error && agents.length > 0 && (
                    <motion.div
                        initial={{ opacity: 0, x: 24 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: 24 }}
                        className="fixed bottom-6 right-6 z-[300] flex items-center gap-2 px-4 py-3 rounded-2xl shadow-2xl bg-red-500 text-white text-sm font-bold animate-toast"
                    >
                        <XCircle size={18} />
                        <span>{t('heartbeat.refresh_failed')}</span>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}

export default HeartbeatMonitor
