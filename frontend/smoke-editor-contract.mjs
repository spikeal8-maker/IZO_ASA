import { readFileSync } from 'node:fs'

const studio = readFileSync(new URL('./src/newUi.tsx', import.meta.url), 'utf8')
const topBar = readFileSync(new URL('./src/TopBarV3.tsx', import.meta.url), 'utf8')
const css = readFileSync(new URL('./src/newStudioV3.css', import.meta.url), 'utf8')
const failures = []
const ok = (condition, message) => { if (!condition) failures.push(message) }

ok(studio.includes('const DEFAULT_FACE_STRENGTH = 75'), 'face reference default must remain 75%')
ok(studio.includes('<span>Что взять из картинки</span>'), 'face reference must keep the role label')
ok(studio.includes('className="editor-face-range"'), 'face reference range is missing')
ok(studio.includes('className="editor-face-value"'), 'separate face percentage button is missing')
ok(studio.includes('{editFaceStrengthPct}%'), 'face percentage button must show the percent sign')
ok(studio.includes('onClick={() => setEditFaceStrength(DEFAULT_FACE_STRENGTH)}'), 'percentage button must reset to 75%')
ok(!css.includes('.editor-role-controls:has(.editor-face-strength)'), 'face role must not remove the shared control panel')
ok(!css.includes('.editor-face-thumb-value'), 'obsolete moving percentage thumb CSS must be removed')
ok(/\.editor-face-strength\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) 34px/s.test(css), 'face range and percentage must use stable columns')
ok(/\.editor-face-value\s*\{[^}]*position:\s*static/s.test(css), 'face percentage must not follow the range thumb')
ok(/\.editor-face-range\s*\{[^}]*min-height:\s*0/s.test(css), 'face range must reset the global input minimum height')
ok(/\.editor-face-range\s*\{[^}]*border:\s*0/s.test(css), 'face range must not inherit the global input border')
ok(/\.editor-face-range\s*\{[^}]*box-shadow:\s*none/s.test(css), 'face range must not inherit form-field shadow')
ok(!topBar.includes("{ id: 'face'"), 'standalone Face tab must not return to the top navigation')
ok(!studio.includes("| 'face' |"), 'standalone Face studio mode must not return')
ok(!studio.includes("? 'faceswap'"), 'standalone Face generation route must not return')
ok(studio.includes("if (h === '#face' || h === '#face-to-image') return { view: 'tabs', tab: 'edit' }"), 'old Face links must redirect to Assembly')

if (failures.length) {
  console.error('smoke-editor-contract FAILED:')
  failures.forEach((failure) => console.error(` - ${failure}`))
  process.exit(1)
}

console.log('smoke-editor-contract OK')
