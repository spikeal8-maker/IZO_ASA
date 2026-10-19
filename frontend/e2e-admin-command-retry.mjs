/** Real CRM controls with lost-response injection after the real Docker API commit.
 * The authenticated loopback bridge keeps fixture sessions inside the volume.
 * No mutation response is mocked; every allowed API request reaches uvicorn.
 */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { execFile } from 'node:child_process'
import { createServer } from 'node:http'
import { readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, extname, isAbsolute, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dist = resolve(root, 'frontend/dist')
const sha = process.env.PROOF_SOURCE_SHA || ''
const run = `${process.env.GITHUB_RUN_ID || ''}-${process.env.GITHUB_RUN_ATTEMPT || ''}`
const output = resolve(process.env.PROOF_OUTPUT || '/invalid-proof-output')
const temporary = resolve(process.env.RUNNER_TEMP || '/invalid-runner-temp')
const within = (base, candidate) => { const path = relative(base, candidate); return path !== '' && !isAbsolute(path) && path !== '..' && !path.startsWith(`..${sep}`) }
assert(process.env.GITHUB_ACTIONS === 'true' && process.env.RUNNER_ENVIRONMENT === 'github-hosted'
  && process.env.RUNNER_OS === 'Linux' && process.platform === 'linux', 'ADMIN_BROWSER_HOSTED_SCOPE_REJECTED')
assert(/^[a-f0-9]{40}$/.test(sha) && /^[0-9]{1,20}-[0-9]{1,4}$/.test(run), 'ADMIN_BROWSER_SOURCE_INVALID')
assert(within(temporary, output) && !within(root, output), 'ADMIN_BROWSER_OUTPUT_SCOPE_REJECTED')
const dockerEndpoint = 'unix:///var/run/docker.sock'
const dockerOverrides = ['DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH',
  'DOCKER_CONFIG', 'DOCKER_API_VERSION', 'BUILDX_BUILDER', 'BUILDX_CONFIG', 'BUILDKIT_HOST']
assert(dockerOverrides.every(key => !process.env[key]), 'ADMIN_BROWSER_DOCKER_OVERRIDE_REJECTED')
const dockerEnvironment = Object.fromEntries(Object.entries(process.env).filter(([key]) => !dockerOverrides.includes(key)))
const cli = (args, input) => {
  const docker = args[0] === 'docker'
  if (docker) assert(statSync('/var/run/docker.sock').isSocket(), 'ADMIN_BROWSER_LOCAL_DOCKER_SOCKET_MISSING')
  const actual = docker ? ['docker', '--host', dockerEndpoint, ...args.slice(1)] : args
  return new Promise((done, reject) => {
    let inputError
    const child = execFile(actual[0], actual.slice(1), { cwd: root, encoding: 'utf8', timeout: 30000,
      maxBuffer: 1024 * 1024, env: docker ? dockerEnvironment : undefined }, (error, stdout) => {
      if (error || inputError) reject(error || inputError)
      else done(stdout.trim())
    })
    child.stdin.on('error', error => { inputError = error })
    child.stdin.end(input)
  })
}
assert.equal(await cli(['git', 'rev-parse', 'HEAD']), sha, 'ADMIN_BROWSER_SOURCE_SHA_MISMATCH')
assert.equal(await cli(['git', 'status', '--porcelain', '--untracked-files=all']), '', 'ADMIN_BROWSER_SOURCE_DIRTY')
const plan = JSON.parse(readFileSync(resolve(output, 'resources.json'), 'utf8'))
assert.equal(plan.sha, sha)
assert.equal(plan.run, run)
const containerName = `izo-admin-${sha.slice(0, 10)}-${run}-api`
assert.equal(plan.names.api, containerName)
const runtime = readFileSync(resolve(root, 'tools/docker_admin_commands_runtime.py'), 'utf8')
const inspected = JSON.parse(await cli(['docker', 'container', 'inspect', containerName]))[0]
const containerId = inspected.Id

async function ownerCheck() {
  const current = JSON.parse(await cli(['docker', 'container', 'inspect', containerId]))[0]
  assert.equal(current.Name, '/' + containerName)
  assert.equal(current.Config.Labels['io.izo.admin-proof.owner'], 'ADMIN-COMMAND-IDEMPOTENCY-001')
  assert.equal(current.Config.Labels['io.izo.admin-proof.run'], run)
  assert.equal(current.Config.Labels['io.izo.admin-proof.source'], sha)
  assert.equal(current.Config.Image, process.env.PROOF_IMAGE_ID)
  assert.equal(current.HostConfig.NetworkMode, 'none')
  assert(!current.HostConfig.PortBindings || Object.keys(current.HostConfig.PortBindings).length === 0)
  assert(current.State.Running && current.Config.User === '10001:10001')
}
await ownerCheck()

async function bridge(message) {
  await ownerCheck()
  const raw = await cli(['docker', 'exec', '--interactive', containerId, 'python', '-', 'bridge', '--request-json', JSON.stringify(message)], runtime)
  const lines = raw.split('\n').filter(line => line.startsWith('IZO_ADMIN_RECEIPT:'))
  assert.equal(lines.length, 1, 'ADMIN_BROWSER_BRIDGE_RECEIPT_INVALID')
  const value = JSON.parse(lines[0].slice('IZO_ADMIN_RECEIPT:'.length))
  assert(value.status === 'PASS' && value.phase === 'bridge', 'ADMIN_BROWSER_BRIDGE_REJECTED')
  return value
}

// Retain serialized fixture access without blocking Playwright's event loop.
let bridgeQueue = Promise.resolve()
function queuedBridge(message) {
  const result = bridgeQueue.then(() => bridge(message))
  bridgeQueue = result.catch(() => {})
  return result
}

const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2' }
const server = createServer((request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://127.0.0.1').pathname)
    const file = resolve(dist, '.' + pathname)
    assert(within(dist, file), 'ADMIN_BROWSER_STATIC_SCOPE_REJECTED')
    let selected = file
    try { if (!statSync(file).isFile()) selected = resolve(dist, 'index.html') }
    catch { selected = resolve(dist, 'index.html') }
    if (pathname.startsWith('/api/')) { response.writeHead(404); response.end(); return }
    response.writeHead(200, { 'Content-Type': mime[extname(selected)] || 'application/octet-stream', 'Cache-Control': 'no-store' })
    response.end(readFileSync(selected))
  } catch { response.writeHead(404); response.end() }
})
await new Promise((done, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', done) })
const base = `http://127.0.0.1:${server.address().port}`
const browser = await chromium.launch({ headless: true })
const report = { status: 'FAIL', sourceSha: sha, realCrm: true, realHttp: true,
  dockerEndpoint,
  fault: 'drop first successful HTTP response after commit', transport: 'browser route → docker exec → network-none uvicorn loopback',
  fixtureSessions: 'volume-only', cases: [], blockedRequests: [] }

async function openConfirmation(page, viewport, kind) {
  const name = `Admin proof ${viewport} ${kind}`
  const search = page.getByPlaceholder('Код, имя, email, телефон или username')
  await search.fill(name)
  await page.getByRole('button', { name: 'Найти', exact: true }).click()
  await page.getByRole('button', { name: `Открыть карточку ${name}`, exact: true }).click()
  const card = page.getByRole('dialog', { name: 'Карточка пользователя', exact: true })
  await card.getByRole('navigation', { name: 'Разделы карточки пользователя' }).getByRole('button', { name: 'Управление', exact: true }).click()
  await card.getByRole('button', { name: kind === 'tokens' ? 'Своя сумма' : 'Изменить тариф', exact: true }).click()
  return page.getByRole('dialog', { name: 'Подтверждение действия', exact: true })
}

try {
  for (const [viewport, dimensions] of [['desktop', { width: 1366, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
    for (const kind of ['tokens', 'plan']) {
      const context = await browser.newContext({ viewport: dimensions, serviceWorkers: 'block' })
      const page = await context.newPage()
      page.setDefaultTimeout(20000)
      const errors = []
      const calls = []
      const routeTasks = new Set()
      const internal = `admin-proof-${run}-browser-${viewport}-${kind}`
      const mutationPath = `/api/admin/users/${internal}/${kind}-v2`
      let drop = true
      let phase = 'open-initial-confirmation'
      page.on('pageerror', error => errors.push(error.message))
      const handleRoute = async route => {
        const request = route.request()
        const url = new URL(request.url())
        if (url.origin !== base) {
          report.blockedRequests.push({ method: request.method(), path: url.pathname })
          await route.abort('blockedbyclient')
          return
        }
        if (!url.pathname.startsWith('/api/')) { await route.continue(); return }
        try {
          const payload = request.postData() ? JSON.parse(request.postData()) : {}
          const result = await queuedBridge({ path: url.pathname + url.search, method: request.method(), payload })
          assert.equal(result.httpStatus, 200, 'ADMIN_BROWSER_API_NOT_SUCCESSFUL')
          if (url.pathname === mutationPath && request.method() === 'POST') {
            calls.push({ payload, bodySha256: result.bodySha256, state: result.ownedState })
            if (drop) { drop = false; await route.abort('connectionreset'); return }
          }
          await route.fulfill({ status: result.httpStatus, contentType: 'application/json', body: JSON.stringify(result.body) })
        } catch (error) {
          errors.push(error.message)
          await route.abort('blockedbyclient')
        }
      }
      await context.route('**/*', route => {
        const task = handleRoute(route)
        routeTasks.add(task)
        task.then(() => routeTasks.delete(task), error => { errors.push(error.message); routeTasks.delete(task) })
        return task
      })
      const drainRoutes = async () => {
        while (routeTasks.size) await Promise.allSettled([...routeTasks])
        await bridgeQueue
      }
      try {
        await page.goto(base + '/admin/crm', { waitUntil: 'networkidle' })
        assert.equal(await page.locator('meta[name="izo-release"]').getAttribute('content'), sha)
        let dialog = await openConfirmation(page, viewport, kind)
        const reason = `Controlled ${viewport} ${kind} retry`
        phase = 'submit-initial-command'
        if (kind === 'tokens') await dialog.getByLabel('Изменение баланса', { exact: true }).fill('25')
        else await dialog.getByRole('combobox', { name: 'Тариф', exact: true }).selectOption('pro')
        await dialog.getByLabel('Причина (обязательно)', { exact: true }).fill(reason)
        await dialog.getByRole('button', { name: 'Подтвердить', exact: true }).click()
        await dialog.locator('.crm-err').waitFor()
        phase = 'check-lost-response'
        assert.equal(calls.length, 1)
        assert.equal(drop, false)
        assert(calls[0].state && calls[0].state.counts.commands === 1)
        await page.screenshot({ path: resolve(output, `crm-${viewport}-${kind}-lost-response.png`), fullPage: true })
        phase = 'recover-confirmation'
        await page.reload({ waitUntil: 'networkidle' })
        dialog = await openConfirmation(page, viewport, kind)
        assert.equal(await dialog.getByLabel('Причина (обязательно)', { exact: true }).inputValue(), reason)
        const restoredField = kind === 'tokens'
          ? dialog.getByLabel('Изменение баланса', { exact: true })
          : dialog.getByRole('combobox', { name: 'Тариф', exact: true })
        assert.equal(await restoredField.inputValue(), kind === 'tokens' ? '25' : 'pro')
        await dialog.getByRole('button', { name: 'Подтвердить', exact: true }).scrollIntoViewIfNeeded()
        const bounds = await dialog.boundingBox()
        assert(bounds && bounds.x >= -1 && bounds.x + bounds.width <= dimensions.width + 1, 'ADMIN_BROWSER_CONFIRMATION_OVERFLOW')
        await page.screenshot({ path: resolve(output, `crm-${viewport}-${kind}-recovered.png`), fullPage: true })
        phase = 'observe-retry-success'
        assert.equal(await dialog.locator('.crm-action-ok').count(), 0, 'ADMIN_BROWSER_SUCCESS_PRECEDES_RETRY')
        // Observe the transient marker while asynchronous refresh bridges run.
        await Promise.all([
          dialog.locator('.crm-action-ok').waitFor({ state: 'visible' }),
          dialog.getByRole('button', { name: 'Подтвердить', exact: true }).dblclick(),
        ])
        phase = 'verify-durable-retry'
        await dialog.waitFor({ state: 'hidden' })
        await page.waitForLoadState('networkidle')
        await drainRoutes()
        assert.equal(await page.evaluate(path => sessionStorage.getItem('izo.admin-command.v1:' + path), mutationPath.slice(4)), null)
        await context.close()
        await drainRoutes()
        assert.equal(calls.length, 2, 'ADMIN_BROWSER_DUPLICATE_FINANCIAL_COMMAND')
        assert.deepEqual(calls[0], calls[1], 'ADMIN_BROWSER_RETRY_KEY_RESPONSE_OR_STATE_CHANGED')
        assert.deepEqual(calls[1].state.counts, { ledger: 1, grants: kind === 'plan' ? 1 : 0, audit: 1, commands: 1 })
        assert.deepEqual(errors, [])
        report.cases.push({ viewport, kind, status: 'PASS', httpRequests: 2, lostResponseInjected: true,
          reloadedInput: true, sameKeyResponseAndState: true, commandKeySha256: createHash('sha256').update(calls[0].payload.idempotency_key).digest('hex'),
          apiBodySha256: calls[0].bodySha256, effects: calls[1].state.counts, persistedState: calls[1].state, target: internal })
      } catch (error) {
        report.failedCase = { viewport, kind, phase, httpRequests: calls.length, lostResponseInjected: !drop,
          browserErrorCount: errors.length, commands: calls.slice(0, 3).map(call => ({
            commandKeySha256: typeof call.payload.idempotency_key === 'string'
              ? createHash('sha256').update(call.payload.idempotency_key).digest('hex') : null,
            apiBodySha256: call.bodySha256, persistedState: call.state,
          })) }
        try {
          const confirmation = page.getByRole('dialog', { name: 'Подтверждение действия', exact: true })
          report.failedCase.confirmationCount = await confirmation.count()
          report.failedCase.successMarkerCount = await confirmation.locator('.crm-action-ok').count()
          await page.screenshot({ path: resolve(output, `crm-${viewport}-${kind}-failure.png`), fullPage: true, timeout: 5000 })
        } catch { report.failedCase.domDiagnostics = 'unavailable' }
        throw error
      } finally { await drainRoutes(); await context.close(); await drainRoutes() }
    }
  }
  assert.equal(report.cases.length, 4)
  assert.deepEqual(report.blockedRequests, [])
  report.status = 'PASS'
} catch (error) {
  report.failure = `${error.name}:${error.message}`
  process.exitCode = 1
} finally {
  await browser.close()
  server.closeAllConnections()
  await new Promise(done => server.close(done))
  writeFileSync(resolve(output, 'browser-receipt.json'), JSON.stringify(report, null, 2) + '\n')
  console.log(JSON.stringify({ status: report.status, sourceSha: sha, browserCases: report.cases.length, failure: report.failure }))
}
