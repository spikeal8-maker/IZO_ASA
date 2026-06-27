// Phase 20C.2 — local/prod admin parity visual check (no Claude-in-Chrome needed).
// Screenshots the app + probes the admin diagnostics on each target so the data-source
// difference (same backend/DB, different auth) is visible side by side.
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const TARGETS = [
  { name: 'local-preview', url: 'http://127.0.0.1:5173/' },
  { name: 'production', url: 'https://izo.alikinas.ru/' },
]
const OUT = 'visual-out'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const rows = []
for (const t of TARGETS) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errs = []
  page.on('pageerror', (e) => errs.push(String(e.message).slice(0, 120)))
  let version = null, asset = null, diag = null
  try {
    await page.goto(t.url, { waitUntil: 'networkidle', timeout: 40000 })
    await page.waitForTimeout(1200)
    await page.screenshot({ path: `${OUT}/${t.name}-landing.png` })
    version = await page.evaluate(async () => {
      try { return (await (await fetch('/api/version')).json()).build } catch { return null }
    })
    diag = await page.evaluate(async () => {
      try { const r = await fetch('/api/admin/diagnostics-v2', { credentials: 'include' }); return { status: r.status, body: r.ok ? await r.json() : null } } catch { return { status: 0 } }
    })
    asset = await page.evaluate(() => {
      const s = [...document.querySelectorAll('script[src]')].map((x) => x.getAttribute('src')).find((x) => /assets\/index-/.test(x || ''))
      return s || null
    })
  } catch (e) {
    rows.push({ target: t.name, error: String(e.message).slice(0, 120) })
    await page.close(); continue
  }
  rows.push({
    target: t.name, version, asset,
    admin_diag_status: diag?.status,
    admin: diag?.status === 200 ? 'admin session ✓' : 'no admin session',
    db_file: diag?.body?.db_file ?? null,
    user_count: diag?.body?.user_count ?? null,
    pageerrors: errs.length ? errs.join(' | ') : 'none',
  })
  await page.close()
}
await browser.close()
console.log(JSON.stringify(rows, null, 2))
console.log('\nScreenshots in', OUT + '/')
