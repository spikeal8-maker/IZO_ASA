// Source UI proof only. Python owns the hard 140s work + 5s descendant drain.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { constants } from 'node:fs'
import { open, realpath, stat } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const frontend = path.join(root, 'frontend')
const require = createRequire(path.join(frontend, 'package.json'))
const LIMIT = 16384
const digest = (value) => createHash('sha256').update(value).digest('hex')
const ensure = (condition, code) => { if (!condition) throw new Error(code) }
const expectedCases = [390, 430].flatMap((width) => [
  `image-${width}-completed`, `image-${width}-cancelled`, `image-${width}-spa-unmount`,
  `video-${width}-spa-unmount`, `image-${width}-recovery-retry`,
]).sort()

async function boundedFile(filename, limit) {
  const handle = await open(filename, constants.O_RDONLY | constants.O_NOFOLLOW)
  try {
    const info = await handle.stat()
    ensure(info.isFile() && info.uid === process.getuid() && info.nlink === 1 && info.size <= limit, 'D3_PHONE_UI_FILE_INVALID')
    const buffer = Buffer.alloc(limit + 1)
    const { bytesRead } = await handle.read(buffer, 0, limit + 1, 0)
    ensure(bytesRead <= limit, 'D3_PHONE_UI_FILE_INVALID')
    return buffer.subarray(0, bytesRead)
  } finally { await handle.close() }
}

async function readInput() {
  let bytes = 0
  const chunks = []
  for await (const chunk of process.stdin) {
    bytes += chunk.length
    ensure(bytes <= LIMIT, 'D3_PHONE_UI_INPUT_INVALID')
    chunks.push(chunk)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

async function within(promise, milliseconds) {
  let timer
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('D3_PHONE_UI_DEADLINE_EXCEEDED')), milliseconds)
    })])
  } finally { clearTimeout(timer) }
}

async function readIndex(origin) {
  const response = await fetch(`${origin}/phone/image`, { redirect: 'error', signal: AbortSignal.timeout(5000),
    headers: { Accept: 'text/html', 'Accept-Encoding': 'identity' } })
  ensure(response.status === 200 && response.headers.get('content-type')?.startsWith('text/html'), 'D3_PHONE_UI_BUILD_MISMATCH')
  const reader = response.body.getReader(), chunks = []
  let bytes = 0
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      bytes += value.length
      ensure(bytes <= 65536, 'D3_PHONE_UI_FILE_INVALID')
      chunks.push(value)
    }
    return Buffer.concat(chunks)
  } finally { await reader.cancel() }
}

async function writeReceipt(output, report) {
  const encoded = Buffer.from(JSON.stringify(report) + '\n')
  ensure(encoded.length <= LIMIT, 'D3_PHONE_UI_RECEIPT_LIMIT')
  const handle = await open(path.join(output, 'phone-ui-browser.json'), 'wx', 0o600)
  try { await handle.writeFile(encoded) } finally { await handle.close() }
}

