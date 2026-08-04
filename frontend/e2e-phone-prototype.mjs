import { chromium } from 'playwright'

const origin = (process.env.IZO_E2E_BASE_URL || 'http://127.0.0.1:4178').replace(/\/$/, '')
const pixel = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="640"><rect width="640" height="640" fill="#6D4AFF"/><circle cx="320" cy="320" r="190" fill="#EE86FB"/></svg>')
const uploadPixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR42mNkYPj/n4GBgYGJAQoAHgQCAf2IseUAAAAASUVORK5CYII=', 'base64')

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const me = {
  profile: { display_name: 'Тестовый пользователь', avatar_url: pixel },
  account: { plan: 'pro', token_balance: 321, daily_tokens_remaining: 87, daily_tokens_limit: 100 },
}
const modelAccess = {
  ok: true,
  plan: 'pro',
  modes: {
    text_to_image: { models: [{ id: 'server:local_flux_klein', label: 'ИЗО Base', provider: 'comfyui', modelProfile: 'local_flux_klein', tokenHint: 1, supportedResolutionIds: ['sq-sd', 'sq-hd', 'sq-fhd', 'h-hd', 'v-hd', 'p-hd'] }], presets: { fast: 'server:local_flux_klein' } },
  },
}
const videoModel = {
  id: 'test/video-model', name: 'ИЗО Видео', supportedDurations: [4, 6], supportedResolutions: ['720p', '1080p'],
  supportedAspectRatios: ['16:9', '9:16', '1:1'], supportedFrameImages: ['first_frame'], generateAudio: true,
  publicPricing: { fromTokens: 13 },
}
const videoConfig = { modes: { text_to_video: [videoModel], image_to_video: [videoModel], first_last_frame: [videoModel], reference_to_video: [videoModel] }, plan: 'pro', videoSlots: 10, economy: { tokenRub: 5 } }

