import { ROUTES_AREA, SIDEBAR_NAV_AREA } from '@hermes/plugin-sdk'
import { createElement as h, useEffect, useState } from 'react'

const field = { padding: '8px 10px', border: '1px solid var(--ui-stroke-secondary)', borderRadius: 7, background: 'var(--ui-bg-tertiary)', color: 'var(--ui-text-primary)' }
const card = { padding: 16, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 12, display: 'grid', gap: 10 }
const row = { display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }
const button = (text, onClick, disabled = false, props = {}) => h('button', { style: { ...field, opacity: disabled ? 0.5 : 1 }, onClick, disabled, ...props }, text)

function Unit({ unit, save, busy }) {
  const [text, setText] = useState(unit.translation ?? '')
  useEffect(() => setText(unit.translation ?? ''), [unit.id, unit.translation])
  return h('article', { style: card }, h('strong', null, `Unit ${unit.id}${unit.kind === 'database' ? ' · database' : unit.kind === 'system_term' ? ' · system text' : unit.kind === 'system_type' ? ' · system type' : unit.aliases ? ' · choice' : ' · message'}`),
    h('p', null, unit.source), unit.blocked_reason && h('p', { role: 'note' }, unit.blocked_reason),
    h('label', null, 'Translation', h('textarea', { style: { ...field, display: 'block', width: '100%', minHeight: 70 }, value: text,
      disabled: busy || !!unit.blocked_reason, maxLength: 10000, onChange: e => setText(e.target.value) })),
    button('Save translation', () => save(unit.id, text), busy || !!unit.blocked_reason))
}

function Localization({ ctx }) {
  const [path, setPath] = useState(''), [rows, setRows] = useState(''), [systemTypes, setSystemTypes] = useState(false), [draft, setDraft] = useState(null), [page, setPage] = useState(null)
  const [offset, setOffset] = useState(0), [report, setReport] = useState(null), [exported, setExported] = useState(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const call = (operation, args = {}) => ctx.rest('/action', { method: 'POST', body: { operation, arguments: args }, timeoutMs: 60000 })
  const task = async fn => { setBusy(true); setError(''); try { await fn() } catch (e) { setError(String(e.message || e)) } finally { setBusy(false) } }
  const load = async (id, start) => setPage(await call('localize_get', { draft_id: id, offset: start, limit: 20 }))
  const save = (id, text) => task(async () => { await call('localize_translate', { draft_id: draft.draft_id, unit_id: id, text }); setReport(null); setExported(null); await load(draft.draft_id, offset) })
  return h('main', { style: { maxWidth: 1000, padding: 28, margin: 'auto', display: 'grid', gap: 20, color: 'var(--ui-text-primary)' } },
    h('header', null, h('h1', { style: { fontSize: 28, fontWeight: 700 } }, 'Game Lab: Game Localization Studio'), h('p', null, 'Translate the text while keeping the game data intact.')),
    error && h('p', { role: 'alert', style: card }, error),
    h('form', { style: card, onSubmit: e => { e.preventDefault(); task(async () => {
      const args = { source_path: path, ...(rows ? { message_rows: Number(rows) } : {}), ...(systemTypes ? { include_system_types: true } : {}) }
      const result = await call('localize_inspect', args); setDraft(result); setOffset(0); setReport(null); setExported(null); await load(result.draft_id, 0)
    }) } },
      h('label', null, 'RPG Maker JSON file on the Hermes host', h('input', { style: { ...field, display: 'block', width: '100%' }, value: path, disabled: busy, onChange: e => setPath(e.target.value) })),
      h('label', null, 'Measured message-row limit (optional)', h('input', { style: { ...field, display: 'block' }, type: 'number', min: 1, max: 20, value: rows, disabled: busy, onChange: e => setRows(e.target.value) })),
      h('label', null, h('input', { type: 'checkbox', checked: systemTypes, disabled: busy, onChange: e => setSystemTypes(e.target.checked) }), ' Include System.json type names (custom scripts may depend on original spellings)'),
      button('Open editable draft', undefined, busy || !path.trim(), { type: 'submit' })),
    draft && h('section', { style: { display: 'grid', gap: 14 }, 'aria-label': 'Translation draft' },
      h('div', { style: card }, h('h2', null, draft.source_name), h('p', null, `${draft.units} units · ${draft.message_groups} message groups`),
        h('p', null, draft.layout_status), draft.system_type_notice && h('p', { role: 'note' }, draft.system_type_notice),
        h('div', { style: row }, button('Validate draft', () => task(async () => setReport(await call('localize_validate', { draft_id: draft.draft_id }))), busy),
          button('Export translated copy', () => task(async () => setExported(await call('localize_export', { draft_id: draft.draft_id }))), busy)),
        report && h('div', { role: 'status' }, h('p', null, report.structural_ok ? 'Structural checks passed' : `${report.errors.length} checks need attention`),
          h('p', null, report.layout_status), h('p', null, report.coverage), report.system_type_notice && h('p', null, report.system_type_notice), ...report.errors.map((e, i) => h('p', { key: i }, `${e.error} ${e.unit ?? e.group ?? ''}`))),
        exported && h('details', null, h('summary', null, 'Show exported file location'), h('code', { style: { overflowWrap: 'anywhere' } }, exported.path))),
      page && h('section', { 'aria-label': 'Translation units', style: { display: 'grid', gap: 12 } }, ...page.units.map(unit => h(Unit, { key: `${draft.draft_id}/${unit.id}`, unit, save, busy }))),
      page && h('div', { style: row }, button('Previous units', () => task(async () => { const n = Math.max(0, offset - 20); setOffset(n); await load(draft.draft_id, n) }), busy || !offset),
        button('Next units', () => task(async () => { const n = page.next_offset; setOffset(n); await load(draft.draft_id, n) }), busy || page.next_offset == null))))
}

export default { id: 'game-lab', name: 'Game Lab', register(ctx) {
  ctx.register({ id: 'page', area: ROUTES_AREA, data: { path: '/game-lab' }, render: () => h(Localization, { ctx }) })
  ctx.register({ id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/game-lab', label: 'Game Lab', codicon: 'globe' } })
} }
