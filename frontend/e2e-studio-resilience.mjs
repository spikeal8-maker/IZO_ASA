import { chromium } from 'playwright'

const baseUrl = process.env.IZO_E2E_BASE_URL || 'http://127.0.0.1:5173/#text-to-image'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const browser = await chromium.launch({ headless: true })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await context.addInitScript((draft) => {
    window.sessionStorage.setItem('izo:studio-draft-v1', JSON.stringify(draft))
  }, {
    prompts: { text: 'Черновик должен сохраниться', i2i: '', edit: '', paint: '' },
    styleId: '',
    resolutionId: 'h-1280',
    quality: 'standard',
    seed: 424242,
    strengthPct: 63,
    editSlots: Array.from({ length: 4 }, () => ({ role: '', takeNote: '' })),
    editFaceStrengthPct: 75,
  })
  const page = await context.newPage()
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  const textarea = page.locator('.prompt-section textarea')
  await textarea.waitFor({ state: 'visible' })
  assert(await textarea.inputValue() === 'Черновик должен сохраниться', 'prompt draft was not restored')

  const activeQuality = page.locator('.quality-button.active')
  assert(await activeQuality.count() === 1, 'exactly one quality button must be active')
  assert((await activeQuality.locator('.quality-label').textContent())?.includes('Стандарт'), 'standard quality was not restored')
  const activeModel = activeQuality.locator('.quality-model-name')
  const beforeHover = await activeModel.evaluate((node) => getComputedStyle(node).color)
  assert(!beforeHover.includes('rgba(0, 0, 0, 0)'), `active model label is transparent: ${beforeHover}`)
  await activeQuality.hover()
  const afterHover = await activeModel.evaluate((node) => getComputedStyle(node).color)
  assert(!afterHover.includes('rgba(0, 0, 0, 0)'), `hovered model label is transparent: ${afterHover}`)

  const selectedFormat = page.locator('.iv3-format-option.active')
  if (await selectedFormat.count() === 1) {
    assert((await selectedFormat.textContent())?.includes('1280×720'), 'wide format was not restored')
  }
  console.log(JSON.stringify({ ok: true, beforeHover, afterHover, baseUrl }))
} finally {
  await browser.close()
}
