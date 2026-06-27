import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('./src/App.tsx', import.meta.url), 'utf8')
const css = readFileSync(new URL('./src/index.css', import.meta.url), 'utf8')

const requiredModes = [
  'text_to_image',
  'image_to_image',
  'edit',
  'paint',
  'inpaint',
  'outpaint',
  'faceswap',
]

const requiredUi = [
  'OneNode Image Studio',
  'Telegram',
  'MAX',
  'GalleryView',
  'PresetsView',
  'SettingsView',
  'AdminView',
  'Use as',
  'react-konva',
]

const requiredCss = [
  '.studio-grid',
  '.gallery-view',
  '.bottom-nav',
  '@media (max-width: 980px)',
]

const missing = [
  ...requiredModes.filter((item) => !app.includes(item)),
  ...requiredUi.filter((item) => !app.includes(item)),
  ...requiredCss.filter((item) => !css.includes(item)),
]

if (missing.length) {
  console.error(`Missing UI smoke-test markers: ${missing.join(', ')}`)
  process.exit(1)
}

console.log(`UI smoke test passed: ${requiredModes.length} modes and ${requiredUi.length} UI markers found.`)
