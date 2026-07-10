type SeoLocale = 'ru' | 'en'

export interface SeoMeta {
  title: string
  description: string
  canonical: string
  robots?: string
  ogTitle?: string
  ogDescription?: string
  ogImage?: string
}

const DEFAULT_OG_IMAGE = 'https://izo.alikinas.ru/static/og/izo-asa-og.jpg'

export function currentSeoLocale(): SeoLocale {
  if (typeof navigator === 'undefined') return 'ru'
  const lang = (navigator.languages?.[0] || navigator.language || '').toLowerCase()
  return lang.startsWith('en') ? 'en' : 'ru'
}

function setMetaByName(name: string, content: string) {
  let node = document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)
  if (!node) {
    node = document.createElement('meta')
    node.setAttribute('name', name)
    document.head.appendChild(node)
  }
  node.setAttribute('content', content)
}

function setMetaByProperty(property: string, content: string) {
  let node = document.head.querySelector<HTMLMetaElement>(`meta[property="${property}"]`)
  if (!node) {
    node = document.createElement('meta')
    node.setAttribute('property', property)
    document.head.appendChild(node)
  }
  node.setAttribute('content', content)
}

function setCanonical(href: string) {
  let node = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')
  if (!node) {
    node = document.createElement('link')
    node.setAttribute('rel', 'canonical')
    document.head.appendChild(node)
  }
  node.setAttribute('href', href)
}

export function applyClientSeo(meta: SeoMeta) {
  if (typeof document === 'undefined') return
  const ogTitle = meta.ogTitle || meta.title
  const ogDescription = meta.ogDescription || meta.description
  const ogImage = meta.ogImage || DEFAULT_OG_IMAGE

  document.title = meta.title
  setMetaByName('description', meta.description)
  setMetaByName('robots', meta.robots || 'index, follow')
  setCanonical(meta.canonical)

  setMetaByProperty('og:title', ogTitle)
  setMetaByProperty('og:description', ogDescription)
  setMetaByProperty('og:url', meta.canonical)
  setMetaByProperty('og:image', ogImage)
  setMetaByProperty('og:image:secure_url', ogImage)
  setMetaByName('twitter:title', ogTitle)
  setMetaByName('twitter:description', ogDescription)
  setMetaByName('twitter:image', ogImage)
}

export function appShellSeo(path: string): SeoMeta {
  const locale = currentSeoLocale()
  const canonicalPath = path === '/new' ? '/' : path
  const canonical = `https://izo.alikinas.ru${canonicalPath}`

  if (path.startsWith('/admin')) {
    return locale === 'en'
      ? { title: 'IZO ASA — admin panel', description: 'Private administration area for IZO ASA.', canonical, robots: 'noindex, nofollow' }
      : { title: 'ИЗО АСА — админ-панель', description: 'Закрытая панель администрирования ИЗО АСА.', canonical, robots: 'noindex, nofollow' }
  }
  if (path === '/old' || path === '/legacy' || path === '/v1') {
    return locale === 'en'
      ? { title: 'IZO ASA — legacy interface 1.0', description: 'Legacy IZO ASA 1.0 interface kept for compatibility while UI 2.0 is being completed.', canonical, robots: 'noindex, follow' }
      : { title: 'ИЗО АСА — старая версия 1.0', description: 'Старая версия интерфейса ИЗО АСА сохранена для совместимости, пока UI 2.0 доводится до полного релиза.', canonical, robots: 'noindex, follow' }
  }
  return locale === 'en'
    ? { title: 'IZO ASA — AI generator and editor', description: 'Create visual content with By Text, By Photo, Assembly, Face, Editor, gallery, feed, and the upcoming Video mode.', canonical: 'https://izo.alikinas.ru/' }
    : { title: 'ИЗО АСА — генератор и редактор', description: 'Создавайте визуальный контент: По тексту, По фото, Сборка, Лицо, Редактор, галерея, лента и будущий режим Видео.', canonical: 'https://izo.alikinas.ru/' }
}
