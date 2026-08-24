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

test('sends a real inpaint mask and source image', async () => {
  const previousFetch = globalThis.fetch
  let body: Record<string, unknown> = {}
  globalThis.fetch = async (input, init) => {
    if (String(input) === '/api/generate') {
      body = JSON.parse(String(init?.body || '{}')) as Record<string, unknown>
      return new Response(JSON.stringify({ id: 'mask-job' }), { status: 200 })
    }
    return new Response(JSON.stringify({ job: { id: 'mask-job', modality: 'image', operation: 'inpaint', status: 'failed', phase: 'terminal', progress: 100, message: 'controlled', createdAt: null, startedAt: null, completedAt: null, terminal: true, result: null, billing: { chargedTokens: 0, tokenKind: 'daily', refunded: true } } }), { status: 200 })
  }
  try {
    await startPhoneImage({ mode: 'inpaint', prompt: 'добавить цветок', model: { id: 'server:local_flux_klein', label: 'ИЗО Base', provider: 'comfyui', modelProfile: 'local_flux_klein', tokenHint: 1, supportedResolutionIds: ['sq-hd'] }, resolutionId: 'sq-hd', width: 1024, height: 1024, inputImages: ['data:image/png;base64,source'], mask: 'data:image/png;base64,mask' })
    assert.equal(body.mode, 'inpaint')
    assert.equal(body.inputImage1, 'data:image/png;base64,source')
    assert.equal(body.maskImage, 'data:image/png;base64,mask')
  } finally { globalThis.fetch = previousFetch }
})

test('sends face role and selected full-quality LoRA strength', async () => {
  const previousFetch = globalThis.fetch
  let body: Record<string, unknown> = {}
  globalThis.fetch = async (input, init) => {
    if (String(input) === '/api/generate') {
      body = JSON.parse(String(init?.body || '{}')) as Record<string, unknown>
      return new Response(JSON.stringify({ id: 'face-job' }), { status: 200 })
    }
    return new Response(JSON.stringify({ job: { id: 'face-job', modality: 'image', operation: 'edit', status: 'failed', phase: 'terminal', progress: 100, message: 'controlled', createdAt: null, startedAt: null, completedAt: null, terminal: true, result: null, billing: { chargedTokens: 0, tokenKind: 'daily', refunded: true } } }), { status: 200 })
  }
  try {
    await startPhoneImage({ mode: 'edit', prompt: 'сохранить тело', model: { id: 'server:local_flux_klein', label: 'ИЗО Base', provider: 'comfyui', modelProfile: 'local_flux_klein', tokenHint: 1, supportedResolutionIds: ['sq-hd'] }, resolutionId: 'sq-hd', width: 1024, height: 1024, inputImages: ['base', 'face'], inputRoles: ['base', 'face'], faceLora: { id: 'quality-face.safetensors' }, faceStrength: 75 })
    assert.equal((body.inputImages as Array<{ role: string }>)[1].role, 'face')
    assert.deepEqual(body.loras, [{ id: 'quality-face.safetensors', strength: .75, triggerWord: '' }])
  } finally { globalThis.fetch = previousFetch }
})
