import { chromium } from 'playwright'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const mePayload = {
  internal_user_id: 'iuid-profile-e2e',
  legacy_user_id: 'web_profile_e2e',
  status: 'active',
  account: {
    role: 'user',
    plan: 'plus',
    token_balance: 123,
    daily_tokens_used: 7,
    daily_tokens_limit: 100,
    daily_tokens_remaining: 93,
    daily_tokens: 100,
    gallery_slots: 200,
    gallery_used: 12,
    gallery_free: 188,
    gallery_full: false,
    gallery_access: true,
    gallery_enabled: true,
    password_configured: true,
    monthly_tokens_grant: 250,
    plan_started_at: '2026-07-01T00:00:00Z',
    plan_expires_at: '2026-10-01T00:00:00Z',
    video_slots: 20,
    video_used: 2,
    video_free: 18,
  },
  session: {
    provider: 'web_email',
    platform: 'web_desktop',
    expires_at: '2099-01-01T00:00:00Z',
    refresh_expires_at: '2099-02-01T00:00:00Z',
  },
  identities: [
    {
      provider: 'web_email',
      provider_email: 'profile@example.test',
      verified_at: '2099-01-01T00:00:00Z',
      linked_at: '2099-01-01T00:00:00Z',
      last_login_at: '2099-01-01T00:00:00Z',
    },
    {
      provider: 'telegram',
      provider_username: 'profile_user',
      linked_at: '2099-01-01T00:00:00Z',
      last_login_at: '2099-01-01T00:00:00Z',
    },
  ],
  profile: {
    display_name: 'Алиса Профиль',
    public_user_code: 'USR12345',
    first_name: 'Алиса',
    last_name: 'Профиль',
    username: 'alice_profile',
    email: 'profile@example.test',
    email_verified_at: '2099-01-01T00:00:00Z',
    language_code: 'ru',
    avatar_url: '/media/avatars/alice-profile.webp',
    avatar_preset: null,
    gender: 'female',
    age: 28,
    providers: ['web_email', 'telegram'],
  },
  created_at: '2026-06-26T04:15:07Z',
  last_seen_at: '2026-07-19T10:00:00Z',
}

const videoModel = {
  id: 'google/veo-profile-e2e',
  name: 'Google: Veo Profile E2E',
  description: 'Полное описание видеомодели открывается только по запросу пользователя.',
  supportedResolutions: ['720p', '1080p'],
  supportedAspectRatios: ['16:9', '9:16'],
  supportedDurations: [4, 6],
  generateAudio: true,
  publicPricing: { fromTokens: 7 },
}

async function mockApi(page, { authenticated = true } = {}) {
  const authState = { authenticated }
  await page.route('**/media/avatars/**', async (route) => {
    await route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect width="160" height="160" fill="#151d17"/><circle cx="80" cy="64" r="34" fill="#c7f500"/><path d="M28 150c8-36 30-54 52-54s44 18 52 54" fill="#c4cec6"/></svg>',
    })
  })
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/bootstrap-v2') {
      await route.fulfill({ json: { installation_id: 'inst-profile-e2e', anonymous_id: 'anon-profile-e2e' } })
      return
    }
    if (url.pathname === '/api/me-v2') {
      if (!authState.authenticated) {
        await route.fulfill({ status: 401, json: { detail: 'Not authenticated' } })
        return
      }
      await route.fulfill({ json: mePayload })
      return
    }
    if (url.pathname === '/api/auth/password/login-v2') {
      authState.authenticated = true
      await route.fulfill({ json: { ok: true } })
      return
    }
    if (url.pathname === '/api/auth/bot-login/status') {
      await route.fulfill({ status: 401, json: { detail: 'bot_login_challenge_missing' } })
      return
    }
    if (url.pathname === '/api/auth/bot-login/start') {
      const provider = (route.request().postDataJSON() || {}).provider || 'telegram'
      await route.fulfill({ json: { deep_link: `about:blank#${provider}-login-e2e`, poll_interval_ms: 2000 } })
      return
    }
    if (url.pathname === '/api/auth/capabilities-v2') {
      await route.fulfill({
        json: {
          password_login_available: true,
          password_register_available: true,
          email_otp_available: true,
          bot_login: { telegram_bot_login_available: true, max_bot_login_available: true },
        },
      })
      return
    }
    if (url.pathname === '/api/tariffs') {
      await route.fulfill({
        json: {
          tariffs: {
            free: { daily_tokens: 10, gallery_slots: 20 },
            mini: { daily_tokens: 50, gallery_slots: 80 },
            plus: { daily_tokens: 100, gallery_slots: 200 },
            pro: { daily_tokens: 200, gallery_slots: 500 },
          },
        },
      })
      return
    }
    if (url.pathname === '/api/models') {
      await route.fulfill({ json: { ok: true, profiles: [] } })
      return
    }
    if (url.pathname === '/api/video/config') {
      await route.fulfill({
        json: {
          modes: {
            text_to_video: [videoModel],
            image_to_video: [videoModel],
            first_last_frame: [videoModel],
            reference_to_video: [videoModel],
          },
          plan: 'plus',
          videoSlots: 20,
          economy: { tokenRub: 5, minMarginPercent: 40 },
          availability: {},
        },
      })
      return
    }
    await route.fulfill({ json: { ok: true, items: [], images: [] } })
  })
  return authState
}

