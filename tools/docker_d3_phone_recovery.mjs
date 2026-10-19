// One existing chat-image job, one extra page in its owner's admitted BrowserContext.
import { createHash } from 'node:crypto'
import { lstat, open, realpath } from 'node:fs/promises'
import path from 'node:path'

const ensure = (condition, code) => { if (!condition) throw new Error(code) }
const validId = (value) => typeof value === 'string' && /^[A-Za-z0-9_-]{1,120}$/.test(value)
const active = new Set(['queued', 'running', 'processing'])
export const PHONE_CHECKPOINT = 'phone-active-held.json'

function identity(value) {
  ensure(value && typeof value.sourceSha === 'string' && /^[0-9a-f]{40}$/.test(value.sourceSha)
    && typeof value.project === 'string' && /^izo-asa-shadow-[a-z0-9-]{3,40}$/.test(value.project)
    && typeof value.runId === 'string' && /^[0-9a-f]{32}$/.test(value.runId)
    && validId(value.jobId), 'D3_PHONE_IDENTITY_INVALID')
  return { sourceSha: value.sourceSha, project: value.project, runId: value.runId, jobId: value.jobId }
}

export function activePhoneJob(envelope, jobId) {
  const job = envelope?.job
  ensure(envelope?.ok === true && job?.id === jobId && job.modality === 'image'
    && job.operation === 'text_to_image' && active.has(job.status) && job.terminal === false
    && Number.isFinite(job.progress) && job.progress >= 0 && job.progress < 100
    && job.result === null, 'D3_PHONE_ACTIVE_JOB_MISMATCH')
  return job.status
}

export function phoneCheckpoint(input, statuses, observations) {
  const names = ['initialStatus', 'reloadedStatus', 'returnedStatus']
  ensure(statuses && Object.keys(statuses).length === names.length
    && names.every((key) => Object.hasOwn(statuses, key) && active.has(statuses[key])), 'D3_PHONE_CHECKPOINT_STATUS_INVALID')
  ensure(observations?.sameJobAfterReload === true && observations.spaSignalAborted === true
    && observations.pollsAfterUnmount === 0 && observations.imageSubmits === 0
    && observations.videoSubmits === 0 && Object.keys(observations).length === 5
    && ['sameJobAfterReload', 'spaSignalAborted', 'pollsAfterUnmount', 'imageSubmits', 'videoSubmits']
      .every((key) => Object.hasOwn(observations, key)),
  'D3_PHONE_CHECKPOINT_OBSERVATION_INVALID')
  const owner = identity(input)
  return { schema: 'izo-d3-phone-active/v1', status: 'AWAITING_RELEASE', ...owner,
    clientSha256: createHash('sha256').update(`onenode-backend-${owner.jobId}`).digest('hex'),
    ...statuses, observations: { ...observations }, modelExecution: false, acceleratorExecution: false }
}

export async function writePhoneCheckpoint(output, value) {
  try {
    const expected = phoneCheckpoint(value, { initialStatus: value.initialStatus,
      reloadedStatus: value.reloadedStatus, returnedStatus: value.returnedStatus }, value.observations)
    ensure(JSON.stringify(value) === JSON.stringify(expected), 'D3_PHONE_CHECKPOINT_SCHEMA_INVALID')
    const directory = path.resolve(output), stat = await lstat(directory)
    ensure(await realpath(directory) === directory && !stat.isSymbolicLink() && stat.isDirectory()
      && typeof process.getuid === 'function' && stat.uid === process.getuid()
      && (stat.mode & 0o777) === 0o700, 'D3_PHONE_CHECKPOINT_DIRECTORY_INVALID')
    const data = Buffer.from(JSON.stringify(value) + '\n')
    ensure(data.length < 4096, 'D3_PHONE_CHECKPOINT_TOO_LARGE')
    const file = await open(path.join(directory, PHONE_CHECKPOINT), 'wx', 0o600)
    try {
      const actual = await file.stat()
      ensure(actual.isFile() && actual.nlink === 1 && actual.uid === process.getuid()
        && (actual.mode & 0o777) === 0o600, 'D3_PHONE_CHECKPOINT_FILE_INVALID')
      await file.writeFile(data)
      await file.sync()
    } finally { await file.close() }
  } catch (error) {
    throw new Error(/^D3_PHONE_[A-Z_]+$/.test(error?.message) ? error.message : 'D3_PHONE_CHECKPOINT_IO_FAILED')
  }
}

