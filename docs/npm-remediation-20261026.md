# Supply-chain remediation, 2026-10-26

Owner-authorized blocker remediation for the shared Qwen rollout; no deployment.
The default prohibition on automatic dependency mutation, `npm audit fix`,
`npm update`, untracked high/critical findings and unavailable scanners remains.
This bounded reviewed dependency/lockfile delta resolves issues #154 and #155
instead of extending their expired exceptions. Historical exception regression
cases now read an explicitly dated test fixture, not the active policy.

## Dependency changes

Vite's safe floor is raised from8.0.16 to`^8.1.6`; the lockfile resolves8.3.5.
Explicit compatible-major
transitive floors resolve browserslist4.29.4, nanoid3.3.20, postcss8.5.31,
zod4.6.7 and baseline-browser-mapping2.11.33. All are development-only in the
lockfile; no production dependency or backend requirement changes.

Fresh full and production audits, build and focused checks are required on the
final SHA. Historical counts are not accepted as fresh evidence.

## Exact-version license review

These are current reviews of primary evidence, not a blanket acceptance of
unknown licenses. Both keep the scanner's exact classification and expire on
2027-01-24; a different version or license still requires review. Copyright and
permission notices must accompany redistribution. No backend dependency changes.

- Pillow12.3.0: [immutable upstream LICENSE](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/LICENSE)
  matches PyPI's `license_expression: MIT-CMU` and the
  [SPDX MIT-CMU identifier](https://spdx.org/licenses/MIT-CMU.html).
  LICENSE SHA-256: `15181e7363dca9aed78b79bebebc7fde7f1814b8bd311ea3b87ae8ccadfc185b`.
  Retain notices and the license's no-endorsement condition.
- socksio1.0.0: PyPI wheel metadata omits a license, but its bundled LICENSE
  exactly matches the [immutable upstream MIT LICENSE](https://github.com/sethmlarson/socksio/blob/e69158473125060879319368e9465d7881cee0b8/LICENSE).
  Wheel SHA-256: `95dc1f15f9b34e8d7b16f06d74b8ccf48f609af32ab33c608d08761c5dcbb1f3`.
  Bundled/upstream LICENSE SHA-256:
  `7087f0f5f7c2993f3c4ed117baa3622c1063626e7c692e9ea116475b5fc1396c`.
  The policy continues to match only this exact `UNKNOWN` scanner finding;
  it does not approve `UNKNOWN` globally. Tracking: #156.

## Rollback and limits

Revert the dependency, lockfile and active-policy commit together. Reverting
restores the former fail-closed expired baseline; it is not release permission.
No runtime, database, provider, image model or text-model state is changed.
