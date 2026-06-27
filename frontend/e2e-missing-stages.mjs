import { chromium } from 'playwright'

const baseUrl = `http://127.0.0.1:5173?platform=web&userId=e2e_missing_${Date.now()}`

async function waitForJob(page, jobId, timeoutMs = 360000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const job = await page.evaluate(async (id) => {
      const response = await fetch(`/api/jobs/${id}`)
      return response.json()
    }, jobId)
    if (['completed', 'failed', 'cancelled'].includes(job.status)) return job
    await page.waitForTimeout(1500)
  }
  throw new Error(`Timeout waiting for ${jobId}`)
}

async function generateFromUi(page, label) {
  const responsePromise = page.waitForResponse((response) => response.url().includes('/api/generate') && response.request().method() === 'POST')
  await page.getByRole('button', { name: /Сгенерировать/ }).click()
  const response = await responsePromise
  const created = await response.json()
  const job = await waitForJob(page, created.id)
  if (job.status !== 'completed') throw new Error(`${label} failed: ${job.error || job.message}`)
  console.log(`${label}: ${job.resultImageId} ${job.resultUrl}`)
  return job
}

async function setFastSettings(page, seed) {
  await page.locator('label').filter({ hasText: 'Width' }).locator('input').fill('512')
  await page.locator('label').filter({ hasText: 'Height' }).locator('input').fill('512')
  await page.locator('label').filter({ hasText: 'Seed' }).locator('input').fill(String(seed))
  const advanced = page.locator('.advanced')
  if (!(await advanced.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /Расширенные настройки/ }).click()
  }
  await page.locator('label').filter({ hasText: 'Steps' }).locator('input').fill('1')
  await page.locator('label').filter({ hasText: 'CFG' }).locator('input').fill('1.1')
}

async function drawOnCanvas(page) {
  const canvas = page.locator('.konva-stage canvas').first()
  const box = await canvas.boundingBox()
  if (!box) throw new Error('Canvas was not rendered')
  await page.mouse.move(box.x + 120, box.y + 120)
  await page.mouse.down()
  await page.mouse.move(box.x + 260, box.y + 160)
  await page.mouse.move(box.x + 380, box.y + 230)
  await page.mouse.up()
}

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 920 } })
    page.setDefaultTimeout(30000)
    await page.goto(baseUrl, { waitUntil: 'networkidle' })

    await page.getByRole('heading', { name: 'Текст → изображение' }).waitFor()
    await setFastSettings(page, 5101)
    await page.locator('textarea').fill(`full tz source image ${Date.now()}`)
    await generateFromUi(page, 'Text to Image source')

    await page.getByRole('button', { name: 'Рисование' }).first().click()
    await page.getByText('Пустой слой').waitFor()
    await page.locator('label').filter({ hasText: 'Толщина кисти' }).locator('input').fill('18')
    await drawOnCanvas(page)
    await page.locator('textarea').fill('turn the sketch into a clean product render')
    await setFastSettings(page, 5201)
    await generateFromUi(page, 'Paint')

    await page.getByRole('button', { name: 'Закрасить область' }).first().click()
    await page.getByRole('button', { name: /Использовать последнее изображение/ }).click()
    await page.getByText('Показать / скрыть маску').waitFor()
    await drawOnCanvas(page)
    await page.locator('textarea').fill('replace masked area with soft blue fabric')
    await setFastSettings(page, 5301)
    await generateFromUi(page, 'Inpaint')

    await page.getByRole('button', { name: 'Расширить изображение' }).first().click()
    await page.getByRole('button', { name: /Использовать последнее изображение/ }).click()
    await page.locator('label').filter({ hasText: 'Expand Right' }).locator('input').fill('128')
    await page.locator('label').filter({ hasText: 'Expand Bottom' }).locator('input').fill('128')
    await page.getByText(/Итоговый размер/).waitFor()
    await page.locator('textarea').fill('extend the scene naturally with matching light')
    await setFastSettings(page, 5401)
    await generateFromUi(page, 'Outpaint')

    await page.getByRole('button', { name: 'Замена лица' }).first().click()
    for (const index of [0, 1]) {
      const box = page.locator('.image-box').nth(index)
      const lastButton = box.getByRole('button', { name: /Использовать последнее изображение/ })
      if (await lastButton.isVisible().catch(() => false)) await lastButton.click()
    }
    await page.locator('textarea').fill('replace the face while preserving lighting')
    await setFastSettings(page, 5501)
    await generateFromUi(page, 'Face Swap')

    await page.getByRole('button', { name: /Пресеты/ }).click()
    await page.getByRole('button', { name: /Улучшить качество/ }).click()
    await page.getByRole('heading', { name: 'Редактирование' }).waitFor()

    await page.getByRole('button', { name: /Настройки/ }).click()
    await page.getByText('Rate limit').waitFor()
    await page.getByRole('button', { name: /К генерации/ }).click()
    await page.getByRole('button', { name: /Админ/ }).click()
    await page.getByText('availableModels').waitFor()

    await page.getByRole('button', { name: /К генерации/ }).click()
    await page.locator('label').filter({ hasText: 'Провайдер' }).locator('select').selectOption('openrouter')
    await page.getByText(/OpenRouter не поддерживает/).waitFor()

    console.log('Missing stages e2e passed: canvas modes, face swap, presets, settings, admin, provider limits.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



