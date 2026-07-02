# Bot Work Instructions

Use this as the standard instruction block for any secondary bot or agent.

## Required First Step

Before coding, read:

- `README.md`
- `CLAUDE.md`
- `TEST_PLAN.md`
- `docs/documentation-map.md`
- `docs/current-architecture.md`
- `docs/auth-current-state.md`
- `docs/release-checklist.md`
- `docs/collaboration-rules.md`

If working on `/new`, also read:

- `docs/new-ui-v2-plan.md`
- `docs/new-ui-v2-review.md`

## Required Report Before Coding

Return:

- branch;
- documents read;
- files you plan to touch;
- files you will not touch;
- risks;
- tests planned.

## Coding Rules

- Work on a dedicated branch.
- Do not work directly on `main`.
- Do not use `git add .`.
- Do not commit secrets, DB, logs, screenshots, backups, dist, node_modules or cache files.
- Do not deploy unless explicitly asked.
- Update docs with behavior changes.
- Keep one task per branch.

## Security Rules

Never use as auth:

- `X-OneNode-User`
- `onenode_user`
- `demo_user`
- query/body `userId`
- provider username/phone/email
- Telegram `initDataUnsafe`
- unsigned MAX payload

## Required Final Report

```text
Branch:
Commit:
Files changed:
Docs updated:
Tests run:
Screenshots/artifacts:
Security checks:
Known issues:
Ready for review: yes/no
```

