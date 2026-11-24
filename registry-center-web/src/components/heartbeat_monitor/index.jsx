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
// The surrounding shared layout (stats cards, search box, list/card toggle)
// lives in the registry center page; this component renders only the
// heartbeat view below it.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AnimatePresence, motion } from 'framer-motion'
import { createPortal } from 'react-dom'
import {
    HeartPulse,
    RefreshCw,
    Radio,
    X,
    XCircle,
    LayoutDashboard,
    Bot,
    Code2,
    Info,
    AlertTriangle,
} from 'lucide-react'
import { getAgentsHealth, getAgentsHealthHistory, getAgentCards, getAgentCardsManage, getHealthStreamUrl } from '@/service/api.js'
import { useHealthPolling } from '@/hooks/use_health_polling.js'
import StatusBadge, { STATUS_STYLES } from './status_badge.jsx'
import HealthTable, { formatRelative, formatAbsolute } from './health_table.jsx'
import AgentCard from '../registry_center/agentcard_visualization/index.jsx'
import CodeInspector from '../registry_center/code_inspector/index.jsx'
import { getAgentLayer } from '../registry_center/agent-layer.js'
import { getAssetsBySeed } from '../registry_center/index.jsx'

const TABS = ['all', 'healthy', 'suspect', 'offline']
const POLL_INTERVAL_MS = 5000
const SSE_FALLBACK_POLL_MS = 60000

