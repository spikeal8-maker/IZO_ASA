import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./src/newUi.tsx', import.meta.url), 'utf8')
const failures = []
const expectSource = (pattern, message) => {
  if (!pattern.test(source)) failures.push(message)
}

expectSource(
  /const allowsExactRepeat = selectedModel\.generation\?\.allowsExactRepeat[\s\S]{0,180}!allowsExactRepeat && lastText/,
  'local duplicate protection must not block intentional OpenRouter repeats',
)
expectSource(
  /selectedModel\.generation\?\.fixedSteps[\s\S]{0,180}selectedModel\.provider === 'comfyui'[\s\S]{0,80}\? 4/,
  'local text generation must always send four steps',
)
expectSource(
  /if \(mode === 'text'\)[\s\S]{0,120}lastTextSubmittedRef\.current/,
  'last text submission must only be updated by the text tab',
)
expectSource(
  /const dockPromptText = dockImage[\s\S]{0,160}: ''/,
  'image prompt dock must stay empty without a selected image',
)

if (failures.length) {
  console.error('smoke-text-generation-contract FAILED:')
  failures.forEach((failure) => console.error(` - ${failure}`))
  process.exit(1)
}

console.log('smoke-text-generation-contract OK')
