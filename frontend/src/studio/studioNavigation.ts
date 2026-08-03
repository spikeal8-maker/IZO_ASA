// ARCH-FE-STUDIO-001A: URL interpretation and SEO metadata for the studio
// shell. Keeping navigation policy together prevents it from leaking into
// rendering and general-purpose data helpers.
import { currentSeoLocale, type SeoMeta } from '../seo'
import type { N2Tab, N2View } from './studioTypes'

// Начальное состояние из URL. Статические /feed и /gallery отдаются backend,
// а hash-ссылки из этих страниц возвращают пользователя в нужный режим UI 2.0.
export function initialViewFromPath(): { view: N2View; tab: N2Tab } {
  const p = typeof window !== 'undefined' ? window.location.pathname : '/feed'
  const h = typeof window !== 'undefined' ? window.location.hash : ''
  if (p === '/gallery' || p.startsWith('/gallery') || p.startsWith('/new/gallery')) return { view: 'tabs', tab: 'text' }
  if (p === '/profile' || p.startsWith('/profile') || p.startsWith('/new/profile')) return { view: 'profile', tab: 'feed' }
  if (h === '#image-to-image') return { view: 'tabs', tab: 'i2i' }
  if (h === '#editor') return { view: 'tabs', tab: 'edit' }
  if (h === '#face' || h === '#face-to-image') return { view: 'tabs', tab: 'edit' }
  if (h === '#draw' || h === '#drawing' || h === '#paint') return { view: 'tabs', tab: 'paint' }
  if (h === '#video') return { view: 'tabs', tab: 'video' }
  if (h === '#text-to-image') return { view: 'tabs', tab: 'text' }
  if (p === '/paint' || p.startsWith('/paint/') || p === '/new/paint' || p.startsWith('/new/paint/')) return { view: 'tabs', tab: 'paint' }
  if (p === '/video' || p.startsWith('/video/') || p === '/new/video' || p.startsWith('/new/video/')) return { view: 'tabs', tab: 'video' }
  // /feed is owned by backend/static/feed/index.html. If the SPA is ever served
  // for that path by a stale build or broken proxy, do not revive the old React feed.
  return { view: 'tabs', tab: 'text' }
}

export function initialProfileTabFromPath(): 'profile' | 'tariffs' | 'earn' | 'models' {
  const path = typeof window !== 'undefined' ? window.location.pathname.replace(/\/+$/, '') : '/profile'
  const segment = path.split('/').filter(Boolean).at(-1)
  if (segment === 'tariffs' || segment === 'earn' || segment === 'models') return segment
  return 'profile'
}

export function studioSeoMeta(tab: N2Tab, view: N2View): SeoMeta {
  const locale = currentSeoLocale()
  const path = view === 'profile' ? '/profile' : tab === 'paint' ? '/paint' : tab === 'video' ? '/video' : '/'
  const canonical = `https://izo.alikinas.ru${path}`

  if (view === 'profile') {
    return locale === 'en'
      ? {
        title: 'Profile and settings — IZO ASA',
        description: 'Manage your IZO ASA profile, avatar, accounts, tariffs, bonuses and generation history settings.',
        canonical,
        robots: 'noindex, nofollow',
      }
      : {
        title: 'Профиль и настройки — ИЗО АСА',
        description: 'Управляйте профилем ИЗО АСА: аватаром, аккаунтами, тарифами, бонусами и настройками истории генераций.',
        canonical,
        robots: 'noindex, nofollow',
      }
  }

  const ru: Record<N2Tab, SeoMeta> = {
    feed: {
      title: 'ИЗО АСА — лента AI-изображений',
      description: 'Смотрите публичную ленту изображений, промптов и идей пользователей ИЗО АСА.',
      canonical: 'https://izo.alikinas.ru/feed',
    },
    text: {
      title: 'По тексту — ИЗО АСА',
      description: 'Создавайте изображения нейросетью по текстовому описанию: выбирайте стиль, формат, качество и публикуйте результат в ленту.',
      canonical,
    },
    i2i: {
      title: 'По фото — ИЗО АСА',
      description: 'Преобразуйте исходное изображение по промпту и стилю, управляйте влиянием описания и сохраняйте результат в галерею.',
      canonical,
    },
    edit: {
      title: 'Сборка изображения — ИЗО АСА',
      description: 'Объединяйте несколько изображений, переносите одежду, фон, стиль и детали с референсов через AI-редактор ИЗО АСА.',
      canonical,
    },
    paint: {
      title: 'Редактор изображения — ИЗО АСА',
      description: 'Редактируйте изображения: рисуйте эскиз, работайте с маской, расширением холста и AI-дорисовкой.',
      canonical,
    },
    video: {
      title: 'Видео — ИЗО АСА',
      description: 'Создавайте видео по тексту, изображению, начальному и конечному кадру или набору референсов.',
      canonical,
    },
  }
  const en: Record<N2Tab, SeoMeta> = {
    feed: {
      title: 'AI image feed — IZO ASA',
      description: 'Explore public AI images, prompts, ideas and remixes from IZO ASA users.',
      canonical: 'https://izo.alikinas.ru/feed',
    },
    text: {
      title: 'By text — IZO ASA',
      description: 'Create AI images from text prompts, choose styles, aspect ratios and quality, then publish results to the feed.',
      canonical,
    },
    i2i: {
      title: 'By photo — IZO ASA',
      description: 'Transform a source image with a prompt and style, control prompt influence and save results to your gallery.',
      canonical,
    },
    edit: {
      title: 'Image assembly — IZO ASA',
      description: 'Combine multiple images, transfer clothes, background, style and details from references with the IZO ASA editor.',
      canonical,
    },
    paint: {
      title: 'Image editor — IZO ASA',
      description: 'Edit images with sketches, masks, outpainting and AI-assisted canvas tools.',
      canonical,
    },
    video: {
      title: 'Video — IZO ASA',
      description: 'Create videos from text, images, first and last frames, or visual references.',
      canonical,
    },
  }
  return locale === 'en' ? en[tab] : ru[tab]
}
