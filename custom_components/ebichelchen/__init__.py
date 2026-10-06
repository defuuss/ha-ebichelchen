"""Unofficial eBichelchen calendar integration."""

from dataclasses import dataclass

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api import EbichelchenClient
from .const import CONF_REFRESH, DEFAULT_REFRESH
from .coordinator import EbichelchenCoordinator

PLATFORMS = [Platform.CALENDAR]


@dataclass
class RuntimeData:
    session: aiohttp.ClientSession
    coordinator: EbichelchenCoordinator


def create_client(username: str, password: str, refresh: int = DEFAULT_REFRESH):
    """An isolated cookie jar prevents account/session cross-contamination."""
    session = aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(),
        timeout=aiohttp.ClientTimeout(total=30),
        headers={"Accept": "application/json, text/html;q=0.9"},
    )
    return session, EbichelchenClient(session, username, password, refresh * 60)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session, client = create_client(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.options.get(CONF_REFRESH, DEFAULT_REFRESH),
    )
    coordinator = EbichelchenCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = RuntimeData(session, coordinator)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await session.close()
        raise
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.session.close()
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
