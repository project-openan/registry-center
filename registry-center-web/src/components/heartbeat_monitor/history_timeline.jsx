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
import { History, ArrowDown } from 'lucide-react'
import { STATUS_STYLES } from './status_badge.jsx'

// Horizontal timeline: the time axis runs left to right (oldest -> newest),
// each event is a vertical stack of the status transition below the axis.
// At most the 10 most recent transitions are shown (scrollable if needed).
const MAX_EVENTS = 10

const HistoryTimeline = ({ history }) => {
    const { t } = useTranslation()
    if (!history || history.length === 0) {
        return (
            <div className="h-40 flex items-center justify-center text-zinc-400 text-sm font-bold">
                {t('heartbeat.no_history')}
            </div>
        )
    }
    // Data arrives newest-first: keep the 10 most recent, then flip it so
    // time flows left to right.
    const events = [...history].slice(0, MAX_EVENTS).reverse()
    return (
        <div className="p-5 overflow-x-auto custom-scrollbar">
            <div className="flex items-stretch min-w-max">
                {events.map((entry, idx) => {
                    const prevStyle = STATUS_STYLES[entry.previous_health_status] || STATUS_STYLES.unknown
                    const newStyle = STATUS_STYLES[entry.health_status] || STATUS_STYLES.unknown
                    const first = idx === 0
                    const last = idx === events.length - 1
                    const d = new Date(entry.changed_at)
                    const time = Number.isNaN(d.getTime()) ? entry.changed_at : d.toLocaleString()
                    return (
                        <div key={idx} className="flex-1 flex flex-col items-center min-w-[8rem]">
                            {/* Time label above the axis */}
                            <div className="mb-2 text-[11px] font-bold text-zinc-400 dark:text-zinc-500 whitespace-nowrap">
                                {time}
                            </div>
                            {/* Axis: half-segment, dot, half-segment */}
                            <div className="w-full flex items-center">
                                <div
                                    className={`flex-1 h-px ${
                                        first ? 'opacity-0' : 'bg-zinc-200 dark:bg-zinc-800'
                                    }`}
                                />
                                <div
                                    className={`w-2.5 h-2.5 rounded-full shrink-0 mx-1 ${
                                        newStyle.dot
                                    } ${last ? newStyle.glow : ''}`}
                                />
                                <div
                                    className={`flex-1 h-px ${
                                        last ? 'opacity-0' : 'bg-zinc-200 dark:bg-zinc-800'
                                    }`}
                                />
                            </div>
                            {/* Event below the axis: vertical status transition */}
                            <div className="mt-2 flex flex-col items-center gap-1">
                                <span
                                    className={`px-2 py-0.5 rounded-md text-sm font-black uppercase border ${prevStyle.badge}`}
                                >
                                    {t(`heartbeat.status_${entry.previous_health_status || 'unknown'}`)}
                                </span>
                                <ArrowDown size={12} className="text-zinc-300 dark:text-zinc-600" />
                                <span
                                    className={`px-2 py-0.5 rounded-md text-sm font-black uppercase border ${newStyle.badge}`}
                                >
                                    {t(`heartbeat.status_${entry.health_status || 'unknown'}`)}
                                </span>
                            </div>
                        </div>
                    )
                })}
            </div>
            <div className="flex items-center gap-2 mt-4 text-sm font-black uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
                <History size={12} />
                {t('heartbeat.timeline_hint')}
            </div>
        </div>
    )
}

export default HistoryTimeline
