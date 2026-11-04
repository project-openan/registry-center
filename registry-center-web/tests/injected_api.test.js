// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {getAgentCardsManage, getAgentReviewStatus, getAgentsHealth, getHealthStreamUrl} from '../src/service/api.js';

test('Portal REST and native SSE use the injected component gateway', async () => {
    globalThis.localStorage = {getItem: () => JSON.stringify({mode:'ip', ip:'192.0.2.1', port:'5001'})};
    const calls = [];
    const api = {get: async (url) => {calls.push(url); return {};},
        getUri: ({url}) => '/custom-registry-gateway' + url};
    await getAgentCardsManage(api);
    await getAgentReviewStatus('测试组织', 'Agent A', api);
    await getAgentsHealth(undefined, api);
    assert.deepEqual(calls, ['/rest/v1/registry-center/agent-cards/manage',
        '/rest/v1/registry-center/agent-cards/%E6%B5%8B%E8%AF%95%E7%BB%84%E7%BB%87/Agent%20A/review-status',
        '/rest/v1/registry-center/agents/health']);
    assert.equal(getHealthStreamUrl(api), '/custom-registry-gateway/rest/v1/registry-center/agents/health/stream');
    delete globalThis.localStorage;
});
