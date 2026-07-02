# Current Architecture

This document describes the current project shape. It is not a wishlist and should
be updated whenever runtime structure, launch flow, auth boundaries or major data
contracts change.

## Product Surfaces

- `/` — current production user interface.
- `/admin` or the admin view inside the current SPA — operational admin/CRM area.
- `/new` — experimental UI 2.0. It must remain isolated until explicitly accepted.
- `https://izo.alikinas.ru` — public tunnel/domain that points to the local public
  frontend port.

## Backend

- Runtime: FastAPI.
- Main file: `backend/main.py`.
- Storage: SQLite through raw `sqlite3`.
- There is no ORM and no dedicated migration tool.
- Schema creation and additive migrations live in `init_db()`.
- Production/live mode must use explicit `DATABASE_URL`.
- Production DB guard checks path, size, required tables, user count and active admin count.

Important backend areas:

- Health/version:
  - `GET /api/health`
  - `GET /api/version`
- Auth/session:
  - `GET /api/me-v2`
  - `GET /api/auth/capabilities-v2`
  - password register/login endpoints
  - Telegram/MAX Mini App endpoints
  - bot-login challenge endpoints
- Generation:
  - `POST /api/generate`
  - `GET /api/jobs/{id}`
  - job lifecycle and ComfyUI adapter
- Gallery:
  - `GET /api/gallery`
  - image detail/favorite/delete/use-as/send endpoints
- Admin:
  - trusted admin v2 endpoints
  - dashboard, users analytics, logs, token settings and CRM actions

## Frontend

- Runtime: React + Vite + TypeScript.
- Main app: `frontend/src/App.tsx`.
- Auth UI/state: `frontend/src/authV2.tsx`.
- Admin analytics/CRM: `frontend/src/adminAnalytics.tsx`.
- Global styles: `frontend/src/index.css`.
- Experimental UI 2.0:
  - `frontend/src/newUi.tsx`
  - `frontend/src/newUi.css`
  - `frontend/src/stylePresets.ts`

The current frontend is still mostly a monolithic SPA. Be careful with shared files:
`App.tsx`, `index.css`, `authV2.tsx` and `stylePresets.ts` can affect multiple surfaces.

## Public Launch Model

The public tunnel points to frontend port `5173`.

- Development:
  - `start-project.bat`
  - Vite dev server
  - hot reload
  - not for public/live tunnel

- Public/live preview:
  - `start-public.bat`
  - builds `frontend/dist`
  - starts backend on `127.0.0.1:8000`
  - starts `vite preview` on `127.0.0.1:5173`
  - writes backend log to `logs/live_backend_<timestamp>.log`
  - probes health and auth capabilities

For final hardened production, `frontend/dist` should be served by a real static web
server such as nginx or Caddy, with the backend managed by a process manager/service.

## Database Rules

- Do not destructively change schema.
- Do not drop tables or columns.
- Do not rename or rewrite `users.id`.
- Prefer additive `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and safe
  `ALTER TABLE ADD COLUMN`.
- Do not mutate live DB manually unless there is an explicit owner-approved repair plan.
- Do not edit owner/admin accounts manually.

## Security Boundaries

Trusted authentication is server-issued cookie session auth.

Forbidden as auth:

- `X-OneNode-User`
- `onenode_user`
- query/body `userId`
- username, phone or email as proof of provider identity
- Telegram `initDataUnsafe`
- unsigned MAX payload

Admin mutations must require trusted admin session and must create audit/security
events where applicable.

## Generation Architecture

Generation is job-based:

1. Frontend calls `POST /api/generate`.
2. Backend validates session, credits/limits and request.
3. Backend creates a job.
4. Backend sends a patched workflow to ComfyUI.
5. Frontend polls `GET /api/jobs/{id}`.
6. Completed jobs save output image and thumbnail into media/gallery.

Large uploaded input images must be downscaled before ComfyUI processing according to
backend limits. The source aspect ratio may remain, but raw user image resolution must
not be passed directly into GPU workflow.

## Admin Architecture

The admin area is still evolving. The target direction is:

- compact operational dashboard;
- trusted cookie admin endpoints only;
- clear logs/errors/config views;
- CRM user list/card with real data;
- no legacy header-auth actions in primary UI.

Before admin work, read `docs/admin-panel-product-spec.md` and the current code.

