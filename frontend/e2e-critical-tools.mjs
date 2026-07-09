import { chromium } from 'playwright'
import { resolve } from 'node:path'

const URL = process.env.APP_URL || 'http://127.0.0.1:5173'
const fixture = resolve('stage4-input.png')
const checks = []

function record(name, ok, details = '') {
  checks.push({ name, ok, details })
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${details ? ` — ${details}` : ''}`)
}

async function openApp(viewport, suffix) {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport })
  page.setDefaultTimeout(30000)
  await page.goto(`${URL}?platform=web&userId=critical_tools_${suffix}_${Date.now()}`, { waitUntil: 'networkidle' })
  await page.locator('textarea[aria-label]').first().waitFor()
  return { browser, page }
}

async function clickMode(page, label) {
  await page.locator('.mode').filter({ hasText: label }).first().click()
  await page.waitForTimeout(200)
}

async function uploadByButton(page, locator, label) {
  const chooser = page.waitForEvent('filechooser')
  await locator.click()
  const fileChooser = await chooser
  await fileChooser.setFiles(fixture)
  await page.waitForTimeout(500)
  record(label, (await page.locator('img').count()) > 0)
}

async function drawOnCanvas(page, canvasSelector, label) {
  const canvas = page.locator(canvasSelector).first()
  await canvas.waitFor({ timeout: 10000 })
  const box = await canvas.boundingBox()
  if (!box) throw new Error(`Canvas not visible: ${label}`)
  await page.mouse.move(box.x + box.width * 0.25, box.y + box.height * 0.25)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.36, { steps: 8 })
  await page.mouse.move(box.x + box.width * 0.58, box.y + box.height * 0.52, { steps: 8 })
  await page.mouse.up()
  record(label, true, `${Math.round(box.width)}x${Math.round(box.height)}`)
}

async function runViewport(name, viewport) {
  const { browser, page } = await openApp(viewport, name)
  try {
    await clickMode(page, 'По фото')
    await uploadByButton(page, page.getByRole('button', { name: /Загрузить изображение|Добавить изображение|Файл/ }).first(), `${name}: Изо→Изо загрузка файла`)
    record(`${name}: Изо→Изо изображение попало в предпросмотр`, (await page.locator('.preview-panel img, .mobile-thumb img').count()) > 0)

    await clickMode(page, 'Редактор')
    await uploadByButton(page, page.getByRole('button', { name: /Загрузить изображение|Добавить изображение|Файл/ }).first(), `${name}: Редактор основное изображение`)
    record(`${name}: Редактор prompt подставлен`, (await page.locator('textarea[aria-label]').first().inputValue()).length > 30)

    await page.goto(`${URL}?platform=web&userId=critical_tools_${name}_face_${Date.now()}`, { waitUntil: 'networkidle' })
    await page.locator('textarea[aria-label]').first().waitFor()
    await clickMode(page, 'Лицо')
    let faceFileButtons = page.getByRole('button', { name: /^Файл$/ })
    if ((await faceFileButtons.count()) >= 2) {
      await uploadByButton(page, faceFileButtons.first(), `${name}: Лицо→Изо target`)
      faceFileButtons = page.getByRole('button', { name: /^Файл$/ })
      await uploadByButton(page, faceFileButtons.first(), `${name}: Лицо→Изо source`)
    } else {
      let uploadButtons = page.getByRole('button', { name: /^Загрузить изображение$/ })
      await uploadByButton(page, uploadButtons.first(), `${name}: Лицо→Изо target`)
      uploadButtons = page.getByRole('button', { name: /^Загрузить изображение$/ })
      await uploadByButton(page, uploadButtons.first(), `${name}: Лицо→Изо source`)
    }
    record(`${name}: Лицо→Изо prompt подставлен`, (await page.locator('textarea[aria-label]').first().inputValue()).includes('лицо') || (await page.locator('textarea[aria-label]').first().inputValue()).includes('Замени'))

    await page.goto(`${URL}?platform=web&userId=critical_tools_${name}_paint_${Date.now()}`, { waitUntil: 'networkidle' })
    await page.locator('textarea[aria-label]').first().waitFor()
    await clickMode(page, 'Редактор')
    await page.locator('.paint-choice:visible, .mobile-paint-actions button:visible').filter({ hasText: 'Эскиз' }).first().click()
    await page.locator('.sketch-editor').waitFor()
    await drawOnCanvas(page, '.sketch-editor canvas', `${name}: Эскиз canvas рисует`)
    await page.getByRole('button', { name: /Сохранить/ }).first().click()
    await page.locator('.paint-editor').waitFor({ state: 'detached' })
    record(`${name}: Эскиз сохранился в изображение`, (await page.locator('.preview-panel img, .mobile-thumb img').count()) > 0)

    await page.locator('.paint-choice:visible, .mobile-paint-actions button:visible').filter({ hasText: /Маска|Расширение/ }).first().click()
    await page.locator('.mask-editor').waitFor()
    if (!(await page.locator('.mask-image-layer').count())) {
      await uploadByButton(page, page.locator('.mask-top button').filter({ hasText: 'Загрузить' }).first(), `${name}: Маска загрузка изображения`)
    }
    await drawOnCanvas(page, '.mask-editor canvas', `${name}: Маска canvas рисует`)
    await page.locator('.mask-top button').filter({ hasText: 'Расширить изображение' }).first().click({ force: true })
    await page.locator('.outpaint-inline').waitFor()
    record(`${name}: Расширение показывает настройки сторон`, true)
    await page.locator('.mask-top button').filter({ hasText: /Применить/ }).first().click({ force: true })
    await page.locator('.paint-editor').waitFor({ state: 'detached' })
    record(`${name}: Маска/расширение применились`, true)
  } finally {
    await browser.close()
  }
}

await runViewport('desktop', { width: 1440, height: 900 })
await runViewport('mobile', { width: 390, height: 844 })

const failed = checks.filter((item) => !item.ok)
if (failed.length) {
  console.error(`\nFAILED ${failed.length}/${checks.length}`)
  process.exit(1)
}
console.log(`\nOK ${checks.length}/${checks.length}`)
