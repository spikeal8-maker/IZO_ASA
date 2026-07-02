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
export const EDIT_SELECTABLE_REFERENCE_ROLES: EditReferenceRole[] = ['face', 'clothing', 'style', 'object', 'background', 'other']
export const EDIT_DISABLED_REFERENCE_ROLES: EditReferenceRole[] = ['pose']

export const EDIT_REFERENCE_ROLE_LABELS: Record<EditReferenceRole, string> = {
  face: 'Лицо',
  clothing: 'Одежда',
  style: 'Стиль / цвет',
  object: 'Предмет',
  pose: 'Поза',
  background: 'Фон',
  color_material: 'Цвет/материал',
  other: 'Другое',
}

// ── Modular Prompt Composer ────────────────────────────────────────────────
// finalPrompt = GLOBAL BASE LOCK + one independent role-block per filled reference
// (Reference 1 in UI = Image 2 in prompt, etc.) + optional user-note block.
// Each role-block hard-limits what may be taken from its image and what must be
// preserved from Image 1, so roles sum without bleeding into each other.

export const GLOBAL_BASE_LOCK = [
  'Edit Image 1. Image 1 is the primary source image.',
  '',
  'Preserve the main subject, identity, face, body proportions, original realism, and the overall scene from Image 1, except for the specific attributes explicitly assigned to reference images below.',
  '',
  'Each reference image has a limited role. Use every reference image only for its declared role. Do not copy unrelated identity, face, clothing, pose, background, colors, objects, or style from a reference image unless that exact attribute is assigned to that reference role.',
  '',
  'If role instructions conflict, follow this priority:',
  'Face identity > Pose > Clothing > Object > Background > Style > Color/Material > optional user note.',
  '',
  'The final image must look like one coherent edited photo, not a collage, not a blend of different people, and not a split-screen.',
].join('\n')

// Per-role fixed English block. `n` = image index in the prompt (2..4).
// `custom` = user instruction (only used / required for the OTHER role).
const ROLE_BLOCKS: Record<EditReferenceRole, (n: number, custom: string) => string> = {
  face: (n) => `Reference Image ${n} role: FACE.

Use Image ${n} only as a facial identity reference.
Transfer only the facial identity, facial structure, facial features, expression character, eyes, nose, mouth, jawline, and recognizable face likeness.

Do not transfer clothing, body shape, pose, hands, hair color, hairstyle, background, lighting setup, room, objects, camera angle, or visual style from Image ${n}.

Apply the face naturally to the main subject from Image 1.
Preserve the body, clothing, pose, background, and scene from Image 1 unless another reference role explicitly changes them.`,

  clothing: (n) => `Reference Image ${n} role: CLOTHING.

Use Image ${n} only as a clothing reference.
Transfer only the garment type, cut, silhouette, fabric, texture, color, fit, seams, accessories attached to the outfit, and visible clothing details.

Do not transfer the face, identity, hair, skin, body proportions, pose, hands, background, room, lighting, camera angle, or visual style from Image ${n}.

Dress the main subject from Image 1 in this clothing while preserving the subject's identity, face, body proportions, and the current scene.
The clothing must fit naturally on the body and pose of the final subject.`,

  style: (n) => `Reference Image ${n} role: STYLE.

Use Image ${n} only as a visual style reference.
Transfer only the aesthetic treatment: color grading, contrast, lighting mood, rendering style, lens feeling, photographic tone, artistic finish, and overall atmosphere.

Do not transfer any person, face, identity, clothing, pose, body shape, object, background layout, room structure, or composition from Image ${n}.

Keep the subject and content from Image 1. Apply only the visual treatment of Image ${n}.`,

  object: (n) => `Reference Image ${n} role: OBJECT.

Use Image ${n} only as a reference for the main visible object.
Transfer only the selected object's shape, design, material, color, texture, proportions, and important details.

Do not transfer people, faces, bodies, clothing, pose, background, room, lighting style, camera angle, or unrelated objects from Image ${n}.

Place or integrate the object naturally into the scene from Image 1.
The object must look physically present in the final image, with matching perspective, scale, shadows, and lighting.

If Image ${n} contains a person holding or wearing the object, ignore the person completely and use only the object.`,

  pose: (n) => `Reference Image ${n} role: POSE.

Use Image ${n} only as a pose reference.
Transfer only the body position, limb angles, hand placement, head tilt, posture, weight distribution, gesture, and overall silhouette.

Do not transfer the face, identity, gender, hair, clothing, skin details, colors, background, room, lighting, camera style, or visual style from Image ${n}.

The final subject must remain the person from Image 1.
Preserve the face, identity, clothing, body proportions, background, and scene from Image 1 unless another reference role explicitly changes one of those attributes.

Use the pose as structural guidance only, not as an appearance reference.`,

  background: (n) => `Reference Image ${n} role: BACKGROUND.

Use Image ${n} only as a background and environment reference.
Transfer only the location, room type, architecture, background layout, environmental atmosphere, depth, and lighting mood.

Do not transfer any people, faces, bodies, skin, hair, clothing, creatures, foreground subjects, objects held by people, or identity from Image ${n}.

Keep the main subject from Image 1.
Place the subject from Image 1 naturally into the environment inspired by Image ${n}, with consistent perspective, shadows, and lighting.`,

  color_material: (n) => `Reference Image ${n} role: COLOR/MATERIAL.

Use Image ${n} only as a color, material, and surface reference.
Transfer only the color palette, material quality, texture, reflectivity, roughness, finish, surface pattern, and tactile feeling.

Do not transfer object shape, face, identity, body, pose, clothing design, background layout, room, camera angle, or composition from Image ${n}.

Apply the color or material treatment only to the relevant subject, clothing, object, or surface in Image 1.
Preserve the structure and identity of the original content.`,

  other: (n, custom) => `Reference Image ${n} role: CUSTOM.

Use Image ${n} only according to the user's custom instruction:
"${custom}"

Do not transfer anything from Image ${n} that is not explicitly requested in the custom instruction.

Preserve all other important attributes from Image 1.`,
}

