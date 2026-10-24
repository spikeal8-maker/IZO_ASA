import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import os from 'node:os'

const origin = 'http://127.0.0.1:48214'
const evidence = join(os.homedir(), 'AppData', 'Local', 'IZO_ASA_Comfy214Runtime', 'evidence')
const cases = [
  { name: 'desktop', viewport: { width: 1366, height: 900 }, isMobile: false },
  { name: 'mobile', viewport: { width: 390, height: 844 }, isMobile: true },
]
await mkdir(evidence, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const c of cases) {
    const context = await browser.newContext({
      viewport: c.viewport,
      isMobile: c.isMobile,
      hasTouch: c.isMobile,
    })
    const page = await context.newPage()
    const errors = []
    const generationPosts = []
    page.on('pageerror', e => errors.push(String(e)))
    page.on('request', req => {
      if (req.method() === 'POST' && new URL(req.url()).pathname === '/api/generate') {
        generationPosts.push(req.url())
      }
    })
    try {
      const response = await page.goto(origin + '/#text-to-image', { waitUntil: 'domcontentloaded' })
      if (response?.status() !== 200) throw new Error('STUDIO_HTTP_NOT_200')
      const box = page.locator('.prompt-section textarea').first()
      await box.waitFor({ state: 'visible', timeout: 25_000 })
      const models = await context.request.get(origin + '/api/models')
      if (!models.ok()) throw new Error('REAL_MODELS_API_NOT_READY')
      const payload = await models.json()
      if (!payload.ok || !payload.diffusion_models.includes('ИЗО Base')) {
        throw new Error('LOCAL_FLUX_4B_NOT_SHOWN_IN_ACTUAL_MODELS')
      }
      const value = 'Дружелюбный робот в школьной лаборатории электроники'
      await box.fill(value)
      if (await box.inputValue() !== value) throw new Error('PROMPT_NOT_EDITABLE')
      await page.screenshot({ path: join(evidence, 'candidate-' + c.name + '.png'), fullPage: true })
      if (errors.length) throw new Error('STUDIO_JS_ERRORS: ' + errors.map(s => s.slice(0, 160)).join('; '))
      if (generationPosts.length) throw new Error('GUEST_GENERATION_POST_ALREADY_SENT')
      results.push({ type: c.name, http: 200, modelCatalog: true, prompt: true, pageErrors: 0, actualGpuGeneration: 'NOT_RUN_GUEST' })
      console.log('PASS_CANDIDATE_REAL_CHROMIUM_' + c.name.toUpperCase() + '_GUEST_SHELL')
    } finally { await context.close() }
  }
  console.log('COMFY214_BROWSER_GUEST_PASS ' + JSON.stringify(results))
} finally { await browser.close() }
