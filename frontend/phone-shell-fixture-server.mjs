import http from 'node:http'


const upstream = process.env.IZO_PHONE_FIXTURE_UPSTREAM || 'http://127.0.0.1:4188'
const port = Number(process.env.IZO_PHONE_FIXTURE_PORT || 4190)

const platform = {
  ok: true,
  apiVersion: 'v1',
  defaultRoute: '/phone/image',
  shell: { nativeReact: true, resumeJobs: true, offlineDrafts: true, notificationHost: true },
  contracts: { capabilities: 'v1', jobs: 'v1', media: 'v1', billing: 'v1' },
  workspaces: [
    ['image', 'Картинка', 'Фото', true, 'ready', 'primary', ['create', 'edit', 'draw']],
    ['video', 'Видео', 'Видео', true, 'ready', 'primary', ['text_to_video', 'image_to_video']],
    ['chat', 'Чат', 'Чат', true, 'ready', 'primary', ['conversation', 'web_search']],
    ['audio', 'Звук', 'Звук', false, 'partial', 'primary', ['speech_to_text']],
    ['3d', '3D-модель', '3D', false, 'planned', 'menu', []],
  ].map(([id, label, shortLabel, enabled, stage, navigation, operations]) => ({
    id, label, shortLabel, route: `/phone/${id}`, enabled, stage, navigation, operations,
  })),
}

const json = (response, payload) => {
  response.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  response.end(JSON.stringify(payload))
}

http.createServer(async (request, response) => {
  const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`)
  if (url.pathname === '/api/phone/v1/platform') return json(response, platform)
  if (url.pathname === '/api/me-v2') return json(response, {
    profile: { display_name: 'Тестовый пользователь' },
    account: { token_balance: 1259, daily_tokens_limit: 100, daily_tokens_remaining: 93 },
  })
  try {
    const upstreamResponse = await fetch(new URL(url.pathname + url.search, upstream), { redirect: 'manual' })
    const headers = Object.fromEntries(upstreamResponse.headers.entries())
    delete headers['content-encoding']
    delete headers['content-length']
    response.writeHead(upstreamResponse.status, headers)
    response.end(Buffer.from(await upstreamResponse.arrayBuffer()))
  } catch {
    response.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' })
    response.end('fixture upstream unavailable')
  }
}).listen(port, '127.0.0.1', () => {
  console.log(`PHONE_SHELL_FIXTURE_READY http://127.0.0.1:${port}`)
})
