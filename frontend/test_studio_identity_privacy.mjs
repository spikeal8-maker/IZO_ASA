import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

// The optional URL runs these behavioral controls against the immutable base
// during RED verification. Normal use loads the candidate pure TS serializer.
const draft = await import(process.env.STUDIO_DRAFT_MODULE_URL || './src/studio/studioDraft.ts')
const previousWindow = globalThis.window
const key = draft.STUDIO_DRAFT_KEY

function fixture(owner = 'account:A') {
  let identity = { owner, generation: 1 }
  const values = new Map()
  const storage = {
    getItem: (name) => values.get(name) ?? null,
    setItem: (name, value) => { values.set(name, value) },
    removeItem: (name) => { values.delete(name) },
  }
  globalThis.window = { sessionStorage: storage }
  draft.bindStudioDraftOwner?.(() => identity)
  return {
    values, storage,
    capture: () => draft.captureStudioDraftOwner?.() ?? identity,
    switchTo: (next) => { identity = next === null ? null : { owner: next, generation: (identity?.generation ?? 1) + 1 } },
    refresh: () => { identity = { ...identity } },
  }
}

afterEach(() => {
  draft.bindStudioDraftOwner?.(() => null)
  if (previousWindow === undefined) delete globalThis.window
  else globalThis.window = previousWindow
})

test('same owner recovers prompt, private source and edit inputs', () => {
  fixture()
  const payload = { prompts: { text: 'A private prompt' }, sourceImage: '/api/media/A.png', editSlots: [{ image: 'data:image/png;base64,QQ==' }] }
  draft.writeStudioDraft(payload)
  assert.deepEqual(draft.readStudioDraft(), payload)
})

test('B cannot hydrate A draft and unrelated installation state is retained', () => {
  const f = fixture()
  f.values.set('installation_id', 'keep-installation')
  draft.writeStudioDraft({ prompts: { text: 'A secret' }, sourceImage: '/api/media/A.png' })
  f.switchTo('account:B')
  assert.deepEqual(draft.readStudioDraft(), {})
  assert.equal(f.values.has(key), false)
  assert.equal(f.values.get('installation_id'), 'keep-installation')
})

test('logout guest cannot hydrate authenticated draft', () => {
  const f = fixture()
  draft.writeStudioDraft({ prompts: { text: 'private before logout' } })
  f.switchTo('anonymous')
  assert.deepEqual(draft.readStudioDraft(), {})
})

test('unattributed legacy image draft and prompt handoff are discarded', () => {
  const f = fixture('anonymous')
  f.values.set(key, JSON.stringify({ prompts: { text: 'unowned legacy private prompt' } }))
  f.values.set('izoUseAsDraft', JSON.stringify({ prompt: 'legacy private handoff' }))
  assert.deepEqual(draft.readStudioDraft(), {})
  assert.equal(f.values.has(key), false)
  assert.equal(f.values.has('izoUseAsDraft'), false)
})

test('attributed guest draft still survives reload within the guest identity', () => {
  fixture('anonymous')
  draft.writeStudioDraft({ prompts: { text: 'guest work' }, seed: 71 })
  assert.deepEqual(draft.readStudioDraft(), { prompts: { text: 'guest work' }, seed: 71 })
})

test('ordinary same-owner refresh preserves captured autosave', () => {
  const f = fixture()
  const captured = f.capture()
  f.refresh()
  draft.writeStudioDraft({ prompts: { text: 'same-owner work' } }, captured)
  assert.equal(draft.readStudioDraft().prompts.text, 'same-owner work')
})

test('delayed A autosave cannot overwrite B draft after switching', () => {
  const f = fixture()
  const captured = f.capture()
  f.switchTo('account:B')
  draft.writeStudioDraft({ prompts: { text: 'B current work' } }, f.capture())
  draft.writeStudioDraft({ prompts: { text: 'late A work' } }, captured)
  assert.equal(draft.readStudioDraft().prompts.text, 'B current work')
})

test('A to B to A does not revive an old generation of autosave', () => {
  const f = fixture()
  const captured = f.capture()
  f.switchTo('account:B')
  f.switchTo('account:A')
  draft.writeStudioDraft({ prompts: { text: 'new A work' } }, f.capture())
  draft.writeStudioDraft({ prompts: { text: 'old A work' } }, captured)
  assert.equal(draft.readStudioDraft().prompts.text, 'new A work')
})

