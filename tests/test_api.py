"""Synthetic protocol tests. No HARs, real credentials or school data in fixtures."""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from yarl import URL

from custom_components.ebichelchen.api import (
    AccessDenied,
    CannotConnect,
    EbichelchenClient,
    InvalidAuth,
    InvalidResponse,
    Page,
    UnsupportedAuth,
    validate_url,
    week_parameter,
)
from custom_components.ebichelchen.const import API_URL


def envelope(objects, status=200):
    return Page(
        API_URL + "/v2/get-user",
        status,
        json.dumps({"code": 0, "objects": objects}),
        "application/json",
    )


@pytest.fixture
def client():
    return EbichelchenClient(MagicMock(), "demo-user", "demo-password")


@pytest.mark.parametrize(
    "day,expected",
    [(date(2026, 10, 6), "2026-10-06 +02:00"), (date(2026, 11, 2), "2026-11-02 +01:00")],
)
def test_dst_parameter(day, expected):
    assert week_parameter(day) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://auth.education.lu/login",
        "https://auth.education.lu.evil.test/",
        "https://evil.test/",
        "https://user:password@ssl.education.lu/",
        "https://ssl.education.lu:444/",
    ],
)
def test_auth_destination_allowlist(url):
    with pytest.raises(UnsupportedAuth):
        validate_url(url)


async def test_complete_login_flow(client):
    discovery = Page(
        "https://auth.education.lu/module.php/saml/disco",
        200,
        """<form method="get" action="/module.php/saml/disco"><input name="return" value="dynamic-state"><input name="username"><button name="idp_urn:x-auth-education-lu:auth:iam"></button></form>""",
    )
    login = Page(
        "https://iam.auth.education.lu/module.php/core/loginuserpass?AuthState=fresh",
        200,
        """<form method="post" action="?AuthState=fresh"><input name="username"><input type="password" name="password"><input type="hidden" name="csrf" value="fresh-csrf"></form>""",
    )
    saml1 = Page(
        login.url,
        200,
        """<form method="post" action="https://auth.education.lu/module.php/saml/sp/saml2-acs.php/default"><input type="hidden" name="SAMLResponse" value="synthetic-one"></form>""",
    )
    saml2 = Page(
        "https://auth.education.lu/module.php/saml/sp/saml2-acs.php/default",
        200,
        """<form method="post" action="https://ssl.education.lu/ebichelchen/app/saml/sso"><input type="hidden" name="SAMLResponse" value="synthetic-two"><input type="hidden" name="RelayState" value="new-state"></form>""",
    )
    client._request = AsyncMock(
        side_effect=[
            discovery,
            Page(discovery.url, 200, '{"syntax":"OK","auth":"urn:x-auth-education-lu:auth:iam"}'),
            login,
            saml1,
            saml2,
            Page("https://ssl.education.lu/ebichelchen/app/", 200, "<html/>"),
            envelope({"id": 123}),
        ]
    )
    await client._login()
    assert client._authenticated
    calls = client._request.call_args_list
    assert calls[1].kwargs["headers"] == {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": discovery.url,
    }
    assert calls[1].kwargs["follow"] is False
    assert calls[2].kwargs["params"]["return"] == "dynamic-state"
    assert "idp_urn:x-auth-education-lu:auth:iam" in calls[2].kwargs["params"]
    assert calls[3].args[1].endswith("?AuthState=fresh")
    assert calls[3].kwargs["data"] == {
        "username": "demo-user",
        "password": "demo-password",
        "csrf": "fresh-csrf",
    }
    assert calls[5].kwargs["data"]["RelayState"] == "new-state"


async def test_wrong_password_only_submitted_once(client):
    login = Page(
        "https://iam.auth.education.lu/module.php/core/loginuserpass",
        200,
        '<form method="post"><input name="username"><input name="password" type="password"></form>',
    )
    client._request = AsyncMock(side_effect=[login, login])
    with pytest.raises(InvalidAuth):
        await client._api("/v2/get-user")
    with pytest.raises(InvalidAuth):
        await client._api("/v2/get-user")
    assert client._request.call_count == 2


async def test_session_expiry_retries_once(client):
    client._authenticated = True
    client._request = AsyncMock(side_effect=[envelope(None, 401), envelope({"id": 123})])
    client._login = AsyncMock()
    assert await client._api("/v2/get-user") == {"id": 123}
    assert client._login.await_count == 1


