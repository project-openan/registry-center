// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// SPDX-License-Identifier: Apache-2.0

// Layer is vendor-defined registration metadata, never inferred from a vendor.
export function registrationLayer(agent) {
    const value = agent.registration?.layer
    return typeof value === 'string' && value.trim() ? value.trim() : 'unknown'
}

export function getAgentLayer(agent) {
    const value = registrationLayer(agent).toLowerCase().replace(/[-_\s]/g, '')
    if (value === 'service' || value === 'servicelayer') return 'service'
    if (value === 'network' || value === 'networklayer') return 'network'
    return 'other'
}

export function agentLayerLabel(agent, t) {
    const group = getAgentLayer(agent)
    if (group !== 'other') return t(`registry.tab_${group}`)
    const value = registrationLayer(agent)
    return value.toLowerCase() === 'unknown' ? t('registry.layer_unknown') : value
}
