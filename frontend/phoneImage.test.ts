import assert from 'node:assert/strict'
import test from 'node:test'

import { I2I_STYLES, styleShortLabel } from './src/stylePresets.ts'
import { startPhoneImage } from './src/phone/features/image/api.ts'


test('keeps approved styles first and removed styles absent', () => {
  assert.deepEqual(I2I_STYLES.slice(0, 4).map((item) => styleShortLabel(item, 'ru')), ['Фото', 'Аниме', 'Комикс', 'Неон'])
  assert.equal(I2I_STYLES.some((item) => ['Невесомость', 'Другой мир / портал', 'Подводный мир', 'Арктика / ледяной мир', 'Пустынный мир', 'Продуктовый каталог'].includes(item.name)), false)
})

test('starts image generation with selected real mode and resolution', async () => {
  const previousFetch = globalThis.fetch
  let body: Record<string, unknown> = {}
  globalThis.fetch = async (input, init) => {
    if (String(input) === '/api/generate') {
      body = JSON.parse(String(init?.body || '{}')) as Record<string, unknown>
      return new Response(JSON.stringify({ id: 'image-job-1' }), { status: 200 })
    }
    return new Response(JSON.stringify({ job: { id: 'image-job-1', modality: 'image', operation: 'text_to_image', status: 'completed', phase: 'terminal', progress: 100, message: '', createdAt: null, startedAt: null, completedAt: null, terminal: true, result: { id: 'image-1', type: 'image', url: '/api/media/image.webp', thumbnailUrl: null, width: 1024, height: 1024, durationSeconds: null, aspectRatio: '1:1' }, billing: { chargedTokens: 1, tokenKind: 'daily', refunded: false } } }), { status: 200 })
  }
  try {
    const result = await startPhoneImage({ mode: 'text_to_image', prompt: 'кружка', model: { id: 'server:local_flux_klein', label: 'ИЗО Base', provider: 'comfyui', modelProfile: 'local_flux_klein', tokenHint: 1, supportedResolutionIds: ['sq-hd'] }, resolutionId: 'sq-hd', width: 1024, height: 1024, inputImages: [] })
    assert.equal(result.result?.url, '/api/media/image.webp')
    assert.equal(body.resolutionId, 'sq-hd')
    assert.equal(body.modelProfile, 'local_flux_klein')
  } finally { globalThis.fetch = previousFetch }
})