async def test_expiry_after_renewal_stops(client):
    client._authenticated = True
    client._request = AsyncMock(return_value=envelope(None, 401))
    client._login = AsyncMock()
    with pytest.raises(InvalidAuth):
        await client._api("/v2/get-user")
    assert client._login.await_count == 1


async def test_forbidden_does_not_reauthenticate(client):
    client._authenticated = True
    client._request = AsyncMock(return_value=envelope(None, 403))
    client._login = AsyncMock()
    with pytest.raises(AccessDenied):
        await client._api("/v4/fetch-entries-for-week")
    client._login.assert_not_called()


async def test_student_and_parent_discovery(client):
    client._api = AsyncMock(return_value={"id": 123, "activeRole": 0, "fullName": "Demo Student"})
    assert await client.account() == ("123", {"123": "Demo Student"})
    client._api = AsyncMock(
        side_effect=[{"id": 456, "activeRole": 3}, [{"id": 123, "fullName": "Demo Student"}]]
    )
    assert await client.account() == ("456", {"123": "Demo Student"})
    assert client._api.call_args.args[0] == "/v2/fetch-students-for-parent"
    assert client._api.call_args.kwargs["method"] == "POST"


async def test_week_cache_and_deduplication(client):
    client._api = AsyncMock(return_value=[{"id": 1, "startDate": "2026-10-06T00:00:00"}])
    first = await client.entries("123", date(2026, 10, 5), date(2026, 10, 19))
    assert len(first) == 1
    assert client._api.call_count == 2
    assert await client.entries("123", date(2026, 10, 5), date(2026, 10, 19)) == first
    assert client._api.call_count == 2
    client.cache_seconds = 0
    await client.entries("123", date(2026, 10, 5), date(2026, 10, 12))
    assert client._api.call_count == 3


@pytest.mark.parametrize("payload", ["not-json", '{"code":1,"objects":[]}', '{"code":0}', "[]"])
def test_api_errors_never_look_like_empty_calendars(payload):
    with pytest.raises(InvalidResponse):
        EbichelchenClient._decode(Page(API_URL, 200, payload, "application/json"))


class FakeContent:
    async def iter_chunked(self, size):
        yield b'{"code":0,'
        yield b'"objects":[]}'


