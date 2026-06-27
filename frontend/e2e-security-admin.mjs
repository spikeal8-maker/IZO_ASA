import { chromium } from 'playwright'

const base = 'http://127.0.0.1:5173'

async function waitForJob(page, jobId, timeoutMs = 300000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const job = await page.evaluate(async (id) => fetch(`/api/jobs/${id}`).then((response) => response.json()), jobId)
    if (['completed', 'failed', 'cancelled'].includes(job.status)) return job
    await page.waitForTimeout(1000)
  }
  throw new Error(`Timeout waiting for ${jobId}`)
}

async function generateOne(page, prompt) {
  await page.locator('textarea').fill(prompt)
  await page.locator('label').filter({ hasText: 'Width' }).locator('input').fill('512')
  await page.locator('label').filter({ hasText: 'Height' }).locator('input').fill('512')
  const advanced = page.locator('.advanced')
  if (!(await advanced.isVisible().catch(() => false))) await page.getByRole('button', { name: /Расширенные настройки/ }).click()
  await page.locator('label').filter({ hasText: 'Steps' }).locator('input').fill('1')
  const responsePromise = page.waitForResponse((response) => response.url().includes('/api/generate') && response.request().method() === 'POST')
  await page.getByRole('button', { name: /Сгенерировать/ }).click()
  const created = await (await responsePromise).json()
  const job = await waitForJob(page, created.id)
  if (job.status !== 'completed') throw new Error(`Generation failed: ${job.error || job.message}`)
  return job
}

async function run() {
  const browser = await chromium.launch()
  try {
    const userA = `accept_a_${Date.now()}`
    const userB = `accept_b_${Date.now()}`
    const context = await browser.newContext({ viewport: { width: 1366, height: 920 } })
    const page = await context.newPage()
    page.setDefaultTimeout(30000)

    await page.goto(`${base}?platform=web&userId=${userA}`, { waitUntil: 'networkidle' })
    const prompt = `security owned image ${Date.now()}`
    const job = await generateOne(page, prompt)
    if (!job.resultUrl.includes('/api/media/')) throw new Error(`Expected secure media URL, got ${job.resultUrl}`)

    await page.getByRole('button', { name: /Отправить в Telegram/ }).click()
    await page.getByText(/Отправлено: telegram/).waitFor()
    await page.getByRole('button', { name: /Отправить в MAX/ }).click()
    await page.getByText(/Отправлено: max/).waitFor()

    await page.getByRole('button', { name: /Галерея/ }).click()
    await page.getByRole('button', { name: /Список/ }).click()
    await page.getByText(prompt.slice(0, 40)).waitFor()
    await page.locator('.image-card').first().click()
    await page.getByText('Model profile').waitFor()
    await page.getByText('ComfyUI prompt').waitFor()

    await page.goto(`${base}?platform=web&userId=${userB}`, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: /Галерея/ }).click()
    const leaked = await page.getByText(prompt.slice(0, 40)).isVisible().catch(() => false)
    if (leaked) throw new Error('User B can see User A image')

    await page.goto(`${base}?platform=web&userId=${userA}`, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: /Админ/ }).click()
    await page.getByRole('heading', { name: 'LoRA' }).waitFor()
    await page.getByText('Настройки провайдеров').waitFor()
    await page.locator('label').filter({ hasText: 'hourly' }).locator('input').fill('25')
    await page.locator('label').filter({ hasText: 'daily' }).locator('input').fill('75')
    await page.getByRole('button', { name: /Сохранить/ }).click()
    await page.getByText(/"hourly":25/).waitFor()

    console.log(`Security/admin e2e passed: ${job.resultImageId} ${job.resultUrl}`)
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



