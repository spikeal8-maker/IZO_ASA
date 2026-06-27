# SQLite Migration Rules

* SQLite schema changes must be additive.
* Use `CREATE TABLE IF NOT EXISTS` for new tables.
* Use `CREATE INDEX IF NOT EXISTS` for indexes.
* Use `ALTER TABLE ADD COLUMN` only for safe nullable/default-safe columns.
* Do not drop tables.
* Do not drop columns.
* Do not rename `users.id`.
* Do not rewrite `users` table.
* Do not mass update `users.id`.
* Do not touch production database.
* Before any migration, ensure a backup exists.
* `init_db` must remain idempotent.
* Existing `users`, `jobs`, `images` and `token_ledger` data must survive repeated
  `init_db` runs.
