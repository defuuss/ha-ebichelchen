from unittest.mock import AsyncMock, MagicMock

from custom_components.ebichelchen.api import InvalidAuth
from custom_components.ebichelchen.config_flow import EbichelchenConfigFlow, EbichelchenOptionsFlow


async def test_login_select_and_store(monkeypatch):
    flow = EbichelchenConfigFlow()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    monkeypatch.setattr(
        "custom_components.ebichelchen.config_flow.validate_credentials",
        AsyncMock(return_value=("456", {"123": "Demo Student"})),
    )
    result = await flow.async_step_user({"username": " demo ", "password": "test-password"})
    assert result["step_id"] == "students"
    result = await flow.async_step_students({"students": ["123"], "refresh_minutes": 30})
    assert result["data"]["username"] == "demo"
    assert result["data"]["students"] == {"123": "Demo Student"}
    assert result["options"]["refresh_minutes"] == 30


async def test_bad_credentials_shows_error(monkeypatch):
    flow = EbichelchenConfigFlow()
    monkeypatch.setattr(
        "custom_components.ebichelchen.config_flow.validate_credentials",
        AsyncMock(side_effect=InvalidAuth("Rejected")),
    )
    result = await flow.async_step_user({"username": "demo", "password": "wrong"})
    assert result["errors"] == {"base": "invalid_auth"}
    assert result["step_id"] == "user"


async def test_student_selection_cannot_inject_id():
    flow = EbichelchenConfigFlow()
    flow._students = {"123": "Demo Student"}
    result = await flow.async_step_students({"students": ["999"], "refresh_minutes": 30})
    assert result["errors"] == {"base": "select_students"}


async def test_options_store_interval():
    result = await EbichelchenOptionsFlow().async_step_init({"refresh_minutes": 60})
    assert result["data"] == {"refresh_minutes": 60}


async def test_reauth_updates_same_entry(monkeypatch):
    flow = EbichelchenConfigFlow()
    entry = MagicMock(data={"username": "demo", "students": {"123": "Demo Student"}})
    flow._get_reauth_entry = MagicMock(return_value=entry)
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_mismatch = MagicMock()
    flow.async_update_reload_and_abort = MagicMock(return_value={"type": "abort"})
    monkeypatch.setattr(
        "custom_components.ebichelchen.config_flow.validate_credentials",
        AsyncMock(return_value=("456", {"123": "Demo Student"})),
    )
    await flow.async_step_reauth_confirm({"password": "new-demo-password"})
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry, data_updates={"password": "new-demo-password"}
    )


async def test_setup_shows_and_logs_safe_error_detail(monkeypatch, caplog):
    from custom_components.ebichelchen.api import InvalidResponse

    flow = EbichelchenConfigFlow()
    detail = "Unexpected API status: HTTP 400 at user_profile"
    monkeypatch.setattr(
        "custom_components.ebichelchen.config_flow.validate_credentials",
        AsyncMock(side_effect=InvalidResponse(detail)),
    )
    result = await flow.async_step_user(
        {"username": "private-user", "password": "private-password"}
    )
    assert result["description_placeholders"] == {"error_detail": detail}
    assert detail in caplog.text
    assert "private-user" not in caplog.text
    assert "private-password" not in caplog.text
