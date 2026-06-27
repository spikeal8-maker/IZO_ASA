import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const base = `http://127.0.0.1:5173?platform=web&userId=real25_${Date.now()}`
const outDir = resolve('real-generation-results')
mkdirSync(outDir, { recursive: true })

const transcript = []
function log(text) {
  const line = `${String(transcript.length + 1).padStart(2, '0')}. ${text}`
  transcript.push(line)
  console.log(line)
  writeFileSync(resolve(outDir, 'real-generations-transcript.txt'), `${transcript.join('\n')}\n`, 'utf8')
}

const pngA = resolve(outDir, 'input-a.png')
const pngB = resolve(outDir, 'input-b.png')
const onePxRed = 'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAWUlEQVR4nO3PQQ0AIBDAMMC/5+ONAvZoFSzZnZm5L1sAVwUqQAWoABWgAlSACpABKkAFqAAVoAJUgApQASpABagAFaACVIAKUAEqQAWoABWgAlSACpABagAF6AFJVgLGkKVLjAAAAABJRU5ErkJggg=='
const onePxBlue = 'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAWElEQVR4nO3PQQ0AIBDAMMC/5+ONAvZoFSzZzMzM7NwXwFWBClABKkAFqAAVoAJUgApQASpABagAFaACVIAKUAEqQAWoABWgAlSACpABagAFaACVIAKUAEqQAXoAQP7Asa9+klZAAAAAElFTkSuQmCC'
writeFileSync(pngA, Buffer.from(onePxRed, 'base64'))
writeFileSync(pngB, Buffer.from(onePxBlue, 'base64'))

async function uploadBox(page, index, file) {
  const box = page.locator('.image-box').nth(index)
  const button = box.getByRole('button', { name: /Загрузить изображение/ }).first()
  if (!(await button.count())) return
  const chooserPromise = page.waitForEvent('filechooser')
  await button.click()
  const chooser = await chooserPromise
  await chooser.setFiles(file)
  await page.waitForTimeout(700)
}

async function uploadFirst(page, file) {
  await uploadBox(page, 0, file)
}

async function uploadSecond(page, file) {
  await uploadBox(page, 1, file)
}

async function setPrompt(page, text) {
  await page.locator('.prompt-dock textarea').fill(text)
}

async function generateAndWait(page, label, round) {
  const previousSrc = await page.locator('.preview-panel img').first().getAttribute('src').catch(() => '')
  await page.getByRole('button', { name: /Сгенерировать/ }).click()
  log(`Круг ${round}: ${label}: генерация запущена`)
  await page.waitForFunction((oldSrc) => {
    const img = document.querySelector('.preview-panel img')
    const text = document.body.textContent || ''
    return (img && img.getAttribute('src') !== oldSrc) || text.includes('Ошибка') || text.includes('failed')
  }, previousSrc, { timeout: 900000 })
  const result = await page.evaluate(() => {
    const img = document.querySelector('.preview-panel img')
    const job = document.querySelector('.job-card')
    return { hasImage: Boolean(img), src: img?.getAttribute('src') || '', text: job?.textContent?.slice(0, 240) || '' }
  })
  if (!result.hasImage) throw new Error(`${label}: no result image. ${result.text}`)
  await page.screenshot({ path: resolve(outDir, `round-${round}-${label.replace(/[^a-z0-9а-я]+/gi, '_')}.png`), fullPage: true })
  log(`Круг ${round}: ${label}: результат получен ${result.src}`)
}

async function drawOnCanvas(page) {
  const box = await page.locator('.konva-stage canvas').first().boundingBox()
  if (!box) throw new Error('Canvas not found')
  await page.mouse.move(box.x + 80, box.y + 80)
  await page.mouse.down()
  await page.mouse.move(box.x + 220, box.y + 160)
  await page.mouse.move(box.x + 340, box.y + 80)
  await page.mouse.up()
}

async function openSketchEditor(page) {
  await page.getByRole('button', { name: /Эскиз|Sketch/ }).click()
  await page.locator('.sketch-editor').waitFor()
}

async function openMaskEditor(page, outpaint = false) {
  await page.getByRole('button', { name: /Маска \/ Расширение|Inpaint \/ Outpaint/ }).click()
  await page.locator('.mask-editor').waitFor()
  if (outpaint) {
    await page.getByRole('button', { name: 'Расширить изображение', exact: true }).click()
    await page.locator('.outpaint-inline').waitFor()
  }
}

async function uploadEditorImage(page, file) {
  const chooserPromise = page.waitForEvent('filechooser')
  await page.locator('.mask-editor').getByRole('button', { name: /Загрузить|Upload image/ }).click()
  const chooser = await chooserPromise
  await chooser.setFiles(file)
  await page.waitForTimeout(700)
}

async function run() {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.setDefaultTimeout(30000)
  try {
    await page.goto(base, { waitUntil: 'networkidle' })
    log('Открыт браузерный интерфейс для 25 реальных генераций')

    for (let round = 1; round <= 5; round++) {
      await page.getByRole('button', { name: 'Текст стрелка вправо Изо' }).click()
      await page.getByRole('button', { name: /Случайный prompt/ }).click()
      await generateAndWait(page, 'text_to_image', round)

      await page.getByRole('button', { name: 'Изо стрелка вправо Изо' }).click()
      await uploadFirst(page, pngA)
      await setPrompt(page, 'Enhance this image into a detailed cinematic object while preserving the source composition.')
      await generateAndWait(page, 'image_to_image', round)

      await page.getByRole('button', { name: 'Редактирование Изо' }).click()
      await uploadFirst(page, pngA)
      await uploadSecond(page, pngB)
      await setPrompt(page, 'Replace the material and color style of image 1 using image 2 as reference, preserving geometry and lighting.')
      await generateAndWait(page, 'edit', round)

      await page.getByRole('button', { name: 'Рисование Изо' }).click()
      const paintMode = round % 3 === 1 ? 'Эскиз' : round % 3 === 2 ? 'Маска' : 'Расширение'
      if (paintMode === 'Эскиз') {
        await openSketchEditor(page)
        await drawOnCanvas(page)
        await page.getByRole('button', { name: /Сохранить|Save sketch/ }).click()
        await page.locator('.paint-editor').waitFor({ state: 'detached' })
        await setPrompt(page, 'Transform this sketch into a realistic small futuristic sculpture on a studio table.')
      } else if (paintMode === 'Маска') {
        await openMaskEditor(page)
        await uploadEditorImage(page, pngA)
        await drawOnCanvas(page)
        await page.getByRole('button', { name: /^Применить$|^Apply$/ }).click()
        await page.locator('.paint-editor').waitFor({ state: 'detached' })
        await setPrompt(page, 'Replace the masked area with a glowing blue glass texture, seamless realistic lighting.')
      } else {
        await openMaskEditor(page, true)
        await uploadEditorImage(page, pngA)
        await page.getByRole('button', { name: /^Применить$|^Apply$/ }).click()
        await page.locator('.paint-editor').waitFor({ state: 'detached' })
        await setPrompt(page, 'Extend the image with a clean futuristic studio background and matching light.')
      }
      await generateAndWait(page, `paint_${paintMode}`, round)

      await page.getByRole('button', { name: 'Лицо стрелка вправо Изо' }).click()
      await uploadFirst(page, pngA)
      await uploadSecond(page, pngB)
      await setPrompt(page, 'Replace the head in image 1 with the head from image 2, adapting lighting and style.')
      await generateAndWait(page, 'faceswap', round)
    }
    log('25/25 браузерных генераций завершены')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  log(`FAILED: ${error.message}`)
  process.exit(1)
})



