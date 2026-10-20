// SPDX-FileCopyrightText: Copyright contributors to the OpenAN project
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import React from 'react'
import { act, create } from 'react-test-renderer'

// Exercise the real component and React hooks; replace external services,
// portals and animations so no browser, polling timer or server is required.
const mocks = {
    '@/service/api.js': `
        export let cards = [];
        export const calls = [];
        export let finishPublish;
        export const setCards = value => { cards = value };
        export const getAgentCardsManage = async () => ({ agentCards: cards });
        export const getAgentsHealth = async () => ({});
        export const publishAgentCard = (...args) => {
            calls.push(args);
            return new Promise(resolve => { finishPublish = resolve });
        };
        export const getAgentReviewStatus = async (...args) => {
            calls.push(args);
            return { status: 'registered', history: [] };
        };
    `,
    '@/hooks/use_health_polling.js': `
        const data = { config: { enabled: true }, agents: [
            { organization: 'North', name: 'Shared', health_status: 'healthy' },
            { organization: 'South', name: 'Shared', health_status: 'offline' },
        ] };
        export const useHealthPolling = () => ({ data });
    `,
    'react-dom': 'export const createPortal = children => children;',
    'react-i18next': 'export const useTranslation = () => ({ t: key => key });',
    'framer-motion': `
        export { Fragment as AnimatePresence } from 'react';
        export const motion = { div: 'div' };
    `,
    './agentcard_visualization/index.jsx': `
        import { createElement } from 'react';
        export default ({ agent }) => createElement('agent-detail', { agent });
    `,
    './code_inspector/index.jsx': 'export default () => null;',
    '../heartbeat_monitor/index.jsx': 'export default () => null;',
}
const { outputFiles } = await build({
    stdin: {
        contents: `export { default } from './src/components/registry_center/index.jsx';
            export * from '@/service/api.js';`,
        resolveDir: fileURLToPath(new URL('../', import.meta.url)),
    },
    bundle: true, write: false, platform: 'node', format: 'cjs',
    jsx: 'automatic', packages: 'external',
    plugins: [{
        name: 'registry-test-boundaries',
        setup(builder) {
            builder.onResolve({ filter: /.*/ }, ({ path }) =>
                Object.hasOwn(mocks, path) ? { path, namespace: 'mock' } : undefined)
            builder.onLoad({ filter: /.*/, namespace: 'mock' }, ({ path }) => ({ contents: mocks[path], resolveDir: fileURLToPath(new URL('../', import.meta.url)) }))
        },
    }],
})
const loaded = { exports: {} }
new Function('require', 'module', 'exports', outputFiles[0].text)(
    createRequire(import.meta.url), loaded, loaded.exports,
)
const registry = loaded.exports
const fixture = (organization, name = 'Shared') => ({
    name, provider: { organization }, publishStatus: 'registered',
    description: 'Test agent', version: '1', skills: [],
})
const cards = [fixture('North'), fixture('South'), fixture('a', 'b-c'), fixture('a-b', 'c'), fixture('a/b', 'Shared')]
const text = node => typeof node === 'string' ? node : (node.children || []).map(text).join('')
const buttons = (root, label) => root.findAllByType('button').filter(node => text(node) === label)
const rowFor = (root, org) => root.findAllByType('tr').find(row =>
    row.findAllByType('td').some(cell => text(cell) === org))

async function mount(t) {
    registry.setCards(cards)
    registry.calls.length = 0
    // The portal boundary returns its children; no actual DOM is accessed.
    const previousDocument = globalThis.document
    globalThis.document = { body: {} }
    t.after(() => {
        if (previousDocument === undefined) delete globalThis.document
        else globalThis.document = previousDocument
    })
    t.mock.method(globalThis, 'setTimeout', () => 0)
    let renderer
    await act(async () => { renderer = create(React.createElement(registry.default, { api: 'injected-api' })) })
    t.after(() => act(() => renderer.unmount()))
    return renderer
}

for (const view of ['table', 'cards']) {
    test(`${view} renders distinct identities across organizations and refresh order`, async t => {
        const errors = []
        t.mock.method(console, 'error', (...args) => errors.push(args.join(' ')))
        const renderer = await mount(t)
        const root = renderer.root
        if (view === 'cards') {
            await act(async () => root.findByProps({ title: 'registry.view_cards' }).props.onClick())
        }
        assert.deepEqual(errors, [], 'same-named agents must not warn about duplicate keys')
        const items = () => view === 'table'
            ? root.findAllByType('tr').filter(node => node.findAllByType('td').length)
            : root.findAllByType('div').filter(node => node.props.className?.startsWith('group relative'))
        assert.equal(items().length, cards.length)
        const first = items()[0]
        await act(async () => root.findByType('input').props.onChange({ target: { value: 'Shared' } }))
        assert.equal(items()[0], first, 'the same agent must retain its identity when filtering')
        await act(async () => root.findByType('input').props.onChange({ target: { value: '' } }))
        // Publishing triggers the real fetchData refresh with reversed ordering.
        if (view === 'cards') await act(async () => root.findByProps({ title: 'registry.view_table' }).props.onClick())
        await act(async () => buttons(rowFor(root, 'North'), 'registry.action_publish')[0].props.onClick())
        await act(async () => root.findByType('textarea').props.onChange({ target: { value: 'approved' } }))
        let pending
        act(() => { pending = buttons(root, 'registry.review_confirm')[0].props.onClick() })
        registry.setCards([...cards].reverse())
        await act(async () => { registry.finishPublish(); await pending })
        if (view === 'cards') await act(async () => root.findByProps({ title: 'registry.view_cards' }).props.onClick())
        assert.equal(items().length, cards.length)
        assert.deepEqual(errors, [], 'refresh must preserve unique keys')
    })
}

test('publishing one organization leaves its namesake enabled and preserves API names', async t => {
    const renderer = await mount(t)
    const root = renderer.root
    const north = rowFor(root, 'North')
    const south = rowFor(root, 'South')
    assert.ok(text(north).includes('heartbeat.status_healthy'))
    assert.ok(text(south).includes('heartbeat.status_offline'))
    await act(async () => buttons(north, 'registry.action_publish')[0].props.onClick())
    assert.equal(buttons(root, 'registry.review_confirm')[0].props.disabled, true)
    await act(async () => root.findByType('textarea').props.onChange({ target: { value: '  approved  ' } }))
    let pending
    act(() => { pending = buttons(root, 'registry.review_confirm')[0].props.onClick() })
    assert.equal(buttons(north, 'registry.action_publishing')[0].props.disabled, true)
    assert.equal(buttons(root, 'registry.action_publishing').length, 2, 'row and review confirmation must both be busy')
    assert.ok(buttons(root, 'registry.action_publishing').every(button => button.props.disabled))
    assert.equal(buttons(south, 'registry.action_publish').length, 1, 'the other organization must not look busy')
    assert.equal(buttons(south, 'registry.action_publish')[0].props.disabled, false)
    assert.deepEqual(registry.calls, [['North', 'Shared', 'approved', 'injected-api']])
    await act(async () => { registry.finishPublish(); await pending })
    assert.equal(buttons(rowFor(root, 'North'), 'registry.action_publish')[0].props.disabled, false)
    await act(async () => buttons(rowFor(root, 'South'), 'registry.review_trail_btn')[0].props.onClick())
    assert.deepEqual(registry.calls.at(-1), ['South', 'Shared', 'injected-api'])
    await act(async () => root.findByType('input').props.onChange({ target: { value: 'shared' } }))
    assert.equal(root.findAllByType('tr').length, 4, 'search still matches the original name')
})
