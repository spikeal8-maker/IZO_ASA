import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

function argument(name, fallback) {
  const index = process.argv.indexOf(name)
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.resolve(argument('--dist', path.join(repoRoot, 'frontend', 'dist')))
const expected = argument(
  '--expected',
  process.env.FRONTEND_BUILD_LABEL || process.env.GITHUB_SHA || '',
).trim()
if (!expected) throw new Error('expected frontend release id is required')
if (/^(dev|unknown)$/i.test(expected)) {
  throw new Error(`unsafe frontend release id is forbidden: ${expected}`)
}

const indexHtml = await readFile(path.join(dist, 'index.html'), 'utf8')
const escapedName = 'izo-release'.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const marker = new RegExp(`<meta\\s+[^>]*name=["']${escapedName}["'][^>]*content=["']([^"']+)["'][^>]*>`, 'i').exec(indexHtml)
  || new RegExp(`<meta\\s+[^>]*content=["']([^"']+)["'][^>]*name=["']${escapedName}["'][^>]*>`, 'i').exec(indexHtml)
if (!marker) throw new Error('frontend release meta marker is missing')
if (marker[1] !== expected) throw new Error(`frontend release meta mismatch: expected ${expected}, got ${marker[1]}`)

const assetsDirectory = path.join(dist, 'assets')
const assetNames = await readdir(assetsDirectory)
const javascriptAssets = assetNames.filter((name) => name.endsWith('.js'))
let embedded = false
for (const name of javascriptAssets) {
  const source = await readFile(path.join(assetsDirectory, name), 'utf8')
  if (source.includes(expected)) {
    embedded = true
    break
  }
}
if (!embedded) throw new Error('frontend release id is not embedded in JavaScript assets')

console.log(`FRONTEND_RELEASE_IDENTITY_OK release=${expected} jsAssets=${javascriptAssets.length}`)
