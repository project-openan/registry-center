// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// SPDX-License-Identifier: Apache-2.0
import {test} from 'node:test'
import assert from 'node:assert/strict'
import {getAgentLayer, registrationLayer, agentLayerLabel} from '../src/components/registry_center/agent-layer.js'

test('registration layer overrides any vendor-name assumptions', () => {
    assert.equal(getAgentLayer({provider:{organization:'Huawei'},registration:{layer:'ServiceLayer'}}),'service')
    assert.equal(getAgentLayer({provider:{organization:'移动'},registration:{layer:'NetworkLayer'}}),'network')
})
test('missing or vendor-defined layer is never guessed to be a standard layer', () => {
    for (const layer of [undefined,null,'','unknown','OMC','domain-workbench']) {
        assert.equal(getAgentLayer({provider:{organization:'Huawei'},registration:{layer}}),'other')
    }
    assert.equal(getAgentLayer({provider:{organization:'Huawei'}}),'other')
})
test('custom metadata stays readable and unknown has a translated label', () => {
    const t = key => ({'registry.layer_unknown':'未指定','registry.tab_service':'服务层'}[key] || key)
    assert.equal(registrationLayer({registration:{layer:'  vendor-domain-layer  '}}),'vendor-domain-layer')
    assert.equal(agentLayerLabel({registration:{layer:'vendor-domain-layer'}},t),'vendor-domain-layer')
    assert.equal(agentLayerLabel({},t),'未指定')
    assert.equal(agentLayerLabel({registration:{layer:'ServiceLayer'}},t),'服务层')
})