let output, server, browser, timedOut = false
const report = { status: 'FAIL', phase: 'input', browserCleanup: 'NOT_RUN', serverCleanup: 'NOT_RUN' }
try {
  const input = await within(readInput(), 5000)
  const keys = ['schema', 'sourceSha', 'jobIdentity', 'runId', 'output', 'helperSha256', 'buildIndexSha256', 'runnerSha256', 'supervisorSha256']
  ensure(input && Object.keys(input).sort().join() === keys.sort().join()
    && input.schema === 'izo-d3-phone-ui/v1' && /^[0-9a-f]{40}$/.test(input.sourceSha)
    && /^[0-9a-f]{32}$/.test(input.runId) && /^[0-9]{1,20}\.[0-9]{1,8}\.[A-Za-z0-9_-]{1,64}$/.test(input.jobIdentity)
    && ['helperSha256', 'buildIndexSha256', 'runnerSha256', 'supervisorSha256'].every((key) => /^[0-9a-f]{64}$/.test(input[key])),
  'D3_PHONE_UI_INPUT_INVALID')
  ensure(process.platform === 'linux' && process.getuid() !== 0 && process.env.GITHUB_ACTIONS === 'true'
    && process.env.RUNNER_ENVIRONMENT === 'github-hosted' && process.env.GITHUB_SHA === input.sourceSha
    && ['GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB'].map((key) => process.env[key]).join('.') === input.jobIdentity,
  'D3_PHONE_UI_CI_SCOPE_INVALID')
  ensure(typeof input.output === 'string' && path.isAbsolute(input.output) && await realpath(input.output) === input.output,
    'D3_PHONE_UI_OUTPUT_INVALID')
  const info = await stat(input.output)
  ensure(info.isDirectory() && info.uid === process.getuid() && (info.mode & 0o777) === 0o700
    && process.env.RUNNER_TEMP && path.dirname(input.output) === await realpath(process.env.RUNNER_TEMP), 'D3_PHONE_UI_OUTPUT_INVALID')
  output = input.output
  Object.assign(report, Object.fromEntries(keys.filter((key) => key !== 'output').map((key) => [key, input[key]])))
  const helperPath = path.join(frontend, 'phoneJobRecovery.ui.mjs')
  ensure(digest(await boundedFile(helperPath, 24576)) === input.helperSha256
    && digest(await boundedFile(fileURLToPath(import.meta.url), 24576)) === input.runnerSha256
    && digest(await boundedFile(path.join(frontend, 'dist/index.html'), 65536)) === input.buildIndexSha256,
  'D3_PHONE_UI_SOURCE_MISMATCH')
  const work = async () => {
    report.phase = 'preview'
    const { preview } = await import(pathToFileURL(require.resolve('vite')).href)
    // No API/media proxy and no host app: serve only this checkout's built dist.
    server = await preview({ root: frontend, configFile: false, envFile: false, logLevel: 'silent',
      build: { outDir: 'dist' }, preview: { host: '127.0.0.1', port: 0, strictPort: true,
        open: false, proxy: undefined, cors: false, allowedHosts: ['127.0.0.1'] } })
    if (timedOut) await within(server.close(), 2000)
    ensure(!timedOut, 'D3_PHONE_UI_DEADLINE_EXCEEDED')
    const address = server.httpServer.address()
    ensure(address && typeof address === 'object' && address.address === '127.0.0.1'
      && Number.isInteger(address.port) && address.port > 1024, 'D3_PHONE_UI_SERVER_INVALID')
    const origin = `http://127.0.0.1:${address.port}`
    ensure(digest(await readIndex(origin)) === input.buildIndexSha256, 'D3_PHONE_UI_BUILD_MISMATCH')
    report.previewPort = address.port
    report.phase = 'browser'
    const { chromium } = require('playwright')
    browser = await chromium.launch({ headless: true, timeout: 15000 })
    if (timedOut) await within(browser.close(), 2000)
    ensure(!timedOut, 'D3_PHONE_UI_DEADLINE_EXCEEDED')
    const { provePhoneJobRecoveryUI } = await import(pathToFileURL(helperPath).href)
    report.phase = 'cases'
    const proof = await provePhoneJobRecoveryUI(browser, { origin })
    ensure(!timedOut, 'D3_PHONE_UI_DEADLINE_EXCEEDED')
    assert.deepEqual(proof.cases.map((entry) => entry.case).sort(), expectedCases)
    ensure(proof.status === 'PASS' && proof.cases.every((entry) => entry.status === 'PASS'), 'D3_PHONE_UI_CASES_INVALID')
    report.proof = proof
    report.status = 'PASS'
  }
  try { await within(work(), 125000) }
  catch (error) { timedOut = true; throw error }
} catch (error) {
  const failure = error?.phoneUiFailure
  if (expectedCases.includes(failure?.case) && ['TIMEOUT', 'ASSERTION', 'ERROR'].includes(failure.kind)
    && Number.isInteger(failure.sourceLine) && failure.sourceLine >= 0 && failure.sourceLine <= 500) {
    report.failure = { case: failure.case, kind: failure.kind, sourceLine: failure.sourceLine }
  }
  report.status = 'FAIL'
  report.errorCode = /^D3_PHONE_UI_[A-Z_]+$/.test(error?.message || '') ? error.message : 'D3_PHONE_UI_CHECK_FAILED'
} finally {
  const cleanup = await Promise.allSettled([
    browser ? within(Promise.resolve().then(() => browser.close()), 3000) : Promise.resolve(),
    server ? within(Promise.resolve().then(() => server.close()), 3000) : Promise.resolve(),
  ])
  report.browserCleanup = cleanup[0].status === 'fulfilled' ? 'PASS' : 'FAIL'
  report.serverCleanup = cleanup[1].status === 'fulfilled' && !server?.httpServer.listening ? 'PASS' : 'FAIL'
  if (report.browserCleanup !== 'PASS' || report.serverCleanup !== 'PASS') {
    report.status = 'FAIL'; report.errorCode = 'D3_PHONE_UI_CLEANUP_FAILED'
  }
  if (output) {
    try { await writeReceipt(output, report) }
    catch { report.status = 'FAIL'; report.errorCode = 'D3_PHONE_UI_RECEIPT_FAILED' }
  }
  process.exitCode = report.status === 'PASS' ? 0 : 1
}
