#!/usr/bin/env node
/**
 * CTX-001: deterministic frontend map.
 *
 * Statically derives route -> entry component -> imported feature components
 * -> hooks/state -> API literals -> CSS -> tests from frontend/src sources.
 * No code is executed, no network, no production data. Output is byte-stable
 * on Windows: UTF-8, LF line endings, forward-slash paths, sorted lists.
 *
 * Usage:
 *   node tools/generate_frontend_map.mjs          # write both map files
 *   node tools/generate_frontend_map.mjs --check  # fail (exit 2) on drift
 */
import { readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'frontend', 'src')
const APP_FILE = join(SRC, 'App.tsx')
const JSON_OUT = join(ROOT, 'docs', 'generated', 'frontend-map.json')
const MD_OUT = join(ROOT, 'docs', 'generated', 'frontend-map.md')

// Tests are associated per entry module explicitly; the generator fails when
// a referenced test file disappears, so the mapping cannot rot silently.
const ENTRY_TESTS = {
  './newUi': [
    'frontend/e2e-critical-prompts.mjs',
    'frontend/e2e-critical-tools.mjs',
    'frontend/e2e-paint-workbench.mjs',
    'frontend/e2e-profile-auth.mjs',
    'frontend/e2e-responsive-layout.mjs',
    'frontend/e2e-result-layout.mjs',
    'frontend/e2e-stage1.mjs',
    'frontend/e2e-studio-resilience.mjs',
    'frontend/e2e-ui.mjs',
    'frontend/e2e-video-studio-layout.mjs',
  ],
  './AdminApp': [
    'frontend/e2e-security-admin.mjs',
    'frontend/smoke-admin-analytics.mjs',
    'frontend/visual-admin-parity.mjs',
  ],
  './LegacyApp': [],
  './PaymentResultPage': [],
  './CommercePage': [],
}

const read = (path) => readFileSync(path, 'utf8').replace(/\r\n/g, '\n')
const rel = (path) => path.slice(ROOT.length + 1).replace(/\\/g, '/')

function parseAppRoutes(appSource) {
  const lazyEntries = {}
  for (const match of appSource.matchAll(/const (\w+) = lazy\(\(\) => import\('(\.\/[\w]+)'\)\)/g)) {
    lazyEntries[match[1]] = match[2]
  }
  const predicatePaths = {}
  for (const match of appSource.matchAll(/function (is\w+Route)\(path[^)]*\) \{([\s\S]*?)\n\}/g)) {
    const literals = [...match[2].matchAll(/'(\/[^']*)'/g)].map((m) => m[1])
    predicatePaths[match[1]] = [...new Set(literals)].sort()
  }
  const routeGroups = []
  for (const match of appSource.matchAll(/(is\w+Route)\(path\)\s*\?\s*(\w+)/g)) {
    const [, predicate, component] = match
    if (!lazyEntries[component]) continue
    routeGroups.push({
      predicate,
      paths: predicatePaths[predicate] ?? [],
      component,
      entry_module: lazyEntries[component],
    })
  }
  const legacyMatch = appSource.match(/\((is\w+Route)\(path\)\s*\?\s*(\w+)\s*:\s*null\)/)
  if (legacyMatch && lazyEntries[legacyMatch[2]] && !routeGroups.some((g) => g.component === legacyMatch[2])) {
    routeGroups.push({
      predicate: legacyMatch[1],
      paths: predicatePaths[legacyMatch[1]] ?? [],
      component: legacyMatch[2],
      entry_module: lazyEntries[legacyMatch[2]],
    })
  }
  return { routeGroups, predicatePaths }
}

function resolveModule(fromDirectory, specifier) {
  const base = resolve(fromDirectory, specifier)
  for (const candidate of [base, `${base}.tsx`, `${base}.ts`, `${base}.css`]) {
    if (existsSync(candidate) && candidate.startsWith(SRC)) return candidate
  }
  return null
}

