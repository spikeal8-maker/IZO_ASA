declare const __APP_RELEASE__: string

export const FRONTEND_RELEASE_ID =
  typeof __APP_RELEASE__ === 'string' && __APP_RELEASE__.trim()
    ? __APP_RELEASE__.trim()
    : 'unknown'
