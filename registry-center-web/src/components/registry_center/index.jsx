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

// Merged page: orchestration-center agent-library browse UI (cards + tabs +
// search + RAW/structured detail). Calls the registry-center backend
// (response.agentCards).

import { cloneElement, useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { AnimatePresence, motion } from 'framer-motion'
import {
    Search,
    Code2,
    LayoutDashboard,
    X,
    Layers,
    Server,
    Radio,
    Network,
    Globe,
    CheckCircle2,
    AlertCircle,
    LayoutGrid,
    List,
} from 'lucide-react'
import { getAgentCards } from '@/service/api.js'
import AgentCard from './agentcard_visualization/index.jsx'
import CodeInspector from './code_inspector/index.jsx'

const NETWORK_LAYER_VENDORS = ['huawei', 'ericsson', 'zte', '华为', '爱立信', '中兴']
const SERVICE_LAYER_VENDORS = ['直真', '新大陆', '福诺', '亿阳', '移动']

const getAssetsBySeed = (seed, layer) => {
    const SERVICE_THEMES = ['blue', 'indigo', 'cyan']
    const NETWORK_THEMES = ['emerald', 'amber', 'rose']
    let hash = 0
    for (let i = 0; i < seed.length; i++) {
        hash = seed.charCodeAt(i) + ((hash << 5) - hash)
    }
    const themes = layer === 'network' ? NETWORK_THEMES : SERVICE_THEMES
    return {
        theme: themes[Math.abs(hash) % themes.length],
        icon: layer === 'network' ? <Network size={22} /> : <Server size={22} />,
    }
}

const getAgentLayer = (agent) => {
    const org = (agent.provider?.organization || '').toLowerCase()
    if (NETWORK_LAYER_VENDORS.some((v) => org.includes(v))) return 'network'
    if (SERVICE_LAYER_VENDORS.some((v) => org.includes(v))) return 'service'
    return 'service'
}

const TABS = ['all', 'service', 'network', 'vendor']

// ── Stats cards — bold, colorful, count summary ──

const StatsCard = ({ icon: Icon, label, value, accent, isDark }) => (
    <div
        className="relative overflow-hidden flex items-center gap-5 rounded-2xl border p-6 transition-all hover:shadow-xl hover:-translate-y-1"
        style={{
            background: isDark ? '#18181b' : '#fff',
            borderColor: isDark ? '#27272a' : '#e4e4e7',
        }}
    >
        {/* soft accent glow */}
        <div
            className="absolute -right-6 -top-6 w-28 h-28 rounded-full blur-2xl pointer-events-none"
            style={{ background: accent + (isDark ? '26' : '1a') }}
        />
        <div
            className="w-14 h-14 rounded-2xl grid place-items-center shrink-0 relative"
            style={{ background: accent + (isDark ? '2e' : '1c'), color: accent }}
        >
            <Icon size={26} strokeWidth={2.1} />
        </div>
        <div className="leading-tight min-w-0 relative">
            <div
                className="text-4xl font-black tabular-nums tracking-tight"
                style={{ color: isDark ? '#fafafa' : '#18181b' }}
            >
                {value}
            </div>
            <div
                className="text-sm font-bold truncate mt-1"
                style={{ color: isDark ? '#a1a1aa' : '#71717a' }}
            >
                {label}
            </div>
        </div>
    </div>
)

const StatsBar = ({ agents, isDark }) => {
    const { t } = useTranslation()
    const total = agents.length
    const service = agents.filter((a) => a.layer === 'service').length
    const network = agents.filter((a) => a.layer === 'network').length
    const orgs = new Set(agents.map((a) => a.provider?.organization || 'Unknown')).size

    return (
        <div className="shrink-0 grid grid-cols-2 xl:grid-cols-4 gap-4 mb-5">
            <StatsCard icon={Layers} label={t('registry.stats_total')} value={total} accent="#3b82f6" isDark={isDark} />
            <StatsCard icon={Radio} label={t('registry.stats_service')} value={service} accent="#6366f1" isDark={isDark} />
            <StatsCard icon={Network} label={t('registry.stats_network')} value={network} accent="#10b981" isDark={isDark} />
            <StatsCard icon={Globe} label={t('registry.stats_orgs')} value={orgs} accent="#f59e0b" isDark={isDark} />
        </div>
    )
}

// ── Table row view ──

const renderTableRow = (agent, setSelectedAgent, setViewMode, themeColor, layerBadge, t) => (
    <tr
        key={agent.id}
        onClick={() => {
            setSelectedAgent(agent)
            setViewMode('structured')
        }}
        className="cursor-pointer border-b border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
    >
        <td className="px-4 py-3">
            <div className="flex items-center gap-3">
                <div className={`p-2 rounded-lg text-white shadow-sm ${agent.layer === 'network' ? 'bg-emerald-500' : themeColor(agent.theme)}`}>
                    {cloneElement(agent.icon, { size: 14 })}
                </div>
                <div className="leading-tight">
                    <div className="text-sm font-black text-zinc-900 dark:text-white">{agent.id}</div>
                    <div className="text-[11px] text-zinc-400 dark:text-zinc-500 truncate max-w-[280px]">
                        {agent.description}
                    </div>
                </div>
            </div>
        </td>
        <td className="px-4 py-3">
            <span className={`text-xs font-black px-3 py-1 rounded-lg border uppercase ${layerBadge(agent.layer)}`}>
                {agent.layer === 'network' ? 'Network' : 'Service'}
            </span>
        </td>
        <td className="px-4 py-3 text-xs font-bold text-zinc-500 dark:text-zinc-400">
            {agent.provider?.organization}
        </td>
        <td className="px-4 py-3">
            <div className="flex flex-wrap gap-1 max-w-[220px]">
                {(agent.skills || []).slice(0, 2).map((skill) => (
                    <span
                        key={skill.id}
                        className="px-2 py-0.5 rounded-md text-[9px] font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-zinc-700"
                    >
                        {skill.name}
                    </span>
                ))}
                {(agent.skills || []).length > 2 && (
                    <span className="px-1.5 py-0.5 rounded-md text-[9px] font-bold text-zinc-400 dark:text-zinc-500">
                        +{agent.skills.length - 2}
                    </span>
                )}
            </div>
        </td>
        <td className="px-4 py-3 text-xs font-mono font-bold text-zinc-500 dark:text-zinc-400">
            v{agent.version}
        </td>
        <td className="px-4 py-3 text-[11px] font-bold text-zinc-400 dark:text-zinc-500">
            {agent.skills?.length || 0} {t('registry.skills_count')}
        </td>
    </tr>
)

const AgentRegistry = ({ isDark, api }) => {
    const { t } = useTranslation()
    const [searchTerm, setSearchTerm] = useState('')
    const [agents, setAgents] = useState([])
    const [loading, setLoading] = useState(true)
    const [activeTab, setActiveTab] = useState('all')
    const [selectedAgent, setSelectedAgent] = useState(null)
    const [viewMode, setViewMode] = useState('structured')
    const [listMode, setListMode] = useState('cards')

    const [toast, setToast] = useState(null)

    const showToast = useCallback((messageKey, type) => {
        const id = Date.now()
        setToast({ id, messageKey, type })
        setTimeout(() => setToast((cur) => (cur && cur.id === id ? null : cur)), 3200)
    }, [])

    const fetchData = useCallback(async () => {
        setLoading(true)
        try {
            // injectedApi: Portal plugin mode (PortalContext.api); standalone
            // mode omits it and uses the local service instance.
            const response = await getAgentCards(undefined, undefined, api)
            const rawList = response?.agentCards || []
            const enhancedData = rawList.map((val) => {
                const key = val.name
                const syncedRaw = { ...val, provider: val.provider }
                const modifiedSkills = (syncedRaw.skills || []).map((skill) => {
                    const { inputs, outputs, ...rest } = skill
                    return rest
                })
                const layer = getAgentLayer(syncedRaw)
                const ui = getAssetsBySeed(key, layer)
                return {
                    ...syncedRaw,
                    id: key,
                    displayName: key.toUpperCase(),
                    ...ui,
                    layer,
                    _raw: { ...syncedRaw, skills: modifiedSkills },
                }
            })
            setAgents(enhancedData)
        } catch (_e) {
            showToast('toast.load_failed', 'error')
            setAgents([])
        } finally {
            setLoading(false)
        }
    }, [showToast])

    useEffect(() => {
        fetchData()
    }, [fetchData])

    const filteredAgents = useMemo(() => {
        let result = agents
        if (searchTerm) {
            const term = searchTerm.toLowerCase()
            result = result.filter(
                (a) =>
                    a.id.toLowerCase().includes(term) ||
                    a.description?.toLowerCase().includes(term) ||
                    (a.skills || []).some((s) => s.name?.toLowerCase().includes(term)),
            )
        }
        if (activeTab === 'service') result = result.filter((a) => a.layer === 'service')
        else if (activeTab === 'network') result = result.filter((a) => a.layer === 'network')
        result = [...result].sort((a, b) => {
            const order = { service: 0, network: 1 }
            return (order[a.layer] ?? 2) - (order[b.layer] ?? 2)
        })
        return result
    }, [agents, searchTerm, activeTab])

    const vendorGroups = useMemo(() => {
        const groups = {}
        const source = searchTerm
            ? agents.filter((a) => {
                  const term = searchTerm.toLowerCase()
                  return a.id.toLowerCase().includes(term) || a.description?.toLowerCase().includes(term)
              })
            : agents
        source.forEach((a) => {
            const org = a.provider?.organization || 'Unknown'
            if (!groups[org]) groups[org] = []
            groups[org].push(a)
        })
        Object.values(groups).forEach((arr) =>
            arr.sort((a, b) => {
                const order = { service: 0, network: 1 }
                return (order[a.layer] ?? 2) - (order[b.layer] ?? 2)
            }),
        )
        return groups
    }, [agents, searchTerm])

    const tabCounts = useMemo(
        () => ({
            all: agents.length,
            service: agents.filter((a) => a.layer === 'service').length,
            network: agents.filter((a) => a.layer === 'network').length,
            vendor: Object.keys(vendorGroups).length,
        }),
        [agents, vendorGroups],
    )

    const themeColor = (theme) => {
        const map = {
            emerald: 'bg-emerald-500',
            blue: 'bg-blue-600',
            indigo: 'bg-indigo-500',
            rose: 'bg-rose-500',
            cyan: 'bg-cyan-500',
            amber: 'bg-amber-500',
            violet: 'bg-violet-500',
        }
        return map[theme] || 'bg-blue-600'
    }
    const themeBorder = (theme) => {
        const map = {
            emerald: 'hover:border-emerald-300 dark:hover:border-emerald-700',
            blue: 'hover:border-blue-300 dark:hover:border-blue-700',
            indigo: 'hover:border-indigo-300 dark:hover:border-indigo-700',
            rose: 'hover:border-rose-300 dark:hover:border-rose-700',
            cyan: 'hover:border-cyan-300 dark:hover:border-cyan-700',
            amber: 'hover:border-amber-300 dark:hover:border-amber-700',
            violet: 'hover:border-violet-300 dark:hover:border-violet-700',
        }
        return map[theme] || 'hover:border-blue-300'
    }
    const layerBadge = (layer) =>
        layer === 'network'
            ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800'
            : 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 border-blue-200 dark:border-blue-800'

    const renderCard = (agent) => (
        <div
            key={agent.id}
            onClick={() => {
                setSelectedAgent(agent)
                setViewMode('structured')
            }}
            className={`group relative p-6 rounded-2xl border cursor-pointer transition-all duration-300 bg-white dark:bg-zinc-900 border-zinc-100 dark:border-zinc-800 ${themeBorder(
                agent.theme,
            )} hover:shadow-lg hover:-translate-y-1 animate-in fade-in duration-300`}
        >
            <div className="flex items-start justify-between mb-4">
                <div
                    className={`p-3 rounded-xl text-white shadow-lg ${
                        agent.layer === 'network' ? 'bg-emerald-500' : themeColor(agent.theme)
                    }`}
                >
                    {cloneElement(agent.icon, { size: 22 })}
                </div>
                <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_6px_#10b981]" />
                    <span className="text-[10px] font-black text-zinc-400 dark:text-zinc-500 uppercase">
                        V{agent.version}
                    </span>
                </div>
            </div>

            <h3 className="text-sm font-black text-zinc-900 dark:text-white mb-2 leading-tight truncate">
                {agent.id}
            </h3>
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400 line-clamp-2 mb-4 leading-relaxed min-h-[2.5em]">
                {agent.description}
            </p>

            <div className="flex flex-wrap gap-1.5 mb-4">
                {(agent.skills || []).slice(0, 3).map((skill) => (
                    <span
                        key={skill.id}
                        className="px-2 py-0.5 rounded-md text-[9px] font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-zinc-700"
                    >
                        {skill.name}
                    </span>
                ))}
                {(agent.skills || []).length > 3 && (
                    <span className="px-2 py-0.5 rounded-md text-[9px] font-bold text-zinc-400 dark:text-zinc-500">
                        +{agent.skills.length - 3}
                    </span>
                )}
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-zinc-100 dark:border-zinc-800">
                <div className="flex items-center gap-2">
                    <span
                        className={`text-xs font-black px-4 py-1 rounded-lg border uppercase ${layerBadge(agent.layer)}`}
                    >
                        {agent.layer === 'network' ? 'Network' : 'Service'}
                    </span>
                    <span
                        className={`text-xs font-black px-3 py-1 rounded-lg border ${
                            agent.layer === 'network'
                                ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800'
                                : 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800'
                        }`}
                    >
                        {agent.provider?.organization}
                    </span>
                </div>
                <span className="text-[10px] font-bold text-zinc-400 dark:text-zinc-500">
                    {agent.skills?.length || 0} {t('registry.skills_count')}
                </span>
            </div>
        </div>
    )

    return (
        <div className="h-full p-6 flex flex-col w-full transition-all animate-in fade-in duration-500 overflow-hidden font-sans">
            {/* 1. Stats cards on top */}
            {!loading && <StatsBar agents={agents} isDark={isDark} />}

            {/* 2. Search + view toggle row */}
            <div className="shrink-0 flex items-center justify-between mb-4">
                <div className="relative w-72">
                    <input
                        type="text"
                        placeholder={t('registry.search_placeholder')}
                        className="w-full pl-10 pr-4 py-2.5 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-bold focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 outline-none transition-all dark:text-white"
                        onChange={(e) => setSearchTerm(e.target.value)}
                        value={searchTerm}
                    />
                    <Search className="absolute left-3.5 top-3 text-zinc-400" size={14} />
                </div>
                <div className="flex items-center gap-1 bg-zinc-100 dark:bg-zinc-800 p-1 rounded-xl border border-zinc-200 dark:border-zinc-700">
                    <button
                        onClick={() => setListMode('cards')}
                        title={t('registry.view_cards')}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${listMode === 'cards' ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300'}`}
                    >
                        <LayoutGrid size={14} />
                        {t('registry.view_cards_btn')}
                    </button>
                    <button
                        onClick={() => setListMode('table')}
                        title={t('registry.view_table')}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${listMode === 'table' ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300'}`}
                    >
                        <List size={14} />
                        {t('registry.view_table_btn')}
                    </button>
                </div>
            </div>

            {/* 3. Tabs */}
            <div className="shrink-0 flex items-center gap-1 mb-6 px-2">
                {TABS.map((tab) => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-black uppercase tracking-wide transition-all duration-300 ${
                            activeTab === tab
                                ? 'bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 shadow-md'
                                : 'text-zinc-400 dark:text-zinc-500 hover:text-zinc-600 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800'
                        }`}
                    >
                        {tab === 'all' && <Layers size={14} />}
                        {tab === 'service' && <Radio size={14} />}
                        {tab === 'network' && <Network size={14} />}
                        {tab === 'vendor' && <Globe size={14} />}
                        {t(`registry.tab_${tab}`)}
                        <span
                            className={`px-1.5 py-0.5 rounded-md text-[9px] font-black ${
                                activeTab === tab ? 'bg-white/20 dark:bg-zinc-900/20' : 'bg-zinc-100 dark:bg-zinc-800'
                            }`}
                        >
                            {tabCounts[tab]}
                        </span>
                    </button>
                ))}
            </div>

            {/* Agent list — cards or table */}
            <div className="flex-1 overflow-y-auto custom-scrollbar min-h-0 px-2">
                {loading ? (
                    <div className="h-full flex items-center justify-center">
                        <div className="flex flex-col items-center gap-3 text-zinc-400">
                            <div className="w-8 h-8 border-2 border-zinc-300 dark:border-zinc-600 border-t-blue-500 rounded-full animate-spin" />
                            <span className="text-sm font-bold uppercase tracking-wider">
                                {t('registry.synchronizing')}
                            </span>
                        </div>
                    </div>
                ) : listMode === 'table' ? (
                    /* ── Table view (applies to all tabs) ── */
                    <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden pb-8">
                        <div className="overflow-x-auto">
                            <table className="w-full border-collapse text-sm">
                                <thead>
                                    <tr className="bg-zinc-50 dark:bg-zinc-800/50">
                                        {[
                                            t('registry.col_name'),
                                            t('registry.col_layer'),
                                            t('registry.col_org'),
                                            t('registry.col_skills'),
                                            t('registry.col_version'),
                                            t('registry.col_skills_count'),
                                        ].map((h) => (
                                            <th
                                                key={h}
                                                className="px-4 py-3 text-left text-[11px] font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500 border-b border-zinc-200 dark:border-zinc-800"
                                            >
                                                {h}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {(activeTab === 'vendor'
                                        ? Object.values(vendorGroups).flat()
                                        : filteredAgents
                                    ).map((agent) =>
                                        renderTableRow(agent, setSelectedAgent, setViewMode, themeColor, layerBadge, t),
                                    )}
                                    {(activeTab === 'vendor'
                                        ? Object.values(vendorGroups).flat()
                                        : filteredAgents
                                    ).length === 0 && (
                                        <tr>
                                            <td colSpan={6} className="py-16 text-center text-zinc-400 text-sm font-bold">
                                                {t('registry.no_agents')}
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ) : activeTab === 'vendor' ? (
                    <div className="space-y-8 pb-8">
                        {Object.entries(vendorGroups).map(([org, orgAgents]) => (
                            <div key={org}>
                                <div className="flex items-center gap-3 mb-4">
                                    <div className="p-2 rounded-lg bg-zinc-100 dark:bg-zinc-800">
                                        <Globe size={16} className="text-zinc-500" />
                                    </div>
                                    <h2 className="text-sm font-black text-zinc-700 dark:text-zinc-300 uppercase">
                                        {org}
                                    </h2>
                                    <span className="text-[10px] font-bold text-zinc-400 bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 rounded-full">
                                        {orgAgents.length} {t('registry.units')}
                                    </span>
                                </div>
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                                    {orgAgents.map(renderCard)}
                                </div>
                            </div>
                        ))}
                        {Object.keys(vendorGroups).length === 0 && (
                            <div className="h-64 flex items-center justify-center text-zinc-400 text-sm font-bold">
                                {t('registry.no_agents')}
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-8">
                        {filteredAgents.map(renderCard)}
                        {filteredAgents.length === 0 && (
                            <div className="col-span-full h-64 flex items-center justify-center text-zinc-400 text-sm font-bold">
                                {t('registry.no_agents')}
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Detail drawer — portaled to body so it renders ABOVE the Portal shell
                (the plugin container sits inside an overflow-hidden/relative <main>,
                which would otherwise clip/stack beneath the Portal header). */}
            {selectedAgent && createPortal(
                <AnimatePresence>
                    <>
                        <motion.div
                            key="overlay"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="fixed inset-0 z-[100] bg-black/40 dark:bg-black/60 backdrop-blur-sm"
                            onClick={() => setSelectedAgent(null)}
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
                                    <div
                                        className={`p-3 rounded-xl text-white shadow-lg shrink-0 ${
                                            selectedAgent.layer === 'network'
                                                ? 'bg-emerald-500'
                                                : themeColor(selectedAgent.theme)
                                        }`}
                                    >
                                        {cloneElement(selectedAgent.icon, { size: 24 })}
                                    </div>
                                    <div className="min-w-0">
                                        <h2 className="text-lg font-black dark:text-white leading-none truncate">
                                            {selectedAgent.id}
                                        </h2>
                                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                                            <span className="text-[10px] font-bold text-zinc-400 uppercase">
                                                {selectedAgent.provider?.organization}
                                            </span>
                                            <span className="w-1 h-1 rounded-full bg-zinc-300" />
                                            <span className="text-[10px] font-bold text-zinc-400">
                                                V{selectedAgent.version}
                                            </span>
                                            <span className="w-1 h-1 rounded-full bg-zinc-300" />
                                            <span className="text-[10px] font-bold text-zinc-400">
                                                {selectedAgent.skills?.length} {t('registry.skills_count')}
                                            </span>
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
                                        onClick={() => setSelectedAgent(null)}
                                        className="p-2 rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                                    >
                                        <X size={20} className="text-zinc-400" />
                                    </button>
                                </div>
                            </div>
                            {/* Drawer body */}
                            <div className="flex-1 overflow-y-auto no-scrollbar">
                                {viewMode === 'structured' ? (
                                    <AgentCard agent={selectedAgent._raw} isDark={isDark} />
                                ) : (
                                    <CodeInspector
                                        data={selectedAgent._raw}
                                        fileName={`${selectedAgent.id} AgentCard`}
                                        isDark={isDark}
                                    />
                                )}
                            </div>
                        </motion.div>
                    </>
                </AnimatePresence>,
                document.body,
            )}

            <AnimatePresence>
                {toast && createPortal(
                    <motion.div
                        key={toast.id}
                        initial={{ opacity: 0, x: 24 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: 24 }}
                        className={`fixed bottom-6 right-6 z-[300] flex items-center gap-2 px-4 py-3 rounded-2xl shadow-2xl text-white text-sm font-bold animate-toast ${
                            toast.type === 'success' ? 'bg-emerald-500' : 'bg-red-500'
                        }`}
                    >
                        {toast.type === 'success' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
                        <span>{t(toast.messageKey)}</span>
                        <button onClick={() => setToast(null)} className="ml-1 opacity-70 hover:opacity-100">
                            <X size={14} />
                        </button>
                    </motion.div>,
                    document.body,
                )}
            </AnimatePresence>
        </div>
    )
}

export default AgentRegistry
