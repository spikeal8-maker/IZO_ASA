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

async function mockApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/bootstrap-v2') {
      await route.fulfill({ json: { installation_id: 'inst-profile-e2e', anonymous_id: 'anon-profile-e2e' } })
      return
    }
    if (url.pathname === '/api/me-v2') {
      await route.fulfill({ json: mePayload })
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
}

async function run() {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 430, height: 932 }, isMobile: true, hasTouch: true })
    page.setDefaultTimeout(20000)
    await mockApi(page)

    await page.goto(`${base}/profile?profile_auth=${Date.now()}`, { waitUntil: 'networkidle' })
    await page.locator('.profile-page').waitFor()

    const data = await page.evaluate(() => ({
      hasDialog: Boolean(document.querySelector('.auth-modal, [role="dialog"]')),
      hasGuestCopy: document.body.innerText.includes('После входа здесь появятся'),
      hasName: document.body.innerText.includes('Алиса Профиль'),
      hasEmail: Array.from(document.querySelectorAll('input')).some((input) => input.value === 'profile@example.test'),
      hasBalance: document.body.innerText.includes('123'),
      avatarSrc: document.querySelector('.profile-avatar img')?.getAttribute('src') || '',
      topbarAvatarSrc: document.querySelector('.account-button .user-glyph img')?.getAttribute('src') || '',
      overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
    }))

    assert(!data.hasDialog, 'Authorized profile opened an auth dialog')
    assert(!data.hasGuestCopy, 'Authorized profile rendered guest login copy')
    assert(data.hasName, 'Authorized profile did not render display name')
    assert(data.hasEmail, 'Authorized profile did not render email')
    assert(data.hasBalance, 'Authorized profile did not render token balance')
    assert(data.avatarSrc.includes('/media/avatars/alice-profile.webp'), `Profile avatar src is wrong: ${data.avatarSrc}`)
    assert(data.topbarAvatarSrc.includes('/media/avatars/alice-profile.webp'), `Topbar avatar src is wrong: ${data.topbarAvatarSrc}`)
    assert(!data.overflowX, 'Authorized profile overflows horizontally on mobile')

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

    console.log('Authorized profile e2e passed.')
  } finally {
    await browser.close()
  }
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})
