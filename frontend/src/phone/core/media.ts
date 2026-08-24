import type { PhoneMediaAsset } from './jobs.ts'


export function phoneMediaAspect(asset: PhoneMediaAsset): number | null {
  if (asset.width && asset.height && asset.width > 0 && asset.height > 0) return asset.width / asset.height
  const match = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(asset.aspectRatio || '')
  if (!match) return null
  const width = Number(match[1])
  const height = Number(match[2])
  return width > 0 && height > 0 ? width / height : null
}

export function isSafePhoneMediaUrl(value: string): boolean {
  const url = value.trim()
  return url.startsWith('/api/')
    || url.startsWith('/media/')
    || url.startsWith('blob:')
    || /^data:(image|video|audio)\/[a-z0-9.+-]+[;,]/i.test(url)
}

export function phoneMediaFit(asset: PhoneMediaAsset): 'contain' | 'cover' {
  return asset.type === 'image' || asset.type === 'video' || asset.type === '3d' ? 'contain' : 'cover'
}
