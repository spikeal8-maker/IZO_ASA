import { chromium } from 'playwright'
const BASE = 'http://127.0.0.1:48145'
const CODE = process.env.IZO_QA_ADMIN_CODE || ''
const OUTPUT = process.env.IZO_QA_OUTPUT || 'visual-out'
const KEY = 'sk-or-SYNTHETIC-CANDIDATE-210-NOT-A-REAL-KEY'
const assert = (condition, text) => { if (!condition) throw new Error(text) }
if (CODE.length < 32) throw new Error('NO_TEMP_BOOTSTRAP_PROVIDED')
const { mkdirSync } = await import('node:fs')
mkdirSync(OUTPUT, { recursive: true })
const browser = await chromium.launch({ headless: true })
try {
  for (const width of [1440, 390]) {
    const ctx = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 } })
    try {
      const guest = await ctx.request.get(BASE + '/api/admin/openrouter/status')
      assert(guest.status() === 401, 'guest status not protected')
      const auth = await ctx.request.post(BASE + '/api/auth/web-login', {
        data: { code: CODE }, headers: { Origin: BASE },
      })
      assert(auth.status() === 200, 'admin login failed ' + auth.status())
      const status = await ctx.request.get(BASE + '/api/admin/openrouter/status')
      assert(status.status() === 200, 'admin provider status not visible')
      const initial = (await status.json()).key
      assert(!initial?.configured, 'synthetic test must start without key')
      const page = await ctx.newPage()
      await page.goto(BASE + '/admin/models/openrouter/settings', { waitUntil: 'networkidle', timeout: 40000 })
      await page.getByRole('heading', { name: 'Ключ и тест OpenRouter' }).waitFor()
      if (width < 700) {
        await page.getByRole('button', { name: 'Открыть меню админки' }).click()
        await page.getByRole('link', { name: 'OpenRouter', exact: true }).waitFor()
        await page.getByRole('button', { name: 'Закрыть меню', exact: true }).click()
        await page.waitForTimeout(400)
      }
      const input = page.locator('.api-key-panel input[type="password"]')
      await input.fill('invalid-not-an-openrouter-key')
      await page.getByRole('button', { name: 'Сохранить ключ' }).click()
      assert((await input.inputValue()) === 'invalid-not-an-openrouter-key', 'failed save cleared input')
      await input.fill(KEY)
      await page.getByRole('button', { name: 'Сохранить ключ' }).click()
      await page.getByText('Ключ сохранён в защищённом хранилище', { exact: false }).waitFor()
      assert((await input.inputValue()) === '', 'saved key still in text field')
      const stored = await ctx.request.get(BASE + '/api/admin/openrouter/status')
      assert(stored.status() === 200, 'saved key status API unavailable')
      assert((await stored.json()).key.configured === true, 'key was not saved')
      await page.reload({ waitUntil: 'networkidle' })
      assert((await page.locator('.api-key-panel input[type="password"]').inputValue()) === '', 'refresh exposed key')
      const text = await page.locator('body').innerText()
      assert(!text.includes(KEY), 'DOM contains key')
      const local = await page.evaluate(() => JSON.stringify(localStorage))
      assert(!local.includes(KEY), 'local storage contains key')
      await page.screenshot({ path: OUTPUT + '/openrouter-real-' + width + '.png', fullPage: true })
      const blocked = await ctx.request.put(BASE + '/api/admin/openrouter/key', {
        data: { key: 'sk-or-invalid-origin-should-not-save' },
        headers: { Origin: 'https://evil.example' },
      })
      assert(blocked.status() === 403, 'cross-site mutation not blocked')
      const deleteButton = page.getByRole('button', { name: 'Удалить UI-ключ' })
      await deleteButton.click()
      await page.waitForTimeout(250)
      const removed = await ctx.request.get(BASE + '/api/admin/openrouter/status')
      assert((await removed.json()).key.configured === false, 'key not deleted after user action')
      const logout = await ctx.request.post(BASE + '/api/auth/session/logout-v2', {
        data: {}, headers: { Origin: BASE },
      })
      assert(logout.status() === 200, 'temporary session logout failed')
      assert((await ctx.request.get(BASE + '/api/admin/openrouter/status')).status() === 401, 'temporary admin session alive')
      console.log('REAL_OPENROUTER_ADMIN_PASS', width, 'keySaveReadbackDelete', '401/403', 'noProviderPayment')
    } finally {
      await ctx.close()
    }
  }
} finally {
  await browser.close()
}
