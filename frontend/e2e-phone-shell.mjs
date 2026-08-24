import { chromium } from 'playwright'


const origin = (process.env.IZO_E2E_BASE_URL || 'http://127.0.0.1:4178').replace(/\/$/, '')
const workspaces = [
  ['image', 'Картинка', 'Фото', true, 'ready', 'primary'],
  ['video', 'Видео', 'Видео', true, 'ready', 'primary'],
  ['chat', 'Чат', 'Чат', true, 'ready', 'primary'],
  ['audio', 'Звук', 'Звук', false, 'partial', 'primary'],
  ['3d', '3D-модель', '3D', false, 'planned', 'menu'],
].map(([id, label, shortLabel, enabled, stage, navigation]) => ({
  id, label, shortLabel, route: `/phone/${id}`, enabled, stage, navigation, operations: [],
}))
const platform = {
  ok: true,
  apiVersion: 'v1',
  defaultRoute: '/phone/image',
  shell: { nativeReact: true, resumeJobs: true, offlineDrafts: true, notificationHost: true },
  contracts: { capabilities: 'v1', jobs: 'v1', media: 'v1', billing: 'v1' },
  workspaces,
}
const me = {
  profile: { display_name: 'Тестовый пользователь' },
  account: { token_balance: 1259, daily_tokens_limit: 100, daily_tokens_remaining: 93 },
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const browser = await chromium.launch({ headless: true })
try {
  for (const viewport of [{ width: 390, height: 844 }, { width: 430, height: 932 }]) {
    const context = await browser.newContext({ viewport, isMobile: true, hasTouch: true })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.route('**/api/phone/v1/platform', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(platform) }))
    await page.route('**/api/phone/v1/jobs?active=true', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, items: [] }) }))
    await page.route('**/api/me-v2', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(me) }))
    const thread = { id: '0123456789abcdef', title: 'Новый чат', chatModelId: 'local:izo-chat', imageModelId: null, videoModelId: null, contextChars: 60000, createdAt: '2026-08-24T00:00:00Z', updatedAt: '2026-08-24T00:00:00Z' }
    await page.route('**/api/phone/chat/threads', async (route) => route.request().method() === 'POST'
      ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, thread }) })
      : route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, threads: [] }) }))
    await page.route('**/api/phone/chat/models', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, defaultModel: 'local:izo-chat', models: [{ id: 'local:izo-chat', name: 'ИЗО Чат', provider: 'local', tokenCost: 1, tokenKind: 'daily', description: 'Быстрые ответы на этом сервере', contextChars: 60000 }] }) }))
    await page.route('**/api/phone/chat', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, reply: 'Готово — это проверенный ответ.', modelId: 'local:izo-chat', chargedTokens: 1, tokenKind: 'daily', tools: [] }) }))

    await page.goto(`${origin}/phone`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('heading', { name: 'Картинка', exact: true }).waitFor()
    assert(new URL(page.url()).pathname === '/phone/image', `${viewport.width}: root did not redirect to image`)
    assert(await page.locator('iframe').count() === 0, `${viewport.width}: native shell still uses iframe`)
    const layout = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, app: document.querySelector('.phone-app')?.getBoundingClientRect().width }))
    assert(layout.document === layout.viewport && layout.app === layout.viewport, `${viewport.width}: shell overflows ${JSON.stringify(layout)}`)
    const balance = await page.getByRole('button', { name: 'Открыть профиль и баланс' }).innerText()
    assert(balance.includes('93') && balance.includes('1259'), `${viewport.width}: balance is wrong: ${balance}`)

    await page.getByRole('button', { name: 'Видео', exact: true }).click()
    await page.getByRole('heading', { name: 'Видео', exact: true }).waitFor()
    assert(new URL(page.url()).pathname === '/phone/video', `${viewport.width}: video route did not change`)

    await page.getByRole('button', { name: 'Меню', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Разделы ИЗО АСА' })
    await dialog.waitFor()
    assert(await dialog.getByRole('button').count() === 6, `${viewport.width}: menu actions are incomplete`)
    assert(await dialog.getByRole('button', { name: /Звук/ }).isDisabled(), `${viewport.width}: partial audio is not disabled`)
    assert(await dialog.getByRole('button', { name: /3D-модель/ }).isDisabled(), `${viewport.width}: planned 3D is not disabled`)
    const sheet = await page.locator('.phone-menu-sheet').boundingBox()
    assert(sheet, `${viewport.width}: menu sheet has no box`)
    await page.mouse.move(sheet.x + sheet.width / 2, sheet.y + 8)
    await page.mouse.down()
    await page.mouse.move(sheet.x + sheet.width / 2, sheet.y + 150, { steps: 5 })
    await page.mouse.up()
    await dialog.waitFor({ state: 'hidden' })

    await page.goto(`${origin}/phone/chat`, { waitUntil: 'domcontentloaded' })
    await page.getByText('С чего начнём?').waitFor()
    await page.getByPlaceholder('Сообщение…').fill('Проверка мобильного чата')
    await page.getByRole('button', { name: 'Отправить' }).click()
    await page.getByText('Готово — это проверенный ответ.').waitFor()
    assert((await page.locator('.phone-chat-message.user').count()) === 1, `${viewport.width}: user message missing`)
    assert((await page.locator('.phone-chat-message.assistant').count()) === 1, `${viewport.width}: assistant message missing`)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.getByText('С чего начнём?').waitFor()
    assert(new URL(page.url()).pathname === '/phone/chat', `${viewport.width}: direct route did not survive refresh`)
    assert(errors.length === 0, `${viewport.width}: page errors: ${errors.join('; ')}`)
    await context.close()
  }

  console.log('PHONE_SHELL_E2E_OK routes=5 viewports=390x844,430x932 iframe=false')
} finally {
  await browser.close()
}
