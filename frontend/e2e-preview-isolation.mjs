import { chromium } from 'playwright'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'
const tinyPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAZElEQVR4nO3PQQ0AIBDAMMC/5+ONAvZoFSzZnZk9zL0F8G4DWAawDGAZwDKAZQDLABYBrANYBrAMYBnAMoBlAMsAlgEsA1gGsAxgGcAygGUAywCWAawDWAawDGAZwDKAZQDLABYBrANYBvAMO4QAQKdOLooAAAAASUVORK5CYII=',
  'base64',
)

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function selectMode(page, label) {
  await page.locator('.mode-tabs .tab').filter({ hasText: label }).first().click()
}

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 430, height: 932 }, isMobile: true, hasTouch: true })
    page.setDefaultTimeout(20000)
    await page.goto(`${base}/new?preview_isolation=${Date.now()}`, { waitUntil: 'networkidle' })
    await page.locator('.preview-panel').waitFor()

    await selectMode(page, 'По фото')
    await page.getByRole('button', { name: /^Загрузить$/ }).first().click()
    await page.locator('input[type="file"]').setInputFiles({ name: 'source.png', mimeType: 'image/png', buffer: tinyPng })
    await page.locator('.iv3-inspect-image').waitFor()
    const i2iSrc = await page.locator('.iv3-inspect-image').first().getAttribute('src')
    assert(i2iSrc?.startsWith('data:image/'), `i2i source preview did not render uploaded data image: ${i2iSrc}`)

    await selectMode(page, 'По тексту')
    await page.waitForTimeout(100)
    const textInspectCount = await page.locator('.iv3-inspect-image').count()
    assert(textInspectCount === 0, 'text tab inherited i2i inspect preview')

    await selectMode(page, 'По фото')
    await page.locator('.iv3-inspect-image').waitFor()
    const restoredSrc = await page.locator('.iv3-inspect-image').first().getAttribute('src')
    assert(restoredSrc === i2iSrc, 'i2i preview was not restored after tab switch')

    const stageBox = await page.locator('.iv3-inspect-stage').first().boundingBox()
    assert(Boolean(stageBox), 'inspect stage has no bounding box')
    const tap = (x, y) => ({ identifier: 1, clientX: x, clientY: y })
    const x = stageBox.x + stageBox.width / 2
    const y = stageBox.y + stageBox.height / 2
    for (let i = 0; i < 2; i += 1) {
      await page.locator('.iv3-inspect-stage').first().dispatchEvent('touchstart', {
        touches: [tap(x, y)],
        targetTouches: [tap(x, y)],
        changedTouches: [tap(x, y)],
      })
      await page.locator('.iv3-inspect-stage').first().dispatchEvent('touchend', {
        touches: [],
        targetTouches: [],
        changedTouches: [tap(x, y)],
      })
      await page.waitForTimeout(70)
    }
    await page.waitForTimeout(120)
    const zoomedTransform = await page.locator('.iv3-inspect-image').first().evaluate((node) => getComputedStyle(node).transform)
    assert(zoomedTransform && zoomedTransform !== 'none', `double tap did not zoom preview: ${zoomedTransform}`)

    const shape = await page.locator('.preview-image').first().evaluate((node) => Array.from(node.classList).filter((x) => x.startsWith('preview-shape-')))
    assert(shape.length === 1, `mobile preview shape class missing: ${shape.join(',')}`)

    console.log('Preview isolation e2e passed.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
