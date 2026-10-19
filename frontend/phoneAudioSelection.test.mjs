// Deferred real component handlers; state setters are fixtures, no React DOM or ASR service runs here.
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const source = readFileSync(new URL('./src/phone/features/audio/PhoneAudioWorkspace.tsx', import.meta.url), 'utf8')
function between(start, end) {
  assert.equal(source.split(start).length, 2, 'The component handler must have one source owner')
  const from = source.indexOf(start), to = source.indexOf(end, from)
  assert.ok(to > from, 'The source handler boundary must be present')
  return source.slice(from, to)
}
const add = between('  async function addFile(', '  async function beginRecording(')
const remove = between('  function removeEntry(', '  return <main ')
const temporary = mkdtempSync(path.join(tmpdir(), 'izo-audio-selection-'))
after(() => rmSync(temporary, { recursive: true, force: true }))
const modulePath = path.join(temporary, 'owned-component-handlers.ts')
// Native pinned Node strips only TS annotations. Both async update and delete handlers remain the actual source.
writeFileSync(modulePath, `export default function harness() {
  let entries = [], selected = null, sequence = 0;
  const pending = [], revoked = [], messages = [];
  const setEntries = (update) => { entries = update(entries); };
  const setSelected = (update) => { selected = typeof update === 'function' ? update(selected) : update; };
  const setPlaying = () => undefined, setMessage = (value) => messages.push(value);
  const recognize = () => new Promise((resolve) => pending.push(resolve));
  const mediaDuration = () => { throw new Error('No browser media measurement in this source test'); };
  const URL = { createObjectURL: () => 'blob:owned-' + (sequence + 1), revokeObjectURL: (value) => revoked.push(value) };
  const crypto = { randomUUID: () => 'entry-' + (++sequence) };
  ${add}
  ${remove}
  return { addFile, removeEntry, select: setSelected, finish: (text) => { const resolve = pending.shift(); if (!resolve) throw new Error('No pending ASR'); resolve(text); },
    get selected() { return selected; }, get entries() { return entries; }, revoked, messages };
}
`, { flag: 'wx', mode: 0o600 })
const { default: harness } = await import(pathToFileURL(modulePath).href)
const file = (name) => new File([new Uint8Array([0, 1])], name, { type: 'audio/wav' })

test('deleting a pending recording does not restore its card or revoked URL after ASR completes', async () => {
  const state = harness(), operation = state.addFile(file('deleted.wav'), 1500)
  const originating = state.selected
  state.removeEntry(originating)
  assert.equal(state.selected, null)
  assert.deepEqual(state.entries, [])
  assert.deepEqual(state.revoked, [originating.url])
  state.finish('late deleted transcript'); await operation
  assert.equal(state.selected, null)
  assert.deepEqual(state.entries, [])
  assert.deepEqual(state.revoked, [originating.url])
})

test('choosing an earlier history recording preserves selection when a newer ASR request finishes', async () => {
  const state = harness(), first = state.addFile(file('earlier.wav'), 1500)
  state.finish('earlier transcript'); await first
  const previous = state.selected, second = state.addFile(file('pending.wav'), 1500)
  const pendingId = state.selected.id
  state.select(previous)
  state.finish('newer transcript'); await second
  assert.strictEqual(state.selected, previous)
  assert.equal(state.selected.text, 'earlier transcript')
  assert.equal(state.entries.find((entry) => entry.id === pendingId).text, 'newer transcript')
  assert.equal(state.entries.length, 2)
  assert.deepEqual(state.revoked, [])
})

test('starting a new recording keeps empty selection while the retained history entry receives its transcript', async () => {
  const state = harness(), operation = state.addFile(file('retained.wav'), 1500)
  const id = state.selected.id
  state.select(null)
  state.finish('retained transcript'); await operation
  assert.equal(state.selected, null)
  assert.equal(state.entries.length, 1)
  assert.equal(state.entries[0].id, id)
  assert.equal(state.entries[0].text, 'retained transcript')
})

test('the unchanged originating selection and history receive the same completed result', async () => {
  const state = harness(), operation = state.addFile(file('current.wav'), 1500)
  const id = state.selected.id, url = state.selected.url
  state.finish('current transcript'); await operation
  assert.equal(state.selected.id, id)
  assert.equal(state.selected.url, url)
  assert.equal(state.selected.text, 'current transcript')
  assert.strictEqual(state.selected, state.entries[0])
  assert.deepEqual(state.revoked, [])
})
