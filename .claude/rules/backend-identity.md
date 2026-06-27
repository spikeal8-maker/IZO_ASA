# Backend Identity Rules

* `users.id` is legacy and must remain stable.
* `users.internal_user_id` is the new canonical identity id.
* `auth_identities` maps `provider` + `provider_user_id` to `internal_user_id`.
* `auth_sessions` maps trusted server sessions to `internal_user_id` and legacy `users.id`.
* Do not use `provider_user_id` as internal identity.
* Do not create duplicate users for the same provider identity.
* Telegram provider identity is valid only after server-side `initData` validation.
* MAX provider identity is valid only after server-side `WebAppData` validation.
* Existing `jobs` / `images` / `token_ledger` should continue using legacy `users.id` until
  later migration.
* New v2 auth endpoints should use `internal_user_id`.
