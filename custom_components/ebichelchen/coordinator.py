"""Coordinate polling and expose safe Home Assistant errors."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EbichelchenClient, EbichelchenError, InvalidAuth
from .const import CONF_REFRESH, CONF_STUDENTS, DEFAULT_REFRESH, DOMAIN, LOOKAHEAD
from .events import events_in_range

_LOGGER = logging.getLogger(__name__)


class EbichelchenCoordinator(DataUpdateCoordinator):
    """Fetch current and upcoming calendar entries at the chosen interval."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: EbichelchenClient):
        self.client = client
        self.students = entry.data[CONF_STUDENTS]
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(minutes=entry.options.get(CONF_REFRESH, DEFAULT_REFRESH)),
        )

    async def _async_update_data(self):
        start = dt_util.start_of_local_day()
        end = start + LOOKAHEAD
        result = {}
        try:
            for student_id in self.students:
                rows = await self.client.entries(student_id, start.date(), end.date())
                result[student_id] = events_in_range(rows, student_id, start, end)
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from None
        except EbichelchenError as err:
            raise UpdateFailed(str(err)) from None
        return result
