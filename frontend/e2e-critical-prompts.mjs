import { chromium } from 'playwright'

const URL = process.env.APP_URL || 'http://127.0.0.1:5173'
const badEnglish = /\b(Transform|Replace|Seamlessly|Generated image|Expand prompt|Discover|A beautiful|high-fashion|young woman|cyberpunk girl)\b/i

const checks = []

function record(name, ok, details = '') {
  checks.push({ name, ok, details })
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${details ? ` — ${details}` : ''}`)
}

async function openApp(viewport) {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport })
  await page.goto(URL, { waitUntil: 'networkidle' })
  await page.locator('textarea[aria-label]').first().waitFor({ timeout: 15000 })
  return { browser, page }
}

async function clickMode(page, label) {
  await page.locator('.image-mode-tabs button').filter({ hasText: label }).first().click()
  await page.waitForTimeout(150)
}

async function openTemplates(page) {
  const existing = await page.locator('.discover-panel').count()
  if (existing) await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Шаблоны' }).first().click()
  await page.locator('.discover-panel').waitFor({ timeout: 5000 })
}

async function readTemplatePrompts(page) {
  return page.locator('.discover-panel .discover-cards button small').evaluateAll((nodes) => nodes.map((node) => node.textContent?.trim() || ''))
}

async function closeTemplates(page) {
  if (await page.locator('.discover-panel').count()) await page.keyboard.press('Escape')
  await page.waitForTimeout(100)
}

async function assertTemplates(page, name, expectedCount) {
  await openTemplates(page)
  const prompts = await readTemplatePrompts(page)
  const z = await page.locator('.discover-panel').evaluate((node) => Number(getComputedStyle(node).zIndex || 0))
  const bottomZRaw = await page.locator('.bottom-nav').evaluateAll((nodes) => nodes[0] ? Number(getComputedStyle(nodes[0]).zIndex || 0) : 0)
  const bottomZ = Number.isFinite(bottomZRaw) ? bottomZRaw : 0
  const russianEnough = prompts.every((text) => (text.match(/[А-Яа-яЁё]/g)?.length || 0) >= 25 && !badEnglish.test(text))
  record(`${name}: шаблонов ${expectedCount}`, prompts.length === expectedCount, `получено ${prompts.length}`)
  record(`${name}: промты на русском`, russianEnough, prompts.find((text) => badEnglish.test(text)) || '')
  record(`${name}: окно шаблонов выше навигации`, z > bottomZ, `z=${z}, bottom=${bottomZ}`)
  await closeTemplates(page)
  return prompts
}

async function assertRandomFromCurrentSet(page, name, prompts) {
  const before = await page.locator('textarea[aria-label]').first().inputValue()
  await page.getByRole('button', { name: 'Случайный' }).first().click()
  await page.waitForTimeout(100)
  const after = await page.locator('textarea[aria-label]').first().inputValue()
  const inCurrentSet = prompts.some((shortPrompt) => after.startsWith(shortPrompt) || shortPrompt.startsWith(after.slice(0, 100)))
  record(`${name}: случайный берёт текущую вкладку`, inCurrentSet, `changed=${before !== after}`)
}

async function desktopRun() {
  const { browser, page } = await openApp({ width: 1440, height: 900 })
  try {
    await clickMode(page, 'По тексту')
    let prompts = await assertTemplates(page, 'Desktop По тексту', 20)
    await assertRandomFromCurrentSet(page, 'Desktop По тексту', prompts)

    await clickMode(page, 'По фото')
    prompts = await assertTemplates(page, 'Desktop По фото', 20)
    await assertRandomFromCurrentSet(page, 'Desktop По фото', prompts)

    await clickMode(page, 'Редактор')
    prompts = await assertTemplates(page, 'Desktop Редактор', 20)
    await assertRandomFromCurrentSet(page, 'Desktop Редактор', prompts)

    await clickMode(page, 'Редактор')
    prompts = await assertTemplates(page, 'Desktop Редактор / Эскиз', 20)
    await assertRandomFromCurrentSet(page, 'Desktop Редактор / Эскиз', prompts)

    await page.getByRole('button', { name: /Маска \/ Расширение/i }).first().click()
    await page.waitForTimeout(150)
    if (await page.locator('.mask-editor').count()) await page.locator('.mask-top button').filter({ hasText: 'Отмена' }).first().click({ force: true })
    prompts = await assertTemplates(page, 'Desktop Редактор / Маска', 20)
    await assertRandomFromCurrentSet(page, 'Desktop Редактор / Маска', prompts)

    await page.getByRole('button', { name: /Маска \/ Расширение/i }).first().click()
    await page.locator('.mask-editor').waitFor({ timeout: 5000 })
    await page.locator('.mask-top button').filter({ hasText: 'Расширить изображение' }).first().click({ force: true })
    await page.locator('.mask-top button').filter({ hasText: 'Отмена' }).first().click({ force: true })
    prompts = await assertTemplates(page, 'Desktop Редактор / Расширение', 20)
    await assertRandomFromCurrentSet(page, 'Desktop Редактор / Расширение', prompts)

  } finally {
    await browser.close()
  }
}

async function mobileRun() {
  const { browser, page } = await openApp({ width: 390, height: 844 })
  try {
    for (const [label, count] of [['По тексту', 20], ['По фото', 20], ['Редактор', 20], ['Редактор', 20]]) {
      await clickMode(page, label)
      const prompts = await assertTemplates(page, `Mobile ${label}`, count)
      await assertRandomFromCurrentSet(page, `Mobile ${label}`, prompts)
    }
  } finally {
    await browser.close()
  }
}

await desktopRun()
await mobileRun()

const failed = checks.filter((item) => !item.ok)
if (failed.length) {
  console.error(`\nFAILED ${failed.length}/${checks.length}`)
  process.exit(1)
}
console.log(`\nOK ${checks.length}/${checks.length}`)
