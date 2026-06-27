import { chromium } from 'playwright'

const base = 'http://127.0.0.1:5173'

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
    page.setDefaultTimeout(20000)
    await page.goto(`${base}?platform=web&userId=preset_login_${Date.now()}`, { waitUntil: 'networkidle' })

    await page.locator('label').filter({ hasText: 'LoRA' }).locator('select').selectOption('product_photo')
    await page.getByText(/Trigger word: product photo|Trigger word.*product photo/).waitFor()

    await page.getByRole('button', { name: /Пресеты/ }).click()
    await page.getByRole('button', { name: /Try On/ }).waitFor()
    await page.getByRole('button', { name: /Texture Transfer/ }).waitFor()
    await page.getByRole('button', { name: /Text Editing/ }).click()
    await page.getByRole('heading', { name: 'Редактирование' }).waitFor()
    await page.locator('textarea').evaluate((node) => {
      if (!node.value.includes('Text Editing')) throw new Error(`Preset did not update prompt: ${node.value}`)
    })

    await page.getByRole('button', { name: /Настройки/ }).click()
    await page.locator('label').filter({ hasText: 'Код администратора' }).locator('input').fill('admin-demo')
    await page.getByRole('button', { name: /^Войти$/ }).click()
    await page.getByText(/admin: web_admin/).waitFor()

    console.log('Presets/LoRA/admin-login e2e passed.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



