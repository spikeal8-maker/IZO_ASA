import { isPhoneWorkspaceId, type PhoneWorkspaceId } from './contracts.ts'

export function phoneWorkspaceFromPath(pathname: string): PhoneWorkspaceId | null {
  const match = /^\/phone\/([^/]+)\/?$/.exec(pathname)
  return match && isPhoneWorkspaceId(match[1]) ? match[1] : null
}

export function phoneWorkspacePath(id: PhoneWorkspaceId): `/phone/${PhoneWorkspaceId}` {
  return `/phone/${id}`
}
