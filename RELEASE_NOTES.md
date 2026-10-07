## eBichelchen v0.1.5

- Fix HTTP 500 during the SAML redirect before the IAM password form. Preserve the original URL encoding so the HTTP client does not alter the signed query string.
- Keep normal query encoding for newly constructed API and discovery requests.
- Show the HTTP status and a fixed step label in connection errors, including the setup form. No credentials, signed URLs, cookies or response bodies are logged.

Validation: 49 synthetic tests pass with Home Assistant 2025.4.4 and Python 3.13, plus lint/format checks and offline login replay. A live public IAM selection check with a dummy username reproduced the failure with normal URL encoding and reached the password form (HTTP 200) when the signed URL was preserved. No password was submitted; full account login remains to be verified on the user's installation.

Update to **v0.1.5** through HACS, restart Home Assistant, and retry eBichelchen setup.
