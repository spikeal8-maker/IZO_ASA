# Claude Code instructions for IZO_ASA

Before any action, read `AGENTS.md` completely. It is the authoritative
repository-wide policy. The files in `.claude/rules/` add identity, security and
SQLite details; they do not override `AGENTS.md`.

Project-specific reminders:

- Work only in `D:\Google Drive\My progact\Генератор картинок`.
- The product is already live with users, payments, public feed, gallery, bots
  and mail integration. Preserve behavior while optimizing it.
- Do not add new business logic to `backend/main.py` and do not raise its
  architecture budget to accept growth. Extract one tested seam at a time.
- Identity remains additive: preserve legacy `users.id`; trusted identity uses
  server-side sessions/internal identity. Never trust legacy client headers or
  cookies.
- Preserve production SQLite, media and DPAPI secrets. Tests use temporary
  roots and fake providers.
- Public user-facing model branding is `Flux2`; technical identifiers are
  internal/admin-only.
- Do not deploy, restart production, alter VPS/FRP or send real provider traffic
  unless the current user request explicitly authorizes that operation.
- Update tests, generated maps and the current optimization plan in the same
  package when their contract changes.
