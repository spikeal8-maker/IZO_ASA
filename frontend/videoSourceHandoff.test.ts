// Run: node videoSourceHandoff.test.ts (Node >= 22.18 / 24 strips TS types natively)
import assert from 'node:assert/strict'
import {
  VIDEO_SOURCE_HANDOFF_KEY,
  VIDEO_SOURCE_HANDOFF_TTL_MS,
  VIDEO_SOURCE_UNAVAILABLE_MESSAGE,
  clearVideoSourceHandoff,
  closestVideoAspectRatio,
  readVideoSourceHandoff,
  resolveVerifiedVideoSource,
  writeVideoSourceHandoff,
} from './src/studio/videoSourceHandoff.ts'

class MemoryStorage {
  values = new Map<string, string>()
  getItemCalls = 0
  getItem(key: string) { this.getItemCalls += 1; return this.values.get(key) ?? null }
  setItem(key: string, value: string) { this.values.set(key, value) }
  removeItem(key: string) { this.values.delete(key) }
}

let passed = 0
async function test(name: string, run: () => void | Promise<void>) {
  await run(); passed += 1; console.log('  ok -', name)
}

await test('reads once and clears a tab-scoped handoff after successful application', async () => {
  const storage = new MemoryStorage()
  writeVideoSourceHandoff({ galleryImageId: 'img-1', mediaUrl: '/api/media/user/result.png?ignored=1', thumbnailUrl: '/api/media/user/thumb.webp', width: 900, height: 1600, imagePrompt: 'portrait' }, storage, 10_000)
  const handoff = readVideoSourceHandoff(storage, 10_100)
  assert.equal(storage.getItemCalls, 1)
  assert.equal(handoff?.mediaUrl, '/api/media/user/result.png')
  assert.equal(handoff?.thumbnailUrl, '/api/media/user/thumb.webp')
  assert.equal(handoff?.galleryImageId, 'img-1')
  assert.equal(closestVideoAspectRatio(handoff!, ['16:9', '9:16', '1:1']), '9:16')
  assert.deepEqual(await resolveVerifiedVideoSource(handoff!, async () => undefined), { ok: true, source: handoff })
  clearVideoSourceHandoff(storage)
  assert.equal(storage.values.has(VIDEO_SOURCE_HANDOFF_KEY), false)
})

await test('rejects arbitrary external URLs before they reach session storage', () => {
  const storage = new MemoryStorage()
  assert.throws(() => writeVideoSourceHandoff({ mediaUrl: 'https://evil.example/image.png' }, storage), /internal private-media path/)
  assert.equal(storage.getItem(VIDEO_SOURCE_HANDOFF_KEY), null)
})

await test('drops invalid and expired payloads', () => {
  const invalid = new MemoryStorage()
  invalid.setItem(VIDEO_SOURCE_HANDOFF_KEY, JSON.stringify({ version: 2, createdAt: 20_000, mediaUrl: '/api/media/a.png' }))
  assert.equal(readVideoSourceHandoff(invalid, 20_100), null)
  assert.equal(invalid.getItem(VIDEO_SOURCE_HANDOFF_KEY), null)

  const expired = new MemoryStorage()
  writeVideoSourceHandoff({ mediaUrl: '/api/media/a.png' }, expired, 30_000)
  assert.equal(readVideoSourceHandoff(expired, 30_000 + VIDEO_SOURCE_HANDOFF_TTL_MS + 1), null)
  assert.equal(expired.getItem(VIDEO_SOURCE_HANDOFF_KEY), null)
})

await test('maps an unavailable private image to the product-safe error', async () => {
  const storage = new MemoryStorage()
  const handoff = writeVideoSourceHandoff({ mediaUrl: '/api/media/missing.png' }, storage)
  const result = await resolveVerifiedVideoSource(handoff, async () => { throw new Error('404') })
  assert.deepEqual(result, { ok: false, message: VIDEO_SOURCE_UNAVAILABLE_MESSAGE })
})

console.log(`\n${passed} video source handoff tests passed`)
