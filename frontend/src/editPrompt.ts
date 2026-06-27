// Prompt Composer for the Edit mode.
// Pure, framework-free module so it can be unit-tested with `node editPrompt.test.ts`.
// It only ASSEMBLES the final text prompt — the generation pipeline (inputImages,
// ReferenceLatent chain, denoise) is untouched.

export const EDIT_SLOT_COUNT = 4
export const DEFAULT_EDIT_STRENGTH = 0.4

export type EditReferenceRole =
  | 'face'
  | 'clothing'
  | 'style'
  | 'object'
  | 'pose'
  | 'background'
  | 'color_material'
  | 'other'

export type EditSlot = { image?: string; role: EditReferenceRole | ''; takeNote: string }

export const EDIT_REFERENCE_ROLES: EditReferenceRole[] = ['face', 'clothing', 'style', 'object', 'pose', 'background', 'color_material', 'other']

export const EDIT_REFERENCE_ROLE_LABELS: Record<EditReferenceRole, string> = {
  face: 'Лицо',
  clothing: 'Одежда',
  style: 'Стиль',
  object: 'Объект',
  pose: 'Поза',
  background: 'Фон',
  color_material: 'Цвет/материал',
  other: 'Другое',
}

export type EditRoleRule = {
  // Word used in "Image N is used ONLY as a <word> reference."
  word: string
  take: string
  doNotTake: string
  preserve: string
  defaultTask: (n: number) => string
  critical?: boolean
}

// Central semantics map. Strong take / do-not-take / preserve per role — this is what
// makes a "Pose" reference actually transfer only the pose (and not clothing/face/etc.).
export const EDIT_ROLE_PROMPT_RULES: Record<EditReferenceRole, EditRoleRule> = {
  face: {
    word: 'face',
    take: 'facial identity, facial structure, expression if requested and key facial features',
    doNotTake: 'clothing, body pose, background, lighting, color grading and hairstyle unless explicitly requested',
    preserve: 'body, clothing, pose, background, lighting and composition from image 1',
    defaultTask: (n) => `Use the face identity from image ${n} for the main character in image 1.`,
  },
  clothing: {
    word: 'clothing',
    take: 'garment type, cut, fabric, color, fit and clothing details',
    doNotTake: 'face, hair, identity, body pose, background, room and camera angle',
    preserve: 'face, body, pose, background, lighting and composition from image 1',
    defaultTask: (n) => `Dress the character in image 1 with the clothing from image ${n}.`,
  },
  style: {
    word: 'visual style',
    take: 'visual style, color grading, lighting mood, rendering style and artistic atmosphere',
    doNotTake: 'objects, people, face identity, clothing, pose and background layout',
    preserve: 'the main subject, composition, identity and scene structure from image 1',
    defaultTask: (n) => `Apply the visual style of image ${n} to image 1 while preserving the content and composition.`,
  },
  object: {
    word: 'object',
    take: 'the selected object, its shape, material, color and design',
    doNotTake: 'people, face, pose, full background and unrelated objects',
    preserve: 'the scene, lighting, perspective and main subject from image 1',
    defaultTask: (n) => `Add or replace the relevant object in image 1 using the object from image ${n}.`,
  },
  pose: {
    word: 'pose',
    take: 'body pose, limb placement, hand position, leg position, head tilt, body orientation, standing/sitting posture and overall silhouette',
    doNotTake: 'clothing, face, hair, identity, age, colors, background, room, lighting style and visual style',
    preserve: 'identity, face, clothing, background, lighting, camera angle, body proportions and style from image 1',
    defaultTask: (n) => `Apply only the pose from image ${n} to the character in image 1.`,
    critical: true,
  },
  background: {
    word: 'background',
    take: 'environment, location, background layout, atmosphere and time of day if relevant',
    doNotTake: 'people, clothing, face, pose and the foreground subject',
    preserve: 'the main character or object from image 1, with realistic integration, scale and perspective',
    defaultTask: (n) => `Replace or adapt the background of image 1 using the environment from image ${n}.`,
  },
  color_material: {
    word: 'color and material',
    take: 'color palette, material, texture, surface finish and fabric/metal/wood qualities',
    doNotTake: 'object shape, face, pose, background and identity',
    preserve: 'composition, objects, pose, identity and scene from image 1',
    defaultTask: (n) => `Apply the color and material qualities from image ${n} to the relevant part of image 1.`,
  },
  other: {
    word: 'specific-detail',
    take: 'only the details explicitly described by the user',
    doNotTake: 'anything not explicitly requested',
    preserve: 'as much as possible from image 1',
    defaultTask: (n) => `Use image ${n} only according to the user's written instruction.`,
  },
}

const BASE_INSTRUCTION = 'Image 1 is the base image to edit. Preserve the main subject, identity, composition, camera angle, lighting, background and overall realism unless a reference role explicitly changes one of these elements.'

const CONFLICT_RULES = [
  'Conflict resolution:',
  '- Image 1 is always the source of the main composition unless the user explicitly says otherwise.',
  '- Identity comes from image 1 unless a reference has role face.',
  '- Clothing comes from image 1 unless a reference has role clothing.',
  '- Pose comes from image 1 unless a reference has role pose.',
  '- Background comes from image 1 unless a reference has role background.',
  '- Style comes from image 1 unless a reference has role style.',
  "- If several references conflict, obey each reference's assigned role, not its overall appearance.",
].join('\n')

