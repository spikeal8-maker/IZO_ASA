// Installed Phone UI and normal APIs. Owned credentials enter only through stdin.
import { createRequire } from 'node:module'
import { createHash, randomUUID } from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { ensure, snapshot, settlement, completedProjection, decodedImage, publicationFor, poll } from './docker_d3_browser_contracts.mjs'
import { BrowserIO, LIMITS, decodePublicVideo } from './docker_d3_browser_io.mjs'
import { observeActivePhoneImage } from './docker_d3_phone_recovery.mjs'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('playwright')
const chunks = []
let inputBytes = 0
for await (const chunk of process.stdin) {
  inputBytes += chunk.length
  if (inputBytes > 16384) throw new Error('D3_INPUT_TOO_LARGE')
  chunks.push(chunk)
}
const input = JSON.parse(Buffer.concat(chunks).toString('utf8'))
const target = new URL(input.origin)
ensure(target.protocol === 'http:' && target.hostname === '127.0.0.1' && Number(target.port) >= 20000
  && !target.username && !target.password && !target.search && !target.hash && target.pathname === '/'
  && /^[0-9a-f]{32}$/.test(input.runId) && typeof input.phoneActive === 'boolean'
  && (!input.phoneActive || /^web_[0-9a-f]{32}$/.test(input.ownerId))
  && /^[0-9a-f]{40}$/.test(input.sourceSha) && /^izo-asa-shadow-[a-z0-9-]{3,40}$/.test(input.project)
  && ['isolatedData', 'fakeProviderOnly', 'networkEgressDenied', 'externalEffectsDisabled'].every((k) => input[k] === true),
  'D3_TARGET_NOT_ADMITTED')
const output = path.resolve(input.output)
await mkdir(output, { recursive: true, mode: 0o700 })
const result = { status: 'FAIL', sourceSha: input.sourceSha, project: input.project,
  runId: input.runId, modelExecution: false, acceleratorExecution: false, checks: {} }
const digest = (value) => createHash('sha256').update(value).digest('hex')
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b)
const id = (value) => { ensure(typeof value === 'string' && /^[A-Za-z0-9_-]{1,120}$/.test(value), 'D3_ID_INVALID'); return value }
let browser, io, owner, other, guest, page, timedOut = false
const sessions = []
const timer = setTimeout(() => { timedOut = true; void page?.close().catch(() => {}) }, 100000)

async function bounded(operation, milliseconds, code) {
  let timer
  try { return await Promise.race([operation, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(code)), milliseconds)
  })]) } finally { clearTimeout(timer) }
}

const api = (...args) => io.api(...args)
const response = (...args) => io.read(...args)
async function login(client, email, password) {
  sessions.push(client) // A failing response may already have set the owned session cookie.
  const value = await api(client, 'POST', '/api/auth/password/login-v2', { email, password, platform: 'web_mobile' })
  ensure(value.ok === true, 'D3_LOGIN_FAILED')
}
async function ledger() { return api(owner, 'GET', '/api/account/token-history-v2?days=365&limit=200') }
async function accounting() { return snapshot(await api(owner, 'GET', '/api/me-v2'), await ledger()) }
async function account() {
  const value = await api(owner, 'GET', '/api/me-v2')
  return { balance: value.account.token_balance, daily: value.account.daily_tokens_used }
}
const posted = (route) => (r) => new URL(r.url()).origin === target.origin
  && new URL(r.url()).pathname === route && r.request().method() === 'POST'
async function send(kind, threadId, image = false) {
  const textarea = page.locator('.phone-chat-composer textarea'), content = `D3_CHAT_${kind}:${result.runId}`
  await textarea.fill(content)
  await page.waitForFunction(() => document.querySelector('.phone-chat-send')?.disabled === false)
  const [value, admissionResponse] = await Promise.all([
    page.waitForResponse(posted('/api/phone/chat')),
    image ? page.waitForResponse(posted('/api/generate')) : Promise.resolve(null), textarea.press('Enter'),
  ])
  const reply = await io.capture(value), payload = io.requestJSON(value)
  ensure(reply.ok === true && reply.provider === 'local' && reply.chargedTokens === 0, 'D3_CHAT_LOCAL_BILLING_INVALID')
  ensure(payload.threadId === threadId && id(payload.requestId) && same(payload.messages, [{ role: 'user', content }]),
    'D3_CHAT_REQUEST_MISMATCH')
  return { reply, payload, admissionResponse }
}

