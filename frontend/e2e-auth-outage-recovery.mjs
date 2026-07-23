import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const localPort = 5199
const localOrigin = `http://127.0.0.1:${localPort}`
const baseUrl = process.env.IZO_E2E_BASE_URL || localOrigin

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function waitForPreview(url) {
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Preview is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`preview did not start at ${url}`)
}

let previewProcess
if (!process.env.IZO_E2E_BASE_URL) {
  const viteBin = fileURLToPath(new URL('./node_modules/vite/bin/vite.js', import.meta.url))
  previewProcess = spawn(process.execPath, [viteBin, 'preview', '--host', '127.0.0.1', '--port', String(localPort), '--strictPort'], {
    cwd: fileURLToPath(new URL('.', import.meta.url)),
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  await waitForPreview(localOrigin)
}

const browser = await chromium.launch({ headless: true })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  let capabilitiesRequests = 0
  await context.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/capabilities-v2') {
      capabilitiesRequests += 1
      if (capabilitiesRequests <= 2) {
        await route.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({ detail: 'temporary outage' }) })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          password_login_available: true,
          password_register_available: true,
          email_otp_available: false,
          bot_login: {
            telegram_bot_login_available: true,
            max_bot_login_available: true,
          },
        }),
      })
      return
    }
    if (url.pathname === '/api/auth/bootstrap-v2') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ installation_id: 'recovery-e2e', anonymous_id: 'recovery-e2e' }) })
      return
    }
    await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'test guest' }) })
  })

  const page = await context.newPage()
  page.setDefaultTimeout(20_000)
  await page.goto(`${baseUrl}/profile?auth_outage_recovery=${Date.now()}`, { waitUntil: 'domcontentloaded' })
  const dialog = page.getByRole('dialog')
  await dialog.waitFor()

  const telegramButton = dialog.getByRole('button', { name: 'Войти через Telegram-бота', exact: true })
  const maxButton = dialog.getByRole('button', { name: 'Войти через MAX', exact: true })
  await dialog.getByText('Сервер авторизации временно недоступен.', { exact: false }).waitFor()
  assert(await telegramButton.isDisabled(), 'Telegram login must stay closed while capabilities are unknown')
  assert(await maxButton.isDisabled(), 'MAX login must stay closed while capabilities are unknown')

  await page.waitForFunction(() => {
    const buttons = Array.from(document.querySelectorAll('.auth-modal-providers button'))
    return buttons.length >= 2 && buttons.every((button) => !button.disabled)
  })

  assert(capabilitiesRequests >= 3, `expected automatic recovery requests, got ${capabilitiesRequests}`)
  assert(await telegramButton.isEnabled(), 'Telegram login did not recover automatically')
  assert(await maxButton.isEnabled(), 'MAX login did not recover automatically')
  assert(await dialog.getByText('Сервер авторизации временно недоступен.', { exact: false }).count() === 0, 'stale outage error remained visible')

  await context.close()
  console.log(JSON.stringify({ ok: true, capabilitiesRequests }))
} finally {
  await browser.close()
  if (previewProcess) previewProcess.kill()
}
