# GitHub Copilot instructions for IZO_ASA

Read and follow the repository-root `AGENTS.md` before proposing or applying any
change. `AGENTS.md` is authoritative for canonical workspace, production safety,
security, bot ownership, modularization, testing, commits and releases.

This is a live modular-monolith product. Preserve compatibility, keep tests away
from production DB/media/providers, place new backend logic under `backend/app`,
never raise protected-file budgets just to pass a gate, and update generated maps
in the same code-bearing commit.
