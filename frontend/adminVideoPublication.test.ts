import assert from 'node:assert/strict'
import test from 'node:test'
import { setVideoPublication } from './src/adminVideoPublication.ts'

test('unpublishing a video model removes operation and tariff access', () => {
  const next = setVideoPublication({
    published: ['vendor/a', 'vendor/b'],
    enabled: { text_to_video: ['vendor/a', 'vendor/b'], image_to_video: ['vendor/a'] },
    access: {
      text_to_video: { mini: ['vendor/a'], pro: ['vendor/a', 'vendor/b'] },
      image_to_video: { max: ['vendor/a'] },
    },
  }, ['vendor/a'], false)
  assert.deepEqual(next, {
    published: ['vendor/b'],
    enabled: { text_to_video: ['vendor/b'] },
    access: { text_to_video: { pro: ['vendor/b'] } },
  })
})

test('publishing only exposes the model globally without granting operations', () => {
  const next = setVideoPublication({}, ['vendor/a'], true)
  assert.deepEqual(next, { published: ['vendor/a'], enabled: {}, access: {} })
})
