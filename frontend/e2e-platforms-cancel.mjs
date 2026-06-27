import { chromium } from 'playwright'

const base = 'http://127.0.0.1:5173'

async function waitForJob(page, jobId, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const job = await page.evaluate(async (id) => fetch(`/api/jobs/${id}`).then((response) => response.json()), jobId)
    if (['completed', 'failed', 'cancelled'].includes(job.status)) return job
    await page.waitForTimeout(700)
  }
  throw new Error(`Timeout waiting for ${jobId}`)
}

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 860 } })
    page.setDefaultTimeout(20000)
    for (const platform of ['web', 'telegram', 'max']) {
      await page.goto(`${base}?platform=${platform}&userId=platform_${platform}_${Date.now()}`, { waitUntil: 'networkidle' })
      await page.getByRole('heading', { name: 'Текст → изображение' }).waitFor()
      const bootstrap = await page.evaluate(async () => fetch('/api/app/bootstrap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: new URLSearchParams(location.search).get('platform'), language: 'ru', userId: 'browser_acceptance' }),
      }).then((response) => response.json()))
      if (bootstrap.platform !== platform) throw new Error(`Wrong platform bootstrap: expected ${platform}, got ${bootstrap.platform}`)
    }

    await page.setViewportSize({ width: 390, height: 820 })
    await page.goto(`${base}?platform=telegram&userId=mobile_${Date.now()}`, { waitUntil: 'networkidle' })
    await page.locator('.bottom-nav').waitFor()
    await page.getByRole('button', { name: /Настройки/ }).last().click()
    await page.getByRole('heading', { name: 'Настройки' }).waitFor()
    await page.getByRole('button', { name: /Генерация/ }).last().click()
    await page.getByRole('heading', { name: 'Текст → изображение' }).waitFor()

    await page.setViewportSize({ width: 1280, height: 860 })
    await page.goto(`${base}?platform=web&userId=cancel_${Date.now()}`, { waitUntil: 'networkidle' })
    await page.locator('textarea').fill(`cancel acceptance ${Date.now()}`)
    await page.locator('label').filter({ hasText: 'Width' }).locator('input').fill('512')
    await page.locator('label').filter({ hasText: 'Height' }).locator('input').fill('512')
    await page.getByRole('button', { name: /Расширенные настройки/ }).click()
    await page.locator('label').filter({ hasText: 'Steps' }).locator('input').fill('8')
    const responsePromise = page.waitForResponse((response) => response.url().includes('/api/generate') && response.request().method() === 'POST')
    await page.getByRole('button', { name: /Сгенерировать/ }).click()
    const created = await (await responsePromise).json()
    await page.getByRole('button', { name: /Остановить/ }).click()
    const job = await waitForJob(page, created.id)
    if (job.status !== 'cancelled') throw new Error(`Cancel did not stick, final status: ${job.status}`)

    console.log('Platforms/mobile/cancel e2e passed.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



