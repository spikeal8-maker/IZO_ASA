import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const sourcePath = resolve(here, '../src/stylePresets.ts')
const outputPath = resolve(here, '../public/phone-image-presets.js')
const source = await readFile(sourcePath, 'utf8')

function templateBody(functionName) {
  const functionStart = source.indexOf(`export function ${functionName}()`)
  const valueStart = source.indexOf('return `', functionStart)
  const bodyStart = valueStart + 'return `'.length
  const bodyEnd = source.indexOf('`', bodyStart)
  if (functionStart < 0 || valueStart < 0 || bodyEnd < 0) throw new Error(`Could not read ${functionName} from ${sourcePath}`)
  return source.slice(bodyStart, bodyEnd)
}

function rows(functionName) {
  return templateBody(functionName).trim().split(/\r?\n/).map((line) => {
    const [number, name, ...prompt] = line.split('\t')
    return { number: number.trim().padStart(2, '0'), name: name.trim(), prompt: prompt.join('\t').trim() }
  })
}

const removed = new Set(['05', '20', '21', '22', '23', '36'])
const featured = ['01', '24', '26', '08', '02']
const shortLabels = new Map(Array.from(source.matchAll(/'([0-9]{2})': \{ ru: '([^']+)'/g), (match) => [match[1], match[2]]))

const styles = rows('imageToImageTransformRows')
  .filter((item) => !removed.has(item.number))
  .sort((left, right) => {
    const leftRank = featured.indexOf(left.number)
    const rightRank = featured.indexOf(right.number)
    return (leftRank < 0 ? Number.MAX_SAFE_INTEGER : leftRank) - (rightRank < 0 ? Number.MAX_SAFE_INTEGER : rightRank)
  })
  .map((item) => ({
    id: `i2i-transform-${item.number}`,
    name: item.name,
    shortName: shortLabels.get(item.number) || item.name.split(/[\s/]+/)[0],
    stylePrompt: item.prompt,
    transformPrompt: `Преобразуй исходное изображение в выбранное визуальное направление. Сохрани главный объект, силуэт, читаемую композицию и важные детали исходника. Не добавляй читаемый текст, логотипы и водяные знаки. ${item.prompt}`,
    preview: `/preset-previews/i2i/female/i2i-transform-${item.number}.webp`,
  }))

const templates = rows('textToImageTemplateRows').map((item) => ({
  id: `t2i-template-${item.number}`,
  name: item.name,
  prompt: item.prompt,
}))

const banner = '// Generated from src/stylePresets.ts by scripts/sync-phone-image-presets.mjs.\n'
const body = `${banner}window.__IZO_PHONE_IMAGE_PRESETS__ = ${JSON.stringify({ styles, templates }, null, 2)}\n`
await writeFile(outputPath, body, 'utf8')
console.log(`Synced ${styles.length} styles and ${templates.length} templates to ${outputPath}`)