test('unresolved identity neither hydrates nor writes private drafts', () => {
  const f = fixture()
  draft.writeStudioDraft({ prompts: { text: 'A secret' } })
  f.switchTo(null)
  assert.deepEqual(draft.readStudioDraft(), {})
  draft.writeStudioDraft({ prompts: { text: 'unresolved' } })
  assert.equal(f.values.has(key), false)
})

test('storage failures remain nonfatal without exposing another owner', () => {
  const f = fixture()
  f.storage.getItem = () => { throw new Error('disabled storage') }
  f.storage.setItem = () => { throw new Error('disabled storage') }
  assert.deepEqual(draft.readStudioDraft(), {})
  assert.doesNotThrow(() => draft.writeStudioDraft({ prompts: { text: 'private' } }))
})

test('quota fallback preserves owner attribution while omitting data URLs', () => {
  const f = fixture()
  let calls = 0
  f.storage.setItem = (name, value) => {
    if (++calls === 1) throw new Error('quota')
    f.values.set(name, value)
  }
  draft.writeStudioDraft({ prompts: { text: 'A secret' }, sourceImage: 'data:image/png;base64,QQ==', editSlots: [{ image: 'data:image/png;base64,QQ==' }] })
  assert.equal(draft.readStudioDraft().sourceImage, undefined)
  assert.equal(draft.readStudioDraft().editSlots[0].image, undefined)
  f.switchTo('account:B')
  assert.deepEqual(draft.readStudioDraft(), {})
})

test('caller-supplied storage metadata cannot reattribute A payload to B', () => {
  const f = fixture()
  draft.writeStudioDraft({ prompts: { text: 'A' }, _studioVersion: 2, _studioOwner: 'account:B' })
  f.switchTo('account:B')
  assert.deepEqual(draft.readStudioDraft(), {})
})

test('invalid JSON never hydrates a draft', () => {
  const f = fixture()
  f.values.set(key, '{broken')
  assert.deepEqual(draft.readStudioDraft(), {})
})

for (const stored of [undefined, '{broken', JSON.stringify({ _studioVersion: 2, _studioOwner: 'account:B' })]) {
  test(`unowned prompt handoff is discarded with ${stored === undefined ? 'no' : stored === '{broken' ? 'corrupt' : 'current-owner'} draft`, () => {
    const f = fixture('account:B')
    if (stored !== undefined) f.values.set(key, stored)
    f.values.set('izoUseAsDraft', JSON.stringify({ target: 'prompt', prompt: 'A private prompt' }))
    draft.readStudioDraft()
    assert.equal(f.values.has('izoUseAsDraft'), false)
  })
}

test('first-mount video handoff retains its existing private-media verification path', () => {
  const f = fixture()
  f.values.set('izo:video-source-v1', 'pending-private-image-verification')
  draft.readStudioDraft()
  assert.equal(f.values.get('izo:video-source-v1'), 'pending-private-image-verification')
})

test('observed owner change clears both handoffs before the next child mount', () => {
  const f = fixture()
  draft.readStudioDraft()
  f.values.set('izoUseAsDraft', JSON.stringify({ target: 'prompt', prompt: 'A private prompt' }))
  f.values.set('izo:video-source-v1', 'A private video source')
  f.switchTo('account:B')
  draft.readStudioDraft()
  assert.equal(f.values.has('izoUseAsDraft'), false)
  assert.equal(f.values.has('izo:video-source-v1'), false)
})

for (const [source, idField, target] of [['gallery', 'imageId', 'image'], ['gallery', 'imageId', 'editor'], ['gallery', 'imageId', 'draw'], ['uploaded', 'sourceId', 'face_source'], ['uploaded', 'sourceId', 'face_target'], ['feed', 'publicationId', 'editor'], ['feed', 'publicationId', 'prompt']]) {
  test(`fresh ${source}/${target} handoff replaces cached fields even beside a legacy draft`, async () => {
    const f = fixture(); const handoffKey = 'izoUseAsDraft'
    f.values.set(key, JSON.stringify({ prompts: { text: 'legacy A text' } }))
    f.values.set(handoffKey, JSON.stringify({ source, [idField]: 'item-1', target, prompt: 'cached A text', inputImage: '/api/media/A.png' }))
    const fresh = { ok: true, [idField]: 'item-1', target, inputImage: target === 'prompt' ? null : source === 'feed' ? '/api/feed/media/current?variant=large' : '/api/media/current.png', ...(source === 'uploaded' ? {} : { prompt: 'fresh authorized text' }) }
    await draft.prepareStudioHandoffs(f.capture(), async (request) => {
      assert.deepEqual(request, { source, id: 'item-1', target }); return fresh
    })
    assert.deepEqual(draft.readStudioDraft(), {})
    assert.deepEqual(JSON.parse(f.values.get(handoffKey)), { ...fresh, source })
  })
}

