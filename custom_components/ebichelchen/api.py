"""Private asynchronous client. Never log credentials, URLs with state, or bodies."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from time import monotonic
from urllib.parse import urljoin, urlsplit

import aiohttp
from bs4 import BeautifulSoup
from yarl import URL

from .const import ALLOWED_HOSTS, API_URL, SCHOOL_TZ

_LOGGER = logging.getLogger(__name__)


def endpoint_label(url: str) -> str:
    """Use fixed labels so redirect URLs cannot leak state into diagnostics."""
    return {
        "/ebichelchen/app/api/login": "login_start",
        "/module.php/IAM/idpSelection.php": "iam_discovery",
        "/module.php/core/loginuserpass": "iam_password",
        "/module.php/saml/disco": "iam_selection",
        "/module.php/saml/sp/discoResponse": "iam_selection_handoff",
        "/module.php/saml/idp/singleSignOnService": "saml_sign_on",
        "/module.php/saml/sp/saml2-acs.php/default": "saml_identity_handoff",
        "/ebichelchen/app/saml/sso": "saml_application_handoff",
        "/ebichelchen/app/api/v2/get-user": "user_profile",
        "/ebichelchen/app/api/v2/fetch-students-for-parent": "student_list",
        "/ebichelchen/app/api/v4/fetch-entries-for-week": "calendar_week",
    }.get(urlsplit(url).path, "authentication_redirect")


class EbichelchenError(Exception):
    """Safe error whose text contains no server-supplied personal information."""


class CannotConnect(EbichelchenError):
    """Transport failure."""


class InvalidAuth(EbichelchenError):
    """Credentials rejected or login session could not be established."""


class UnsupportedAuth(InvalidAuth):
    """Interactive MFA, LuxTrust, or an unknown authentication flow."""


class AccessDenied(EbichelchenError):
    """The account is not authorized for the requested resource."""


class InvalidResponse(EbichelchenError):
    """Unexpected API or HTML schema."""


class UnsupportedRole(EbichelchenError):
    """Only student and parent accounts are supported."""


class SessionExpired(EbichelchenError):
    """Internal signal: one automatic login retry is permitted."""


@dataclass
class Page:
    url: str
    status: int
    text: str
    content_type: str = ""


def validate_url(url: str) -> None:
    """Do not send cookies or SAML assertions outside the observed HTTPS hosts."""
    p = urlsplit(url)
    try:
        valid = p.scheme == "https" and p.hostname in ALLOWED_HOSTS and p.port in (None, 443)
    except ValueError:
        valid = False
    if not valid or p.username or p.password:
        raise UnsupportedAuth("Unexpected authentication destination")


def form_data(form) -> dict[str, str]:
    """Preserve hidden dynamic fields; do not click unrelated submit buttons."""
    result = {}
    for field in form.find_all("input"):
        name = field.get("name")
        kind = field.get("type", "text").lower()
        if not name or field.has_attr("disabled") or kind in ("submit", "button", "file", "reset"):
            continue
        if kind in ("radio", "checkbox") and not field.has_attr("checked"):
            continue
        result[name] = field.get("value", "")
    return result


def week_parameter(day: date) -> str:
    """Match the browser's date + offset format, including Luxembourg DST."""
    offset = datetime.combine(day, time.min, SCHOOL_TZ).strftime("%z")
    return f"{day.isoformat()} {offset[:3]}:{offset[3:]}"


