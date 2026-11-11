import { act } from 'react'
import { createRoot } from 'react-dom/client'
import plugin from '../desktop/plugin.js'

export async function run(assert, document) {
  const contributions = [], calls = []
  let translation = null, includeTypes = false
  const id = 'a'.repeat(32)
  const ctx = { register: c => contributions.push(c), rest: async (_, { body }) => {
    calls.push(body)
    switch (body.operation) {
      case 'localize_inspect': includeTypes = !!body.arguments.include_system_types; return { draft_id: id, source_name: 'Map001.json', units: 1, message_groups: 1, layout_status: 'unknown; no row limit', system_type_notice: includeTypes ? 'Custom scripts may depend on type names.' : '' }
      case 'localize_get': return { draft_id: id, units: [{ id: 0, source: 'Hello %1', translation, group: null, kind: includeTypes ? 'system_type' : 'system_term' }], total: 1, next_offset: null }
      case 'localize_translate': translation = body.arguments.text; return { saved: true }
      case 'localize_validate': return { structural_ok: true, errors: [], layout_status: 'unknown; no row limit supplied', coverage: 'Selected fields only' }
      case 'localize_export': return { path: '/tmp/translated.json' }
      default: throw Error('Unexpected operation')
    }
  } }
  plugin.register(ctx)
  const root = createRoot(document.getElementById('root'))
  const change = async (element, value) => act(async () => {
    const proto = element.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(element, value)
    element.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
  const click = async text => act(async () => {
    const button = [...document.querySelectorAll('button')].find(e => e.textContent === text)
    assert.ok(button && !button.disabled, 'Missing or disabled ' + text); button.click()
  })
  try {
    await act(async () => root.render(contributions.find(c => c.area === 'routes').render()))
    await change(document.querySelector('input'), '/tmp/Map001.json')
    await act(async () => document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
    assert.equal(calls.filter(c => c.operation === 'localize_export').length, 0)
    assert.equal(calls.find(c => c.operation === 'localize_inspect').arguments.include_system_types, undefined)
    assert.match(document.body.textContent, /system text/)
    await change(document.querySelector('input'), '/tmp/System.json')
    await act(async () => document.querySelector('input[type=checkbox]').click())
    await act(async () => document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
    assert.equal(calls.filter(c => c.operation === 'localize_inspect').at(-1).arguments.include_system_types, true)
    assert.match(document.body.textContent, /system type/)
    assert.match(document.body.textContent, /Custom scripts may depend/)
    await change(document.querySelector('textarea'), 'Bonjour %1')
    await click('Save translation')
    assert.equal(calls.find(c => c.operation === 'localize_translate').arguments.text, 'Bonjour %1')
    await click('Validate draft')
    assert.match(document.querySelector('[role=status]').textContent, /unknown; no row limit/)
    await click('Export translated copy')
    assert.equal(document.querySelector('details').open, false)
  } finally { await act(async () => root.unmount()) }
  return { passed: true, checks: ['explicit import', 'system type opt-in and warning', 'system text/type labels', 'translation editing', 'unknown layout is visible', 'explicit export', 'file path collapsed', 'timer cleanup'] }
}
