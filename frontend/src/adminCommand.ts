/** Pending CRM entitlement commands survive uncertain responses and page reload. */
export type AdminCommandResult = { ok: boolean; status: number; detail?: string }
type Body = Record<string, unknown>
type StoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
type Sender = (path: string, body: Body) => Promise<AdminCommandResult>
// attempts is a durable receipt revision: adoption and each submission advance it.
type Pending = { version: 1; key: string; body: Body; attempts: number }
const PREFIX = 'izo.admin-command.v1:'
const KEY = /^[A-Za-z0-9][A-Za-z0-9._:-]{11,119}$/
const PATH = /^\/admin\/users\/[^/]+\/(tokens|plan)-v2$/

function operationKey(): string {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return `crm-${Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')}`
}

function normalizedBody(path: string, body: Body): Body {
  const route = PATH.exec(path)
  if (!route) throw new Error('Неподдерживаемое административное действие.')
  const reason = typeof body.reason === 'string' ? body.reason.trim() : ''
  if (!reason || reason.length > 500) throw new Error('Укажите причину длиной от 1 до 500 символов.')
  if (route[1] === 'tokens') {
    const delta = body.delta
    if (typeof delta !== 'number' || !Number.isInteger(delta) || delta === 0 || Math.abs(delta) > 100000) {
      throw new Error('Укажите ненулевое целое изменение баланса не больше 100000 по модулю.')
    }
    return { delta, reason }
  }
  const plan = body.plan
  const duration = body.duration_days ?? 30
  if (typeof plan !== 'string' || !['free', 'mini', 'plus', 'pro', 'business'].includes(plan)
      || typeof duration !== 'number' || !Number.isInteger(duration) || duration < 1 || duration > 3660) {
    throw new Error('Укажите корректный тариф и срок.')
  }
  return { plan, duration_days: duration, reason }
}

function read(storage: StoragePort, path: string): Pending | null {
  const raw = storage.getItem(PREFIX + path)
  if (raw === null) return null
  let parsed: Partial<Pending> | null
  try { parsed = JSON.parse(raw) as Partial<Pending> | null }
  catch { throw new Error('Не удалось проверить сохранённое действие. Новое начисление не отправлено.') }
  if (!parsed || parsed.version !== 1 || typeof parsed.key !== 'string' || !KEY.test(parsed.key) || parsed.key !== parsed.key.trim()
      || !parsed.body || typeof parsed.body !== 'object' || Array.isArray(parsed.body)
      || !Number.isSafeInteger(parsed.attempts) || Number(parsed.attempts) < 1) {
    throw new Error('Не удалось проверить сохранённое действие. Новое начисление не отправлено.')
  }
  return { version: 1, key: parsed.key, body: normalizedBody(path, parsed.body), attempts: Number(parsed.attempts) }
}

function clearConfirmed(storage: StoragePort, path: string, command: Pending): boolean {
  const current = read(storage, path)
  if (current?.key === command.key && current.attempts === command.attempts) {
    storage.removeItem(PREFIX + path)
    return true
  }
  return false
}