function importClosure(entryFile) {
  const queue = [entryFile]
  const visited = new Set()
  while (queue.length) {
    const file = queue.shift()
    if (visited.has(file) || file.endsWith('.css')) {
      visited.add(file)
      continue
    }
    visited.add(file)
    const source = read(file)
    const specifiers = [
      ...[...source.matchAll(/from\s+'(\.[^']+)'/g)].map((m) => m[1]),
      ...[...source.matchAll(/import\('(\.[^']+)'\)/g)].map((m) => m[1]),
      ...[...source.matchAll(/import\s+'(\.[^']+)'/g)].map((m) => m[1]),
    ]
    for (const specifier of specifiers) {
      const resolved = resolveModule(dirname(file), specifier)
      if (resolved && !visited.has(resolved)) queue.push(resolved)
    }
  }
  return [...visited].sort()
}

function analyzeEntry(entryModule) {
  const entryFile = resolveModule(SRC, entryModule)
  if (!entryFile) throw new Error(`Entry module not found: ${entryModule}`)
  const closure = importClosure(entryFile)
  const hooks = new Set()
  const api = new Set()
  const css = []
  const components = []
  for (const file of closure) {
    if (file.endsWith('.css')) {
      css.push(rel(file))
      continue
    }
    components.push(rel(file))
    const source = read(file)
    for (const match of source.matchAll(/\buse[A-Z]\w*/g)) hooks.add(match[0])
    for (const match of source.matchAll(/['"`](\/api\/[A-Za-z0-9_\-./{}$?=&]*)['"`]/g)) api.add(match[1])
    // The studio builds URLs as apiFetch('/x') and `${API}/x` with API='/api'.
    for (const match of source.matchAll(/apiFetch\(\s*['"`](\/[A-Za-z0-9_\-./]+)/g)) api.add(`/api${match[1]}`)
    for (const match of source.matchAll(/\$\{API\}(\/[A-Za-z0-9_\-./]+)/g)) api.add(`/api${match[1]}`)
  }
  return {
    entry: rel(entryFile),
    components,
    hooks: [...hooks].sort(),
    api: [...api].sort(),
    css: css.sort(),
  }
}

function buildMap() {
  const appSource = read(APP_FILE)
  const { routeGroups, predicatePaths } = parseAppRoutes(appSource)
  const routes = routeGroups.map((group) => {
    const analysis = analyzeEntry(group.entry_module)
    const tests = ENTRY_TESTS[group.entry_module] ?? []
    for (const test of tests) {
      if (!existsSync(join(ROOT, test))) throw new Error(`Mapped test file is missing: ${test}`)
    }
    return { paths: group.paths, predicate: group.predicate, ...analysis, tests }
  })
  const staticShells = [
    { paths: predicatePaths.isStaticFeedRoute ?? [], shell: 'backend/static/feed/index.html' },
    { paths: predicatePaths.isStaticGalleryRoute ?? [], shell: 'backend/static/gallery/index.html' },
  ]
  for (const shell of staticShells) {
    if (!existsSync(join(ROOT, shell.shell))) throw new Error(`Static shell is missing: ${shell.shell}`)
  }
  return {
    version: 1,
    generated_by: 'tools/generate_frontend_map.mjs',
    source_of_truth: 'frontend/src/App.tsx',
    routes,
    static_shells: staticShells,
  }
}

function renderMarkdown(map) {
  const lines = [
    '# Frontend map (generated)',
    '',
    'Generated by `tools/generate_frontend_map.mjs` — do not edit by hand.',
    'Route groups come from `frontend/src/App.tsx`; per-entry data is the',
    'static import closure (components, hooks, `/api/*` literals, CSS, tests).',
    '',
  ]
  for (const route of map.routes) {
    lines.push(`## ${route.paths.join(', ') || '(dynamic)'} → \`${route.entry}\``)
    lines.push('')
    lines.push(`- predicate: \`${route.predicate}\``)
    lines.push(`- components (${route.components.length}): ${route.components.map((c) => `\`${c}\``).join(', ')}`)
    lines.push(`- hooks (${route.hooks.length}): ${route.hooks.join(', ') || '—'}`)
    lines.push(`- api (${route.api.length}): ${route.api.map((a) => `\`${a}\``).join(', ') || '—'}`)
    lines.push(`- css: ${route.css.map((c) => `\`${c}\``).join(', ') || '—'}`)
    lines.push(`- tests: ${route.tests.map((t) => `\`${t}\``).join(', ') || '—'}`)
    lines.push('')
  }
  lines.push('## Static shells (served by Caddy/backend, not the React app)')
  lines.push('')
  for (const shell of map.static_shells) {
    lines.push(`- ${shell.paths.join(', ')} → \`${shell.shell}\``)
  }
  lines.push('')
  return lines.join('\n')
}

function main() {
  const check = process.argv.includes('--check')
  const map = buildMap()
  const jsonText = `${JSON.stringify(map, null, 2)}\n`
  const mdText = renderMarkdown(map)
  if (check) {
    const currentJson = existsSync(JSON_OUT) ? read(JSON_OUT) : ''
    const currentMd = existsSync(MD_OUT) ? read(MD_OUT) : ''
    if (currentJson !== jsonText || currentMd !== mdText) {
      console.error('frontend map is stale: run `node tools/generate_frontend_map.mjs`')
      process.exit(2)
    }
    console.log('ok: frontend map')
    return
  }
  writeFileSync(JSON_OUT, jsonText, 'utf8')
  writeFileSync(MD_OUT, mdText, 'utf8')
  console.log(`wrote ${rel(JSON_OUT)}`)
  console.log(`wrote ${rel(MD_OUT)}`)
}

main()
