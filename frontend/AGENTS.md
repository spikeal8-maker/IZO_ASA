# Frontend scoped policy

Root `AGENTS.md` and `AI_START_HERE.md` remain mandatory. This file owns only
rules for `frontend/**`; it does not own reading order, current status or backlog.

## UI ownership and locality

- `frontend/src/LegacyApp.tsx` is frozen compatibility. New product work belongs
  in the current UI; removal requires parity, telemetry and rollback evidence.
- Keep feature state, API calls and view code near the feature that owns them.
  Do not grow `newUi.tsx`, `adminModels.tsx` or other protected hotspots for
  convenience when a bounded component/module is the natural owner.
- Use frontend/context maps and bounded symbol/range reads before opening large
  TSX/CSS files broadly.
- Decomposition is behavior-preserving. Do not combine extraction with visual
  redesign, navigation changes or unrelated cleanup.

## Styling and browser contracts

- CSS belongs to the owning feature/component/layout boundary. Avoid new global
  selectors when a local feature stylesheet is sufficient.
- Preserve desktop/mobile class and interaction contracts during extraction.
- Frontend identity is never authority: server-trusted sessions and backend
  authorization own access decisions.
- User-facing image model branding remains `Flux2`; technical model/workflow
  identifiers stay internal/admin-only.

## Frontend verification

- Run targeted component/unit checks after small edits, then type/lint/build as
  applicable; use focused Playwright for changed browser behavior.
- UI acceptance requires the relevant desktop/mobile behavior evidence, not
  merely HTTP 200 or a successful bundle.
- Generated frontend maps change through their generator, not manual edits.