const browser = await chromium.launch({ headless: true })
try {
  for (const [viewportIndex, viewport] of [{ width: 390, height: 844 }, { width: 430, height: 932 }].entries()) {
    const generated = []
    const generatedVideos = []
    const chatRequests = []
    let transcribeRequests = 0
    const context = await browser.newContext({ viewport, isMobile: true, hasTouch: true })
    await context.addInitScript(() => {
      Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } })
      class FakeMediaRecorder extends EventTarget {
        static isTypeSupported() { return true }
        constructor(_stream, options = {}) { super(); this.mimeType = options.mimeType || 'audio/webm' }
        start() {}
        stop() {
          this.dispatchEvent(new BlobEvent('dataavailable', { data: new Blob(['phone voice'], { type: this.mimeType }) }))
          this.dispatchEvent(new Event('stop'))
        }
      }
      Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: FakeMediaRecorder })
    })
    const page = await context.newPage()
    const pageErrors = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await page.route('**/api/**', async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      const path = url.pathname
      const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
      if (path === '/api/me-v2') return json(me)
      if (path === '/api/auth/session/refresh-v2') return json({ ok: true })
      if (path === '/api/model-access') return json(modelAccess)
      if (path === '/api/video/config') return json(videoConfig)
      if (path === '/api/feed') return json({ items: [{ id: 'feed-1', media_type: 'image', thumbnail_url: pixel, image_url: pixel, title: 'Реальная работа', author_name: 'Автор' }] })
      if (path === '/api/gallery/items') return json({ items: [{ id: 'gallery-1', mediaType: 'image', url: pixel, thumbnailUrl: pixel, promptOriginal: 'Из галереи' }] })
      if (path === '/api/tools/improve-prompt') return json({ ok: true, improvedPrompt: 'Розовый стеклянный шар на светлом деревянном столе, мягкий студийный свет' })
      if (path === '/api/tools/transcribe') { transcribeRequests += 1; return json({ ok: true, text: 'добавь мягкие отражения' }) }
      if (path === '/api/phone/chat') { chatRequests.push(request.postDataJSON()); return json({ ok: true, reply: 'Предлагаю сделать выразительную сцену с мягким светом.', provider: 'local', model: 'gemma4:31b-cloud' }) }
      if (path === '/api/generate' && request.method() === 'POST') { generated.push(request.postDataJSON()); return json({ id: 'image-job-1', status: 'queued', progress: 4 }) }
      if (path === '/api/jobs/image-job-1') return json({ id: 'image-job-1', status: 'completed', progress: 100, resultUrl: pixel, resultImageId: 'image-1' })
      if (path === '/api/video/estimate') return json({ chargedTokens: 13 })
      if (path === '/api/video/generate' && request.method() === 'POST') { generatedVideos.push(request.postDataJSON()); return json({ id: 'video-job-1', status: 'queued', progress: 10 }) }
      if (path === '/api/video/history') return json({ items: [{ id: 'video-job-1', status: 'completed', progress: 100, prompt: 'Видео', createdAt: new Date().toISOString(), videoUrl: 'data:video/mp4;base64,', galleryVideoId: 'gallery-video-1' }] })
      return json({ detail: `Unexpected test request: ${path}` }, 404)
    })

    await page.goto(`${origin}/phone`, { waitUntil: 'load' })
    const frameElement = page.locator('iframe[title="Мобильный интерфейс ИЗО АСА"]')
    await frameElement.waitFor()
    await page.waitForFunction(() => {
      const element = document.querySelector('iframe[title="Мобильный интерфейс ИЗО АСА"]')
      return element instanceof HTMLIFrameElement
        && element.contentDocument?.readyState === 'complete'
        && element.contentWindow?.location.pathname.endsWith('/phone-prototype.html')
    })
    const frame = page.frames().find((candidate) => candidate.url().includes('/phone-prototype.html'))
    assert(frame, `${viewport.width}: phone iframe did not load`)
    await frame.waitForFunction(() => window.__IZO_PHONE_RUNTIME__?.ready === true)
    await frame.getByText('Реальная работа · Автор', { exact: true }).waitFor()

    const layout = await page.evaluate(() => ({
      width: innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      frame: (() => { const element = document.querySelector('iframe'); if (!(element instanceof HTMLIFrameElement)) return null; const rect = element.getBoundingClientRect(); return { width: rect.width, height: rect.height } })(),
    }))
    const innerLayout = await frame.evaluate(() => ({ width: innerWidth, documentWidth: document.documentElement.scrollWidth, phoneWidth: document.querySelector('.ph')?.getBoundingClientRect().width }))
    assert(layout.documentWidth <= layout.width, `${viewport.width}: outer document overflows`)
    assert(innerLayout.documentWidth <= innerLayout.width, `${viewport.width}: template overflows`)
    assert(layout.frame?.width === viewport.width && layout.frame?.height === viewport.height, `${viewport.width}: iframe does not fill viewport`)
    assert(innerLayout.phoneWidth === viewport.width, `${viewport.width}: template width changed`)

    if (viewportIndex === 0) {
      await frame.getByRole('button', { name: 'Картинка', exact: true }).click()
      assert(await frame.evaluate(() => document.querySelector('.ph')?.scrollTop || 0) === 0, 'root phone container scrolled after bottom navigation')
      const imagePrompt = frame.getByPlaceholder('Например: сова в космосе, неоновые звёзды…', { exact: true })
      assert(await frame.getByRole('tab').count() === 3, 'image editor tabs were not merged')
      assert(await frame.getByRole('tab', { name: 'Изменить', exact: true }).count() === 1, 'unified image edit tab is missing')
      await frame.getByText('Все шаблоны ›', { exact: true }).click()
      assert(await frame.locator('[data-template]').count() === 23, 'shared image templates are incomplete')
      assert(await frame.locator('[data-si]').count() === 0, 'template sheet opened on the wrong section')
      await frame.locator('[data-template="0"]').click()
      await frame.waitForFunction(() => document.querySelector('#gp')?.value.includes('фарфоровая чашка'))
      await frame.locator('[data-st="0"]').click()
      await imagePrompt.fill('Розовый шар на столе')
      await frame.getByTitle('Улучшить описание').click()
      await frame.waitForFunction(() => document.querySelector('#gp')?.value.includes('стеклянный шар'))
      const imageMic = frame.locator('[data-live-mic="image"]')
      await imageMic.click()
      await frame.waitForFunction(() => document.querySelector('[data-live-mic="image"]')?.classList.contains('live-recording'))
      await frame.waitForTimeout(900)
      await imageMic.click()
      await frame.waitForFunction(() => document.querySelector('#gp')?.value.includes('мягкие отражения'))
      assert(transcribeRequests === 1, `voice transcription request count=${transcribeRequests}`)
      await frame.locator('#run').click()
      await frame.waitForFunction(() => window.__IZO_PHONE_RUNTIME__?.imageResults?.length === 1 || Boolean(window.__IZO_PHONE_RUNTIME__?.lastError), null, { timeout: 8000 })
      const imageRuntime = await frame.evaluate(() => ({ results: window.__IZO_PHONE_RUNTIME__?.imageResults?.length || 0, error: window.__IZO_PHONE_RUNTIME__?.lastError || '' }))
      assert(imageRuntime.results === 1 && !imageRuntime.error, `phone image runtime failed: ${JSON.stringify(imageRuntime)}`)
      const imageResultCount = await frame.locator('.canvas img[alt="Результат генерации"]').count()
      const imageMarkup = imageResultCount === 1 ? '' : await frame.evaluate(() => document.querySelector('#scr')?.innerHTML.slice(0, 1200) || '')
      assert(imageResultCount === 1, `image result is not rendered in the Drive template: ${imageMarkup}`)
      assert(await frame.locator('.canvas.live-result-host .live-result-preview').count() === 1, 'generated image stayed in a thumbnail instead of the preview')
      const resultBox = await frame.locator('.canvas.live-result-host').boundingBox()
      assert(resultBox && resultBox.height >= 270, `generated image preview is too small: ${JSON.stringify(resultBox)}`)
      assert(generated.length === 1, `image request count=${generated.length}`)
      assert(generated[0].mode === 'text_to_image', 'phone image mode is not real text_to_image')
      assert(generated[0].provider === 'comfyui' && generated[0].modelProfile === 'local_flux_klein', 'phone image model contract changed')
      assert(generated[0].resolutionId === 'sq-hd' && generated[0].width === 1024 && generated[0].height === 1024, 'phone default is not square HD')
      assert(generated[0].prompt.includes('коммерческая фотография'), 'selected shared style was not sent to generation')

      await frame.locator('.live-result-preview').dblclick()
      await frame.locator('.live-image-viewer').waitFor({ state: 'visible' })
      assert((await frame.evaluate(() => window.__IZO_PHONE_RUNTIME__?.imageViewer))?.open === true, 'fullscreen image viewer did not open')
      const viewerStage = frame.locator('.live-image-viewer-stage')
      await viewerStage.dblclick()
      assert((await frame.evaluate(() => window.__IZO_PHONE_RUNTIME__?.imageViewer?.scale || 0)) > 2, 'double tap zoom did not enlarge the image')
      await frame.getByRole('button', { name: 'Вписать', exact: true }).click()
      await frame.evaluate(() => {
        const stage = document.querySelector('.live-image-viewer-stage')
        const fire = (type, pointerId, clientX) => stage.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId, pointerType: 'touch', clientX, clientY: 360, buttons: type === 'pointerup' ? 0 : 1 }))
        fire('pointerdown', 1, 150); fire('pointerdown', 2, 240); fire('pointermove', 2, 330)
      })
      assert((await frame.evaluate(() => window.__IZO_PHONE_RUNTIME__?.imageViewer?.scale || 0)) > 1.5, 'two-finger pinch did not enlarge the image')
      await frame.evaluate(() => {
        const stage = document.querySelector('.live-image-viewer-stage')
        stage.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1, pointerType: 'touch', clientX: 150, clientY: 360 }))
        stage.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 2, pointerType: 'touch', clientX: 330, clientY: 360 }))
      })
      await frame.locator('.live-image-viewer [data-viewer-close]').click()
      await frame.locator('.live-image-viewer').waitFor({ state: 'hidden' })

      const fileChooserPromise = page.waitForEvent('filechooser')
      await frame.getByTitle('Прикрепить').click()
      const chooser = await fileChooserPromise
      await chooser.setFiles([
        { name: 'base.png', mimeType: 'image/png', buffer: uploadPixel },
        { name: 'reference.png', mimeType: 'image/png', buffer: uploadPixel },
      ])
      await frame.waitForFunction(() => window.__IZO_PHONE_RUNTIME__?.imageRefs?.length === 2)
      assert(await frame.getByRole('tab', { name: 'Изменить', exact: true }).getAttribute('aria-selected') === 'true', 'adding images did not switch to the unified edit tab')
      const sourceCount = await frame.locator('.live-source-item').count()
      assert(sourceCount === 2, `multiple source images are not visible in the unified editor: ${await frame.evaluate(() => document.querySelector('#scr')?.innerHTML.slice(0, 1200) || '')}`)
      await frame.locator('#gp').fill('Совмести основной объект и детали референса')
      await frame.locator('#run').click()
      await frame.waitForTimeout(250)
      const editStart = await frame.evaluate(() => ({ disabled: document.querySelector('#run')?.disabled, phase: window.__IZO_PHONE_RUNTIME__?.imagePhase, error: window.__IZO_PHONE_RUNTIME__?.lastError }))
      assert(generated.length === 2, `unified edit did not start: ${JSON.stringify({ editStart, pageErrors })}`)
      await frame.waitForFunction(() => window.__IZO_PHONE_RUNTIME__?.imageResults?.length === 1 || Boolean(window.__IZO_PHONE_RUNTIME__?.lastError), null, { timeout: 8000 })
      assert(generated.length === 2, `unified edit request count=${generated.length}`)
      assert(generated[1].mode === 'edit' && generated[1].inputImages?.length === 2, 'unified editor did not route multiple sources to edit mode')

      await frame.getByRole('button', { name: 'Чат', exact: true }).click()
      const chatPrompt = frame.getByLabel('Сообщение в чат')
      await chatPrompt.fill('Придумай идею для новой картинки')
      await frame.getByRole('button', { name: 'Отправить сообщение' }).click()
      await frame.getByText('Предлагаю сделать выразительную сцену с мягким светом.', { exact: true }).waitFor()
      assert(chatRequests.length === 1, `chat request count=${chatRequests.length}`)
      assert(chatRequests[0].route === 'auto' && chatRequests[0].messages.at(-1)?.content === 'Придумай идею для новой картинки', 'phone chat request contract changed')
      await frame.getByRole('button', { name: 'Добавить фото или файл' }).click()
      assert(await frame.getByText('Добавить фото', { exact: true }).isVisible(), 'chat attachment menu did not open')
      await frame.getByRole('button', { name: 'Инструменты чата' }).click()
      await frame.getByText('Улучшить сообщение', { exact: true }).waitFor()
      await frame.evaluate(() => closeSheets())

      await frame.getByRole('button', { name: 'Показать нижнее меню' }).click()
      await frame.getByRole('button', { name: 'Видео', exact: true }).click()
      await frame.getByPlaceholder('Например: робот идёт по ночному городу, камера приближается…', { exact: true }).fill('Камера плавно приближается')
      await frame.getByRole('button', { name: 'Сделать видео 13 кр.', exact: true }).click()
      await frame.waitForFunction(() => window.__IZO_PHONE_RUNTIME__?.videoJob?.id === 'video-job-1')
      assert(generatedVideos.length === 1, `video request count=${generatedVideos.length}`)
      assert(generatedVideos[0].mode === 'text_to_video' && generatedVideos[0].model === 'test/video-model', 'phone video request uses wrong model or mode')
      assert(generatedVideos[0].duration === 4 && generatedVideos[0].resolution === '720p' && generatedVideos[0].aspectRatio === '16:9', 'phone video defaults are not model-supported')
    }
    await context.close()
  }
  console.log('Phone Drive-template e2e passed: merged image editor, shared presets, preview zoom and pinch, voice input, chat and video request.')
} finally {
  await browser.close()
}
