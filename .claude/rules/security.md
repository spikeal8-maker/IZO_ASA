# Security Rules for Identity Core

* Do not trust client-supplied user identity.
* Do not trust `X-OneNode-User`.
* Do not trust `onenode_user` cookie.
* Do not trust Telegram `initDataUnsafe`.
* Do not trust MAX data before signature validation.
* Session tokens must be generated server-side using cryptographically secure randomness.
* Store only hashes of session and refresh tokens.
* OTP codes must be stored only as hashes.
* Do not log raw tokens, OTP, cookies, `Authorization` headers, full raw `initData`,
  full raw `WebAppData`.
* Invalid auth attempts must write `security_events`.
* Admin mutations must write `audit_logs`.
* Revoked sessions must not work.
* Expired sessions must not work.
* Blocked/banned users must not refresh sessions.
