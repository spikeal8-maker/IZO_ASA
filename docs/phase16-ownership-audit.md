# Phase 16: Jobs/Images/Gallery Ownership Audit

## 1. Verdict: **AUDIT READY — Critical gaps found**

Generation is protected (Phase 15). All other data-access endpoints still trust spoofable headers.

---

## 2. Endpoint inventory

### 2.1 Mutating endpoints (create job / spend tokens)

| Method | Path | Function | Line | Auth | Risk |
|---|---|---|---|---|---|
| POST | `/api/generate` | `generate()` | 3067 | `require_trusted_user` | **PROTECTED** (Phase 15) |

### 2.2 Job read/mutate endpoints

| Method | Path | Function | Line | Read/Mutate | Auth | Trusts header? | Risk |
|---|---|---|---|---|---|---|---|
| GET | `/api/jobs/{job_id}` | `get_job()` | 3128 | Read | `request_user_id` | **YES** (`X-OneNode-User`) | HIGH |
| POST | `/api/jobs/{job_id}/cancel` | `cancel_job()` | 3138 | Mutate | `request_user_id` | **YES** (`X-OneNode-User`) | HIGH |
| GET | `/api/admin/jobs` | `admin_jobs()` | 4998 | Read (all) | `require_admin` | — | LOW (admin only) |

### 2.3 Gallery/image read/mutate endpoints

| Method | Path | Function | Line | Read/Mutate | Auth | Trusts header? | Risk |
|---|---|---|---|---|---|---|---|
| GET | `/api/gallery` | `gallery()` | 3196 | Read (filtered) | `request_user_id` | **YES** (`X-OneNode-User`) | HIGH |
| GET | `/api/gallery/{id}` | `gallery_detail()` | 3204 | Read | `request_user_id` | **YES** (`X-OneNode-User`) | HIGH |
| POST | `/api/gallery/{id}/favorite` | `gallery_favorite()` | 3214 | Mutate | `request_user_id` | **YES** (`X-OneNode-User`) | HIGH |
| DELETE | `/api/gallery/{id}` | `gallery_delete()` | 3227 | Mutate | `request_user_id` | **YES** (`X-OneNode-User`) | HIGH |
| POST | `/api/gallery/{id}/use-as` | `gallery_use_as()` | 3240 | Read | `request_user_id` | **YES** (`X-OneNode-User`) | HIGH |
| POST | `/api/gallery/{id}/send` | `send_gallery_image()` | 4708 | Read/Mutate | `request_user_id` | **YES** (`X-OneNode-User`) | HIGH |

### 2.4 Token/preset endpoints

| Method | Path | Function | Line | Read/Mutate | Auth | Risk |
|---|---|---|---|---|---|---|
| GET | `/api/presets` | `get_presets()` | — | Read | `request_user_id` | MEDIUM |
| POST | `/api/presets` | `save_preset()` | — | Mutate | `request_user_id` | MEDIUM |
| Various | `/api/admin/users/*` | admin mutate | 4810+ | Mutate | `require_admin` | LOW |

### 2.5 Token balance (implicit)

| Endpoint | How accessed | Risk |
|---|---|---|
| `users.token_balance` | `GET /api/gallery` filters by `userId` but doesn't expose balance | N/A |
| `token_ledger` | No public endpoint exposes it directly | N/A |
| `token_balance` check | Inside `POST /api/generate` (Phase 15 protected) | PROTECTED |

---

## 3. Data model: user ownership columns

| Table | Owner column | Type | Value examples |
|---|---|---|---|
| `jobs` | `user_id` | TEXT | `web_a1b2c3...`, `telegram_111`, `demo_user` |
| `images` | `user_id` | TEXT | `web_a1b2c3...`, `telegram_111`, `demo_user` |
| `token_ledger` | `user_id` | TEXT | `web_a1b2c3...`, `telegram_111`, `demo_user` |
| `users` | `id` (primary) | TEXT | Legacy provider-based ID |
| `users` | `internal_user_id` | TEXT | UUID4 hex (canonical, additive) |

**Key fact:** `jobs.user_id`, `images.user_id`, `token_ledger.user_id` all contain legacy IDs that map to `users.id`. No `internal_user_id` column exists in these tables. Adding one would be straightforward (`ALTER TABLE ADD COLUMN`) but not strictly needed — the trusted session provides both `internal_user_id` and `legacy_user_id` so ownership checks can use either.

---

## 4. Current ownership model (legacy)

All 6 HIGH-risk endpoints use the same pattern:

```python
user_id = request_user_id(request)  # reads X-OneNode-User header
if record["userId"] != user_id:
    raise HTTPException(404, "Not found")
```

This `request_user_id()` function (line 410) trusts:
1. `X-OneNode-User` request header (highest priority)
2. `onenode_user` cookie (fallback)
3. Falls back to `"demo_user"`

