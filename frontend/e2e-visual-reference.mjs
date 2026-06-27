import { chromium } from 'playwright'

const base = `http://127.0.0.1:5173?platform=web&userId=visual_${Date.now()}`

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 2048, height: 1152 } })
    page.setDefaultTimeout(15000)
    await page.goto(base, { waitUntil: 'networkidle' })

    await page.getByRole('button', { name: 'Текст стрелка вправо Изо' }).waitFor()
    await page.locator('.preview-panel').waitFor()
    await page.locator('.prompt-dock textarea').waitFor()

    const checks = await page.evaluate(() => {
      const bodyBg = getComputedStyle(document.body).backgroundColor
      const preview = document.querySelector('.preview-panel')
      const prompt = document.querySelector('.prompt-dock')
      const control = document.querySelector('.control-panel')
      const instruction = document.querySelector('.instruction-button')
      const generate = document.querySelector('.generate')
      const gallery = document.querySelector('.top-actions .icon-button:nth-child(2)')
      const mode = document.querySelector('.mode.active')
      const genStyle = generate ? getComputedStyle(generate) : null
      const previewBox = preview?.getBoundingClientRect()
      const promptBox = prompt?.getBoundingClientRect()
      const controlBox = control?.getBoundingClientRect()
      const instructionBox = instruction?.getBoundingClientRect()
      const generateBox = generate?.getBoundingClientRect()
      return {
        bodyBg,
        activeMode: mode?.textContent?.trim(),
        generateBg: genStyle?.backgroundColor,
        galleryBg: gallery ? getComputedStyle(gallery).backgroundImage : '',
        previewRight: previewBox ? previewBox.left > window.innerWidth * 0.26 : false,
        promptBelowControls: promptBox && controlBox ? promptBox.top > controlBox.bottom + 12 : false,
        promptAboveFold: promptBox ? promptBox.top < window.innerHeight * 0.75 : false,
        promptWide: promptBox ? promptBox.width > window.innerWidth * 0.8 : false,
        instructionClickable: promptBox && instructionBox ? instructionBox.bottom < promptBox.top : false,
        generateClickable: promptBox && generateBox ? generateBox.bottom < promptBox.top : false,
      }
    })

    if (!checks.bodyBg.includes('7, 7, 7')) throw new Error(`Wrong body background: ${checks.bodyBg}`)
    if (checks.activeMode !== 'Текст → Изо') throw new Error(`Wrong active mode text: ${checks.activeMode}`)
    if (!checks.generateBg.includes('236, 255, 47')) throw new Error(`Wrong Generate color: ${checks.generateBg}`)
    if (!checks.galleryBg.includes('gradient')) throw new Error('Gallery button is not gradient styled')
    if (!checks.previewRight || !checks.promptBelowControls || !checks.promptAboveFold || !checks.promptWide || !checks.instructionClickable || !checks.generateClickable) throw new Error(`Layout mismatch: ${JSON.stringify(checks)}`)

    await page.screenshot({ path: 'visual-reference-current.png', fullPage: true })
    console.log('Visual reference e2e passed: visual-reference-current.png')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})