// Optional refinement appended to a standard role block when the user added a note
// in Advanced for that reference. Never widens the role, only narrows the focus.
function roleBlock(n: number, role: EditReferenceRole, custom: string): string {
  const block = ROLE_BLOCKS[role](n, custom)
  if (role !== 'other' && custom) return `${block}\nFocus specifically on this from Image ${n}: ${custom}.`
  return block
}

function userNoteBlock(note: string): string {
  return `Additional user request:\n"${note}"\n\nApply this request only if it does not conflict with the reference roles above.\nDo not use the user note to override identity preservation or role boundaries unless the user explicitly asks for it.`
}

export type ComposedPrompt = { prompt: string; hasTask: boolean }

// GLOBAL BASE LOCK + independent role-block per filled reference + optional user note.
// Empty refs and refs without a role are skipped entirely.
export function buildEditComposedPrompt(params: { slots: EditSlot[]; userNote: string }): ComposedPrompt {
  const userNote = (params.userNote || '').trim()
  const refs = params.slots
    .map((slot, i) => ({ slot, n: i + 1 }))
    .filter((x) => x.n >= 2 && x.slot.image && x.slot.role)

  const blocks: string[] = [GLOBAL_BASE_LOCK]
  for (const { slot, n } of refs) {
    blocks.push(roleBlock(n, slot.role as EditReferenceRole, (slot.takeNote || '').trim()))
  }
  if (userNote) blocks.push(userNoteBlock(userNote))

  return { prompt: blocks.join('\n\n'), hasTask: refs.length > 0 || userNote.length > 0 }
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
    if (s.image && s.role === 'pose') return { blockReason: 'Смена позы временно отключена: workflow нестабилен и может долго занимать видеокарту.', finalPrompt: '', composedPrompt: composed.prompt }
    if (s.image && s.role === 'other' && !s.takeNote.trim()) return { blockReason: `Уточните, что именно взять из референса ${i}.`, finalPrompt: '', composedPrompt: composed.prompt }
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
  { id: 'clothing', title: 'Одежда на персонажа', assign: [{ refIndex: 1, role: 'clothing' }], userNote: 'Надень одежду из изображения 2 на персонажа из изображения 1.' },
  { id: 'background', title: 'Фон из референса', assign: [{ refIndex: 1, role: 'background' }], userNote: 'Перемести персонажа из изображения 1 в окружение изображения 2.' },
  { id: 'face_style', title: 'Лицо + стиль', assign: [{ refIndex: 1, role: 'face' }, { refIndex: 2, role: 'style' }], userNote: 'Используй лицо из изображения 2 и визуальный стиль из изображения 3.' },
  { id: 'style_color', title: 'Стиль и цвет', assign: [{ refIndex: 1, role: 'style' }], userNote: 'Возьми визуальный стиль, цветовую палитру, свет и материал из изображения 2, не перенося композицию и объекты.' },
  { id: 'object_style', title: 'Предмет + стиль', assign: [{ refIndex: 1, role: 'object' }, { refIndex: 2, role: 'style' }], userNote: 'Добавь предмет из изображения 2 и выдержи общий стиль/цвет из изображения 3.' },
]
