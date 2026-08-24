# Windows project release promoter

`promote-project-release.ps1` is the tracked source for the installed
`C:\IZO_ASA\runtime\promote-project-release.ps1` release switcher.

Availability invariants:

- the global promotion mutex permits one release owner;
- the rollback database is created through `tools/sqlite_hot_backup.py` while
  the current backend is still serving;
- only the short service/config switch happens after the online snapshot;
- an automatic additive-schema rollback restores code and configuration but
  never overwrites the live database;
- the outer cleanup attempts to leave backend and Caddy running;
- production installation must compare the normalized tracked and runtime
  scripts and record the exact release SHA.

Install the promoter only from an exact clean commit. The installer creates a
rollback copy and a machine-readable receipt, and it does not restart services:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\ops\release\install-project-promoter.ps1 `
  -ExpectedCommit <40-character-clean-commit-sha>
```