class FakeResponse:
    content = FakeContent()
    status = 302
    url = "https://iam.auth.education.lu/module.php/core/loginuserpass"
    headers = {"Location": "https://evil.test/capture"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


async def test_redirect_is_checked_before_request(client):
    client.session.request.return_value = FakeResponse()
    with pytest.raises(UnsupportedAuth):
        await client._request("GET", FakeResponse.url)
    assert client.session.request.call_count == 1


async def test_signed_redirect_query_is_preserved(client):
    signed_url = (
        "https://iam.auth.education.lu/module.php/saml/idp/singleSignOnService"
        "?SAMLRequest=demo%2Fvalue%2B%3D&SigAlg=https%3A%2F%2Fexample.test%2Fsig"
        "&Signature=demo%2Fsignature%2B%3D"
    )
    redirect = FakeResponse()
    redirect.headers = {"Location": signed_url}
    destination = FakeResponse()
    destination.url = signed_url
    destination.status = 200
    destination.headers = {}
    client.session.request.side_effect = [redirect, destination]
    await client._request("GET", redirect.url)
    sent_url = client.session.request.call_args_list[1].args[1]
    assert isinstance(sent_url, URL)
    assert str(sent_url) == signed_url
    assert sent_url.raw_query_string == signed_url.split("?", 1)[1]
    assert str(URL(signed_url)) != signed_url


async def test_new_query_parameters_still_use_normal_encoding(client):
    response = FakeResponse()
    response.status = 200
    response.headers = {}
    client.session.request.return_value = response
    params = {"dateLocatedInWeek": "2026-10-07 +02:00"}
    await client._request("GET", API_URL + "/v4/fetch-entries-for-week", params=params)
    call = client.session.request.call_args
    assert isinstance(call.args[1], str)
    assert call.kwargs["params"] == params


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_server_error_reports_safe_step_and_status(client, status):
    response = FakeResponse()
    response.url = (
        "https://iam.auth.education.lu/module.php/saml/idp/singleSignOnService"
        "?SAMLRequest=private-state"
    )
    response.status = status
    response.headers = {}
    client.session.request.return_value = response
    with pytest.raises(CannotConnect) as error:
        await client._request("GET", response.url)
    assert str(error.value) == f"Education.lu returned HTTP {status} at saml_sign_on"
    assert client.session.request.call_count == 1


async def test_ajax_headers_reach_the_server(client):
    def request(method, url, **kwargs):
        response = FakeResponse()
        response.url = url
        response.status = (
            200 if kwargs.get("headers", {}).get("X-Requested-With") == "XMLHttpRequest" else 404
        )
        response.headers = {}
        return response

    client.session.request.side_effect = request
    url = "https://auth.education.lu/module.php/IAM/idpSelection.php"
    assert (await client._request("GET", url, headers={}, follow=False)).status == 404
    page = await client._request(
        "GET", url, headers={"X-Requested-With": "XMLHttpRequest"}, follow=False
    )
    assert page.status == 200


async def test_request_headers_are_not_forwarded_on_redirect(client):
    redirect = FakeResponse()
    redirect.headers = {"Location": "https://ssl.education.lu/ebichelchen/app/"}
    destination = FakeResponse()
    destination.url = redirect.headers["Location"]
    destination.status = 200
    destination.headers = {}
    client.session.request.side_effect = [redirect, destination]
    await client._request("GET", redirect.url, headers={"Referer": redirect.url + "?state=demo"})
    assert client.session.request.call_args_list[1].kwargs["headers"] is None


@pytest.mark.parametrize("status", [302, 404])
async def test_discovery_http_errors_stop_before_password(client, status):
    url = "https://auth.education.lu/module.php/saml/disco"
    client._request = AsyncMock(
        side_effect=[
            Page(url, 200, '<form><input name="username"></form>'),
            Page(url, status, '{"syntax":"OK","auth":"urn:x-auth-education-lu:auth:iam"}'),
        ]
    )
    with pytest.raises(InvalidResponse, match=f"IAM discovery returned HTTP {status}"):
        await client._login()
    assert client._request.call_count == 2
    assert not client._authenticated


async def test_credentials_cannot_be_replayed_to_other_trusted_host(client):
    response = FakeResponse()
    response.status = 307
    response.headers = {"Location": "https://auth.education.lu/capture"}
    client.session.request.return_value = response
    with pytest.raises(UnsupportedAuth):
        await client._request("POST", response.url, data={"password": "demo"}, credentials=True)
    assert client.session.request.call_count == 1


async def test_mfa_discovery_rejected_before_password(client):
    page = Page(
        "https://auth.education.lu/module.php/saml/disco",
        200,
        '<form><input name="username"></form>',
    )
    client._request = AsyncMock(
        side_effect=[
            page,
            Page(page.url, 200, '{"syntax":"OK","auth":"urn:x-auth-education-lu:auth:iam:2fa"}'),
        ]
    )
    with pytest.raises(UnsupportedAuth):
        await client._login()
    assert all(
        "password" not in call.kwargs.get("data", {}) for call in client._request.call_args_list
    )


def test_json_bom_is_accepted():
    page = Page(
        API_URL + "/v2/get-user", 200, '\ufeff{"code":0,"objects":{"id":123}}', "application/json"
    )
    assert EbichelchenClient._decode(page) == {"id": 123}


def test_api_error_diagnostics_do_not_include_private_response_data():
    page = Page(
        API_URL + "/v2/get-user?secret=private-state",
        400,
        "private password and body",
        "text/plain",
    )
    with pytest.raises(InvalidResponse) as error:
        EbichelchenClient._decode(page)
    assert str(error.value) == "Unexpected API status: HTTP 400 at user_profile"
    assert "private" not in str(error.value)


def test_api_envelope_diagnostics_do_not_echo_server_strings():
    page = Page(
        API_URL + "/v2/get-user",
        200,
        '{"code":"private-data","message":"secret","objects":null}',
        "application/json",
    )
    with pytest.raises(InvalidResponse) as error:
        EbichelchenClient._decode(page)
    assert "user_profile" in str(error.value)
    assert "private-data" not in str(error.value)
    assert "secret" not in str(error.value)
