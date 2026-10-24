/** Preprod216: protected Ollama admin routing without fake browser sessions. */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  ADMIN_MODELS_PAGES,
  adminModelsPageFromPath,
  adminModelsPath,
  adminModelsRouteDefinition,
} from './src/adminModelsRoutes.ts'

const root = fileURLToPath(new URL('.', import.meta.url))
const cases = [
  ['/admin/models/ollama', 'ollama'],
  ['/admin/models/config-ui', 'config'],
  ['/admin/models/openai', 'openai'],
  ['/admin/models/openrouter/text', 'api'],
  ['/admin/models/energy', 'energy'],
]
for (const [path, expected] of cases) {
  assert.equal(adminModelsPageFromPath(path), expected)
  assert.equal(adminModelsRouteDefinition(path).path, path)
}
assert.equal(adminModelsPath('ollama'), '/admin/models/ollama')
assert.equal(ADMIN_MODELS_PAGES.filter((entry) => entry.id === 'ollama').length, 1)

const panel = readFileSync(join(root, 'src', 'adminOllamaPage.tsx'), 'utf8')
const admin = readFileSync(join(root, 'src', 'adminModels.tsx'), 'utf8')
assert.match(panel, /disabled=\{busy \|\| !ollama\.ok \|\| !installed\}/)
assert.match(panel, /checked=\{chat\.enabled && chat\.localEnabled && ollama\.ok && installed\}/)
assert.match(panel, /disabled=\{busy \|\| !ollama\.ok \|\| !installed \|\| !testPrompt\.trim\(\)\}/)
assert.match(admin, /localEnabled: Boolean\(assistantData\.ollama\.ok && assistantData\.config\.chat\.localEnabled\)/)
assert.match(admin, /onSave=\{\(\) => void saveAssistantConfig\('ollama'\)\}/)
assert.match(admin, /onTest=\{\(\) => void testPromptAssistant\('local', assistantData\?\.config\.chat\.localModel\)\}/)
assert.match(admin, /pageTab === 'ollama' && ollamaPanel/)
assert.match(admin, /configSection === 'text' && ollamaPanel/)
assert.match(admin, /Comfy214StatusOverview/)
console.log('PREPROD216_OLLAMA_ADMIN_ROUTE_FAIL_CLOSED_PASS')
