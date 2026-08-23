import assert from 'node:assert/strict'
import { imageTokenVisualKind, tokenVisualClass, tokenVisualLabel, videoTokenVisualKind } from './src/tokenVisual.ts'

assert.equal(imageTokenVisualKind({ id: 'server:local_flux_klein', provider: 'comfyui' }), 'daily')
assert.equal(imageTokenVisualKind({ id: 'openai/gpt-image-1', provider: 'openrouter' }), 'main')
assert.equal(videoTokenVisualKind({ id: 'local/ltx-2.3-fast-q3', provider: 'local_ltx' }), 'daily')
assert.equal(videoTokenVisualKind({ id: 'openai/sora-2', provider: 'openrouter' }), 'main')
assert.equal(tokenVisualClass('daily'), 'token-cost token-cost--daily')
assert.equal(tokenVisualLabel('main'), 'Основные токены')

console.log('token visual tests passed')
