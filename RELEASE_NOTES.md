## eBichelchen v0.1.3

- Provide a named GitHub release so HACS can download a versioned source archive instead of selecting a short commit ID as a branch.
- Show the safe error reason in the setup form and Home Assistant log when an API response cannot be parsed.
- Add optional debug traces containing only fixed step labels, HTTP methods and status codes. Passwords, cookies, SAML assertions, response bodies and URL parameters are excluded.
- Accept an optional UTF-8 byte-order mark in JSON responses.
- Keep the Home Assistant compatible BeautifulSoup minimum requirement introduced in v0.1.2.

After refreshing repository information in HACS, select **v0.1.3** under **Redownload**, then restart Home Assistant.

This is an initial unofficial integration. Synthetic tests and offline replay of the supplied login capture pass; live IAM authentication remains to be verified on the user's installation. If setup still fails, send the new detailed error shown by eBichelchen, not a password or full HAR.
