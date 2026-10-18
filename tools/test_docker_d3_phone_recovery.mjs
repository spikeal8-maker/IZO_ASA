import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { chmod, lstat, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { activePhoneJob, phoneCheckpoint, writePhoneCheckpoint, observeActivePhoneImage, PHONE_CHECKPOINT } from './docker_d3_phone_recovery.mjs'

const owner = { sourceSha: 'a'.repeat(40), project: 'izo-asa-shadow-owned', runId: 'b'.repeat(32), jobId: 'owned-image-1234567890' }
const statuses = { initialStatus: 'running', reloadedStatus: 'processing', returnedStatus: 'running' }
const observations = { sameJobAfterReload: true, spaSignalAborted: true, pollsAfterUnmount: 0, imageSubmits: 0, videoSubmits: 0 }
const value = () => phoneCheckpoint(owner, statuses, observations)
const phone = () => ({ ok: true, job: { id: owner.jobId, modality: 'image', operation: 'text_to_image',
  status: 'running', terminal: false, progress: 42, result: null } })
const fileOptions = { skip: typeof process.getuid !== 'function' ? 'POSIX owned-file mode contract; Linux source gate required' : false }

test('checkpoint has only bounded fixed fields and the full job identity digest', () => {
  const result = value()
  assert.equal(result.clientSha256, createHash('sha256').update(`onenode-backend-${owner.jobId}`).digest('hex'))
  assert.equal(result.status, 'AWAITING_RELEASE')
  assert.equal(result.schema, 'izo-d3-phone-active/v1')
  assert.equal(result.modelExecution, false)
  assert.equal(result.acceleratorExecution, false)
  assert.ok(Buffer.byteLength(JSON.stringify(result)) < 4096)
  const collidingPrefix = phoneCheckpoint({ ...owner, jobId: 'owned-image-9999999999' }, statuses, observations)
  assert.equal(owner.jobId.slice(0, 10), collidingPrefix.jobId.slice(0, 10))
  assert.notEqual(result.clientSha256, collidingPrefix.clientSha256)
})

test('identity rejects coercible arrays, foreign project, path-like IDs, and extra-long IDs', () => {
  for (const change of [{ sourceSha: [owner.sourceSha] }, { project: ['izo-asa-shadow-owned'] },
    { runId: [owner.runId] }, { project: 'foreign-project' }, { jobId: '../job' }, { jobId: 'a'.repeat(121) }]) {
    assert.throws(() => phoneCheckpoint({ ...owner, ...change }, statuses, observations), { message: 'D3_PHONE_IDENTITY_INVALID' })
  }
})

test('checkpoint cannot assert release readiness for a terminal or missing observation', () => {
  assert.throws(() => phoneCheckpoint(owner, { ...statuses, returnedStatus: 'completed' }, observations))
  for (const change of [{ sameJobAfterReload: false }, { spaSignalAborted: false }, { pollsAfterUnmount: 1 },
    { imageSubmits: 1 }, { videoSubmits: 1 }, { unexpected: 'secret' }]) {
    assert.throws(() => phoneCheckpoint(owner, statuses, { ...observations, ...change }))
  }
  const inherited = Object.assign(Object.create(observations), { a: 0, b: 0, c: 0, d: 0, e: 0 })
  assert.throws(() => phoneCheckpoint(owner, statuses, inherited), { message: 'D3_PHONE_CHECKPOINT_OBSERVATION_INVALID' })
})

test('real Phone envelope must still be this owned active image job', () => {
  assert.equal(activePhoneJob(phone(), owner.jobId), 'running')
  for (const change of [{ id: 'another-job' }, { modality: 'video' }, { operation: 'edit' },
    { status: 'completed' }, { terminal: true }, { progress: NaN }, { progress: 100 }, { result: {} }]) {
    const payload = phone(); Object.assign(payload.job, change)
    assert.throws(() => activePhoneJob(payload, owner.jobId), { message: 'D3_PHONE_ACTIVE_JOB_MISMATCH' })
  }
  assert.throws(() => activePhoneJob({ ...phone(), ok: false }, owner.jobId))
})

async function privateDirectory(action) {
  const directory = await mkdtemp(path.join(path.dirname(fileURLToPath(import.meta.url)), 'phone-recovery-test-'))
  await chmod(directory, 0o700)
  try { await action(directory) } finally { await rm(directory, { recursive: true, force: true }) }
}

test('private marker is exclusive 0600 and cannot be overwritten or widened', fileOptions, async () => {
  await privateDirectory(async (directory) => {
    await writePhoneCheckpoint(directory, value())
    const target = path.join(directory, PHONE_CHECKPOINT), before = await readFile(target)
    assert.equal((await lstat(target)).mode & 0o777, 0o600)
    assert.deepEqual(JSON.parse(before.toString()), value())
    await assert.rejects(writePhoneCheckpoint(directory, value()), { message: 'D3_PHONE_CHECKPOINT_IO_FAILED' })
    assert.deepEqual(await readFile(target), before)
    await assert.rejects(writePhoneCheckpoint(directory, { ...value(), extra: 'untrusted' }), { message: 'D3_PHONE_CHECKPOINT_SCHEMA_INVALID' })
    assert.deepEqual(await readFile(target), before)
  })
})

test('marker refuses a symlink and leaves its owned target unchanged', fileOptions, async () => {
  await privateDirectory(async (directory) => {
    const target = path.join(directory, 'owned-target.txt')
    await writeFile(target, 'preserved', { flag: 'wx', mode: 0o600 })
    await symlink(target, path.join(directory, PHONE_CHECKPOINT))
    await assert.rejects(writePhoneCheckpoint(directory, value()), { message: 'D3_PHONE_CHECKPOINT_IO_FAILED' })
    assert.equal(await readFile(target, 'utf8'), 'preserved')
  })
})

test('nonprivate output and a directory alias are rejected before marker creation', fileOptions, async () => {
  await privateDirectory(async (directory) => {
    await chmod(directory, 0o755)
    await assert.rejects(writePhoneCheckpoint(directory, value()), { message: 'D3_PHONE_CHECKPOINT_DIRECTORY_INVALID' })
    await chmod(directory, 0o700)
    const alias = path.join(directory, 'alias')
    await symlink(directory, alias)
    await assert.rejects(writePhoneCheckpoint(alias, value()), { message: 'D3_PHONE_CHECKPOINT_DIRECTORY_INVALID' })
    await assert.rejects(lstat(path.join(directory, PHONE_CHECKPOINT)), { code: 'ENOENT' })
  })
})

const input = (context, workAllowed = () => true) => ({ ...owner, context, workAllowed,
  origin: 'http://127.0.0.1:48993', output: '/not-used-before-checkpoint', ownerId: 'web_' + 'c'.repeat(32),
  readPhone: async () => { throw new Error('UNEXPECTED_API_READ') } })

test('invalid target and cancelled caller create no page and perform no API call', async () => {
  let pages = 0
  const context = { newPage: async () => { pages++; throw new Error('UNEXPECTED_PAGE') } }
  await assert.rejects(observeActivePhoneImage({ ...input(context), origin: 'https://example.invalid' }), { message: 'D3_PHONE_TARGET_NOT_ADMITTED' })
  await assert.rejects(observeActivePhoneImage(input(context, () => false)), { message: 'D3_PHONE_WORK_DEADLINE' })
  assert.equal(pages, 0)
})

test('late caller cancellation closes only the newly owned page', async () => {
  const events = []; let allowed = true
  const context = { newPage: async () => {
    events.push('new-owned-page'); allowed = false
    return { close: async () => { events.push('close-owned-page') } }
  } }
  await assert.rejects(observeActivePhoneImage(input(context, () => allowed)), { message: 'D3_PHONE_WORK_DEADLINE' })
  assert.deepEqual(events, ['new-owned-page', 'close-owned-page'])
})

test('page cleanup failure remains a fixed failure without exposing transport text', async () => {
  let allowed = true
  const context = { newPage: async () => { allowed = false; return {
    close: async () => { throw new Error('provider-url?secret=not-for-receipt') },
  } } }
  await assert.rejects(observeActivePhoneImage(input(context, () => allowed)), { message: 'D3_PHONE_PAGE_CLOSE_FAILED' })
})

test('owned page cleanup cannot wait indefinitely', async () => {
  let allowed = true
  const context = { newPage: async () => { allowed = false; return { close: () => new Promise(() => {}) } } }
  const before = performance.now()
  await assert.rejects(observeActivePhoneImage(input(context, () => allowed)), { message: 'D3_PHONE_PAGE_CLOSE_FAILED' })
  assert.ok(performance.now() - before < 3000)
})
