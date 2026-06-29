// Run: node editPrompt.test.ts   (Node >= 22.18 / 24 strips TS types natively)
import assert from 'node:assert'
import { buildEditComposedPrompt, editComposerStatus, GLOBAL_BASE_LOCK, type EditSlot } from './src/editPrompt.ts'

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

// Every composed prompt starts with the GLOBAL BASE LOCK.
test('global base lock + priority always present', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'd', role: 'pose', takeNote: '' }), userNote: '' })
  assert.ok(prompt.startsWith('Edit Image 1. Image 1 is the primary source image.'))
  assert.match(prompt, /Face identity > Pose > Clothing > Object > Background > Style > Color\/Material/)
  assert.ok(GLOBAL_BASE_LOCK.length > 0)
})

// Scenario A: POSE must NOT transfer face/gender/hair/clothing/background.
test('pose: do-not-transfer face/gender/hair/clothing/background; preserve them from Image 1', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'p', role: 'pose', takeNote: '' }), userNote: '' })
  assert.match(prompt, /Reference Image 2 role: POSE\./)
  assert.match(prompt, /Do not transfer the face, identity, gender, hair, clothing,[^]*from Image 2\./)
  assert.match(prompt, /The final subject must remain the person from Image 1\./)
  assert.match(prompt, /Preserve the face, identity, clothing, body proportions, background, and scene from Image 1/)
  assert.match(prompt, /Use the pose as structural guidance only, not as an appearance reference\./)
})

// Scenario B: BACKGROUND must not transfer the person/face/clothing.
test('background: transfer environment only; not people/face/clothing', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'b', role: 'background', takeNote: '' }), userNote: '' })
  assert.match(prompt, /Reference Image 2 role: BACKGROUND\./)
  assert.match(prompt, /Do not transfer any people, faces, bodies, skin, hair, clothing,[^]*from Image 2\./)
  assert.match(prompt, /Keep the main subject from Image 1\./)
})

// Clothing forbids face/identity/hair/pose/background.
test('clothing: do-not-transfer face/identity/hair/pose/background', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'c', role: 'clothing', takeNote: '' }), userNote: '' })
  assert.match(prompt, /Reference Image 2 role: CLOTHING\./)
  assert.match(prompt, /Do not transfer the face, identity, hair, skin, body proportions, pose,[^]*from Image 2\./)
})

// Scenario D: three references → three separate role blocks in order, then user note last.
test('three references: separate ordered role blocks + user note at the end', () => {
  const { prompt } = buildEditComposedPrompt({
    slots: slots(
      { image: 'p', role: 'pose', takeNote: '' },
      { image: 'c', role: 'clothing', takeNote: '' },
      { image: 'b', role: 'background', takeNote: '' },
    ),
    userNote: 'make it cinematic',
  })
  const iPose = prompt.indexOf('Reference Image 2 role: POSE.')
  const iCloth = prompt.indexOf('Reference Image 3 role: CLOTHING.')
  const iBg = prompt.indexOf('Reference Image 4 role: BACKGROUND.')
  const iNote = prompt.indexOf('Additional user request:')
  assert.ok(iPose > 0 && iCloth > iPose && iBg > iCloth, 'role blocks must be in slot order 2,3,4')
  assert.ok(iNote > iBg, 'user note must come last')
  assert.match(prompt, /"make it cinematic"/)
})

// Index mapping: Reference 1 (UI) = Image 2, Reference 3 (UI) = Image 4.
test('UI reference index maps to prompt Image index (slot1->2, slot3->4)', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots(empty, empty, { image: 'f', role: 'face', takeNote: '' }), userNote: '' })
  assert.match(prompt, /Reference Image 4 role: FACE\./)
  assert.ok(!/Reference Image 2/.test(prompt) && !/Reference Image 3/.test(prompt))
})

// Scenario C: OTHER without custom instruction blocks generation.
test('other without custom instruction blocks generation', () => {
  const st = editComposerStatus({ slots: slots({ image: 'o', role: 'other', takeNote: '' }), userNote: '', manualMode: false, manualPrompt: '' })
  assert.ok(st.blockReason && /уточните/i.test(st.blockReason))
  assert.equal(st.finalPrompt, '')
})

// OTHER with custom instruction embeds it into the CUSTOM block.
test('other with custom instruction embeds it', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'o', role: 'other', takeNote: 'take only the necklace' }), userNote: '' })
  assert.match(prompt, /Reference Image 2 role: CUSTOM\./)
  assert.match(prompt, /"take only the necklace"/)
})

// Standard-role advanced note narrows focus, not the role.
test('advanced note on a standard role adds a focus line', () => {
  const { prompt } = buildEditComposedPrompt({ slots: slots({ image: 'p', role: 'pose', takeNote: 'sitting, hands on knees' }), userNote: '' })
  assert.match(prompt, /Focus specifically on this from Image 2: sitting, hands on knees\./)
})

// manual mode sends the manual prompt unchanged.
test('manual mode sends manual prompt unchanged', () => {
  const st = editComposerStatus({ slots: slots(), userNote: 'auto note', manualMode: true, manualPrompt: 'MY MANUAL PROMPT' })
  assert.equal(st.blockReason, null)
  assert.equal(st.finalPrompt, 'MY MANUAL PROMPT')
})

// missing base blocks.
test('missing base blocks', () => {
  const st = editComposerStatus({ slots: [empty, empty, empty, empty], userNote: 'x', manualMode: false, manualPrompt: '' })
  assert.ok(st.blockReason && /основу/.test(st.blockReason))
})

// ref without role blocks.
test('ref without role blocks', () => {
  const st = editComposerStatus({ slots: slots({ image: 'd', role: '', takeNote: '' }), userNote: '', manualMode: false, manualPrompt: '' })
  assert.ok(st.blockReason && /роль/.test(st.blockReason))
})

console.log(`\n${passed} editPrompt tests passed`)