/** One client belongs to one confirmation dialog; a successful dialog cannot resubmit. */
export function createAdminCommandClient(storage: StoragePort, send: Sender, newKey = operationKey) {
  const inflight = new Map<string, { body: string; promise: Promise<AdminCommandResult> }>()
  const completed = new Map<string, { body: string; result: AdminCommandResult }>()
  const unconfirmed = new Map<string, Pending>()
  const recoveryBlocked = new Set<string>()

  return {
    recover(path: string): Body | null {
      try {
        const own = unconfirmed.get(path)
        const shared = read(storage, path)
        let pending = own ?? shared
        if (!pending) return null
        if (own && shared && (own.key !== shared.key || JSON.stringify(own.body) !== JSON.stringify(shared.body))) {
          return { ...own.body }
        }
        // Adopting a restored intent advances the receipt revision before it is displayed.
        pending = { ...pending, attempts: Math.max(pending.attempts, shared?.attempts ?? 0) + (own ? 0 : 1) }
        if (!Number.isSafeInteger(pending.attempts)) throw new Error('Command revision exhausted')
        unconfirmed.set(path, pending)
        if (!shared || shared.attempts !== pending.attempts) storage.setItem(PREFIX + path, JSON.stringify(pending))
        recoveryBlocked.delete(path)
        return { ...pending.body }
      } catch { recoveryBlocked.add(path); return null }
    },
    submit(path: string, body: Body): Promise<AdminCommandResult> {
      let normalized: Body
      try {
        normalized = normalizedBody(path, body)
      } catch (error) {
        return Promise.resolve({ ok: false, status: 0, detail: error instanceof Error ? error.message : 'Не удалось сохранить действие.' })
      }
      let shared: Pending | null
      try { shared = read(storage, path) }
      catch { return Promise.resolve({ ok: false, status: 0, detail: 'Не удалось проверить сохранённое действие. Новый запрос не отправлен.' }) }
      const serialized = JSON.stringify(normalized)
      const done = completed.get(path)
      if (done) return Promise.resolve(done.body === serialized ? done.result : {
        ok: false, status: 409, detail: 'Действие уже выполнено. Для нового действия откройте подтверждение заново.',
      })
      const active = inflight.get(path)
      if (active) return active.body === serialized ? active.promise : Promise.resolve({
        ok: false, status: 409, detail: 'Дождитесь результата отправленного действия.',
      })
      const own = unconfirmed.get(path)
      if (recoveryBlocked.has(path) && !own && !shared) return Promise.resolve({
        ok: false, status: 0, detail: 'Не удалось восстановить ключ предыдущего действия. Новый запрос не отправлен.',
      })
      let pending = own ?? shared
      if ((own && shared && (own.key !== shared.key || JSON.stringify(own.body) !== JSON.stringify(shared.body)))
          || (pending && JSON.stringify(pending.body) !== serialized)) return Promise.resolve({
        ok: false, status: 409,
        detail: 'Предыдущее действие ещё не подтверждено. Повторите его с сохранёнными параметрами.',
      })
      try {
        pending = pending
          ? { ...pending, attempts: Math.max(pending.attempts, shared?.attempts ?? 0) + 1 }
          : { version: 1, key: newKey(), body: normalized, attempts: 1 }
        if (!KEY.test(pending.key) || pending.key !== pending.key.trim() || !Number.isSafeInteger(pending.attempts)) {
          throw new Error('Не удалось создать ключ операции.')
        }
        storage.setItem(PREFIX + path, JSON.stringify(pending))
        // Another dialog may acknowledge and remove the shared receipt while this response is unknown.
        unconfirmed.set(path, pending)
      } catch {
        return Promise.resolve({ ok: false, status: 0, detail: 'Не удалось сохранить действие для безопасного повтора. Запрос не отправлен.' })
      }
      const command = pending
      const promise = Promise.resolve().then(async () => {
        let result: AdminCommandResult
        try { result = await send(path, { ...normalized, idempotency_key: command.key }) }
        catch { result = { ok: false, status: 0, detail: 'Ответ не получен. Повтор использует то же действие.' } }
        if (!result.ok && (result.status === 0 || result.status >= 500) && !result.detail) {
          result = { ...result, detail: 'Ответ не подтверждён. Повтор использует сохранённое действие.' }
        }
        if (result.ok) {
          completed.set(path, { body: serialized, result })
          unconfirmed.delete(path)
          try { clearConfirmed(storage, path, command) } catch { /* Keeping a receipt is safer than creating another effect. */ }
        } else if (command.attempts === 1 && result.status === 400) {
          // Only an unchanged first attempt proves that no other dialog has retried this rejection.
          try {
            if (clearConfirmed(storage, path, command)) unconfirmed.delete(path)
          } catch { /* Retry keeps the original command. */ }
        }
        return result
      }).finally(() => { inflight.delete(path) })
      inflight.set(path, { body: serialized, promise })
      return promise
    },
  }
}
