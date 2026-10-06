# eBichelchen for Home Assistant

Unofficial, read-only Home Assistant custom integration for Luxembourg's eBichelchen. Designed for installation through HACS as a **custom repository**.

**Initial version: not yet tested against a live IAM login or inside a running Home Assistant installation.** The protocol was reconstructed from a browser capture dated 6 October 2026. 44 automated tests pass against Home Assistant 2025.4.4 and Python 3.13. Tests use synthetic data; newer Home Assistant versions have not yet been run in this test environment. Education.lu does not publish a compatibility contract for these private endpoints; a login-page or API change can require an integration update.

## What it does

- Setup through **Settings → Devices & services → Add integration → eBichelchen**.
- Enter an IAM username and password. No manual cookie copying or separate Docker service.
- Student accounts: discover the signed-in student's calendar.
- Parent accounts: discover children returned by the authorized parent endpoint and select calendars. This endpoint was found in the application's JavaScript; the supplied capture exercised a student account only.
- Create one native, read-only `calendar` entity per selected student.
- Include entry titles, descriptions and subtask descriptions.
- Default refresh every **30 minutes**; configurable from **15 minutes to 24 hours**.
- Reuse session cookies in memory; renew after expiry and retry the failed call once.
- Prompt for reauthentication after a rejected password, instead of repeatedly submitting it.
- Calendar views fetch their requested weeks on demand. Entity state looks ahead 28 days. Week results are cached for the selected refresh interval.

## Requirements

- Home Assistant Core **2025.4.4 or newer**.
- A student or parent **IAM username/password** account with access to eBichelchen.
- Network access from Home Assistant to `ssl.education.lu`, `auth.education.lu`, and `iam.auth.education.lu` using HTTPS.
- eduKey/MFA, LuxTrust/eID, affiliate IAM, teacher and supervisor accounts are not supported in this version. There is no attempt to bypass interactive authentication.

## Installation with HACS

Repository: https://github.com/defuuss/ha-ebichelchen

[Open this repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=defuuss&repository=ha-ebichelchen&category=integration)

1. Open **HACS → ⋮ → Custom repositories**.
2. Add that URL with type **Integration**.
3. Download **eBichelchen** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and search for **eBichelchen**.
5. Enter your IAM credentials, choose the student(s), and set the refresh interval.

This is a HACS custom repository, not a listing in HACS's default catalog. HACS requires the GitHub repository to be public. Only code and synthetic tests belong in the repository; do not upload HARs or school data.

### Manual installation

Copy `custom_components/ebichelchen` into your Home Assistant `/config/custom_components/` directory, restart, and add the integration as above. No YAML is required.

## New or existing calendar?

The integration creates **its own calendar entities**, backed directly by the school data. It does not copy events into Google Calendar, a Home Assistant Local Calendar, or another writable calendar.

To see school events together with an existing calendar, add both entities to the same Home Assistant Calendar card. For example, replacing the entity IDs with the ones in your system:

```yaml
type: calendar
initial_view: dayGridMonth
entities:
  - calendar.family
  - calendar.ebichelchen_demo_student
```

A future optional export/synchronization feature would need a persistent mapping between school event IDs and destination event IDs to update or remove only its own events and avoid duplicates. It is deliberately not implemented in this release.

## Refresh interval versus session lifetime

Under **Settings → Devices & services → eBichelchen → Configure**, change the polling interval. Saving reloads the integration, closes the old session, and creates a new one.

The session lifetime is controlled by Education.lu and is separate from the refresh interval. A cookie expiry timestamp does not prove that the server-side session is still valid. The client therefore:

1. Reuses its authenticated cookie jar.
2. Fetches calendar data at the chosen interval or when a calendar view requests an uncached week.
3. On HTTP 401, an authentication redirect or a login HTML response, logs in again and retries once.
4. On HTTP 403, reports denied access without repeating the password.
5. On rejected credentials, requests Home Assistant reauthentication and stops further automatic credential attempts for that client instance.

