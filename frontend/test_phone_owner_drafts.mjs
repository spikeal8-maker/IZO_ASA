import assert from 'node:assert/strict'
import { beforeEach, test } from 'node:test'
import { phoneDraftKey, readPhoneDraft, writePhoneDraft } from './src/phone/core/accountDraft.ts'

const values = new Map()
globalThis.sessionStorage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => { values.set(key, String(value)) },
  removeItem: (key) => { values.delete(key) },
}
beforeEach(() => values.clear())

test('A and B have independent phone image text and can return to their drafts', () => {
  writePhoneDraft('image.prompt', 'account-A', 'A private image prompt')
  assert.equal(readPhoneDraft('image.prompt', 'account-B'), '')
  writePhoneDraft('image.prompt', 'account-B', 'B independent image prompt')
  assert.equal(readPhoneDraft('image.prompt', 'account-A'), 'A private image prompt')
  assert.equal(readPhoneDraft('image.prompt', 'account-B'), 'B independent image prompt')
})

test('image-to-video handoff and video prompt never cross account boundaries', () => {
  writePhoneDraft('video.source', 'account-A', 'data:image/png;base64,private-A')
  writePhoneDraft('video.prompt', 'account-A', 'A confidential video description')
  assert.equal(readPhoneDraft('video.source', 'account-B'), '')
  assert.equal(readPhoneDraft('video.prompt', 'account-B'), '')
  writePhoneDraft('video.source', 'account-B', '/api/media/B')
  writePhoneDraft('video.prompt', 'account-B', 'B video')
  assert.equal(readPhoneDraft('video.source', 'account-A'), 'data:image/png;base64,private-A')
  assert.equal(readPhoneDraft('video.prompt', 'account-A'), 'A confidential video description')
})

test('orphaned legacy v1 draft and video source are never attributed to B', () => {
  values.set('izo.phone.image.prompt', 'legacy private image')
  values.set('izo.phone.video.prompt', 'legacy private video')
  values.set('izo.phone.video.source', 'data:image/png;base64,legacy-private')
  for (const account of ['account-A', 'account-B']) {
    for (const kind of ['image.prompt', 'video.prompt', 'video.source']) {
      assert.equal(readPhoneDraft(kind, account), '')
    }
  }
})

test('owner identity is required; browser installation ID cannot stand in for account', () => {
  for (const ownerId of ['', ' bad ', '\ninvalid', 'x'.repeat(161)]) {
    assert.throws(() => phoneDraftKey('image.prompt', ownerId), /подтвердить владельца/)
    assert.throws(() => readPhoneDraft('video.prompt', ownerId), /подтвердить владельца/)
  }
})

test('clear is owner-scoped and cannot erase another user draft', () => {
  writePhoneDraft('image.prompt', 'account-A', 'A retained')
  writePhoneDraft('image.prompt', 'account-B', 'B removed')
  writePhoneDraft('image.prompt', 'account-B', '')
  assert.equal(readPhoneDraft('image.prompt', 'account-B'), '')
  assert.equal(readPhoneDraft('image.prompt', 'account-A'), 'A retained')
})

test('invalid or full sessionStorage does not cause cross-owner fallback', () => {
  const before = globalThis.sessionStorage
  globalThis.sessionStorage = {
    getItem: () => { throw new Error('storage restricted') },
    setItem: () => { throw new Error('quota exceeded') },
    removeItem: () => { throw new Error('storage restricted') },
  }
  try {
    assert.equal(readPhoneDraft('video.source', 'account-B'), '')
    assert.doesNotThrow(() => writePhoneDraft('video.source', 'account-B', 'private'))
  } finally {
    globalThis.sessionStorage = before
  }
})
