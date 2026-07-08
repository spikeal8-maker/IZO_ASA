import { chromium } from 'playwright'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 430, height: 932 }, isMobile: true, hasTouch: true })
    page.setDefaultTimeout(20000)

    await page.goto(`${base}/feed?main_routing=${Date.now()}`, { waitUntil: 'networkidle' })
    await page.locator('.feedbar').waitFor()
    assert(await page.locator('.feedbar').count() > 0, '/feed did not render the backend static feed shell')
    assert(await page.locator('.mode-tile').count() > 0, '/feed did not render static feed mode tiles')
    assert(await page.locator('.nf-page, .iv3-feed').count() === 0, '/feed rendered the retired React feed surface')

    await page.goto(`${base}/lenta?main_routing=${Date.now()}`, { waitUntil: 'domcontentloaded' })
    const lentaBody = await page.locator('body').first().textContent()
    assert(/Страница не найдена/i.test(lentaBody || ''), '/lenta should not be a current feed route')
    assert(await page.locator('.nf-page, .iv3-feed').count() === 0, '/lenta rendered the retired React feed surface')

    await page.goto(`${base}/gallery?main_routing=${Date.now()}`, { waitUntil: 'networkidle' })
    await page.locator('.iv3').waitFor()
    assert(await page.locator('.n2-gallery, .compactBar, .page').count() > 0, '/gallery did not render a new gallery surface')
    const galleryTitle = await page.locator('body').first().textContent()
    assert(/Галерея|Gallery|Моя галерея|My gallery/i.test(galleryTitle || ''), `/gallery rendered wrong title: ${galleryTitle}`)

    console.log('Main routing e2e passed.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
