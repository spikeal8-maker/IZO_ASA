# New UI v2 integration handoff - 2026-07-04

Current safe integration branch:

- `hotfix/live-auth-gallery-faceswap-20260703`
- integrated feed/new-ui commits from `feature/new-ui-v2-clean`
- latest integrated commit at the time of this note: `89f4da2`

What was integrated:

- `/new` UI polish from `8cce4e1`
- `/new/feed` and canonical `/feed` feed UI from `70895f6`
- live feed backend/API/publication flow from `bcb6bfe`
- feed stabilization from `864d04f`

Auth rules that must not be reverted:

- Do not reintroduce `AuthV2Panel`.
- Do not render old `Вход (v2)` / `Вход по email (v2)` UI.
- Do not send `X-OneNode-User` from frontend requests.
- Do not use `localStorage('onenode_user')` as identity.
- Admin UI visibility must come only from trusted auth state:
  `authV2Status === 'authed' && authMe?.account?.role === 'admin'`.
- Feed publishing/reactions must use trusted cookie session through backend.

Before any future `/new` merge/deploy, run:

```powershell
rg -n "AuthV2Panel|Вход \(v2\)|Вход по email \(v2\)|X-OneNode-User|onenode_user|SESSION_USER_ID|auth-v2-code|auth-v2-providers" frontend/src
npm run lint
npx tsc -b
npx vite build
python -m pytest backend/test_feed_v2.py backend/test_password_auth.py backend/test_security_hotfix_20260629.py -q
```

Expected grep result:

- no real frontend matches;
- comments explaining that these legacy auth paths are forbidden are acceptable.

Deployment rule:

- Do not deploy `feature/new-ui-v2-clean` directly if it has not first absorbed the auth fixes.
- Deploy from the safe integrated branch after checks pass.