test('StrictMode preparation shares the pending request and exposes no consumer-ready proof early', async () => {
  const f = fixture(); let finish; let calls = 0
  const raw = JSON.stringify({ source: 'gallery', imageId: 'one', target: 'prompt', prompt: 'cached' })
  f.values.set('izoUseAsDraft', raw)
  const resolve = () => { calls += 1; return new Promise((done) => { finish = done }) }
  const first = draft.prepareStudioHandoffs(f.capture(), resolve)
  assert.equal(draft.prepareStudioHandoffs(f.capture(), resolve), first)
  assert.equal(calls, 1)
  finish({ ok: true, imageId: 'one', target: 'prompt', prompt: 'fresh' })
  await first
  draft.readStudioDraft()
  assert.equal(JSON.parse(f.values.get('izoUseAsDraft')).prompt, 'fresh')
})

test('a late A handoff response cannot publish for B or overwrite a newer handoff', async () => {
  const f = fixture(); let finish
  f.values.set('izoUseAsDraft', JSON.stringify({ source: 'gallery', imageId: 'A', target: 'prompt' }))
  const pending = draft.prepareStudioHandoffs(f.capture(), () => new Promise((done) => { finish = done }))
  f.switchTo('account:B')
  const newer = JSON.stringify({ source: 'feed', publicationId: 'B', target: 'prompt' })
  f.values.set('izoUseAsDraft', newer)
  finish({ ok: true, imageId: 'A', target: 'prompt', prompt: 'late A secret' })
  await pending
  assert.equal(f.values.get('izoUseAsDraft'), newer)
  draft.readStudioDraft()
  assert.equal(f.values.has('izoUseAsDraft'), false)
})

for (const failure of ['forbidden', 'missing-id', 'ambiguous-id', 'wrong-id', 'wrong-target', 'external-image', 'backslash-image', 'protocol-relative-image', 'data-image']) {
  test(`${failure} handoff fails closed`, async () => {
    const f = fixture()
    const raw = { source: 'gallery', imageId: 'one', target: 'image', prompt: 'cached secret' }
    if (failure === 'missing-id') delete raw.imageId
    if (failure === 'ambiguous-id') raw.sourceId = 'other'
    f.values.set('izoUseAsDraft', JSON.stringify(raw))
    await draft.prepareStudioHandoffs(f.capture(), async () => {
      if (failure === 'forbidden') throw new Error('403')
      const invalidImage = { 'external-image': 'https://external.invalid/A.png', 'backslash-image': '/\\external.invalid/api/media/one.png', 'protocol-relative-image': '//external.invalid/A.png', 'data-image': 'data:image/png;base64,QQ==' }
      return { ok: true, imageId: failure === 'wrong-id' ? 'other' : 'one', target: failure === 'wrong-target' ? 'prompt' : 'image', inputImage: invalidImage[failure] || '/api/media/one.png' }
    })
    assert.equal(f.values.has('izoUseAsDraft'), false)
  })
}

test('corrupt old image draft does not erase a freshly authorized handoff', async () => {
  const f = fixture()
  f.values.set(key, '{broken')
  f.values.set('izoUseAsDraft', JSON.stringify({ source: 'gallery', imageId: 'one', target: 'prompt' }))
  await draft.prepareStudioHandoffs(f.capture(), async () => ({ ok: true, imageId: 'one', target: 'prompt', prompt: 'fresh authorized prompt' }))
  assert.deepEqual(draft.readStudioDraft(), {})
  assert.equal(JSON.parse(f.values.get('izoUseAsDraft')).prompt, 'fresh authorized prompt')
})

test('unresponsive handoff resolution has a deadline and cannot publish later', { timeout: 10000 }, async () => {
  const f = fixture(); let finish; let signal
  f.values.set('izoUseAsDraft', JSON.stringify({ source: 'gallery', imageId: 'one', target: 'prompt' }))
  await draft.prepareStudioHandoffs(f.capture(), (_, capturedSignal) => {
    signal = capturedSignal; return new Promise((done) => { finish = done })
  })
  assert.equal(signal.aborted, true)
  assert.equal(f.values.has('izoUseAsDraft'), false)
  finish({ ok: true, imageId: 'one', target: 'prompt', prompt: 'late secret' })
  await Promise.resolve()
  assert.equal(f.values.has('izoUseAsDraft'), false)
})
