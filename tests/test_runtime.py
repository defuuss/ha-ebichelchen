"""Check Home Assistant error translation and session cleanup."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.ebichelchen import async_setup_entry, async_unload_entry
from custom_components.ebichelchen.api import CannotConnect, InvalidAuth
from custom_components.ebichelchen.calendar import EbichelchenCalendar
from custom_components.ebichelchen.coordinator import EbichelchenCoordinator


async def test_setup_failure_closes_session(monkeypatch):
    session = MagicMock(close=AsyncMock())
    coordinator = MagicMock(
        async_config_entry_first_refresh=AsyncMock(side_effect=ConfigEntryAuthFailed("Rejected"))
    )
    monkeypatch.setattr(
        "custom_components.ebichelchen.create_client", lambda *a: (session, MagicMock())
    )
    monkeypatch.setattr(
        "custom_components.ebichelchen.EbichelchenCoordinator", lambda *a: coordinator
    )
    entry = MagicMock(data={"username": "demo", "password": "test"}, options={})
    with pytest.raises(ConfigEntryAuthFailed):
        await async_setup_entry(MagicMock(), entry)
    session.close.assert_awaited_once()


async def test_unload_closes_session():
    hass = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    entry = MagicMock()
    entry.runtime_data.session.close = AsyncMock()
    assert await async_unload_entry(hass, entry)
    entry.runtime_data.session.close.assert_awaited_once()


@pytest.mark.parametrize(
    "error,expected",
    [(InvalidAuth("Rejected"), ConfigEntryAuthFailed), (CannotConnect("Offline"), UpdateFailed)],
)
async def test_coordinator_maps_errors(error, expected):
    coordinator = object.__new__(EbichelchenCoordinator)
    coordinator.students = {"123": "Demo Student"}
    coordinator.client = MagicMock(entries=AsyncMock(side_effect=error))
    with pytest.raises(expected):
        await coordinator._async_update_data()


async def test_calendar_next_event_skips_expired_and_fetches_range(monkeypatch):
    tz = ZoneInfo("Europe/Luxembourg")
    now = datetime(2026, 10, 6, 12, tzinfo=tz)
    monkeypatch.setattr("custom_components.ebichelchen.calendar.dt_util.now", lambda: now)
    expired = CalendarEvent(
        datetime(2026, 10, 5, 10, tzinfo=tz), datetime(2026, 10, 5, 11, tzinfo=tz), "Expired"
    )
    future = CalendarEvent(
        datetime(2026, 10, 7, 10, tzinfo=tz), datetime(2026, 10, 7, 11, tzinfo=tz), "Future"
    )
    coordinator = MagicMock(data={"123": [expired, future]})
    coordinator.client.entries = AsyncMock(
        return_value=[{"id": 1, "startDate": "2026-10-06T00:00:00", "title": "Reading"}]
    )
    entity = EbichelchenCalendar(coordinator, MagicMock(unique_id="456"), "123", "Demo Student")
    assert entity.event == future
    events = await entity.async_get_events(
        MagicMock(), datetime(2026, 10, 6, tzinfo=tz), datetime(2026, 10, 7, tzinfo=tz)
    )
    assert len(events) == 1
    assert events[0].summary == "Reading"
