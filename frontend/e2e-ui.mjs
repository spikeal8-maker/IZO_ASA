import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const baseUrl = 'http://127.0.0.1:5173?platform=web'
const cwd = fileURLToPath(new URL('.', import.meta.url))

function startDevServer() {
  const child = spawn('npm run dev -- --host 127.0.0.1', {
    cwd,
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.stdout.on('data', (chunk) => process.stdout.write(String(chunk)))
  child.stderr.on('data', (chunk) => process.stderr.write(String(chunk)))
  return child
}

async function isServerReady() {
  try {
    const response = await fetch(baseUrl)
    return response.ok
  } catch {
    return false
  }
}

async function waitForServer(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      if (await isServerReady()) return
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  }
  throw new Error('Vite dev server did not start')
}

async function run() {
  let server
  let browser
  try {
    if (await isServerReady()) {
      console.log('Using existing Vite server.')
    } else {
      server = startDevServer()
      await waitForServer()
    }
    browser = await chromium.launch()
    const page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
    page.setDefaultTimeout(15000)

    console.log('Open app')
    await page.goto(baseUrl, { waitUntil: 'networkidle' })

    console.log('Settings -> Studio')
    await page.getByRole('heading', { name: 'Текст → изображение' }).waitFor()
    await page.getByRole('button', { name: /Настройки/ }).click()
    await page.getByRole('heading', { name: 'Настройки' }).waitFor()
    await page.getByRole('button', { name: /К генерации/ }).click()
    await page.getByRole('heading', { name: 'Текст → изображение' }).waitFor()

    console.log('Mode switch returns to Studio')
    await page.getByRole('button', { name: 'Изображение → изображение' }).first().click()
    await page.getByRole('heading', { name: 'Изображение → изображение' }).waitFor()
    await page.getByText('Image 1').waitFor()

    console.log('Gallery detail and preview')
    await page.getByRole('button', { name: /Галерея/ }).click()
    const firstCard = page.locator('.image-card').first()
    await firstCard.waitFor()
    await firstCard.click()
    await page.locator('.detail img').waitFor()
    const fit = await page.locator('.detail img').evaluate((node) => getComputedStyle(node).objectFit)
    if (fit !== 'contain') throw new Error(`Detail preview must use object-fit: contain, got ${fit}`)
    console.log('Use as Image to Image')
    await page.getByRole('button', { name: /Использовать как.*Image to Image/ }).click()
    await page.getByRole('heading', { name: 'Изображение → изображение' }).waitFor()
    await page.locator('.image-box img').waitFor()

    console.log('Language switch')
    await page.getByRole('button', { name: /RU/ }).click()
    await page.getByRole('heading', { name: 'Image to Image' }).waitFor()
    await page.getByRole('button', { name: /Studio/ }).click()
    await page.getByRole('button', { name: /EN/ }).waitFor()

    console.log('E2E UI passed: navigation, settings exit, gallery preview, Use as, and RU/EN switch work.')
  } finally {
    if (browser) await browser.close()
    if (server) server.kill()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