async function closePage(page) {
  let timer
  try {
    await Promise.race([page.close(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('D3_PHONE_PAGE_CLOSE_FAILED')), 2000)
    })])
  } catch { throw new Error('D3_PHONE_PAGE_CLOSE_FAILED') }
  finally { clearTimeout(timer) }
}

export async function observeActivePhoneImage({ context, origin, output, sourceSha, project, runId,
  jobId, ownerId, readPhone, workAllowed }) {
  const owner = identity({ sourceSha, project, runId, jobId }), target = new URL(origin)
  ensure(target.origin === origin && target.protocol === 'http:' && target.hostname === '127.0.0.1'
    && Number(target.port) >= 20000 && !target.username && !target.password
    && /^web_[0-9a-f]{32}$/.test(ownerId) && typeof readPhone === 'function'
    && typeof workAllowed === 'function', 'D3_PHONE_TARGET_NOT_ADMITTED')
  const deadline = performance.now() + 45000, detailPath = `/api/phone/v1/jobs/${jobId}`
  let violation = '', reads = 0, imageSubmits = 0, videoSubmits = 0, page
  const guard = () => ensure(workAllowed() === true && performance.now() < deadline && !violation,
    violation || 'D3_PHONE_WORK_DEADLINE')
  const timeout = () => { guard(); return Math.max(1, Math.min(6000, deadline - performance.now())) }
  const read = async () => { guard(); const value = await readPhone(jobId); guard(); return value }
  const statuses = {}, observations = { sameJobAfterReload: false, spaSignalAborted: false,
    pollsAfterUnmount: 0, imageSubmits: 0, videoSubmits: 0 }
  try {
    guard()
    page = await context.newPage()
    guard()
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.protocol === 'http:' || url.protocol === 'https:') {
        if (url.origin !== origin) violation = 'D3_PHONE_EXTERNAL_REQUEST'
        if (request.method() === 'POST' && url.pathname === '/api/generate') imageSubmits++
        if (request.method() === 'POST' && url.pathname === '/api/video/generate') videoSubmits++
        if (url.pathname.startsWith('/api/phone/v1/jobs/')) {
          if (url.pathname !== detailPath || request.method() !== 'GET') violation = 'D3_PHONE_WRONG_JOB_OBSERVED'
          if (++reads > 32) violation = 'D3_PHONE_READ_LIMIT'
        }
        if (imageSubmits || videoSubmits) violation = 'D3_PHONE_DUPLICATE_SUBMIT'
      }
    })
    await page.addInitScript((wanted) => {
      const original = window.fetch
      window.__izoPhoneObserved = []
      window.fetch = function (input, init) {
        const url = new URL(input instanceof Request ? input.url : input, location.origin)
        if (url.pathname === wanted) {
          if (window.__izoPhoneObserved.length >= 32) throw new Error('D3_PHONE_READ_LIMIT')
          const signal = init?.signal, record = { hasSignal: signal instanceof AbortSignal, aborted: signal?.aborted === true }
          window.__izoPhoneObserved.push(record)
          signal?.addEventListener('abort', () => { record.aborted = true }, { once: true })
        }
        return Reflect.apply(original, this, [input, init])
      }
    }, detailPath)
    await page.goto(`${origin}/phone/image`, { waitUntil: 'domcontentloaded', timeout: timeout() })
    await page.locator('.phone-image-busy').waitFor({ state: 'visible', timeout: timeout() })
    statuses.initialStatus = activePhoneJob(await read(), jobId)
    ensure(reads > 0 && await page.locator('.phone-image-prompt button').isDisabled(), 'D3_PHONE_ACTIVE_UI_MISSING')
    const beforeReload = reads
    await page.reload({ waitUntil: 'domcontentloaded', timeout: timeout() })
    await page.locator('.phone-image-busy').waitFor({ state: 'visible', timeout: timeout() })
    statuses.reloadedStatus = activePhoneJob(await read(), jobId)
    ensure(reads > beforeReload && await page.locator('.phone-image-prompt button').isDisabled(), 'D3_PHONE_RELOAD_FAILED')
    observations.sameJobAfterReload = true
    await page.locator('.phone-bottom-nav').getByRole('button', { name: 'Видео', exact: true }).click({ timeout: timeout() })
    await page.locator('[data-phone-workspace="image"]').waitFor({ state: 'detached', timeout: timeout() })
    await page.waitForFunction(() => window.__izoPhoneObserved.length > 0
      && window.__izoPhoneObserved.every((item) => item.hasSignal && item.aborted), undefined, { timeout: timeout() })
    observations.spaSignalAborted = true
    const atUnmount = reads
    await page.waitForTimeout(2100)
    guard()
    observations.pollsAfterUnmount = reads - atUnmount
    ensure(observations.pollsAfterUnmount === 0, 'D3_PHONE_POLLING_AFTER_UNMOUNT')
    await page.locator('.phone-bottom-nav').getByRole('button', { name: 'Фото', exact: true }).click({ timeout: timeout() })
    await page.locator('.phone-image-busy').waitFor({ state: 'visible', timeout: timeout() })
    statuses.returnedStatus = activePhoneJob(await read(), jobId)
    guard()
    observations.imageSubmits = imageSubmits; observations.videoSubmits = videoSubmits
    const checkpoint = phoneCheckpoint(owner, statuses, observations)
    await writePhoneCheckpoint(output, checkpoint) // The caller verifies this job/provider and sends SIGUSR2.
    guard()
    const image = page.getByRole('img', { name: 'Результат генерации', exact: true })
    await image.waitFor({ state: 'visible', timeout: Math.max(1, deadline - performance.now()) })
    await page.waitForFunction(() => {
      const image = document.querySelector('.phone-image-preview img[alt="Результат генерации"]')
      return image?.complete && image.naturalWidth > 0 && image.naturalHeight > 0
    }, undefined, { timeout: timeout() })
    const completed = (await read())?.job, result = completed?.result
    ensure(completed?.id === jobId && completed.modality === 'image' && completed.operation === 'text_to_image'
      && completed.status === 'completed' && completed.terminal === true && completed.progress === 100
      && result?.type === 'image' && validId(result.id) && typeof result.url === 'string'
      && /^\/api\/media\/[A-Za-z0-9_-]+\.(png|webp|jpe?g)(\?userId=[A-Za-z0-9_-]+)?$/.test(result.url)
      && (!result.url.includes('?') || result.url.endsWith(`?userId=${ownerId}`)), 'D3_PHONE_COMPLETION_MISMATCH')
    const decoded = await image.evaluate((element) => ({ width: element.naturalWidth, height: element.naturalHeight,
      url: element.getAttribute('src'), complete: element.complete }))
    ensure(decoded.complete && decoded.url === result.url && [decoded.width, decoded.height].every((v) => Number.isSafeInteger(v) && v > 0 && v <= 8192),
      'D3_PHONE_RESULT_NOT_DECODED')
    guard()
    return { status: 'PASS', ...owner, observations, statuses, decoded,
      imageId: result.id, imageUrl: result.url, uiCancellation: 'NOT_SUPPORTED', newGenerationRequests: 0 }
  } catch (error) {
    throw new Error(/^D3_PHONE_[A-Z_]+$/.test(error?.message) ? error.message : 'D3_PHONE_UI_FAILED')
  } finally { if (page) await closePage(page) }
}
