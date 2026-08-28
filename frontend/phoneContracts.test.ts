import assert from 'node:assert/strict'
import test from 'node:test'

import { isPhonePlatformManifest } from './src/phone/contracts.ts'
import { phoneWorkspaceFromPath, phoneWorkspacePath } from './src/phone/routes.ts'


const manifest = {
  ok: true,
  apiVersion: 'v1',
  defaultRoute: '/phone/image',
  shell: {
    nativeReact: true,
    resumeJobs: true,
    offlineDrafts: true,
    notificationHost: true,
  },
  contracts: { capabilities: 'v1', jobs: 'v1', media: 'v1', billing: 'v1' },
  workspaces: ['image', 'video', 'chat', 'audio'].map((id) => ({
    id,
    label: id,
    shortLabel: id,
    route: `/phone/${id}`,
    enabled: true,
    stage: 'ready',
    operations: [],
    navigation: 'primary',
  })),
}


test('accepts the versioned phone manifest', () => {
  assert.equal(isPhonePlatformManifest(manifest), true)
})


test('rejects malformed or partial manifests', () => {
  assert.equal(isPhonePlatformManifest({ ...manifest, apiVersion: 'v2' }), false)
  assert.equal(isPhonePlatformManifest({ ...manifest, workspaces: [...manifest.workspaces, manifest.workspaces[0]] }), false)
  assert.equal(isPhonePlatformManifest({ ...manifest, defaultRoute: '/' }), false)
})


test('parses only exact phone workspace routes', () => {
  assert.equal(phoneWorkspaceFromPath('/phone/chat'), 'chat')
  assert.equal(phoneWorkspaceFromPath('/phone/3d/'), '3d')
  assert.equal(phoneWorkspaceFromPath('/phone/unknown'), null)
  assert.equal(phoneWorkspaceFromPath('/phone/chat/thread'), null)
  assert.equal(phoneWorkspacePath('video'), '/phone/video')
})
