/**
 * One image-generation intent. Call only for its POST endpoint with a serialized
 * JSON body. A new factory call means a new intent; reusing its closure preserves
 * the exact key/body across network and session-refresh attempts.
 *
 * Deploy together with server-side durable admission before enabling this retry.
 */
export function createGenerationRequest(url: string, init: RequestInit): () => Promise<Response> {
  if (init.method?.toUpperCase() !== 'POST' || typeof init.body !== 'string') {
    throw new TypeError('Generation admission requires a POST with a serialized JSON body.')
  }
  const headers = new Headers(init.headers)
  if (!headers.has('Idempotency-Key')) headers.set('Idempotency-Key', globalThis.crypto.randomUUID())
  const request: RequestInit = { ...init, headers }
  let networkRetryAvailable = true
  const send = async () => {
    const response = await fetch(url, request)
    // Read a clone so a dropped response body is retried before callers parse it.
    if (response.ok) await response.clone().arrayBuffer()
    return response
  }

  return async () => {
    try {
      return await send()
    } catch (error) {
      const aborted = request.signal?.aborted
        || (typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError')
      if (aborted || !networkRetryAvailable) throw error
      networkRetryAvailable = false
      return send()
    }
  }
}
