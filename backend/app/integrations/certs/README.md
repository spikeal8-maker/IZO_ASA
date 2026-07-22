# MAX provider trust anchor

`russian_trusted_root_ca.pem` is the Russian Trusted Root CA used by the
certificate chain currently served by `platform-api2.max.ru`. The application
loads it only into the dedicated MAX HTTP client context; it is not installed
into Windows and does not change trust for any other integration.

- Source: `https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt`
- Retrieved: 2026-07-23
- Source-download SHA-256: `936a43fea6e8e525bcc0f81acd9c3d21b4fc4b9b68acea7906d698005afc6504`
- Bundled PEM SHA-256 (LF-normalized): `aa800ef345422d6158c6fafe1c06c429dbda21c3df4bb1ccb45a920ec1111399`
- Certificate SHA-1 fingerprint: `8ff915ccab7bc16f8c5c8099d53e0e115b3aec2f`
- Subject: `Russian Trusted Root CA`
- Valid through: 2032-02-27
