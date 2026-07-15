import { chromium } from 'playwright'

const origin = (process.env.IZO_SYNTHETIC_BASE_URL || 'http://127.0.0.1:5173').replace(/\/$/, '')
const release = process.env.FRONTEND_BUILD_LABEL || process.env.GITHUB_SHA || 'unknown'
const routes = ['/', '/feed', '/gallery', '/profile']
const started = Date.now()
let status = 'ok'
let failure

const browser = await chromium.launch({ headless: true })
try {
  for (const route of routes) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
    const response = await page.goto(`${origin}${route}`, { waitUntil: 'domcontentloaded', timeout: 20_000 })
    if (!response?.ok()) throw new Error(`${route}: HTTP ${response?.status() || 'no-response'}`)
    await page.locator('body').waitFor({ state: 'visible' })
    if (await page.getByText('Студия временно остановлена').count()) throw new Error(`${route}: root ErrorBoundary visible`)
    await page.close()
  }
} catch (error) {
  status = 'error'
  failure = error instanceof Error ? error.message : String(error)
} finally {
  await browser.close()
}

const result = { status, release, checked_routes: routes, duration_ms: Date.now() - started }
const key = process.env.IZO_SYNTHETIC_KEY || ''
if (key) {
  try {
    await fetch(`${origin}/api/runtime/synthetic-result`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-IZO-Synthetic-Key': key },
      body: JSON.stringify(result),
    })
  } catch {
    // A reporting failure must not hide the actual browser result.
  }
}

console.log(JSON.stringify({ ...result, origin, failure }))
if (status !== 'ok') process.exitCode = 1
