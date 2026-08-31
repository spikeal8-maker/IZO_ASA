# Windows project release promoter

`promote-project-release.ps1` is the tracked source for the installed
`C:\IZO_ASA\runtime\promote-project-release.ps1` release switcher.

Availability invariants:

- promotion runs only from an elevated Windows Administrator process; a
  medium-integrity Codex/terminal process must stop before invoking WinSW;
- `install-project-promoter.ps1 -VerifyOnly` proves the normalized tracked,
  installed and receipt hashes agree before candidate preparation;
- the installed promoter independently compares itself with the candidate's
  tracked promoter before backup or service control;
- the global promotion mutex permits one release owner;
- the promoter fails closed unless the installed health check recognizes
  `C:\IZO_ASA\runtime\project-release-maintenance.flag`;
- the promoter creates that flag before the rollback snapshot/service switch and
  removes it from its outer cleanup; while present, health recovery must not
  auto-start `IZOBackend` or `IZOCaddy`;
- the rollback database is created through `tools/sqlite_hot_backup.py` while
  the current backend is still serving;
- only the short service/config switch happens after the online snapshot;
- an automatic additive-schema rollback restores code and configuration but
  never overwrites the live database;
- the outer cleanup attempts to leave backend and Caddy running;
- production installation must compare the normalized tracked and runtime
  scripts and record the exact release SHA.

The complete operator and agent procedure is
[`docs/production-release-runbook.md`](../../docs/production-release-runbook.md).
Do not install this promoter until the runtime health check has the maintenance
guard and its previous version has been backed up.

Install the promoter only from an exact clean commit. The installer creates a
rollback copy and a machine-readable receipt, and it does not restart services:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\ops\release\install-project-promoter.ps1 `
  -ExpectedCommit <40-character-clean-commit-sha>
```

Before every promotion, from the same exact clean commit, verify the installed
copy without changing runtime state:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\ops\release\install-project-promoter.ps1 `
  -ExpectedCommit <40-character-clean-commit-sha> `
  -VerifyOnly
```

`PROMOTER_VERIFY_FAILED` is a hard stop. Install the promoter through the
installer and re-run all preflight gates; never run the stale installed script.
