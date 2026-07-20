import { chromium } from 'playwright'

const base = 'http://127.0.0.1:5173'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function openPlatform(page, platform, viewport = { width: 1440, height: 900 }) {
  await page.setViewportSize(viewport)
  await page.goto(`${base}?platform=${platform}&userId=stage1_${platform}_${Date.now()}`, { waitUntil: 'networkidle' })
  await page.locator('.app-shell').waitFor()
  await page.locator('.studio-grid').waitFor()
  await page.getByRole('button', { name: 'Текст стрелка вправо Изо' }).waitFor()
}

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    page.setDefaultTimeout(20000)
    await page.goto(`${base}?platform=web&userId=stage1_probe_${Date.now()}`, { waitUntil: 'networkidle' })

    const platforms = await page.evaluate(async () => fetch('/api/platforms').then((response) => response.json()))
    assert(platforms.web.ready, 'Web platform is not ready')
    assert(platforms.telegram.ready, 'Telegram platform is not ready')
    assert(platforms.max.ready, 'MAX platform is not ready')
    assert(!platforms.database, 'Database block must not be exposed on the public platforms payload')
    assert(platforms.telegram.commands.join(',') === '/start,/app,/help,/gallery,/settings', 'Telegram commands are incomplete')
    assert(platforms.max.commands.join(',') === '/start,/app,/help,/gallery,/settings', 'MAX commands are incomplete')

    for (const platform of ['telegram', 'max']) {
      const command = await page.evaluate(async ({ platform }) => fetch('/api/bots/local-command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, text: '/app', chatId: 'stage1' }),
      }).then((response) => response.json()), { platform })
      assert(command.ok, `${platform} local command failed`)
      assert(command.buttons?.[0]?.text === 'Открыть генератор', `${platform} open button is missing`)
      assert(command.buttons?.[0]?.url?.includes(`platform=${platform}`), `${platform} button does not open platform mini app URL`)
    }

    const fingerprints = []
    for (const platform of ['web', 'telegram', 'max']) {
      await openPlatform(page, platform)
      const bootstrap = await page.evaluate(async (platform) => fetch('/api/app/bootstrap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, language: 'ru', userId: `stage1_${platform}`, username: `${platform}_user`, firstName: platform }),
      }).then((response) => response.json()), platform)
      assert(bootstrap.ok, `${platform} bootstrap failed`)
      assert(bootstrap.platform === platform, `${platform} bootstrap returned wrong platform`)
      assert(bootstrap.features.web && bootstrap.features.telegramMiniApp && bootstrap.features.maxMiniApp, `${platform} feature flags incomplete`)
      assert(bootstrap.features.database, `${platform} database feature is false`)

      const fingerprint = await page.evaluate(() => ({
        modes: Array.from(document.querySelectorAll('.mode')).map((node) => node.textContent?.trim()).join('|'),
        hasPrompt: Boolean(document.querySelector('.prompt-dock textarea')),
        hasPreview: Boolean(document.querySelector('.preview-panel')),
        hasGenerate: Boolean(document.querySelector('.generate')),
      }))
      assert(fingerprint.hasPrompt && fingerprint.hasPreview && fingerprint.hasGenerate, `${platform} main screen is incomplete`)
      fingerprints.push(fingerprint)
    }
    assert(new Set(fingerprints.map((item) => JSON.stringify(item))).size === 1, 'Web/Telegram/MAX do not render the same interface')

    await page.getByRole('button', { name: /RU/ }).first().click()
    await page.getByRole('button', { name: 'Text arrow right Image' }).waitFor()
    await page.getByRole('button', { name: /EN/ }).first().click()
    await page.getByRole('button', { name: 'Текст стрелка вправо Изо' }).waitFor()

    await openPlatform(page, 'telegram', { width: 390, height: 844 })
    await page.locator('.bottom-nav').waitFor()
    const mobileNav = await page.evaluate(() => ({
      topbarHidden: getComputedStyle(document.querySelector('.topbar')).display === 'none',
      bottomNavVisible: getComputedStyle(document.querySelector('.bottom-nav')).display !== 'none',
      langVisible: getComputedStyle(document.querySelector('.mobile-lang-toggle')).display !== 'none',
      duplicateTopActions: Array.from(document.querySelectorAll('.top-actions button')).filter((button) => button instanceof HTMLElement && button.offsetParent !== null).length,
    }))
    assert(mobileNav.topbarHidden, 'Mobile topbar must be hidden')
    assert(mobileNav.bottomNavVisible, 'Mobile bottom nav must be visible')
    assert(mobileNav.langVisible, 'Mobile RU/EN switch is missing')
    assert(mobileNav.duplicateTopActions === 0, 'Mobile top actions are duplicated')
    await page.getByRole('button', { name: /^RU$/ }).click()
    await page.getByRole('button', { name: 'Text arrow right Image' }).waitFor()

    await page.screenshot({ path: 'stage1-acceptance.png', fullPage: true })
    console.log('Stage 1 acceptance passed: Web, Telegram, MAX, RU/EN, backend, database.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



