## eBichelchen v0.1.4

- Fix the IAM discovery HTTP 404 by sending the same AJAX headers as the Education.lu login page (`X-Requested-With`, JSON `Accept`, and the discovery-page `Referer`).
- Reject unsuccessful discovery HTTP responses before parsing or submitting credentials.
- Keep request-specific headers out of subsequent redirects.
- Add regression tests for the AJAX request, redirect header handling, and unsuccessful discovery responses.

Validation: 44 synthetic tests against Home Assistant 2025.4.4 and Python 3.13, lint/format checks, and offline replay of the supplied browser login capture. A live discovery request using a dummy username reproduced HTTP 404 without AJAX headers and HTTP 200 with them. Full live account authentication remains to be verified on the user's installation.

In HACS, refresh repository information, select **v0.1.4** under **Redownload**, and restart Home Assistant before retrying setup. The standard Home Assistant warning about an untested custom integration is expected.
