import type { PhoneChatTool } from './api.ts'


export function cleanAssistantText(value: string, tools: PhoneChatTool[]) {
  const text = String(value || '').trim()
  if (!tools.some((tool) => tool.name === 'generate_image')) return text
  if (/^\s*\{[\s\S]*(?:generate_image|action_input|aspect_ratio)[\s\S]*\}\s*$/i.test(text)) return ''
  return text
}
