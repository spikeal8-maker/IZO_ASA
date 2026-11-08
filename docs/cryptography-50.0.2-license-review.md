# cryptography 50.0.2 — exact dependency license review

Tracked review: [#281](https://github.com/spikeal8-maker/IZO_ASA/issues/281).
Owner: `spikeal8-maker`; reviewed on 2026-11-08; review due 2027-02-06.

## Decision and scope

The exact scanner tuple is `backend / cryptography / 50.0.2 /
Apache-2.0 OR BSD-3-Clause / unknown`. The verified upstream expression is
`Apache-2.0 OR BSD-3-Clause`. The BSD-3-Clause option is selected for this pinned
dependency: retain copyright, license conditions and disclaimers in redistributed
source and binary notices; do not imply endorsement. Preserve distributed
upstream notices. This review does not approve another version, a different
scanner tuple, or unrelated bundled components.

The existing `licenses.reviews` mechanism records this decision. Approved
expressions, scanner versions, classification, vulnerability exceptions and
fail-closed rules remain unchanged. Expiry and nonmatching tuples still fail.

## Verified primary artifacts

PyPI metadata: <https://pypi.org/pypi/cryptography/50.0.2/json>.
Source archive: [cryptography-50.0.2.tar.gz](https://files.pythonhosted.org/packages/9d/af/182eb91b0df3fe75c4d9f26fe70684569566745f6ba7e5c9c73a862c5252/cryptography-50.0.2.tar.gz),
880623 bytes, SHA256
`7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5`.

Tag `50.0.2` resolves through annotated tag
`ccdf2da1cce4798ab0ea226693a074eef536c16e` to immutable commit
`4dda5c7fe4ae71b8925f2551910a0ef959df9c7a`.

| Upstream file | Bytes | SHA256 |
|---|---:|---|
| [LICENSE](https://github.com/pyca/cryptography/blob/4dda5c7fe4ae71b8925f2551910a0ef959df9c7a/LICENSE) | 197 | `3e0c7c091a948b82533ba98fd7cbb40432d6f1a9acbf85f5922d2f99a93ae6bb` |
| [LICENSE.BSD](https://github.com/pyca/cryptography/blob/4dda5c7fe4ae71b8925f2551910a0ef959df9c7a/LICENSE.BSD) | 1532 | `602c4c7482de6479dd2e9793cda275e5e63d773dacd1eca689232ab7008fb4fb` |
| [LICENSE.APACHE](https://github.com/pyca/cryptography/blob/4dda5c7fe4ae71b8925f2551910a0ef959df9c7a/LICENSE.APACHE) | 11360 | `aac73b3148f6d1d7111dbca32099f68d26c644c6813ae1e4f05f6579aa2663fe` |

Native read-only operation `de51957235654896bc8e5d6450305ccf` verified the PyPI
archive digest and all three license files byte-for-byte against that immutable
commit. It performed no filesystem extraction, package execution or live change.

## Gate evidence boundary

PR280 head `a20e0b7fe8e07e2fdeb3264b1a316346d21aee94`, Windows run
`42491172145`, stopped at this unreviewed license tuple before full pytest.
Artifact `13621866116` SHA256 is
`dfb58ea6fe16826e59172cc6514c88dc815e09f90fad66a8457724cec9f1b7c8`.
Reevaluating that report checks this policy correction; it does not replace
fresh exact-head supply-chain scans, full CI, or installed Linux acceptance.