const HeartbeatMonitor = ({ isDark, api, searchTerm = '', listMode = 'table' }) => {
    const { t } = useTranslation()
    const [activeTab, setActiveTab] = useState('all')
    const [selected, setSelected] = useState(null)
    const [viewMode, setViewMode] = useState('structured')
    const [cardData, setCardData] = useState(null)
    const [rawCardData, setRawCardData] = useState(null)
    // Inline history expansion state for the main table rows.
    const [historyAgent, setHistoryAgent] = useState(null)
    const [historyData, setHistoryData] = useState([])
    const [historyLoading, setHistoryLoading] = useState(false)
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
    // moments ago) are kept until the sweeper cleans them up. Uses the
    // manage list so rows carry the same icon/layer/description identity
    // as the agent-list table.
    const fetchHealth = useCallback(async () => {
        const [healthResp, cardsResp] = await Promise.all([
            getAgentsHealth(undefined, api),
            getAgentCardsManage(api),
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
            const layer = getAgentLayer(c)
            const ui = getAssetsBySeed(c.name, layer)
            return {
                name: c.name,
                organization,
                description: c.description,
                layer,
                icon: ui.icon,
                theme: ui.theme,
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
        setViewMode('structured')
        setCardData(null)
        setRawCardData(null)
        try {
            const cardResp = await getAgentCards(agent.name, agent.organization, api)
            const raw = (cardResp?.agentCards || []).find(
                (c) => c.name === agent.name && c.provider?.organization === agent.organization,
            ) || (cardResp?.agentCards || [])[0]
            if (raw) {
                setRawCardData(raw)
                const modifiedSkills = (raw.skills || []).map(({ inputs, outputs, ...rest }) => rest)
                setCardData({ ...raw, skills: modifiedSkills })
            }
        } catch (_e) {
            // Card stays empty; the drawer shows the no-card hint.
        }
    }, [api])

    // Toggle the inline history expansion of one table row; collapsing the
    // currently expanded row just clears it.
    const toggleHistory = useCallback(async (agent) => {
        const key = `${agent.organization}/${agent.name}`
        if (historyAgent && `${historyAgent.organization}/${historyAgent.name}` === key) {
            setHistoryAgent(null)
            return
        }
        setHistoryAgent(agent)
        setHistoryData([])
        setHistoryLoading(true)
        try {
            const resp = await getAgentsHealthHistory(agent.name, agent.organization, 50, api)
            setHistoryData(resp?.history || [])
        } catch (_e) {
            setHistoryData([])
        } finally {
            setHistoryLoading(false)
        }
    }, [api, historyAgent])

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

    const renderHealthCard = (agent) => {
        const style = STATUS_STYLES[agent.health_status] || STATUS_STYLES.unknown
        return (
            <div
                key={`${agent.organization}/${agent.name}`}
                onClick={() => openDetail(agent)}
                className="group relative p-6 rounded-2xl border cursor-pointer transition-all duration-300 bg-white dark:bg-zinc-900 border-zinc-100 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-600 hover:shadow-lg hover:-translate-y-1 animate-in fade-in duration-300"
            >
                <div className="flex items-start justify-between mb-4">
                    <div className={`p-3 rounded-xl text-white shadow-lg ${style.bar}`}>
                        <Bot size={22} />
                    </div>
                    <StatusBadge
                        status={agent.health_status}
                        pulse={agent.health_status === 'suspect'}
                    />
                </div>

                <h3 className="text-sm font-black text-zinc-900 dark:text-white mb-2 leading-tight truncate">
                    {agent.name}
                </h3>
                <p className="text-[11px] font-bold text-zinc-500 dark:text-zinc-400 truncate mb-4">
                    {agent.organization || '-'}
                </p>

                <div className="flex items-center justify-between pt-3 border-t border-zinc-100 dark:border-zinc-800">
                    <span className="text-[10px] font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                        {t('heartbeat.col_last_heartbeat')}
                    </span>
                    <span className="text-[10px] font-bold text-zinc-500 dark:text-zinc-400 whitespace-nowrap">
                        {formatRelative(
                            agent.last_heartbeat_at
                                ? now - new Date(agent.last_heartbeat_at).getTime()
                                : NaN,
                            t,
                        )}
                    </span>
                </div>
                <div className="flex items-center justify-between mt-1.5">
                    <span className="text-[10px] font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                        {t('heartbeat.col_changed_at')}
                    </span>
                    <span className="text-[10px] font-bold text-zinc-400 dark:text-zinc-500 whitespace-nowrap">
                        {formatAbsolute(agent.status_changed_at)}
                    </span>
                </div>
            </div>
        )
    }

    return (
        <div className="h-full flex flex-col w-full transition-all animate-in fade-in duration-500 overflow-hidden font-sans">
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
                    <div className="shrink-0 flex flex-wrap items-center gap-1 mb-4 px-2">
                        {TABS.map((tab) => (
                            <button
                                key={tab}
                                onClick={() => setActiveTab(tab)}
                                className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-black uppercase tracking-wide transition-all duration-300 ${
                                    activeTab === tab
                                        ? 'bg-blue-500 dark:bg-white text-white dark:text-zinc-900 shadow-md shadow-blue-500/25 hover:bg-blue-600'
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
                                    className={`px-1.5 py-0.5 rounded-md text-[9px] font-black ${
                                        activeTab === tab
                                            ? 'bg-white/20 dark:bg-zinc-900/20'
                                            : 'bg-zinc-100 dark:bg-zinc-800'
                                    }`}
                                >
                                    {tabCounts[tab]}
                                </span>
                            </button>
                        ))}
                        <div className="flex-1" />
                        {config && (
                            <span className="relative group flex items-center gap-1 mr-1.5 text-[10px] font-bold text-zinc-400 dark:text-zinc-500 cursor-help">
                                {t('heartbeat.config_info')}
                                <Info size={12} />
                                <span
                                    className="pointer-events-none absolute top-full right-0 mt-1.5 z-20 hidden group-hover:flex items-center gap-3 whitespace-nowrap px-3 py-2 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 shadow-lg text-[10px] font-bold text-zinc-500 dark:text-zinc-400"
                                >
                                    <span className="flex items-center gap-1">
                                        <RefreshCw size={11} />
                                        {t('heartbeat.config_sweep')}: {config.sweep_interval}s
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <AlertTriangle size={11} />
                                        {t('heartbeat.config_threshold')}: {config.failure_threshold}
                                    </span>
                                </span>
                            </span>
                        )}
                        <button
                            onClick={() => refresh()}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold uppercase bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-300 transition-all"
                        >
                            <RefreshCw size={13} />
                            {t('heartbeat.refresh')}
                        </button>
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
                        ) : listMode === 'cards' ? (
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                                {filteredAgents.map(renderHealthCard)}
                                {filteredAgents.length === 0 && (
                                    <div className="col-span-full h-40 flex items-center justify-center text-zinc-400 text-sm font-bold">
                                        {t('heartbeat.no_agents')}
                                    </div>
                                )}
                            </div>
                        ) : (
                            <HealthTable
                                agents={filteredAgents}
                                now={now}
                                onSelect={openDetail}
                                onToggleHistory={toggleHistory}
                                historyAgent={historyAgent}
                                history={historyData}
                                historyLoading={historyLoading}
                            />
                        )}
                    </div>
                </>
            )}

            {/* Detail drawer — portaled to body so it renders ABOVE the Portal
                shell, mirroring the agent-list drawer. Slides in from the
                right; body toggles between the structured AgentCard and the
                raw JSON inspector. Status history is expanded inline in the
                main table instead. */}
            {createPortal(
                <AnimatePresence>
                    {selected && (
                        <>
                            <motion.div
                                key="overlay"
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                exit={{ opacity: 0 }}
                                className="fixed inset-0 z-[100] bg-black/40 dark:bg-black/60 backdrop-blur-sm"
                                onClick={() => setSelected(null)}
                            />
                            <motion.div
                                key="drawer"
                                initial={{ x: '100%' }}
                                animate={{ x: 0 }}
                                exit={{ x: '100%' }}
                                transition={{ type: 'tween', duration: 0.28, ease: [0.32, 0.72, 0, 1] }}
                                className="fixed top-0 right-0 bottom-0 z-[110] w-full max-w-2xl bg-white dark:bg-zinc-950 shadow-2xl border-l border-zinc-200 dark:border-zinc-800 flex flex-col"
                            >
                                {/* Drawer header */}
                                <div className="p-5 border-b border-zinc-100 dark:border-zinc-800 flex justify-between items-center bg-zinc-50/50 dark:bg-zinc-900/50 shrink-0">
                                    <div className="flex items-center gap-4 min-w-0">
                                        <div className="p-3 rounded-xl text-white shadow-lg bg-blue-600 shrink-0">
                                            <HeartPulse size={24} />
                                        </div>
                                        <div className="min-w-0">
                                            <h2 className="text-lg font-black dark:text-white leading-none truncate">
                                                {selected.name}
                                            </h2>
                                            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                                                <span className="text-[10px] font-bold text-zinc-400 uppercase truncate">
                                                    {selected.organization}
                                                </span>
                                                <StatusBadge
                                                    status={selected.health_status}
                                                    pulse={selected.health_status === 'suspect'}
                                                />
                                            </div>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-3 shrink-0">
                                        <button
                                            onClick={() => setViewMode(viewMode === 'structured' ? 'raw' : 'structured')}
                                            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all text-[11px] font-black uppercase shadow-sm ${
                                                isDark
                                                    ? 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300'
                                                    : 'bg-zinc-100 hover:bg-zinc-200 text-zinc-600'
                                            }`}
                                        >
                                            {viewMode === 'structured' ? <Code2 size={14} /> : <LayoutDashboard size={14} />}
                                            {viewMode === 'structured'
                                                ? t('registry.switch_to_raw')
                                                : t('registry.switch_to_gui')}
                                        </button>
                                        <button
                                            onClick={() => setSelected(null)}
                                            className="p-2 rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                                        >
                                            <X size={20} className="text-zinc-400" />
                                        </button>
                                    </div>
                                </div>
                                {/* Drawer body — structured AgentCard or the raw
                                    JSON in the code inspector, mirroring the
                                    agent-list drawer. */}
                                <div className="flex-1 overflow-y-auto custom-scrollbar">
                                    {!cardData ? (
                                        <div className="h-40 flex items-center justify-center text-zinc-400 text-sm font-bold">
                                            {t('heartbeat.no_card')}
                                        </div>
                                    ) : viewMode === 'structured' ? (
                                        <AgentCard agent={cardData} isDark={isDark} />
                                    ) : (
                                        <CodeInspector
                                            data={rawCardData}
                                            fileName={`${selected.name} AgentCard`}
                                            isDark={isDark}
                                        />
                                    )}
                                </div>
                            </motion.div>
                        </>
                    )}
                </AnimatePresence>,
                document.body,
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
