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
    const squareMetrics = await page.evaluate(() => {
      const frame = document.querySelector('.paint-outpaint-frame')?.getBoundingClientRect()
      const source = document.querySelector('.paint-outpaint-source')?.getBoundingClientRect()
      return frame && source ? {
        frameW: frame.width,
        frameH: frame.height,
        sourceW: source.width,
        sourceH: source.height,
        sourceX: source.x - frame.x,
        sourceY: source.y - frame.y,
      } : null
    })
    assert(Boolean(squareMetrics), 'outpaint square metrics are missing')
    assert(Math.abs(squareMetrics.frameW - squareMetrics.frameH) <= 2, `square frame is not square: ${JSON.stringify(squareMetrics)}`)
    assert(Math.abs(squareMetrics.sourceW - squareMetrics.frameW) <= 3, `wide source should span square frame width: ${JSON.stringify(squareMetrics)}`)
    assert(squareMetrics.sourceY > 12 && squareMetrics.sourceH < squareMetrics.frameH, `wide source should leave top/bottom outpaint bands in square frame: ${JSON.stringify(squareMetrics)}`)

    await page.getByRole('button', { name: '9:16' }).click()
    await page.waitForTimeout(80)
    const verticalMetrics = await page.evaluate(() => {
      const frame = document.querySelector('.paint-outpaint-frame')?.getBoundingClientRect()
      const source = document.querySelector('.paint-outpaint-source')?.getBoundingClientRect()
      return frame && source ? { frameW: frame.width, frameH: frame.height, sourceW: source.width, sourceH: source.height } : null
    })
    assert(Boolean(verticalMetrics), 'outpaint vertical metrics are missing')
    assert(verticalMetrics.frameH > verticalMetrics.frameW * 1.55, `9:16 should render a vertical frame: ${JSON.stringify(verticalMetrics)}`)
    assert(Math.abs(verticalMetrics.sourceW - verticalMetrics.frameW) <= 3, `wide source should fit across vertical frame width: ${JSON.stringify(verticalMetrics)}`)
    assert(verticalMetrics.sourceH < verticalMetrics.frameH * 0.45, `wide source should leave vertical extension space in 9:16: ${JSON.stringify(verticalMetrics)}`)

    await page.getByRole('button', { name: '16:9' }).click()
    await page.waitForTimeout(80)
    const wideMetrics = await page.evaluate(() => {
      const frame = document.querySelector('.paint-outpaint-frame')?.getBoundingClientRect()
      const source = document.querySelector('.paint-outpaint-source')?.getBoundingClientRect()
      return frame && source ? { frameW: frame.width, frameH: frame.height, sourceW: source.width, sourceH: source.height } : null
    })
    assert(Boolean(wideMetrics), 'outpaint wide metrics are missing')
    assert(wideMetrics.frameW > wideMetrics.frameH * 1.55, `16:9 should render a wide frame: ${JSON.stringify(wideMetrics)}`)
    assert(wideMetrics.sourceW <= wideMetrics.frameW + 3 && wideMetrics.sourceH <= wideMetrics.frameH + 3, `wide source should stay inside 16:9 frame: ${JSON.stringify(wideMetrics)}`)
    assert(wideMetrics.sourceW > wideMetrics.frameW * 0.82 && wideMetrics.sourceH > wideMetrics.frameH * 0.82, `wide source should be fitted prominently in 16:9 frame: ${JSON.stringify(wideMetrics)}`)

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
    const tabsVisible = await page.locator('.paint-mode-tabs').evaluate((el) => getComputedStyle(el).display !== 'none')
    assert(tabsVisible, 'mobile paint mode tabs should stay visible')
    const modeSelectVisible = await page.locator('.paint-mode-select').evaluate((el) => getComputedStyle(el).display !== 'none')
    assert(!modeSelectVisible, 'mobile paint mode select should not replace mode tabs')
    const toolsToggle = page.locator('.paint-tools-toggle')
    await toolsToggle.waitFor()
    const toolsHidden = await page.locator('.paint-sidebar-tools').evaluate((el) => getComputedStyle(el).display === 'none')
    assert(toolsHidden, 'mobile drawing tools should be collapsed by default')
    await toolsToggle.click()
    const toolsOpen = await page.locator('.paint-sidebar-tools').evaluate((el) => getComputedStyle(el).display !== 'none')
    assert(toolsOpen, 'mobile drawing tools should open from the tools toggle')

    const stageBox = await page.locator('.paint-stage').first().boundingBox()
    const actionsBox = await page.locator('.paint-workbench-actions').first().boundingBox()
    assert(Boolean(stageBox) && Boolean(actionsBox), 'mobile sketch stage/actions are missing')
    assert(actionsBox.y >= stageBox.y && actionsBox.y < stageBox.y + stageBox.height * 0.35, `sketch undo/clear actions should stay inside the top of the stage: stage=${stageBox.y},${stageBox.height}; actions=${actionsBox.y}`)

    await page.getByRole('button', { name: 'Маска пусто' }).click()
    const maskControl = await page.locator('.mode-mask .paint-control').first().boundingBox()
    assert(Boolean(maskControl), 'mobile mask size control is missing')
    assert(maskControl.height <= 44, `mobile mask size control is too tall: ${maskControl.height}`)

    await page.getByRole('button', { name: 'Расширение пусто' }).click()
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
