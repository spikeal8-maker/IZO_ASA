import { chromium } from 'playwright'
import { deflateSync } from 'node:zlib'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'

function crc32(buffer) {
  let crc = 0xffffffff
  for (const byte of buffer) {
    crc ^= byte
    for (let i = 0; i < 8; i += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0)
  }
  return (crc ^ 0xffffffff) >>> 0
}

function pngChunk(type, data) {
  const typeBuffer = Buffer.from(type)
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length)
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])))
  return Buffer.concat([length, typeBuffer, data, crc])
}

function solidPng(width, height, rgb = [190, 220, 40]) {
  const header = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8
  ihdr[9] = 2
  const row = Buffer.alloc(1 + width * 3)
  for (let x = 0; x < width; x += 1) {
    row[1 + x * 3] = rgb[0]
    row[2 + x * 3] = rgb[1]
    row[3 + x * 3] = rgb[2]
  }
  const raw = Buffer.concat(Array.from({ length: height }, () => row))
  return Buffer.concat([header, pngChunk('IHDR', ihdr), pngChunk('IDAT', deflateSync(raw)), pngChunk('IEND', Buffer.alloc(0))])
}

const widePng = solidPng(160, 90)

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function openPaint(page) {
  await page.goto(`${base}/paint?paint_workbench=${Date.now()}`, { waitUntil: 'networkidle' })
  await page.locator('.paint-workbench').waitFor()
}

async function testDesktop() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    page.setDefaultTimeout(20000)
    await openPaint(page)

    const techToggle = page.locator('.paint-tech-toggle')
    const techBox = await techToggle.boundingBox()
    assert(Boolean(techBox), 'paint technical prompt toggle is missing')
    assert(techBox.height <= 28, `paint technical prompt toggle is too tall: ${techBox.height}`)

    await page.getByRole('button', { name: /Расширение/ }).first().click()
    await page.getByRole('button', { name: /^Загрузить$/ }).first().click()
    await page.locator('input[type="file"]').setInputFiles({ name: 'paint-source.png', mimeType: 'image/png', buffer: widePng })
    await page.locator('.paint-outpaint-frame.is-filled').waitFor()
    await page.locator('.paint-outpaint-source img').waitFor()
    await page.locator('.paint-outpaint-guidance').waitFor()

    const controls = await page.locator('.mode-outpaint .paint-control').count()
    assert(controls === 4, `outpaint should render 4 compact controls, got ${controls}`)
    const handles = await page.locator('.paint-outpaint-handle').count()
    assert(handles === 4, `outpaint should render 4 edge handles, got ${handles}`)

    const leftValue = Number(await page.locator('.mode-outpaint .paint-control').nth(0).locator('span').last().innerText())
    const topValue = Number(await page.locator('.mode-outpaint .paint-control').nth(2).locator('span').last().innerText())
    assert(leftValue === 0, `wide source in square frame should touch horizontal edges, got left padding ${leftValue}`)
    assert(topValue > 0, `wide source in square frame should have vertical outpaint space, got top padding ${topValue}`)

    const before = await page.locator('.mode-outpaint .paint-control').nth(2).locator('span').last().innerText()
    const box = await page.locator('.paint-outpaint-source').boundingBox()
    assert(Boolean(box), 'outpaint source has no box')
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + 80, { steps: 6 })
    await page.mouse.up()
    const after = await page.locator('.mode-outpaint .paint-control').nth(2).locator('span').last().innerText()
    assert(before !== after, `dragging outpaint source did not update top padding: ${before} -> ${after}`)
  } finally {
    await browser.close()
  }
}

async function testMobile() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
    page.setDefaultTimeout(20000)
    await openPaint(page)
    const modeSelect = page.locator('.paint-mode-select select')
    await modeSelect.waitFor()
    const selectBox = await modeSelect.boundingBox()
    assert(Boolean(selectBox), 'mobile paint mode select is missing')
    const tabsVisible = await page.locator('.paint-mode-tabs').evaluate((el) => getComputedStyle(el).display !== 'none')
    assert(!tabsVisible, 'mobile paint mode tabs should be collapsed into select')

    const stageBox = await page.locator('.paint-stage').first().boundingBox()
    const actionsBox = await page.locator('.paint-workbench-actions').first().boundingBox()
    assert(Boolean(stageBox) && Boolean(actionsBox), 'mobile sketch stage/actions are missing')
    assert(actionsBox.y > stageBox.y + stageBox.height * 0.68, `sketch undo/clear actions should sit near the lower edge: stage=${stageBox.y},${stageBox.height}; actions=${actionsBox.y}`)

    await modeSelect.selectOption('mask')
    const maskControl = await page.locator('.mode-mask .paint-control').first().boundingBox()
    assert(Boolean(maskControl), 'mobile mask size control is missing')
    assert(maskControl.height <= 44, `mobile mask size control is too tall: ${maskControl.height}`)

    await modeSelect.selectOption('outpaint')
    await page.getByRole('button', { name: /^Загрузить$/ }).first().click()
    await page.locator('input[type="file"]').setInputFiles({ name: 'paint-mobile-source.png', mimeType: 'image/png', buffer: widePng })
    await page.locator('.paint-outpaint-guidance').waitFor()
    const overflowX = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2)
    assert(!overflowX, 'paint outpaint controls overflow horizontally on mobile')
  } finally {
    await browser.close()
  }
}

await testDesktop()
await testMobile()
console.log('Paint workbench e2e passed.')