Cookies remain in memory and are recreated after a Home Assistant restart. Background polling preloads the current and following four weeks per student (usually five weekly API calls per full refresh). Browsing other dates can cause additional calls; refresh interval is not a strict limit on on-demand requests. API caching avoids duplicate calls inside that interval. Normal Home Assistant retry behavior applies during outages.

## Date behavior and limitations

- School timezone: **Europe/Luxembourg**, including winter/summer time; the HTTP library encodes query parameters.
- Midnight entries without an end time become one-day all-day events. A time written in the description, such as “19:30”, is preserved as text and is not guessed to be a structured start time.
- Explicit time ranges retain their times. A timed entry with no end uses a one-hour display duration.
- Explicit end dates are treated as exclusive. Multi-day semantics still need confirmation with a real example; the supplied sample only had date-only entries with no end.
- Recurrences are expected to be expanded by the weekly endpoint, as used by the web application. No local recurrence rules are invented. Cross-week multi-day and recurrence behavior needs live verification.
- No attachment downloads, absence management, marking homework complete, or writes to eBichelchen.
- Adding newly linked children currently requires removing and adding the integration again.

## Credentials and privacy

Home Assistant stores the username and password in its local config entry so that it can renew sessions. **This is not encrypted secret storage**: administrators and anyone with access to Home Assistant's config/backups can access those credentials. Protect the configuration and backups accordingly.

The integration uses an isolated cookie jar per account, validates HTTPS destinations at every redirect, and submits passwords only to the observed IAM login endpoint. It does not log credentials, SAML assertions, raw response bodies or URL query strings. No telemetry or external proxy is used.

Do not attach full HAR files to public issues. For troubleshooting, share the displayed error and the integration/Home Assistant versions. Never share IAM passwords, cookies or SAML responses.

## Development

```sh
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
python -m pytest
ruff check .
ruff format --check .
```

Tests cover synthetic SAML discovery/handoffs, redirect restrictions, session renewal, rejected credentials, student discovery, week caching, daylight saving offsets, calendar boundaries, config flow and reauthentication. They do not prove a real IAM login succeeds. GitHub workflows also provide HACS and hassfest checks once the repository is published.

Not affiliated with or endorsed by Education.lu, CGIE, Home Assistant, or HACS.

## License

GNU General Public License v3.0; see [LICENSE](LICENSE).

## Troubleshooting downloads and setup

If HACS requests an archive under `refs/heads/<short-commit>.zip` and receives 404, refresh the repository information and use **Redownload** to select a named release, such as **v0.1.4**. If no release is listed yet, select **main**. Restart Home Assistant after a successful download. A failed download can leave an older integration installed.

The Home Assistant warning that a custom integration has not been tested by Home Assistant is expected; it does not itself mean installation or authentication failed.

Version 0.1.3 and later display the integration's safe error reason in setup and logs it under `custom_components.ebichelchen.config_flow`. Share that line if setup fails. Optional debug logging for `custom_components.ebichelchen.api` records fixed login-step names and HTTP status codes only. No raw requests or responses are logged.

GitHub Actions publishes a named release after the tests and hassfest pass on `main`, when the manifest version has not been released before. New stable releases are explicitly marked **Latest** on GitHub; existing releases are left unchanged. The [latest release link](https://github.com/defuuss/ha-ebichelchen/releases/latest) always points to the current stable release. HACS exposes an update entity for the installed integration and checks for available updates. Unattended installation requires a Home Assistant automation using `update.install` for that entity; a Home Assistant restart is required to load updated integration code. See the [HACS update entity documentation](https://www.hacs.dev/docs/use/entities/update/).

Version 0.1.4 fixes `IAM discovery did not return JSON (HTTP 404)` by sending the AJAX headers used by the Education.lu login page. A live request with a dummy username reproduced HTTP 404 without those headers and HTTP 200 with them. Full account login still needs verification on your installation.
