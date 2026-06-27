import { chromium } from 'playwright'

const userId = `stage3_${Date.now()}`
const base = `http://127.0.0.1:5173?platform=web&userId=${userId}`

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function configureFast(page) {
  await page.getByRole('button', { name: /Настройки/ }).click()
  await page.locator('label').filter({ hasText: 'Width' }).locator('input').fill('512')
  await page.locator('label').filter({ hasText: 'Height' }).locator('input').fill('512')
  await page.locator('label').filter({ hasText: 'Шаги' }).locator('input').fill('1')
  await page.locator('label').filter({ hasText: 'CFG' }).locator('input').fill('1')
  await page.getByRole('button', { name: /К генерации/ }).click()
  await page.locator('.studio-grid').waitFor()
}

async function generate(page, prompt) {
  const previous = await page.locator('.preview-panel img').first().getAttribute('src').catch(() => '')
  await page.locator('.prompt-dock textarea').fill(prompt)
  await page.getByRole('button', { name: /Сгенерировать/ }).click()
  await page.waitForFunction((oldSrc) => {
    const img = document.querySelector('.preview-panel img')
    return img && img.getAttribute('src') !== oldSrc
  }, previous, { timeout: 300000 })
  return page.locator('.preview-panel img').first().getAttribute('src')
}

async function openLatestGalleryItem(page, prompt) {
  await page.getByRole('button', { name: /Галерея/ }).first().click()
  await page.locator('.gallery-view').waitFor()
  await page.getByText(prompt).first().click()
  await page.locator('.detail').waitFor()
}

async function assertGalleryRecord(page, prompt, mode) {
  const records = await page.evaluate(async () => fetch('/api/gallery', {
    headers: { 'X-OneNode-User': localStorage.getItem('onenode_user') || 'demo_user' },
  }).then((response) => response.json()))
  const found = records.find((item) => item.promptOriginal === prompt && item.mode === mode)
  assert(found, `Gallery record for ${mode} was not saved`)
  assert(found.url.includes('/api/media/'), `Gallery record ${mode} has invalid url: ${found?.url}`)
  assert(found.thumbnailUrl.endsWith('.webp') || found.thumbnailUrl.includes('.webp?'), `Gallery record ${mode} has invalid thumbnail`)
  return found
}

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    page.setDefaultTimeout(25000)
    await page.goto(base, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: 'Текст стрелка вправо Изо' }).waitFor()
    await configureFast(page)

    const textPrompt = `stage3 text to image ${Date.now()}`
    await generate(page, textPrompt)
    const t2i = await assertGalleryRecord(page, textPrompt, 'text_to_image')

    await openLatestGalleryItem(page, textPrompt)
    await page.getByRole('button', { name: /Изо → Изо/ }).click()
    await page.locator('.studio-grid').waitFor()
    await page.getByRole('button', { name: 'Изо стрелка вправо Изо' }).waitFor()
    const i2iInput = await page.locator('.image-box img').first().getAttribute('src')
    assert(i2iInput?.includes(t2i.id) || i2iInput?.includes('/api/media/'), 'Use as Image to Image did not place source image')

    const i2iPrompt = `stage3 image to image ${Date.now()}`
    await generate(page, i2iPrompt)
    const i2i = await assertGalleryRecord(page, i2iPrompt, 'image_to_image')

    await openLatestGalleryItem(page, i2iPrompt)
    await page.getByRole('button', { name: /Редактирование 1/ }).click()
    await page.locator('.studio-grid').waitFor()
    await page.getByRole('button', { name: 'Редактирование Изо' }).waitFor()
    const editInput = await page.locator('.image-box img').first().getAttribute('src')
    assert(editInput?.includes(i2i.id) || editInput?.includes('/api/media/'), 'Use as Edit 1 did not place source image')

    const editPrompt = `stage3 edit image ${Date.now()}`
    await generate(page, editPrompt)
    await assertGalleryRecord(page, editPrompt, 'edit')

    await page.getByRole('button', { name: /Галерея/ }).first().click()
    await page.locator('.gallery-view').waitFor()
    await page.getByRole('button', { name: /Список/ }).click()
    await page.getByRole('button', { name: /Сетка/ }).click()
    await page.getByText(editPrompt).first().click()
    await page.locator('.detail').waitFor()
    await page.getByRole('button', { name: /Избранное/ }).click()
    await page.waitForFunction(async (prompt) => {
      const records = await fetch('/api/gallery', { headers: { 'X-OneNode-User': localStorage.getItem('onenode_user') || 'demo_user' } }).then((response) => response.json())
      return records.find((item) => item.promptOriginal === prompt)?.isFavorite
    }, editPrompt, { timeout: 10000 })
    const favoriteState = await page.evaluate(async (prompt) => {
      const records = await fetch('/api/gallery', { headers: { 'X-OneNode-User': localStorage.getItem('onenode_user') || 'demo_user' } }).then((response) => response.json())
      return records.find((item) => item.promptOriginal === prompt)?.isFavorite
    }, editPrompt)
    assert(favoriteState === true, 'Favorite action did not persist')

    await page.screenshot({ path: 'stage3-acceptance.png', fullPage: true })
    console.log('Stage 3 acceptance passed: Text to Image, Image to Image, Edit Image, Gallery, Use as.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