class EbichelchenClient:
    """One cookie jar and one lock per account; no disk cookie persistence."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        cache_seconds: int = 1800,
    ):
        self.session = session
        self.username = username
        self.password = password
        self.cache_seconds = cache_seconds
        self._lock = asyncio.Lock()
        self._authenticated = False
        self._cache: dict[tuple[str, date], tuple[float, list[dict]]] = {}
        self._auth_failed = False

    async def _request(
        self,
        method: str,
        url: str,
        *,
        data=None,
        params=None,
        headers=None,
        follow=True,
        credentials=False,
    ) -> Page:
        """Validate every redirect, with finite timeouts and bounded response bodies."""
        try:
            for _ in range(15):
                validate_url(url)
                if credentials and (
                    urlsplit(url).hostname != "iam.auth.education.lu"
                    or urlsplit(url).path != "/module.php/core/loginuserpass"
                ):
                    raise UnsupportedAuth("Unexpected credential destination")
                async with self.session.request(
                    method,
                    # SAML Redirect signatures cover the original URL-encoded
                    # query. Requoting it invalidates the signature. Requests
                    # with new query parameters still use normal encoding.
                    URL(url, encoded=True) if params is None else url,
                    data=data,
                    params=params,
                    headers=headers,
                    allow_redirects=False,
                ) as response:
                    chunks = []
                    size = 0
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > 4 * 1024 * 1024:
                            raise InvalidResponse("Response exceeds size limit")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    page = Page(
                        str(response.url),
                        response.status,
                        raw.decode("utf-8-sig", errors="replace"),
                        response.headers.get("Content-Type", ""),
                    )
                    location = response.headers.get("Location")
                _LOGGER.debug(
                    "eBichelchen step=%s method=%s status=%d",
                    endpoint_label(page.url),
                    method,
                    page.status,
                )
                params = None
                if follow and page.status in (301, 302, 303, 307, 308):
                    if not location:
                        raise InvalidResponse("Redirect has no destination")
                    url = urljoin(page.url, location)
                    validate_url(url)
                    # Request-specific headers (including Referer) belong only
                    # to the original destination, not a later SAML redirect.
                    headers = None
                    if page.status == 303 or (page.status in (301, 302) and method == "POST"):
                        method, data, credentials = "GET", None, False
                    continue
                if page.status == 429 or page.status >= 500:
                    raise CannotConnect(
                        f"Education.lu returned HTTP {page.status} at {endpoint_label(page.url)}"
                    )
                return page
            raise InvalidResponse("Too many redirects")
        except (aiohttp.ClientError, TimeoutError, UnicodeError):
            raise CannotConnect("Unable to connect to Education.lu") from None

    @staticmethod
    def _decode(page: Page):
        if page.status == 401 or page.status in (301, 302, 303, 307, 308):
            raise SessionExpired()
        if page.status == 403:
            raise AccessDenied("Account is not authorized for this resource")
        if page.status != 200:
            raise InvalidResponse(
                f"Unexpected API status: HTTP {page.status} at {endpoint_label(page.url)}"
            )
        if "text/html" in page.content_type.lower() or page.text.lstrip().startswith("<"):
            raise SessionExpired()
        try:
            payload = json.loads(page.text.lstrip("\ufeff"))
        except (ValueError, TypeError):
            raise InvalidResponse(
                f"Expected JSON at {endpoint_label(page.url)} (HTTP {page.status})"
            ) from None
        if not isinstance(payload, dict) or payload.get("code") != 0 or "objects" not in payload:
            code = payload.get("code") if isinstance(payload, dict) else None
            safe_code = str(code) if type(code) is int else "missing/non-numeric"
            raise InvalidResponse(
                f"Unexpected API envelope at {endpoint_label(page.url)} (HTTP {page.status}, code={safe_code})"
            )
        return payload["objects"]

    async def _login(self) -> None:
        """Run the observed IAM discovery and two-stage SAML POST flow."""
        self._authenticated = False
        self.session.cookie_jar.clear()
        page = await self._request(
            "GET", API_URL + "/login", params={"redirectTo": "/ebichelchen/app"}
        )
        submitted_password = False
        for _ in range(12):
            p = urlsplit(page.url)
            if (
                p.hostname == "ssl.education.lu"
                and p.path.startswith("/ebichelchen/app")
                and page.status == 200
            ):
                # A redirect to the app alone is not proof: verify the user API.
                check = await self._request("GET", API_URL + "/v2/get-user", follow=False)
                try:
                    user = self._decode(check)
                except SessionExpired:
                    raise InvalidAuth("Login did not establish a session") from None
                if not isinstance(user, dict) or not user.get("id"):
                    raise InvalidResponse("Missing account identity")
                self._authenticated = True
                return
            soup = BeautifulSoup(page.text, "html.parser")
            saml_input = soup.find("input", attrs={"name": "SAMLResponse"})
            password_input = soup.find("input", attrs={"type": "password"})
            username_input = soup.find("input", attrs={"name": "username"})
            if saml_input is not None:
                form = saml_input.find_parent("form")
                if form is None or form.get("method", "get").lower() != "post":
                    raise InvalidResponse("Invalid SAML form")
                page = await self._request(
                    "POST", urljoin(page.url, form.get("action", "")), data=form_data(form)
                )
            elif password_input is not None:
                if submitted_password:
                    raise InvalidAuth("IAM rejected the credentials")
                form = password_input.find_parent("form")
                if form is None or form.get("method", "get").lower() != "post":
                    raise UnsupportedAuth("Unsupported IAM login form")
                data = form_data(form)
                data.update(username=self.username, password=self.password)
                submitted_password = True
                page = await self._request(
                    "POST", urljoin(page.url, form.get("action", "")), data=data, credentials=True
                )
            elif (
                username_input is not None
                and p.hostname == "auth.education.lu"
                and p.path == "/module.php/saml/disco"
            ):
                form = username_input.find_parent("form")
                if form is None:
                    raise InvalidResponse("Discovery form missing")
                discovery = await self._request(
                    "GET",
                    "https://auth.education.lu/module.php/IAM/idpSelection.php",
                    params={"username": self.username},
                    # This endpoint returns 404 for ordinary requests. Match
                    # the discovery page's jQuery getJSON request.
                    headers={
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": page.url,
                    },
                    follow=False,
                )
                if discovery.status != 200:
                    raise InvalidResponse(f"IAM discovery returned HTTP {discovery.status}")
                try:
                    choice = json.loads(discovery.text.lstrip("\ufeff"))
                except ValueError:
                    raise InvalidResponse(
                        f"IAM discovery did not return JSON (HTTP {discovery.status})"
                    ) from None
                if not isinstance(choice, dict) or choice.get("syntax") != "OK":
                    raise InvalidAuth("IAM username was not accepted")
                if choice.get("auth") != "urn:x-auth-education-lu:auth:iam":
                    raise UnsupportedAuth("This account requires an unsupported login method")
                button = "idp_" + choice["auth"]
                if form.find(attrs={"name": button}) is None:
                    raise UnsupportedAuth("IAM option missing from discovery form")
                data = form_data(form)
                data.update({"username": self.username, button: ""})
                action = urljoin(page.url, form.get("action", ""))
                method = form.get("method", "get").upper()
                page = await self._request(
                    method, action, **({"params": data} if method == "GET" else {"data": data})
                )
            else:
                raise UnsupportedAuth("Login requires interaction or the login page has changed")
        raise InvalidAuth("Authentication did not complete")

    async def _api(self, path: str, *, method="GET", params=None):
        """Caller holds lock. Never repeat a rejected password on each poll."""
        if self._auth_failed:
            raise InvalidAuth("Reauthentication is required")
        try:
            if not self._authenticated:
                await self._login()
            for attempt in range(2):
                page = await self._request(method, API_URL + path, params=params, follow=False)
                try:
                    return self._decode(page)
                except SessionExpired:
                    self._authenticated = False
                    if attempt:
                        raise InvalidAuth("Session was rejected after login") from None
                    await self._login()
        except InvalidAuth:
            self._auth_failed = True
            raise

    async def account(self) -> tuple[str, dict[str, str]]:
        """Discover only students authorized by the server."""
        async with self._lock:
            user = await self._api("/v2/get-user")
            if not isinstance(user, dict) or not user.get("id"):
                raise InvalidResponse("Missing account identity")
            role = user.get("activeRole")
            if role == 0:
                students = [user]
            elif role == 3:
                students = await self._api("/v2/fetch-students-for-parent", method="POST")
            else:
                raise UnsupportedRole("Use a student or parent account")
            if not isinstance(students, list) or any(
                not isinstance(s, dict) or not s.get("id") for s in students
            ):
                raise InvalidResponse("Unexpected student list")
            return str(user["id"]), {
                str(s["id"]): s.get("fullName")
                or " ".join(filter(None, [s.get("firstName"), s.get("lastName")]))
                or "Student"
                for s in students
            }

    async def entries(self, student_id: str, start: date, end: date) -> list[dict]:
        """Fetch weeks intersecting [start, end); server expands recurring entries."""
        if end <= start:
            return []
        if (end - start).days > 370:
            raise InvalidResponse("Request at most one year at a time")
        monday = start - timedelta(days=start.weekday())
        result = {}
        async with self._lock:
            # Bound cached student data; expired entries are discarded.
            now = monotonic()
            self._cache = {k: v for k, v in self._cache.items() if now - v[0] < self.cache_seconds}
            while monday < end:
                key = (student_id, monday)
                cached = self._cache.get(key)
                if cached is None:
                    rows = await self._api(
                        "/v4/fetch-entries-for-week",
                        params={
                            "studentId": student_id,
                            "dateLocatedInWeek": week_parameter(monday),
                        },
                    )
                    if not isinstance(rows, list) or any(
                        not isinstance(r, dict) or not r.get("startDate") or r.get("id") is None
                        for r in rows
                    ):
                        raise InvalidResponse("Unexpected calendar entries")
                    self._cache[key] = (monotonic(), rows)
                else:
                    rows = cached[1]
                for row in rows:
                    result[(str(row["id"]), row["startDate"])] = row
                monday += timedelta(days=7)
        return list(result.values())
