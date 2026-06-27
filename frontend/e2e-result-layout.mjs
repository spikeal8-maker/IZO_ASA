import { chromium } from 'playwright'

const base = 'http://127.0.0.1:5173'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function createGeneration(page, userId, width, height) {
  await page.goto(`${base}?platform=web&userId=${userId}`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /Настройки/ }).click()
  await page.locator('label').filter({ hasText: 'Width' }).locator('input').fill(String(width))
  await page.locator('label').filter({ hasText: 'Height' }).locator('input').fill(String(height))
  await page.locator('label').filter({ hasText: 'Шаги' }).locator('input').fill('1')
  await page.getByRole('button', { name: /К генерации/ }).click()
  await page.locator('.studio-grid').waitFor()
  await page.locator('textarea').fill(`result fit ${width}x${height} ${Date.now()}`)
  await page.getByRole('button', { name: /Сгенерировать/ }).click()
  await page.locator('.job-card.completed img').waitFor({ timeout: 300000 })
}

async function assertResultFits(page, label) {
  const report = await page.evaluate(() => {
    const preview = document.querySelector('.preview-panel')?.getBoundingClientRect()
    const image = document.querySelector('.job-card.completed img')?.getBoundingClientRect()
    const actions = Array.from(document.querySelectorAll('.job-card.completed .result-actions .secondary'))
    const noticeVisible = Array.from(document.querySelectorAll('.notice')).some((node) => node instanceof HTMLElement && node.offsetParent !== null)
    return {
      preview,
      image,
      actionCount: actions.length,
      actionText: actions.map((node) => node.textContent?.trim()),
      noticeVisible,
    }
  })
  assert(report.preview && report.image, `${label}: missing preview or generated image`)
  assert(report.image.left >= report.preview.left - 1, `${label}: image overflows left`)
  assert(report.image.right <= report.preview.right + 1, `${label}: image overflows right`)
  assert(report.image.top >= report.preview.top - 1, `${label}: image overflows top`)
  assert(report.image.bottom <= report.preview.bottom + 1, `${label}: image overflows bottom`)
  assert(report.actionCount === 2, `${label}: expected 2 result buttons, got ${report.actionCount} (${report.actionText.join(', ')})`)
  assert(!report.actionText.some((text) => /MAX/i.test(text || '')), `${label}: MAX send button must not be visible`)
  assert(!report.noticeVisible, `${label}: send notice must not be visible`)
}

async function run() {
  const browser = await chromium.launch()
  try {
    const desktop = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    desktop.setDefaultTimeout(20000)
    await createGeneration(desktop, `result_desktop_${Date.now()}`, 512, 768)
    await assertResultFits(desktop, 'desktop')
    await desktop.screenshot({ path: 'result-fit-desktop.png', fullPage: true })

    const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
    phone.setDefaultTimeout(20000)
    await createGeneration(phone, `result_phone_${Date.now()}`, 512, 768)
    await assertResultFits(phone, 'phone')
    const promptHeader = await phone.evaluate(() => {
      const label = document.querySelector('.prompt-label-text')?.getBoundingClientRect()
      const presets = document.querySelector('.discover-button')?.getBoundingClientRect()
      const random = document.querySelector('.prompt-actions .expand-button')?.getBoundingClientRect()
      return { label, presets, random }
    })
    assert(promptHeader.label && promptHeader.presets && promptHeader.random, 'phone: prompt header controls are missing')
    assert(promptHeader.label.right + 4 < promptHeader.presets.left, 'phone: prompt label and presets are glued')
    assert(promptHeader.presets.right + 4 < promptHeader.random.left, 'phone: presets and random prompt are glued')
    await phone.screenshot({ path: 'result-fit-phone.png', fullPage: true })

    console.log('Result layout e2e passed: generated image fits desktop and phone preview.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