**Any client can spoof the `X-OneNode-User` header** to impersonate any user and:
- View their gallery
- View their job status
- Favorite/unfavorite their images
- Delete their images
- Cancel their jobs
- Use their images as input

---

## 5. Frontend credential gap

### 5.1 How the frontend calls these endpoints

All gallery/job calls use `apiFetch()` (App.tsx:193):

```typescript
function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  headers.set('X-OneNode-User', window.localStorage.getItem('onenode_user') || SESSION_USER_ID)
  return fetch(`${API}${path}`, { ...init, headers })
  // NOTE: no credentials: 'include'
}
```

Legacy `apiFetch` does NOT set `credentials: 'include'`. However, the default for `fetch()` is `'same-origin'`, which DOES send cookies for same-origin requests. Since both frontend and backend are on `https://izo.alikinas.ru`, the `onenode_session` cookie IS sent automatically.

**But `apiFetch` also sets `X-OneNode-User` from localStorage.** With v2 auth, localStorage no longer stores `onenode_user`. So `apiFetch` sends `X-OneNode-User: demo_user` for v2-authenticated users. The backend must ignore this header when a valid session cookie exists.

### 5.2 Required frontend change for Phase 16.1

To properly protect gallery/job endpoints, the frontend must either:
- **(A)** Switch gallery/job calls to use `authFetch` (credentials: 'include', no X-OneNode-User), OR
- **(B)** Keep `apiFetch` but add `credentials: 'include'`

Option A is cleaner and consistent with the auth-v2 design.

---

## 6. Recommended Phase 16.1 implementation plan

### Step 1: Protect all HIGH-risk endpoints with `require_trusted_user`

For each of the 6 endpoints (lines 3128, 3138, 3196, 3204, 3214, 3227, 3240, 4708):

```python
# Before (legacy — trusts spoofable header):
user_id = request_user_id(request)
if record["userId"] != user_id:
    raise HTTPException(404, "Not found")

# After (v2 — cookie session only):
trusted = require_trusted_user(request)
user_id = trusted["legacy_user_id"]
if record["userId"] != user_id:
    raise HTTPException(404, "Not found")
```

Key changes per endpoint:
- Replace `request_user_id(request)` with `require_trusted_user(request)["legacy_user_id"]`
- Keep existing `record["userId"]` comparison — compatible because both use legacy IDs
- Banned/deleted user automatically gets 403 from resolver
- No session gets 401
- Spoofed `X-OneNode-User` ignored (already handled by resolver, logs spoof attempt)

### Step 2: Frontend — switch legacy calls to cookie-based

In `App.tsx`, the `apiFetch` function needs `credentials: 'include'` added. The `X-OneNode-User` header becomes vestigial (backend ignores it when session cookie is present).

Minimal change: add `credentials: 'include'` to `apiFetch`:

```typescript
function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  headers.set('X-OneNode-User', window.localStorage.getItem('onenode_user') || SESSION_USER_ID)
  return fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
}
```

This is backward-compatible: same-origin cookies are already sent for same-origin requests, so adding explicit `'include'` changes nothing for same-origin. It only helps if the frontend ever moves to a different origin.

### Step 3: Admin exceptions

Admin endpoints (`/api/admin/*`) remain on `require_admin()` (legacy). They're gated by admin role check and operate at a higher privilege level. No change needed now.

### Step 4: Security event logging

All 6 endpoints should:
- Write `security_events` on unauthorized access attempts (already handled by resolver for session failures)
- Write `event_logs` on successful operations: `gallery_viewed`, `image_favorited`, `image_deleted`, `job_cancelled`, etc.

### Step 5: Data model — no changes needed

- `jobs.user_id`, `images.user_id`, `token_ledger.user_id` remain as-is (legacy format)
- Adding `internal_user_id` columns can be deferred — the resolver provides both IDs
- `users.id` / `users.internal_user_id` unchanged

---

## 7. Test requirements for Phase 16.1

| # | Test | Priority |
|---|---|---|
| 1 | User A cannot see User B's gallery | Critical |
| 2 | User A cannot cancel User B's job | Critical |
| 3 | User A cannot favorite User B's image | Critical |
| 4 | User A cannot delete User B's image | Critical |
| 5 | User A cannot use-as User B's image | Critical |
| 6 | Spoofed X-OneNode-User header ignored when session present | Critical |
| 7 | Spoofed onenode_user cookie ignored when session present | Critical |
| 8 | No session → 401 for all protected endpoints | Critical |
| 9 | Banned user → 403 for all protected endpoints | Critical |
| 10 | Admin can still view all via `/api/admin/jobs` | High |
| 11 | Prompt text not in event_logs for gallery operations | Medium |
| 12 | Raw tokens not logged | Medium |
| 13 | `users.id` unchanged | Medium |
| 14 | Phase 15 generation protection tests still pass | Critical |
| 15 | Password auth/cookie session tests still pass | Critical |

---

## 8. Confirmations

- No code changed (audit only)
- No DB changed
- No frontend changed
- No next phase started
