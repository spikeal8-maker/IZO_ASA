# Phase 17.1 — Russia Network Reachability Audit

Diagnosis only. No code/DB/auth/secret changes. Goal: is the public route blocked/
throttled from Russian networks, and what is a stable deployment path.

## Block 1 — DNS / tunnel
- `izo.alikinas.ru` A-records: `104.21.78.49`, `172.67.216.238`; AAAA `2606:4700:30xx::…`.
  All are **Cloudflare anycast** ranges → the domain is **proxied through Cloudflare**
  (orange-cloud), not pointed at a direct origin IP.
- Edge headers: `Server: cloudflare`, `CF-RAY: …-FRA` (Cloudflare **Frankfurt** edge),
  `Cf-Cache-Status: DYNAMIC`.
- Origin: `cloudflared` tunnel (running) → `localhost:5173` (vite preview / dist) →
  backend `:8000`. No tunnel token/secret printed.

Routing: `client → Cloudflare anycast (FRA) → cloudflared tunnel → 5173 (dist) → 8000`.

## Block 2 — Reachability probes (from developer machine, non-RU / VPN)
| path | code | TTFB | total | size | edge IP |
|------|------|------|-------|------|---------|
| `/` | 200 | 0.32s | 0.32s | 458B | 2606:4700:3035:: (CF) |
| `/?diag=1` | 200 | 0.33s | 0.33s | 458B | CF |
| `/api/version` | 200 | 0.28s | 0.28s | 119B | CF |
| `/api/me-v2` | 401 | 0.49s | 0.49s | 35B | CF |
No resets/timeouts from this network. (A real Russian-network test cannot be run from
here; the owner already observes: works via VPN, unreliable/fails without.)

## Block 3 — Russian-network hypothesis (symptoms match)
- **Cloudflare throttling/blocking by Russian ISPs / TSPU (Roskomnadzor)** is widely
  reported; it hits Cloudflare anycast ranges (104.21/172.67) and edge TLS.
- **Mobile operators** throttle foreign CDN/tunnel traffic more aggressively than fixed
  broadband → Telegram/MAX in-app WebViews (short timeouts) "don't open", while desktop
  on some ISPs still loads.
- **VPN works** because it bypasses RU ISP filtering of Cloudflare.
- Not a DNS issue (resolves fine) and not an app bug (app renders, endpoints respond,
  the 16.4D crash is fixed).

## Block 4 — Recommended deployment path
**Option A — Russian (or CIS / RU-reachable) VPS, no Cloudflare proxy/tunnel.** Most
reliable for RU users incl. mobile Telegram/MAX. The `.ru` domain should point directly
(grey-cloud / no Cloudflare proxy) to the VPS IP, with nginx + TLS.

- Option B (non-RU VPS, direct IP, no Cloudflare): may work but RU blocking of foreign
  IPs is unpredictable — weaker than A.
- Option C: keep Cloudflare tunnel for **dev only**; production/staging on the VPS.

## Block 6 — Minimal migration plan (Option A)
1. **VPS:** small Russian/CIS VPS (e.g. 1–2 vCPU / 2–4 GB), Ubuntu; install python3.11,
   node LTS, nginx, certbot. (ComfyUI/GPU stays where it is; backend talks to it via
   `COMFYUI_BASE_URL`.)
2. **Backend:** copy `backend/`, `pip install -r requirements.txt`, run uvicorn under
   **systemd** (`uvicorn main:app --host 127.0.0.1 --port 8000`, Restart=always). Set
   env (`APP_ENV=production`, `SESSION_HMAC_SECRET`, `TRUSTED_COOKIE_SECURE=true`,
   `CORS_ALLOWED_ORIGINS=https://izo.alikinas.ru`, bot tokens) — never commit secrets.
3. **Frontend:** `npm ci && npx vite build` → serve `frontend/dist` via **nginx** with
   SPA fallback (`try_files $uri /index.html`).
4. **nginx reverse proxy:** `/api` and `/media` → `http://127.0.0.1:8000`; everything
   else → static `dist`. Example:
   ```
   server {
     server_name izo.alikinas.ru;
     root /var/www/izo/dist; index index.html;
     location /api/   { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
     location /media/ { proxy_pass http://127.0.0.1:8000; }
     location /       { try_files $uri /index.html; }
   }
   ```
5. **Domain:** point `izo.alikinas.ru` A-record directly at the VPS IP; **disable
   Cloudflare proxy** (grey cloud) or move DNS off Cloudflare.
6. **TLS:** `certbot --nginx -d izo.alikinas.ru` (auto-renew). HTTPS is required by
   Telegram/MAX Mini Apps.
7. **Start/stop:** systemd units for backend + nginx; a deploy script = `git pull` →
   `vite build` → `systemctl restart izo-backend && nginx -s reload`. Retire
   cloudflared for production (keep `start-project.bat` for local dev,
   `start-public.bat` for tunnel-based dev only).

## Block 7 — What to test after migration
- Browser **without VPN** (RU network) → site loads.
- Mobile browser **without VPN** → loads.
- **Telegram mobile** Mini App opens (URL = `https://izo.alikinas.ru/`).
- **MAX mobile** Mini App opens.
- `/api/version` → 200 (build matches).
- No-session `/api/generate` → 401, `/api/gallery` → 401.
- register/login email+password → cookie session, `/api/me-v2` → 200, reload persists.

## Block 5 — Immediate workaround
Until migration: VPN for developer testing only. Do NOT run Telegram/MAX mobile
acceptance tests over the Cloudflare tunnel — move to a directly-reachable VPS/host
first, then resume platform debugging (Phase 17).
