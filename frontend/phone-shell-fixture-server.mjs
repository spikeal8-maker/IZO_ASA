import http from 'node:http'


const upstream = process.env.IZO_PHONE_FIXTURE_UPSTREAM || 'http://127.0.0.1:4188'
const port = Number(process.env.IZO_PHONE_FIXTURE_PORT || 4190)

const platform = {
  ok: true,
  apiVersion: 'v1',
  defaultRoute: '/phone/image',
  shell: { nativeReact: true, resumeJobs: true, offlineDrafts: true, notificationHost: true },
  contracts: { capabilities: 'v1', jobs: 'v1', media: 'v1', billing: 'v1' },
  workspaces: [
    ['image', 'Картинка', 'Фото', true, 'ready', 'primary', ['create', 'edit', 'draw']],
    ['video', 'Видео', 'Видео', true, 'ready', 'primary', ['text_to_video', 'image_to_video']],
    ['chat', 'Чат', 'Чат', true, 'ready', 'primary', ['conversation', 'web_search']],
    ['audio', 'Звук', 'Звук', false, 'partial', 'primary', ['speech_to_text']],
    ['3d', '3D-модель', '3D', false, 'planned', 'menu', []],
  ].map(([id, label, shortLabel, enabled, stage, navigation, operations]) => ({
    id, label, shortLabel, route: `/phone/${id}`, enabled, stage, navigation, operations,
  })),
}

const json = (response, payload) => {
  response.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  response.end(JSON.stringify(payload))
}

let videoGenerated = false

http.createServer(async (request, response) => {
  const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`)
  if (url.pathname === '/api/phone/v1/platform') return json(response, platform)
  if (url.pathname === '/api/phone/v1/jobs') return json(response, { ok: true, items: [] })
  if (url.pathname === '/api/phone/v1/jobs/image-job-1') return json(response, { job: { id: 'image-job-1', modality: 'image', operation: 'text_to_image', status: 'completed', phase: 'terminal', progress: 100, message: '', createdAt: null, startedAt: null, completedAt: null, terminal: true, result: { id: 'image-1', type: 'image', url: '/phone-preview-placeholder.jpg', thumbnailUrl: null, width: 1024, height: 1024, durationSeconds: null, aspectRatio: '1:1' }, billing: { chargedTokens: 1, tokenKind: 'daily', refunded: false } } })
  if (url.pathname === '/api/phone/v1/jobs/video-job-1') return json(response, { job: { id: 'video-job-1', modality: 'video', operation: 'text_to_video', status: 'completed', phase: 'terminal', progress: 100, message: '', createdAt: null, startedAt: null, completedAt: null, terminal: true, result: { id: 'gallery-video-1', type: 'video', url: '/api/video/media/video-job-1', thumbnailUrl: null, width: 854, height: 480, durationSeconds: 4, aspectRatio: '16:9' }, billing: { chargedTokens: 5, tokenKind: 'main', refunded: false } } })
  const videoModel = { id: 'video/test-model', name: 'Seedance Тест', description: '', supportedResolutions: ['480p', '720p', '1080p'], supportedAspectRatios: ['16:9', '9:16', '1:1'], supportedDurations: [4, 6], generateAudio: true, publicPricing: { fromTokens: 5 } }
  if (url.pathname === '/api/video/config') return json(response, { modes: Object.fromEntries(['text_to_video', 'image_to_video', 'first_last_frame', 'reference_to_video'].map((key) => [key, [videoModel]])), videoSlots: 10, feedPublicationEnabled: true })
  if (url.pathname === '/api/video/estimate') return json(response, { chargedTokens: 5 })
  if (url.pathname === '/api/video/generate') { videoGenerated = true; return json(response, { id: 'video-job-1' }) }
  if (url.pathname === '/api/video/history') return json(response, { items: videoGenerated ? [{ id: 'video-job-1', mode: 'text_to_video', status: 'completed', progress: 100, prompt: 'Тестовое видео', createdAt: '2026-08-24T00:00:00Z', completedAt: '2026-08-24T00:00:04Z', model: 'video/test-model', publicModelLabel: 'Seedance Тест', duration: 4, resolution: '480p', aspectRatio: '16:9', tokenCost: 5, videoUrl: '/api/video/media/video-job-1', galleryVideoId: 'gallery-video-1', generateAudio: false }] : [] })
  if (url.pathname === '/api/model-access') return json(response, { plan: 'mini', modes: { text_to_image: { models: [{ id: 'server:local_flux_klein', label: 'ИЗО Base', provider: 'comfyui', modelProfile: 'local_flux_klein', tokenHint: 1, supportedResolutionIds: ['sq-sd', 'sq-hd', 'sq-fhd'] }], presets: { fast: 'server:local_flux_klein' } } } })
  if (url.pathname === '/api/models') return json(response, { ok: true, loras: ['quality-face.safetensors'] })
  if (url.pathname === '/api/generate') return json(response, { id: 'image-job-1' })
  if (url.pathname === '/api/gallery/items') return json(response, { items: [{ id: 'gallery-image-1', viewerSrc: '/phone-preview-placeholder.jpg', thumbnailUrl: '/phone-preview-placeholder.jpg', width: 1024, height: 1024 }] })
  if (url.pathname === '/api/feed/publications') return json(response, { ok: true, publication: { id: 'publication-1' }, moderation: 'approved' })
  if (url.pathname === '/api/me-v2') return json(response, {
    profile: { display_name: 'Тестовый пользователь' },
    account: { token_balance: 1259, daily_tokens_limit: 100, daily_tokens_remaining: 93 },
  })
  if (url.pathname === '/api/phone/chat/threads') return json(response, request.method === 'POST' ? { ok: true, thread: { id: '0123456789abcdef', title: 'Новый чат', chatModelId: 'local:izo-chat', imageModelId: null, videoModelId: null, contextChars: 60000, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() } } : { ok: true, threads: [] })
  if (url.pathname === '/api/phone/chat/models') return json(response, { ok: true, defaultModel: 'local:izo-chat', models: [{ id: 'local:izo-chat', name: 'ИЗО Чат', provider: 'local', tokenCost: 1, tokenKind: 'daily', description: 'Быстрые ответы на этом сервере', contextChars: 60000 }] })
  if (url.pathname === '/api/phone/chat') return json(response, { ok: true, reply: 'Готово — это проверенный ответ.', modelId: 'local:izo-chat', chargedTokens: 1, tokenKind: 'daily', tools: [] })
  try {
    const upstreamResponse = await fetch(new URL(url.pathname + url.search, upstream), { redirect: 'manual' })
    const headers = Object.fromEntries(upstreamResponse.headers.entries())
    delete headers['content-encoding']
    delete headers['content-length']
    response.writeHead(upstreamResponse.status, headers)
    response.end(Buffer.from(await upstreamResponse.arrayBuffer()))
  } catch {
    response.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' })
    response.end('fixture upstream unavailable')
  }
}).listen(port, '127.0.0.1', () => {
  console.log(`PHONE_SHELL_FIXTURE_READY http://127.0.0.1:${port}`)
})
