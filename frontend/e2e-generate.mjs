import { chromium } from 'playwright'

const userId = `e2e_generate_${Date.now()}`
const baseUrl = `http://127.0.0.1:5173?platform=web&userId=${userId}`
const prompt = `ui acceptance teapot ${Date.now()}`

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
    page.setDefaultTimeout(20000)
    await page.goto(baseUrl, { waitUntil: 'networkidle' })

    await page.getByRole('button', { name: 'Текст стрелка вправо Изо' }).waitFor()
    await page.locator('.preview-panel').waitFor()
    await page.getByRole('button', { name: /Настройки/ }).click()
    await page.locator('label').filter({ hasText: 'Width' }).locator('input').fill('512')
    await page.locator('label').filter({ hasText: 'Height' }).locator('input').fill('512')
    await page.locator('label').filter({ hasText: 'Зерно' }).locator('input').fill('4101')
    await page.locator('label').filter({ hasText: 'Шаги' }).locator('input').fill('1')
    await page.locator('label').filter({ hasText: 'CFG' }).locator('input').fill('1.1')
    await page.getByRole('button', { name: /К генерации/ }).click()
    await page.locator('.studio-grid').waitFor()
    await page.locator('textarea').fill(prompt)

    await page.getByRole('button', { name: /Сгенерировать/ }).click()
    await page.locator('.job-card.completed img').waitFor({ timeout: 300000 })
    const resultUrl = await page.locator('.job-card.completed img').getAttribute('src')
    if (!resultUrl?.includes('/api/media/')) throw new Error(`Generation did not render media result, got ${resultUrl}`)

    const gallery = await page.evaluate(async () => fetch('/api/gallery', { headers: { 'X-OneNode-User': localStorage.getItem('onenode_user') || 'demo_user' } }).then((response) => response.json()))
    const created = gallery.find((image) => image.promptOriginal === prompt)
    if (!created) throw new Error('Generated UI image was not persisted to gallery')
    if (created.width !== 512 || created.height !== 512 || created.seed !== 4101) {
      throw new Error(`Settings mismatch: got ${created.width}x${created.height}, seed ${created.seed}`)
    }

    console.log(`E2E generation passed: ${created.id} ${created.url}`)
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



