import { chromium } from 'playwright'

const origin = process.env.QA_ADMIN_BASE_URL || 'http://127.0.0.1:5177'
const json = (data, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(data),
})
function assert(ok, message) { if (!ok) throw new Error(message) }

const browser = await chromium.launch({ headless: true })
try {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport })
    const requests = []
    let savedKey = ''
    let enabled = false
    let model = 'gpt-4.1-mini'
    await page.route('**/api/auth/bootstrap-v2', (route) => route.fulfill(json({
      installation_id: 'isolated-qa', anonymous_id: 'test-device',
    })))
    await page.route('**/api/me-v2', (route) => route.fulfill(json({
      internal_user_id: 'admin-openai-test',
      profile: { display_name: 'Тестовый администратор', public_user_code: 'WEB-QA' },
      account: { role: 'admin', plan: 'admin', token_balance: 100 },
    })))
    await page.route('**/api/admin/**', async (route) => {
      const req = route.request()
      const path = new URL(req.url()).pathname
      if (!path.startsWith('/api/admin/openai')) {
        await route.fulfill(json({ dashboard: {}, totals: {}, users: 0 }))
        return
      }
      const body = ['PUT', 'POST', 'DELETE'].includes(req.method()) ? JSON.parse(req.postData() || '{}') : {}
      requests.push({ path, method: req.method(), body })
      const status = () => ({
        ok: true, keyConfigured: Boolean(savedKey), secretStoreReady: true, enabled, model, liveVerified: false,
        models: [
          { id: 'gpt-4.1-mini', label: 'gpt-4.1-mini' },
          { id: 'gpt-4.1', label: 'gpt-4.1' },
          { id: 'gpt-4o-mini', label: 'gpt-4o-mini' },
        ],
      })
      if (path.endsWith('/key') && req.method() === 'PUT') {
        savedKey = body.key || ''
        await route.fulfill(json(status()))
      } else if (path.endsWith('/key') && req.method() === 'DELETE') {
        savedKey = ''; enabled = false
        await route.fulfill(json(status()))
      } else if (path.endsWith('/settings') && req.method() === 'PUT') {
        if (!savedKey && body.enabled) {
          await route.fulfill(json({ detail: 'Нет ключа' }, 409))
          return
        }
        enabled = body.enabled; model = body.model
        await route.fulfill(json(status()))
      } else if (path.endsWith('/verify') && req.method() === 'POST') {
        await route.fulfill(json({ ok: true, model, verified: true }))
      } else {
        await route.fulfill(json(status()))
      }
    })
    if (viewport.width <= 900) {
      await page.addInitScript(() => window.localStorage.setItem('admin.sidebar.collapsed', '1'))
    }
    await page.goto(origin + '/admin/models/openai', { waitUntil: 'networkidle', timeout: 40000 })
    const title = page.getByRole('heading', { name: 'OpenAI API', exact: true }).first()
    await title.waitFor()
    assert(await page.getByText('Ключ не сохранён').count() === 1, 'initial key status absent')
    if (viewport.width > 900) {
      assert(await page.getByRole('link', { name: 'OpenAI API', exact: true }).count() === 1, 'navigation OpenAI link missing')
    } else {
      await page.getByRole('button', { name: 'Открыть меню админки' }).click()
      assert(await page.getByRole('link', { name: 'OpenAI API', exact: true }).count() === 1, 'mobile link missing')
      await page.getByRole('button', { name: 'Закрыть меню', exact: true }).click()
    }
    const keyInput = page.getByLabel('Проектный ключ OpenAI')
    const testKey = 'sk-proj-FAKE-BROWSER-DO-NOT-USE'
    assert(await keyInput.getAttribute('type') === 'password', 'key input is not masked')
    await keyInput.fill(testKey)
    await page.getByRole('button', { name: 'Сохранить ключ' }).click()
    await page.getByText('Ключ сохранён на сервере').waitFor()
    assert(await keyInput.inputValue() === '', 'key input must clear')
    assert(!(await page.locator('body').innerText()).includes(testKey), 'key appears in body')
    assert(!(await page.evaluate(() => JSON.stringify(window.localStorage))).includes(testKey), 'key leaked to localStorage')
    await page.getByLabel('Включить OpenAI для администратора').check()
    await page.getByRole('button', { name: 'Сохранить настройки' }).click()
    await page.getByText('Провайдер включён').waitFor()
    await page.getByRole('button', { name: 'Проверить доступ' }).click()
    await page.getByText(/OpenAI подтвердил доступ/).waitFor()
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: 'Удалить ключ' }).click()
    await page.getByText('Ключ не сохранён').waitFor()
    assert(requests.some((item) => item.path.endsWith('/verify') && item.method === 'POST'), 'manual probe missing')
    assert(!requests.some((item) => item.path.endsWith('/responses')), 'test must not send paid request')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
    assert(!overflow, 'horizontal overflow at ' + viewport.width)
    console.log('CHROMIUM_ADMIN_OPENAI_OK viewport=' + viewport.width + ' operations=' + requests.length)
    await page.close()
  }
} finally {
  await browser.close()
}
