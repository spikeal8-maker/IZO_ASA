// Run: node src/editPrompt.test.ts   (Node >= 22.18 / 24 strips TS types natively)
import assert from 'node:assert'
import { buildEditComposedPrompt, editComposerStatus, type EditSlot } from './src/editPrompt.ts'

const base: EditSlot = { image: 'data:base', role: '', takeNote: '' }
const empty: EditSlot = { image: undefined, role: '', takeNote: '' }
function slots(...refs: EditSlot[]): EditSlot[] {
  const arr = [base, empty, empty, empty]
  refs.forEach((r, i) => { arr[i + 1] = r })
  return arr
}

let passed = 0
function test(name: string, fn: () => void) {
  fn(); passed++; console.log('  ok -', name)
}

// 1. pose role forbids copying clothing/face/background and preserves them from image 1
test('pose role: do-not-take clothing/face/background; preserve from image 1', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'data:p', role: 'pose', takeNote: '' }), userNote: '' })
  assert.match(prompt, /Image 2 is used ONLY as a pose reference\./)
  assert.match(prompt, /Do NOT take from image 2:.*clothing.*face.*background/i)
  assert.match(prompt, /Preserve from image 1:.*clothing.*background/i)
  assert.match(prompt, /Apply only the pose from image 2/)
})

// 2. clothing role forbids face/pose/background
test('clothing role: do-not-take face/pose/background', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'data:c', role: 'clothing', takeNote: '' }), userNote: '' })
  assert.match(prompt, /Image 2 is used ONLY as a clothing reference\./)
  assert.match(prompt, /Do NOT take from image 2:.*face.*body pose.*background/i)
})

// 3. multiple refs generate separate instructions
test('multiple refs: separate per-image instructions', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'd2', role: 'pose', takeNote: '' }, { image: 'd3', role: 'clothing', takeNote: '' }), userNote: '' })
  assert.match(prompt, /Image 2 is used ONLY as a pose reference/)
  assert.match(prompt, /Image 3 is used ONLY as a clothing reference/)
  assert.match(prompt, /Apply only the pose from image 2.*Dress the character in image 1 with the clothing from image 3/s)
})

// 4. empty userNote still creates a task from roles
test('empty userNote still produces a task', () => {
  const res = buildEditComposedPrompt({ slots: slots({ image: 'd', role: 'background', takeNote: '' }), userNote: '' })
  assert.equal(res.hasTask, true)
  assert.match(res.prompt, /Task:/)
  assert.match(res.prompt, /Replace or adapt the background of image 1/)
})

// 5. role=other without takeNote blocks generation
test('other role without takeNote blocks generation', () => {
  const st = editComposerStatus({ slots: slots({ image: 'd', role: 'other', takeNote: '' }), userNote: '', manualMode: false, manualPrompt: '' })
  assert.ok(st.blockReason && /Уточните/.test(st.blockReason))
  assert.equal(st.finalPrompt, '')
})

// 6. manual mode sends the manual prompt unchanged
test('manual mode sends manual prompt unchanged', () => {
  const st = editComposerStatus({ slots: slots(), userNote: 'auto note', manualMode: true, manualPrompt: 'MY MANUAL PROMPT' })
  assert.equal(st.blockReason, null)
  assert.equal(st.finalPrompt, 'MY MANUAL PROMPT')
})

// extra: takeNote is injected as "Take specifically"
test('takeNote injected as Take specifically', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'd', role: 'pose', takeNote: 'сидячая поза, положение рук' }), userNote: '' })
  assert.match(prompt, /Take specifically from image 2: сидячая поза, положение рук\./)
})

// extra: missing base blocks
test('missing base blocks', () => {
  const st = editComposerStatus({ slots: [empty, empty, empty, empty], userNote: 'x', manualMode: false, manualPrompt: '' })
  assert.ok(st.blockReason && /основу/.test(st.blockReason))
})

// extra: ref without role blocks
test('ref without role blocks', () => {
  const st = editComposerStatus({ slots: slots({ image: 'd', role: '', takeNote: '' }), userNote: '', manualMode: false, manualPrompt: '' })
  assert.ok(st.blockReason && /роль/.test(st.blockReason))
})

console.log(`\n${passed} editPrompt tests passed`)
