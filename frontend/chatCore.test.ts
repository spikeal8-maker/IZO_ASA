import assert from 'node:assert/strict'
import test from 'node:test'

import { PortableChatRuntime } from './src/chatCore/runtime.ts'
import type { PortableChatTransport } from './src/chatCore/types.ts'


const request = {
  provider: 'deepseek',
  model: 'deepseek-flash',
  messages: [{ role: 'user' as const, content: 'Привет' }],
  toolChoice: 'auto' as const,
}

test('portable runtime streams normalized deltas and tools', async () => {
  const events: string[] = []
  const transport: PortableChatTransport = async (_request, _signal, observer) => {
    observer?.onEvent?.({ type: 'state', state: 'streaming' })
    observer?.onEvent?.({ type: 'delta', text: 'При' })
    observer?.onEvent?.({ type: 'delta', text: 'вет' })
    observer?.onEvent?.({ type: 'tool', tool: { name: 'generate_image', status: 'requested', prompt: 'robot' } })
    observer?.onEvent?.({ type: 'done', provider: 'deepseek', model: 'deepseek-flash', messageId: 'message-1' })
    return { text: 'Привет', tools: [{ name: 'generate_image', status: 'requested', prompt: 'robot' }], messageId: 'message-1', stopped: false }
  }
  const runtime = new PortableChatRuntime(transport)
  const result = await runtime.send(request, { onEvent: (event) => events.push(event.type) })
  assert.equal(result.text, 'Привет')
  assert.equal(result.messageId, 'message-1')
  assert.equal(result.tools[0]?.name, 'generate_image')
  assert.deepEqual(events, ['state', 'delta', 'delta', 'tool', 'done'])
  assert.equal(runtime.state.phase, 'idle')
})

test('retry reuses the last request without creating another user turn', async () => {
  let calls = 0
  const transport: PortableChatTransport = async (input) => {
    calls += 1
    assert.deepEqual(input.messages, request.messages)
    return { text: `reply-${calls}`, tools: [], messageId: null, stopped: false }
  }
  const runtime = new PortableChatRuntime(transport)
  await runtime.send(request)
  const retried = await runtime.retry()
  assert.equal(calls, 2)
  assert.equal(retried.text, 'reply-2')
})

test('stop aborts the active request and returns a stopped completion', async () => {
  const transport: PortableChatTransport = async (_request, signal, observer) => {
    observer?.onEvent?.({ type: 'delta', text: 'partial' })
    await new Promise<void>((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    })
    return { text: '', tools: [], messageId: null, stopped: false }
  }
  const runtime = new PortableChatRuntime(transport)
  const pending = runtime.send(request)
  await Promise.resolve()
  runtime.stop()
  const result = await pending
  assert.equal(result.stopped, true)
  assert.equal(result.text, 'partial')
  assert.equal(runtime.state.phase, 'stopped')
})