async function run() {
  const browser = await chromium.launch()
  try {
    for (const device of [
      { name: 'desktop', viewport: { width: 1440, height: 1000 }, isMobile: false },
      { name: 'mobile', viewport: { width: 390, height: 844 }, isMobile: true },
    ]) {
      const page = await browser.newPage({ viewport: device.viewport, isMobile: device.isMobile, hasTouch: device.isMobile })
      page.setDefaultTimeout(20000)
      await mockApi(page)

      await page.goto(`${base}/profile?profile_auth=${Date.now()}`, { waitUntil: 'networkidle' })
      await page.locator('.account-page').waitFor()

      const data = await page.evaluate(() => ({
        hasDialog: Boolean(document.querySelector('.auth-modal, [role="dialog"]')),
        hasGuestCopy: document.body.innerText.includes('После входа здесь появятся'),
        hasName: document.body.innerText.includes('Алиса Профиль'),
        hasEmail: Array.from(document.querySelectorAll('input')).some((input) => input.value === 'profile@example.test'),
        hasBalance: document.body.innerText.includes('123'),
        hasRegistrationDate: document.body.innerText.includes('26 июня 2026'),
        hasExpiryDate: document.body.innerText.includes('01 октября 2026'),
        hasIrrelevantMetrics: document.body.innerText.includes('Лайки') || document.body.innerText.includes('Подписчики') || document.body.innerText.includes('Бонусы'),
        avatarSrc: document.querySelector('.account-avatar img')?.getAttribute('src') || '',
        overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      }))

      assert(!data.hasDialog, `Authorized ${device.name} profile opened an auth dialog`)
      assert(!data.hasGuestCopy, `Authorized ${device.name} profile rendered guest login copy`)
      assert(data.hasName, `Authorized ${device.name} profile did not render display name`)
      assert(data.hasEmail, `Authorized ${device.name} profile did not render email`)
      assert(data.hasBalance, `Authorized ${device.name} profile did not render token balance`)
      assert(data.hasRegistrationDate, `Authorized ${device.name} profile did not render registration date`)
      assert(data.hasExpiryDate, `Authorized ${device.name} profile did not render plan expiry`)
      assert(!data.hasIrrelevantMetrics, `Authorized ${device.name} profile rendered removed metrics`)
      assert(data.avatarSrc.includes('/media/avatars/alice-profile.webp'), `Profile avatar src is wrong: ${data.avatarSrc}`)
      assert(!data.overflowX, `Authorized ${device.name} profile overflows horizontally`)

      await page.screenshot({ path: `artifacts/profile-redesign-${device.name}.png`, fullPage: true })

      if (device.name === 'desktop') {
        await page.getByText('Безопасность', { exact: true }).click()
        await page.getByLabel('Текущий пароль').waitFor()
        await page.screenshot({ path: 'artifacts/profile-redesign-security.png', fullPage: true })
      }

      if (device.name === 'mobile') {
        await page.getByRole('button', { name: 'Модели' }).click()
        await page.locator('.profile-video-catalog').waitFor()
        const catalogInitial = await page.evaluate(() => ({
          groupCount: document.querySelectorAll('.profile-video-catalog > details').length,
          openGroups: document.querySelectorAll('.profile-video-catalog > details[open]').length,
          overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
        }))
        assert(catalogInitial.groupCount === 4, `Expected four video mode groups, got ${catalogInitial.groupCount}`)
        assert(catalogInitial.openGroups === 0, 'Video mode groups must be collapsed by default')
        assert(!catalogInitial.overflowX, 'Video catalog overflows horizontally on mobile')

        await page.locator('.profile-video-catalog > details').first().locator(':scope > summary').click()
        const modelRow = page.locator('.profile-video-model-row').first()
        await modelRow.waitFor()
        assert(await modelRow.getByText('от 7 ток.').isVisible(), 'Compact video model price is missing')
        assert(!(await modelRow.getByText(videoModel.description).isVisible()), 'Full video model description is open by default')
        await modelRow.locator('.profile-video-model-details > summary').click()
        assert(await modelRow.getByText(videoModel.description).isVisible(), 'Full video model description did not open')

        const toggle = modelRow.locator('input[type="checkbox"]')
        assert(await toggle.isChecked(), 'Video model visibility checkbox is not enabled by default')
        await toggle.uncheck()
        assert(!(await toggle.isChecked()), 'Video model visibility checkbox did not switch independently')
      }

      await page.close()
    }

    for (const device of [
      { name: 'desktop', viewport: { width: 1440, height: 1000 }, isMobile: false },
      { name: 'mobile', viewport: { width: 390, height: 844 }, isMobile: true },
    ]) {
      const page = await browser.newPage({ viewport: device.viewport, isMobile: device.isMobile, hasTouch: device.isMobile })
      page.setDefaultTimeout(20000)
      await mockApi(page, { authenticated: false })

      await page.goto(`${base}/profile?guest_auth=${Date.now()}`, { waitUntil: 'networkidle' })
      const dialog = page.getByRole('dialog')
      await dialog.waitFor()
      assert(new URL(page.url()).pathname === '/', `${device.name} guest profile kept the intermediary /profile page`)
      assert((await page.locator('.account-page').count()) === 0, `${device.name} guest profile rendered the intermediary account page`)
      assert(await dialog.getByRole('heading', { name: 'Вход в ИЗО АСА' }).isVisible(), `${device.name} login heading is missing`)
      assert(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2)), `${device.name} login overflows horizontally`)

      const provider = device.name === 'desktop' ? 'telegram' : 'max'
      const providerButton = provider === 'telegram' ? 'Войти через Telegram-бота' : 'Войти через MAX'
      const popupPromise = page.waitForEvent('popup')
      await dialog.getByRole('button', { name: providerButton, exact: true }).click()
      const popup = await popupPromise
      await popup.waitForURL(`about:blank#${provider}-login-e2e`)
      assert(await dialog.getByText(`Подтвердите вход в ${provider === 'telegram' ? 'Telegram' : 'MAX'}-боте.`, { exact: false }).isVisible(), `${device.name} bot login did not enter confirmation phase`)
      await popup.close()
      await dialog.getByRole('button', { name: 'Попробовать снова', exact: true }).click()

      await page.screenshot({ path: `artifacts/auth-redesign-${device.name}.png`, fullPage: true })

      if (device.name === 'desktop') {
        await dialog.getByLabel('Email').fill('profile@example.test')
        await dialog.getByLabel('Пароль').fill('correct-password')
        await dialog.getByRole('button', { name: 'Войти', exact: true }).click()
        await page.waitForURL((url) => url.pathname === '/' && url.hash === '#text-to-image')
      }

      await page.close()
    }

    console.log('Profile and auth desktop/mobile e2e passed.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
