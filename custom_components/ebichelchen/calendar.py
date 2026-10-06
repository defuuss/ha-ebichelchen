"""Read-only calendars; no changes are written to the school system."""

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import EbichelchenError, InvalidAuth
from .coordinator import EbichelchenCoordinator
from .events import as_datetime, events_in_range


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        EbichelchenCalendar(coordinator, entry, student_id, name)
        for student_id, name in coordinator.students.items()
    )


class EbichelchenCalendar(CoordinatorEntity, CalendarEntity):
    """One independent calendar for each selected student."""

    _attr_icon = "mdi:book-open-page-variant"

    def __init__(
        self, coordinator: EbichelchenCoordinator, entry: ConfigEntry, student_id: str, name: str
    ):
        super().__init__(coordinator)
        self._entry = entry
        self._student_id = student_id
        self._attr_unique_id = f"{entry.unique_id}_{student_id}"
        self._attr_name = f"eBichelchen {name}"

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        return next(
            (
                event
                for event in (self.coordinator.data or {}).get(self._student_id, [])
                if as_datetime(event.end, now.tzinfo) > now
            ),
            None,
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        try:
            # Include the ending calendar day if the requested upper bound is not midnight.
            from datetime import timedelta

            end_day = end_date.date()
            if end_date > dt_util.start_of_local_day(end_date):
                end_day += timedelta(days=1)
            rows = await self.coordinator.client.entries(
                self._student_id, start_date.date(), end_day
            )
            return events_in_range(rows, self._student_id, start_date, end_date)
        except InvalidAuth as err:
            self._entry.async_start_reauth(hass)
            raise HomeAssistantError(str(err)) from None
        except EbichelchenError as err:
            raise HomeAssistantError(str(err)) from None
