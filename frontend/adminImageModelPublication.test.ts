import assert from 'node:assert/strict'
import { setImageModelPublished } from './src/adminImageModelPublication.ts'

const modelId = 'provider/model'
const config = {
  published: [modelId],
  enabled: { edit: [modelId] },
  defaults: { edit: modelId },
  access: { edit: { pro: [modelId] } },
  qualityDefaults: { edit: { max: modelId } },
}

const hidden = setImageModelPublished(config, modelId, false)
assert.deepEqual(hidden.published, [])
assert.deepEqual(hidden.enabled, {})
assert.deepEqual(hidden.defaults, {})
assert.deepEqual(hidden.access, {})
assert.deepEqual(hidden.qualityDefaults, {})

const republished = setImageModelPublished(hidden, modelId, true)
assert.deepEqual(republished.published, [modelId])
assert.deepEqual(republished.enabled, {})

console.log('admin image model publication tests passed')
