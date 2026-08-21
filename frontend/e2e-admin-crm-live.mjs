import { chromium } from 'playwright'
import fs from 'node:fs/promises'

const baseURL = process.env.QA_ADMIN_BASE_URL || 'http://127.0.0.1:5174'
const token = process.env.QA_ADMIN_SESSION_TOKEN || ''
const userCode = process.env.QA_CRM_USER_CODE || ''
if (!token || !userCode) throw new Error('QA admin session and CRM user code are required')

const outDir = process.env.QA_ARTIFACT_DIR || '.qa-admin-crm-artifacts'
await fs.mkdir(outDir, { recursive: true })
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1536, height: 960 } })
await context.addCookies([{ name: 'onenode_session', value: token, url: baseURL, httpOnly: true, sameSite: 'Lax' }])
const page = await context.newPage()
const consoleErrors = []
const failedResponses = []
page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()) })
page.on('response', (response) => { if (response.status() >= 400) failedResponses.push({ status: response.status(), url: response.url() }) })

try {
  await page.goto(`${baseURL}/admin`, { waitUntil: 'networkidle' })
  await page.getByText('Генерации сегодня', { exact: true }).waitFor()
  await page.getByText('Изображения / видео', { exact: true }).waitFor()
  await page.getByText('Токены сегодня', { exact: true }).waitFor()
  await page.screenshot({ path: `${outDir}/dashboard.png`, fullPage: true })

  await page.getByRole('button', { name: 'CRM' }).click()
  await page.getByPlaceholder('Код, имя, email, телефон или username').fill(userCode)
  await page.getByRole('button', { name: 'Найти', exact: true }).click()
  await page.getByText(userCode, { exact: true }).first().waitFor()
  const row = page.getByText(userCode, { exact: true }).first().locator('xpath=ancestor::div[contains(@class,"crm-row")]')
  await row.click()
  await page.getByRole('dialog', { name: 'Карточка пользователя' }).waitFor()
  await page.getByText('Основной баланс', { exact: true }).first().waitFor()
  await page.getByText('Последняя генерация', { exact: false }).first().waitFor()
  await page.getByRole('button', { name: 'Медиа', exact: true }).first().click()
  const mediaPanel = page.getByText('Изображения и видео', { exact: true }).locator('..')
  await mediaPanel.locator('video').first().waitFor()
  await mediaPanel.locator('video').first().click()
  const videoDialog = page.getByRole('dialog', { name: 'Видео пользователя' })
  await videoDialog.waitFor()
  const video = videoDialog.locator('video')
  await video.waitFor()
  await page.waitForFunction((element) => element.readyState >= 1 && !element.error, await video.elementHandle())
  await page.screenshot({ path: `${outDir}/user-video.png`, fullPage: true })
  console.log(JSON.stringify({ ok: true, userCode, consoleErrors, failedResponses }))
} catch (error) {
  await page.screenshot({ path: `${outDir}/failure.png`, fullPage: true })
  throw error
} finally {
  await browser.close()
}