try {
  browser = await chromium.launch({ headless: true })
  result.browserVersion = browser.version()
  io = new BrowserIO(browser, target.origin, result.runId, () => timedOut)
  owner = await io.context(); other = await io.context(); guest = await io.context()
  await login(owner, input.email, input.password)
  await login(other, input.otherEmail, input.otherPassword)
  input.email = input.password = input.otherEmail = input.otherPassword = ''
  page = await owner.newPage(); page.setDefaultTimeout(8000)
  const initialAccount = await account()
  const created = await api(owner, 'POST', '/api/phone/chat/threads',
    { title: 'Controlled D3 chat', chatModelId: 'local:izo-chat', contextChars: 4000 })
  const threadId = id(created.thread.id), messagesPath = `/api/phone/chat/threads/${threadId}/messages`
  const [loadedThread] = await Promise.all([
    page.waitForResponse((r) => new URL(r.url()).pathname === messagesPath && r.request().method() === 'GET'),
    page.goto(target.origin + '/phone/chat', { waitUntil: 'domcontentloaded' }),
  ])
  ensure((await io.capture(loadedThread)).messages?.length === 0, 'D3_CHAT_THREAD_NOT_EMPTY')
  await page.locator('.phone-chat-tabs span.active').getByRole('button', { name: 'Controlled D3 chat', exact: true }).waitFor({ state: 'visible' })
  ensure(await page.locator('meta[name="izo-release"]').getAttribute('content') === input.sourceSha, 'D3_SOURCE_MISMATCH')
  await page.locator('[data-phone-workspace="chat"] textarea').waitFor({ state: 'visible' })
  const first = await send('FIRST', threadId)
  ensure(first.payload.threadId === threadId && first.reply.reply === 'Controlled reply one.', 'D3_CHAT_FIRST_INVALID')
  await page.getByText(first.reply.reply, { exact: true }).waitFor({ state: 'visible' })
  const second = await send('SECOND', threadId)
  ensure(second.reply.reply === 'Controlled reply two; prior turn confirmed.', 'D3_CHAT_HISTORY_NOT_USED')
  await page.getByText(second.reply.reply, { exact: true }).waitFor({ state: 'visible' })
  const history = await api(owner, 'GET', messagesPath)
  ensure(history.messages.length === 4 && same(history.messages.map((m) => m.role), ['user', 'assistant', 'user', 'assistant']),
    'D3_CHAT_HISTORY_INVALID')
  ensure(same(await api(owner, 'POST', '/api/phone/chat', second.payload), second.reply), 'D3_CHAT_REPLAY_CHANGED')
  const conflict = { ...second.payload, messages: [{ role: 'user', content: 'Changed controlled request' }] }
  await api(owner, 'POST', '/api/phone/chat', conflict, 409)
  ensure(same((await api(owner, 'GET', messagesPath)).messages, history.messages), 'D3_CHAT_REPLAY_DUPLICATED_HISTORY')
  await api(other, 'GET', messagesPath, undefined, 404)
  const failureBefore = await ledger()
  const failed = { ...second.payload, requestId: randomUUID(), messages: [{ role: 'user', content: `D3_CHAT_FAIL:${result.runId}` }] }
  const failure = await api(owner, 'POST', '/api/phone/chat', failed, 502)
  ensure(failure.detail === 'Чат временно недоступен. Повторите позже или обратитесь в поддержку.', 'D3_CHAT_ERROR_NOT_PUBLIC')
  const failureAfter = await ledger(), previous = new Set(failureBefore.items.map((item) => item.id))
  const failedEntries = failureAfter.items.filter((item) => !previous.has(item.id))
  ensure(failedEntries.length === 2 && same(failedEntries.map((item) => item.reason).sort(), ['chat_refund', 'free_chat'])
    && failedEntries.every((item) => item.delta === 0 && item.spentTokens === 0), 'D3_CHAT_FAILURE_LEDGER_INVALID')
  ensure(same(await api(owner, 'POST', '/api/phone/chat', failed, 502), failure)
    && same(await ledger(), failureAfter) && same(await account(), initialAccount)
    && same((await api(owner, 'GET', messagesPath)).messages, history.messages), 'D3_CHAT_FAILED_REPLAY_MUTATED_STATE')
  result.checks.chat = { status: 'PASS', threadId, firstRequestId: first.payload.requestId,
    secondRequestId: second.payload.requestId, failedRequestId: failed.requestId,
    historyMessages: 4, replay: 'EXACT', conflictHttp: 409, failureHttp: 502, failureRefunds: 1,
    failureLedgerIds: failedEntries.map((item) => item.id), chargedTokens: 0, paidSettlement: 'NOT_RUN' }

  let imageSubmits = 0
  owner.on('request', (r) => { if (r.method() === 'POST' && new URL(r.url()).pathname === '/api/generate') imageSubmits++ })
  const imageBefore = await accounting(), imageAnswer = await send('IMAGE', threadId, true)
  const admission = await io.capture(imageAnswer.admissionResponse), jobId = id(admission.id)
  const generatedRequest = io.requestJSON(imageAnswer.admissionResponse)
  ensure(generatedRequest.mode === 'text_to_image' && generatedRequest.provider === 'comfyui', 'D3_CHAT_IMAGE_REQUEST_INVALID')
  let phoneActive
  if (input.phoneActive) {
    ensure(input.ownerId === imageBefore.identity[0], 'D3_PHONE_OWNER_MISMATCH')
    phoneActive = await observeActivePhoneImage({ context: owner, origin: target.origin, output,
      sourceSha: result.sourceSha, project: result.project, runId: result.runId, jobId, ownerId: input.ownerId,
      readPhone: (value) => api(owner, 'GET', `/api/phone/v1/jobs/${id(value)}`), workAllowed: () => !timedOut })
  }
  const imageSelector = '.phone-chat-tools img[alt="Изображение, созданное из чата"]'
  await page.locator(imageSelector).waitFor({ state: 'visible', timeout: 60000 })
  await page.waitForFunction((s) => { const i = document.querySelector(s); return i?.complete && i.naturalWidth > 0 && i.naturalHeight > 0 }, imageSelector)
  const legacyImage = await api(owner, 'GET', `/api/jobs/${jobId}`)
  const phoneImage = await api(owner, 'GET', `/api/phone/v1/jobs/${jobId}`), completed = phoneImage.job
  const imageProjection = completedProjection(legacyImage, phoneImage, admission,
    { modality: 'image', ownerId: imageBefore.identity[0] })
  ensure(imageSubmits === 1, 'D3_CHAT_IMAGE_RESULT_INVALID')
  const saved = await poll(() => api(owner, 'GET', messagesPath),
    (v) => v.messages.find((m) => m.id === imageAnswer.reply.messageId)?.tools?.[0]?.status === 'done', () => true, 8)
  const tool = saved.messages.find((m) => m.id === imageAnswer.reply.messageId).tools[0]
  ensure(tool.name === 'generate_image' && tool.jobId === jobId && tool.resultUrl === completed.result.url,
    'D3_CHAT_TOOL_PROVENANCE_INVALID')
  const imagePixels = decodedImage(await page.locator(imageSelector).evaluate((i) => ({ complete: i.complete,
    width: i.naturalWidth, height: i.naturalHeight, src: i.getAttribute('src') })), tool.resultUrl)
  const imageAccounting = settlement(imageBefore, await accounting(), admission,
    { mode: 'text_to_image', provider: 'comfyui', chatEntries: 1 })
  await api(other, 'GET', `/api/phone/v1/jobs/${jobId}`, undefined, 404)
  await api(other, 'GET', `/api/jobs/${jobId}`, undefined, 404)
  await api(guest, 'GET', `/api/phone/v1/jobs/${jobId}`, undefined, 401)
  const [reloadedThread] = await Promise.all([
    page.waitForResponse((r) => new URL(r.url()).pathname === messagesPath && r.request().method() === 'GET'),
    page.reload({ waitUntil: 'domcontentloaded' }),
  ])
  ensure(same((await io.capture(reloadedThread)).messages, saved.messages), 'D3_PHONE_CHAT_RESUME_FAILED')
  await page.locator(imageSelector).waitFor({ state: 'visible' })
  await page.waitForFunction((s) => { const i = document.querySelector(s); return i?.complete && i.naturalWidth > 0 && i.naturalHeight > 0 }, imageSelector)
  const resumedPixels = decodedImage(await page.locator(imageSelector).evaluate((i) => ({ complete: i.complete,
    width: i.naturalWidth, height: i.naturalHeight, src: i.getAttribute('src') })), tool.resultUrl, imagePixels)
  ensure((await page.locator(imageSelector).getAttribute('src')) === tool.resultUrl
    && same((await api(owner, 'GET', messagesPath)).messages, saved.messages), 'D3_PHONE_CHAT_RESUME_FAILED')
  result.image = { id: id(completed.result.id), url: tool.resultUrl, jobId, tokenCost: admission.tokenCost }
  result.checks.chatImage = { status: 'PASS', jobId, requestId: id(imageAnswer.payload.requestId), imageSubmits,
    ...(phoneActive ? { phoneActive } : {}),
    resumeBoundary: 'completed tool browser reload', decodedAfterReload: resumedPixels, projection: imageProjection,
    otherUser: 404, guest: 401, accounting: imageAccounting }
  await writeFile(path.join(output, 'chat-video-image.json'), JSON.stringify({ status: 'PARTIAL',
    sourceSha: result.sourceSha, project: result.project, runId: result.runId, image: result.image,
    chatImage: result.checks.chatImage }) + '\n', { mode: 0o600, flag: 'wx' })
  await page.screenshot({ path: path.join(output, 'chat-resumed.png'), animations: 'disabled' })

  const platform = await api(owner, 'GET', '/api/phone/v1/platform')
  await page.evaluate(() => { window.history.pushState({}, '', '/phone/3d'); window.dispatchEvent(new PopStateEvent('popstate')) })
  await page.locator('.phone-not-found').getByText('Такого раздела нет', { exact: true }).waitFor({ state: 'visible' })
  ensure(new URL(page.url()).pathname === '/phone/3d' && !platform.workspaces.some((w) => w.id === '3d')
    && await page.locator('[data-phone-workspace="3d"]').count() === 0, 'D3_PHONE_3D_EXPOSED')
  await page.getByRole('button', { name: 'Меню', exact: true }).click()
  const menu = page.getByRole('dialog', { name: 'Разделы ИЗО АСА', exact: true })
  await menu.waitFor({ state: 'visible' })
  const labels = await menu.locator('.phone-menu-grid button b').allTextContents()
  ensure(labels.length === 4 && same(labels, platform.workspaces.map((w) => w.label)), 'D3_PHONE_MENU_MANIFEST_MISMATCH')
  result.checks.phone3d = { status: 'PASS', route: '/phone/3d', workspace: 'ABSENT', menuLabels: labels }
  await page.keyboard.press('Escape'); await menu.waitFor({ state: 'hidden' })

  const generationBefore3d = imageSubmits
  const desktop = await owner.newPage(); desktop.setDefaultTimeout(8000)
  try {
    await desktop.setViewportSize({ width: 1360, height: 900 })
    await desktop.goto(target.origin + '/3d', { waitUntil: 'domcontentloaded' })
    const placeholder = desktop.locator('.iv3-placeholder-card')
    await placeholder.getByRole('heading', { name: '3D', exact: true }).waitFor({ state: 'visible' })
    ensure(await placeholder.getByText('Создание 3D-моделей появится в этом разделе.', { exact: true }).isVisible()
      && await placeholder.getByRole('button').count() === 1
      && await placeholder.getByRole('button', { name: 'Перейти в «По тексту»', exact: true }).isVisible()
      && imageSubmits === generationBefore3d, 'D3_DESKTOP_3D_NOT_PLACEHOLDER')
    result.checks.desktop3d = { status: 'PASS', route: '/3d', createOperation: 'ABSENT',
      presentation: 'PLACEHOLDER', generationRequests: imageSubmits - generationBefore3d }
  } finally { await bounded(desktop.close(), 5000, 'D3_DESKTOP_CLOSE_TIMEOUT') }

  const config = await api(owner, 'GET', '/api/video/config')
  result.checks.video = { status: 'NOT_RUN', plan: config.plan, videoSlots: config.videoSlots }
  ensure(Number.isInteger(config.videoSlots) && config.videoSlots >= 1, 'D3_VIDEO_ENTITLEMENT_REQUIRED')
  const model = config.modes?.text_to_video?.find((m) => m.id === 'local/ltx-2.3-fast-q3')
  ensure(model?.available !== false && model?.provider === 'local_ltx' && config.feedPublicationEnabled === true,
    'D3_LTX_NOT_CONFIGURED')
  const admissionError = 'D3_LTX_ADMISSION_INVALID'
  const payload = { mode: 'text_to_video', model: model.id, prompt: 'Controlled moving test pattern',
    duration: 2, resolution: '480p', aspectRatio: '16:9', generateAudio: false }
  const quote = await api(owner, 'POST', '/api/video/estimate', payload), videoBefore = await accounting()
  ensure(quote.pricingSource === 'local_profile' && quote.chargedTokens === 1, 'D3_LTX_QUOTE_INVALID')
  const start = await api(owner, 'POST', '/api/video/generate', payload), videoId = id(start.id)
  ensure(start.status === 'queued' && start.tokenCost === quote.chargedTokens, admissionError)
  const video = await poll(() => api(owner, 'GET', `/api/video/jobs/${videoId}`), (v) => v.status === 'completed',
    (v) => ['queued', 'pending', 'in_progress', 'finalizing'].includes(v.status))
  const phoneVideo = await api(owner, 'GET', `/api/phone/v1/jobs/${videoId}`)
  const videoProjection = completedProjection(video, phoneVideo, start, { modality: 'video', ownerId: videoBefore.identity[0] })
  await api(other, 'GET', `/api/video/jobs/${videoId}`, undefined, 404)
  await response(other, 'GET', video.videoUrl, undefined, 404)
  await response(guest, 'GET', video.videoUrl, undefined, 401)
  await api(other, 'GET', `/api/phone/v1/jobs/${videoId}`, undefined, 404)
  await api(guest, 'GET', `/api/phone/v1/jobs/${videoId}`, undefined, 401)
  const bytes = await io.read(owner, 'GET', video.videoUrl, undefined, 200, LIMITS.privateMedia)
  ensure(bytes.length > 1024 && bytes.subarray(4, 8).toString() === 'ftyp', 'D3_VIDEO_CONTAINER_INVALID')
  const gallery = await api(owner, 'GET', '/api/gallery/items?limit=60&filter=video')
  const item = gallery.items?.find((v) => v.id === video.galleryVideoId)
  ensure(item?.mediaType === 'video' && item.videoUrl === video.videoUrl && item.mode === payload.mode
    && item.provider === 'local_ltx' && item.model === payload.model && item.duration === 2 && item.aspectRatio === '16:9',
    'D3_VIDEO_GALLERY_MISSING')
  await page.locator('.phone-bottom-nav').getByRole('button', { name: 'Видео', exact: true }).click()
  const selector = '.phone-video-preview video'
  await page.locator(selector).waitFor({ state: 'visible' })
  ensure((await page.locator(selector).getAttribute('src')) === video.videoUrl, 'D3_PHONE_VIDEO_RESUME_FAILED')
  await page.waitForFunction((s) => { const v = document.querySelector(s); return v?.readyState >= 2 }, selector)
  const playback = await page.locator(selector).evaluate((v) => ({ width: v.videoWidth, height: v.videoHeight, duration: v.duration }))
  ensure(playback.width === 832 && playback.height === 480 && playback.duration > 2 && playback.duration < 2.2, 'D3_VIDEO_DECODE_INVALID')
  const frames = []
  for (const time of [.25, 1.25]) {
    await page.locator(selector).evaluate((v, t) => { v.currentTime = t }, time)
    await page.waitForFunction(({ s, t }) => { const v = document.querySelector(s); return v?.readyState >= 2 && !v.seeking && Math.abs(v.currentTime - t) < .05 }, { s: selector, t: time })
    const pixels = await page.locator(selector).evaluate((v) => { const c = document.createElement('canvas'); c.width = c.height = 32; const x = c.getContext('2d'); x.drawImage(v, 0, 0, 32, 32); return Array.from(x.getImageData(0, 0, 32, 32).data) })
    frames.push(digest(Buffer.from(pixels)))
  }
  ensure(frames[0] !== frames[1], 'D3_VIDEO_HAS_NO_DECODED_MOTION')
  const [publicationResponse] = await Promise.all([page.waitForResponse(posted('/api/feed/publications')),
    page.getByRole('button', { name: 'В ленту', exact: true }).click()])
  const publicationRequest = io.requestJSON(publicationResponse)
  ensure(publicationRequest.videoId === video.galleryVideoId && !publicationRequest.imageId, 'D3_PUBLICATION_SOURCE_MISMATCH')
  const publication = publicationFor(await io.capture(publicationResponse, 202), video.galleryVideoId)
  ensure(publication.status === 'preparing', 'D3_VIDEO_NOT_PREPARING')
  const publicationId = id(publication.id)
  await poll(() => api(owner, 'GET', `/api/feed/publications/${publicationId}/status`),
    (v) => { const p = publicationFor(v, video.galleryVideoId, publicationId); return p.media_status === 'ready' && p.status === 'published' },
    (v) => v.publication.status === 'preparing', 30)
  const publicBytes = await io.read(guest, 'GET', `/api/feed/video/${publicationId}?variant=full`, undefined, 200, LIMITS.publicMedia)
  ensure(publicBytes.length > 1024 && publicBytes.subarray(4, 8).toString() === 'ftyp', 'D3_PUBLIC_VIDEO_MISSING')
  const publicDecoded = await io.pages.get(guest).evaluate(decodePublicVideo,
    { base64: publicBytes.toString('base64'), width: playback.width, height: playback.height })
  ensure(publicDecoded.ok === true && !timedOut, 'D3_PUBLIC_VIDEO_DECODE_FAILED')
  const videoAccounting = settlement(videoBefore, await accounting(), start,
    { mode: 'text_to_video', provider: 'local_ltx' })
  result.checks.video = { status: 'PASS', jobId: videoId, galleryId: video.galleryVideoId, publicationId,
    tokenCost: quote.chargedTokens, sha256: digest(bytes), bytes: bytes.length, playback, frameSha256: frames,
    publicSha256: digest(publicBytes), publicBytes: publicBytes.length, publicPlayback: publicDecoded.playback,
    publicMediaProof: 'GUEST_FETCH_AND_DECODE', projection: videoProjection, quotedSeconds: 2, accounting: videoAccounting,
    modelExecution: false, acceleratorExecution: false,
    galleryWidth: item.width, galleryHeight: item.height, metadataMatches: item.width === playback.width && item.height === playback.height }
  await page.screenshot({ path: path.join(output, 'video-decoded.png'), animations: 'disabled' })
  if (!result.checks.video.metadataMatches) result.checks.video.status = 'FAIL'
  ensure(result.checks.video.metadataMatches, 'D3_VIDEO_GALLERY_DIMENSIONS_MISMATCH')
  result.status = 'PASS'
} catch (error) {
  const code = String(error?.message || '')
  result.errorCode = /^D3_[A-Z0-9_]{2,100}$/.test(code) ? code : 'D3_BROWSER_OPERATION_FAILED'
} finally {
  clearTimeout(timer)
  if (timedOut) { result.status = 'FAIL'; result.errorCode = 'D3_BROWSER_DEADLINE_EXCEEDED' }
  // Only the two owned sessions, with a separate fixed cleanup budget after the work deadline.
  io?.beginCleanup()
  const cleanup = await Promise.allSettled(sessions.map(async (client) => {
    for (const [method, route, expected] of [['POST', '/api/auth/session/logout-v2', 200], ['GET', '/api/me-v2', 401]]) {
      await response(client, method, route, method === 'POST' ? {} : undefined, expected)
    }
  }))
  result.sessionCleanup = sessions.length === 2 && cleanup.every((entry) => entry.status === 'fulfilled') ? 'PASS' : 'FAIL'
  result.browserCleanup = 'PASS'
  try { if (browser) await bounded(browser.close(), 5000, 'D3_BROWSER_CLOSE_TIMEOUT') }
  catch { result.browserCleanup = 'FAIL' }
  if (result.sessionCleanup !== 'PASS' || result.browserCleanup !== 'PASS') result.status = 'FAIL'
  if (io?.violation) { result.status = 'FAIL'; result.errorCode = io.violation }
  Object.assign(result, io?.counts() || { apiRequests: 0, browserHttpRequests: 0, capturedBytes: 0 })
  await writeFile(path.join(output, 'chat-video-browser.json'), JSON.stringify(result, null, 2) + '\n', { mode: 0o600, flag: 'wx' })
  process.exitCode = result.status === 'PASS' ? 0 : 1
}
