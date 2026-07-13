import http from 'node:http'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const toolsDirectory = path.dirname(fileURLToPath(import.meta.url))
const frontendDirectory = path.resolve(toolsDirectory, '..', 'frontend')
const frontendRequire = createRequire(path.join(frontendDirectory, 'package.json'))
const viteEntry = frontendRequire.resolve('vite')
const { preview } = await import(pathToFileURL(viteEntry).href)

function requestWithHost(port, host) {
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        hostname: '127.0.0.1',
        port,
        path: '/',
        method: 'GET',
        headers: { Host: host },
      },
      (response) => {
        response.resume()
        response.once('end', () => resolve(response.statusCode))
      },
    )
    request.once('error', reject)
    request.setTimeout(5_000, () => request.destroy(new Error(`request timed out for Host ${host}`)))
    request.end()
  })
}

const server = await preview({
  root: frontendDirectory,
  logLevel: 'silent',
  preview: {
    host: '127.0.0.1',
    port: 0,
    strictPort: true,
  },
})

try {
  const address = server.httpServer.address()
  if (!address || typeof address === 'string' || address.address !== '127.0.0.1') {
    throw new Error(`preview did not bind to IPv4 loopback: ${JSON.stringify(address)}`)
  }

  const checks = [
    ['izo.alikinas.ru', 200],
    [`127.0.0.1:${address.port}`, 200],
    ['sub.izo.alikinas.ru', 403],
    ['evil.example', 403],
  ]
  const results = []
  for (const [host, expected] of checks) {
    const actual = await requestWithHost(address.port, host)
    if (actual !== expected) {
      throw new Error(`Host ${host} returned ${actual}; expected ${expected}`)
    }
    results.push(`${host}=${actual}`)
  }
  console.log(`ORIGIN_ISOLATION_OK bind=${address.address} checks=${results.join(',')}`)
} finally {
  await server.close()
}