const FINAL_RULES = 'Final rules:\nProduce one coherent edited version of image 1. Do not create a collage. Do not place reference images next to the base image. Use each reference only according to its assigned role. If references conflict, preserve image 1 as the source of identity, composition and scene continuity. Do not add readable text, logos or watermarks unless the user explicitly asks.'

export type ComposedPrompt = { prompt: string; hasTask: boolean }

// Builds the structured prompt from base + per-reference role rules + assembled task
// + conflict rules + user note + final rules. Only filled, role-assigned refs are mentioned.
export function buildEditComposedPrompt(params: { slots: EditSlot[]; userNote: string }): ComposedPrompt {
  const userNote = (params.userNote || '').trim()
  const refs = params.slots
    .map((slot, i) => ({ slot, n: i + 1 }))
    .filter((x) => x.n >= 2 && x.slot.image && x.slot.role)

  const blocks: string[] = [BASE_INSTRUCTION]

  for (const { slot, n } of refs) {
    const rule = EDIT_ROLE_PROMPT_RULES[slot.role as EditReferenceRole]
    const note = (slot.takeNote || '').trim()
    const lines = [
      `Image ${n} is used ONLY as a ${rule.word} reference.`,
      `Take from image ${n}: ${rule.take}.`,
    ]
    if (note) lines.push(`Take specifically from image ${n}: ${note}.`)
    lines.push(`Do NOT take from image ${n}: ${rule.doNotTake}.`)
    lines.push(`Preserve from image 1: ${rule.preserve}.`)
    blocks.push(lines.join('\n'))
  }

  const taskSentences = refs.map(({ slot, n }) => {
    const rule = EDIT_ROLE_PROMPT_RULES[slot.role as EditReferenceRole]
    const note = (slot.takeNote || '').trim()
    const base = rule.defaultTask(n)
    return note ? `${base} Use specifically: ${note}.` : base
  })
  if (taskSentences.length) blocks.push('Task:\n' + taskSentences.join(' '))

  if (refs.length) blocks.push(CONFLICT_RULES)
  if (userNote) blocks.push('Additional user instruction:\n' + userNote)
  blocks.push(FINAL_RULES)

  return { prompt: blocks.join('\n\n'), hasTask: taskSentences.length > 0 || userNote.length > 0 }
}

export type EditComposerStatus = { blockReason: string | null; finalPrompt: string; composedPrompt: string }

// Single source of truth for Generate gating + the prompt that will be sent.
export function editComposerStatus(params: { slots: EditSlot[]; userNote: string; manualMode: boolean; manualPrompt: string }): EditComposerStatus {
  const { slots, userNote, manualMode, manualPrompt } = params
  const composed = buildEditComposedPrompt({ slots, userNote })

  if (!slots[0]?.image) return { blockReason: 'Загрузите основу для редактирования.', finalPrompt: '', composedPrompt: composed.prompt }
  for (let i = 1; i < slots.length; i++) {
    const s = slots[i]
    if (s.image && !s.role) return { blockReason: `Выберите роль для референса ${i}.`, finalPrompt: '', composedPrompt: composed.prompt }
    if (s.image && s.role === 'other' && !s.takeNote.trim()) return { blockReason: `Уточните, что взять из референса ${i}.`, finalPrompt: '', composedPrompt: composed.prompt }
  }
  if (manualMode) {
    if (!manualPrompt.trim()) return { blockReason: 'Введите инструкцию для генерации.', finalPrompt: '', composedPrompt: composed.prompt }
    return { blockReason: null, finalPrompt: manualPrompt, composedPrompt: composed.prompt }
  }
  if (!composed.hasTask) return { blockReason: 'Напишите пожелание или выберите роль референса.', finalPrompt: '', composedPrompt: composed.prompt }
  return { blockReason: null, finalPrompt: composed.prompt, composedPrompt: composed.prompt }
}

export type EditTemplate = { id: string; title: string; assign: Array<{ refIndex: number; role: EditReferenceRole }>; userNote: string }

// Templates are role configurations + a user note, NOT plain text.
export const EDIT_TEMPLATES: EditTemplate[] = [
  { id: 'pose', title: 'Поза из референса', assign: [{ refIndex: 1, role: 'pose' }], userNote: 'Поставь персонажа из изображения 1 в позу из изображения 2.' },
  { id: 'clothing', title: 'Надеть одежду', assign: [{ refIndex: 1, role: 'clothing' }], userNote: 'Надень одежду из изображения 2 на персонажа из изображения 1.' },
  { id: 'background', title: 'Фон из референса', assign: [{ refIndex: 1, role: 'background' }], userNote: 'Перемести персонажа из изображения 1 в окружение изображения 2.' },
  { id: 'face', title: 'Лицо из референса', assign: [{ refIndex: 1, role: 'face' }], userNote: 'Перенеси лицо из изображения 2 на персонажа из изображения 1.' },
  { id: 'style', title: 'Стиль из референса', assign: [{ refIndex: 1, role: 'style' }], userNote: 'Примени визуальный стиль изображения 2 к изображению 1.' },
  { id: 'clothing_pose', title: 'Одежда + поза', assign: [{ refIndex: 1, role: 'clothing' }, { refIndex: 2, role: 'pose' }], userNote: 'Используй одежду из изображения 2 и позу из изображения 3.' },
]
