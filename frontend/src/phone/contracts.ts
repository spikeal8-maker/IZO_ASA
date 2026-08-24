export type PhoneWorkspaceId = 'image' | 'video' | 'chat' | 'audio' | '3d'
export type PhoneWorkspaceStage = 'ready' | 'partial' | 'planned'
export type PhoneNavigationPlacement = 'primary' | 'menu'

export type PhoneWorkspace = {
  id: PhoneWorkspaceId
  label: string
  shortLabel: string
  route: `/phone/${PhoneWorkspaceId}`
  enabled: boolean
  stage: PhoneWorkspaceStage
  operations: string[]
  navigation: PhoneNavigationPlacement
}

export type PhonePlatformManifest = {
  ok: true
  apiVersion: 'v1'
  defaultRoute: `/phone/${PhoneWorkspaceId}`
  shell: {
    nativeReact: boolean
    resumeJobs: boolean
    offlineDrafts: boolean
    notificationHost: boolean
  }
  contracts: {
    capabilities: 'v1'
    jobs: 'v1'
    media: 'v1'
    billing: 'v1'
  }
  workspaces: PhoneWorkspace[]
}

export const PHONE_WORKSPACE_IDS: readonly PhoneWorkspaceId[] = [
  'image',
  'video',
  'chat',
  'audio',
  '3d',
]

export function isPhoneWorkspaceId(value: string): value is PhoneWorkspaceId {
  return PHONE_WORKSPACE_IDS.includes(value as PhoneWorkspaceId)
}

export function isPhonePlatformManifest(value: unknown): value is PhonePlatformManifest {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<PhonePlatformManifest>
  if (candidate.ok !== true || candidate.apiVersion !== 'v1') return false
  if (typeof candidate.defaultRoute !== 'string' || !candidate.defaultRoute.startsWith('/phone/')) return false
  if (!Array.isArray(candidate.workspaces) || candidate.workspaces.length !== PHONE_WORKSPACE_IDS.length) return false
  return candidate.workspaces.every((workspace) => (
    Boolean(workspace)
    && isPhoneWorkspaceId(workspace.id)
    && workspace.route === `/phone/${workspace.id}`
    && typeof workspace.enabled === 'boolean'
    && Array.isArray(workspace.operations)
  ))
}
