import assert from 'node:assert/strict'

import { I2I_STYLES, styleShortLabel } from './src/stylePresets.ts'

const firstFiveLabels = I2I_STYLES
  .slice(0, 5)
  .map((style) => styleShortLabel(style, 'ru'))

assert.deepEqual(
  firstFiveLabels,
  ['Фото', 'Аниме', 'Комикс', 'Неон', 'Премиум'],
  'первые пять стилей после «Нет» должны быть приоритетными',
)

const removedIds = [
  'i2i-transform-05',
  'i2i-transform-20',
  'i2i-transform-21',
  'i2i-transform-22',
  'i2i-transform-23',
  'i2i-transform-36',
]

for (const id of removedIds) {
  assert.equal(
    I2I_STYLES.some((style) => style.id === id),
    false,
    `удалённый стиль ${id} не должен отображаться или выбираться случайно`,
  )
}

assert.equal(I2I_STYLES.length, 30, 'после удаления должно остаться 30 стилей')

console.log('STYLE_PRESETS_OK first=Фото,Аниме,Комикс,Неон,Премиум total=30')
