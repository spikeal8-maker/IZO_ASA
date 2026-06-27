import { chromium } from 'playwright'
import { writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const userId = `stage4_${Date.now()}`
const base = `http://127.0.0.1:5173?platform=web&userId=${userId}`
const inputPath = resolve('stage4-input.png')
writeFileSync(inputPath, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAWUlEQVR4nO3PQQ0AIBDAMMC/5+ONAvZoFSzZnZm5L1sAVwUqQAWoABWgAlSACpABKkAFqAAVoAJUgApQASpABagAFaACVIAKUAEqQAWoABWgAlSACagD+gFHdALGTdYZ+QAAAABJRU5ErkJggg==', 'base64'))

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function draw(page) {
  const canvas = page.locator('.konva-stage canvas').first()
  await canvas.waitFor()
  const before = await canvas.evaluate((node) => node.toDataURL())
  const box = await canvas.boundingBox()
  assert(box, 'Canvas box is missing')
  await page.mouse.move(box.x + 90, box.y + 90)
  await page.mouse.down()
  await page.mouse.move(box.x + 240, box.y + 180)
  await page.mouse.move(box.x + 420, box.y + 120)
  await page.mouse.up()
  const after = await canvas.evaluate((node) => node.toDataURL())
  assert(before !== after, 'Canvas did not change after drawing')
}

async function uploadImage(page) {
  const chooserPromise = page.waitForEvent('filechooser')
  await page.locator('.mask-editor').getByRole('button', { name: /Загрузить|Upload image/ }).click()
  const chooser = await chooserPromise
  await chooser.setFiles(inputPath)
  await page.waitForTimeout(500)
}

async function generate(page, prompt, mode) {
  const previous = await page.locator('.preview-panel img').first().getAttribute('src').catch(() => '')
  await page.locator('.prompt-dock textarea').fill(prompt)
  await page.getByRole('button', { name: /Сгенерировать/ }).click()
  await page.waitForFunction((oldSrc) => {
    const img = document.querySelector('.preview-panel img')
    return img && img.getAttribute('src') !== oldSrc
  }, previous, { timeout: 300000 })
  const records = await page.evaluate(async () => fetch('/api/gallery', {
    headers: { 'X-OneNode-User': localStorage.getItem('onenode_user') || 'demo_user' },
  }).then((response) => response.json()))
  assert(records.some((item) => item.promptOriginal === prompt && item.mode === mode), `${mode} result was not saved to gallery`)
}

async function configureFast(page) {
  await page.getByRole('button', { name: /Настройки/ }).click()
  await page.locator('label').filter({ hasText: 'Width' }).locator('input').fill('512')
  await page.locator('label').filter({ hasText: 'Height' }).locator('input').fill('512')
  await page.locator('label').filter({ hasText: 'Шаги' }).locator('input').fill('1')
  await page.getByRole('button', { name: /К генерации/ }).click()
  await page.locator('.studio-grid').waitFor()
}

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    page.setDefaultTimeout(25000)
    await page.goto(base, { waitUntil: 'networkidle' })
    await configureFast(page)
    await page.getByRole('button', { name: 'Рисование Изо' }).click()
    await page.locator('.paint-compact').waitFor()
    await page.getByRole('button', { name: /Эскиз|Sketch/ }).waitFor()
    await page.getByRole('button', { name: /Маска \/ Расширение|Inpaint \/ Outpaint/ }).waitFor()

    await page.getByRole('button', { name: /Эскиз|Sketch/ }).click()
    await page.locator('.sketch-editor').waitFor()
    await draw(page)
    await page.getByRole('button', { name: /Сохранить|Save sketch/ }).click()
    await page.locator('.paint-editor').waitFor({ state: 'detached' })
    await generate(page, `stage4 sketch ${Date.now()}`, 'paint')

    await page.getByRole('button', { name: 'Рисование Изо' }).click()
    await page.getByRole('button', { name: /Маска \/ Расширение|Inpaint \/ Outpaint/ }).click()
    await page.locator('.mask-editor').waitFor()
    await uploadImage(page)
    await draw(page)
    await page.getByRole('button', { name: /^Применить$|^Apply$/ }).click()
    await page.locator('.paint-editor').waitFor({ state: 'detached' })
    await generate(page, `stage4 inpaint ${Date.now()}`, 'inpaint')

    await page.getByRole('button', { name: 'Рисование Изо' }).click()
    await page.getByRole('button', { name: /Маска \/ Расширение|Inpaint \/ Outpaint/ }).click()
    await page.locator('.mask-editor').waitFor()
    await page.getByRole('button', { name: 'Расширить изображение', exact: true }).click()
    await page.locator('.outpaint-inline').waitFor()
    await page.getByRole('button', { name: /^Применить$|^Apply$/ }).click()
    await page.locator('.paint-editor').waitFor({ state: 'detached' })
    await generate(page, `stage4 outpaint ${Date.now()}`, 'outpaint')

    await page.screenshot({ path: 'stage4-acceptance.png', fullPage: true })
    console.log('Stage 4 acceptance passed: Paint, Inpaint, Outpaint editors and generation.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



