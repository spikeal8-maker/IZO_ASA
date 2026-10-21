import assert from 'node:assert/strict'
import test from 'node:test'
import {
  clearStudioDraft, readStudioDraft, studioDraftKey, studioDraftScope,
  STUDIO_DRAFT_KEY, STUDIO_DRAFT_TTL_MS, writeStudioDraft,
} from './src/studio/studioDraft.ts'

function storageWithMemory() {
  const entries = new Map<string, string>()
  const storage = {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => { entries.set(key, value) },
    removeItem: (key: string) => { entries.delete(key) },
  }
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { sessionStorage: storage } })
  return { entries, storage }
}

test('trusted authentication scope cannot fall back to the guest or another account', () => {
  assert.equal(studioDraftScope('loading'), null)
  assert.equal(studioDraftScope('anon'), 'guest')
  assert.equal(studioDraftScope('authed', undefined), null)
  assert.equal(studioDraftScope('authed', 'WEB-000003'), 'user:WEB-000003')
  assert.equal(studioDraftScope('authed', '../invalid'), null)
})

test('guest, user A and user B drafts are independent even with legacy unscoped data', () => {
  const { entries } = storageWithMemory()
  entries.set('izo:studio-draft-v1', JSON.stringify({ prompts: { text: 'sensitive legacy data' } }))
  writeStudioDraft('guest', { prompts: { text: 'гостевой текст' } })
  writeStudioDraft('user:WEB-000001', { prompts: { text: 'текст А' } })
  writeStudioDraft('user:WEB-000002', { prompts: { text: 'текст Б' } })
  assert.equal(readStudioDraft('guest').prompts?.text, 'гостевой текст')
  assert.equal(readStudioDraft('user:WEB-000001').prompts?.text, 'текст А')
  assert.equal(readStudioDraft('user:WEB-000002').prompts?.text, 'текст Б')
  clearStudioDraft('user:WEB-000001')
  assert.deepEqual(readStudioDraft('user:WEB-000001'), {})
  assert.equal(readStudioDraft('user:WEB-000002').prompts?.text, 'текст Б')
  assert.notEqual(STUDIO_DRAFT_KEY, 'izo:studio-draft-v1')
})

test('inline image bytes are never persisted', () => {
  const { entries } = storageWithMemory()
  writeStudioDraft('guest', {
    prompts: { text: 'text' },
    sourceImage: 'data:image/png;base64,SECRET-BYTES',
    editSlots: [{ image: 'data:image/png;base64,SECRET-EDIT-BYTES', role: '', takeNote: '' }],
  })
  const raw = entries.get(studioDraftKey('guest')) || ''
  assert.equal(raw.includes('SECRET-'), false)
  assert.equal(readStudioDraft('guest').sourceImage, undefined)
  assert.equal(readStudioDraft('guest').editSlots?.[0]?.image, undefined)
})

test('expired, future, malformed or wrong-version records never restore', () => {
  const { entries } = storageWithMemory()
  const key = studioDraftKey('guest')
  for (const payload of [
    '{bad-json',
    JSON.stringify({ version: 1, savedAt: Date.now(), draft: { prompts: { text: 'old' } } }),
    JSON.stringify({ version: 2, savedAt: Date.now() - STUDIO_DRAFT_TTL_MS - 1, draft: { prompts: { text: 'expired' } } }),
    JSON.stringify({ version: 2, savedAt: Date.now() + 60_000, draft: { prompts: { text: 'future' } } }),
  ]) {
    entries.set(key, payload)
    assert.deepEqual(readStudioDraft('guest'), {})
  }
})

test('browser storage refusal does not interrupt input and generation', () => {
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: { sessionStorage: {
      getItem: () => { throw new Error('SecurityError') },
      setItem: () => { throw new Error('QuotaExceededError') },
      removeItem: () => { throw new Error('SecurityError') },
    } },
  })
  assert.doesNotThrow(() => writeStudioDraft('guest', { prompts: { text: 'still editable' } }))
  assert.doesNotThrow(() => clearStudioDraft('guest'))
  assert.deepEqual(readStudioDraft('guest'), {})
})
