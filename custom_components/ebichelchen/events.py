"""Normalize school entries without inferring times from free-text descriptions."""

from datetime import date, datetime, time, timedelta
from hashlib import sha256

from bs4 import BeautifulSoup
from homeassistant.components.calendar import CalendarEvent

from .api import InvalidResponse
from .const import SCHOOL_TZ


def plain_text(value: str | None) -> str:
    """Strip markup, retaining readable breaks."""
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    for node in soup(["script", "style"]):
        node.decompose()
    return soup.get_text("\n", strip=True)


def as_datetime(value: date | datetime, tz=SCHOOL_TZ) -> datetime:
    """All-day dates use the viewing Home Assistant timezone."""
    return value if isinstance(value, datetime) else datetime.combine(value, time.min, tz)


def to_event(row: dict, student_id: str) -> CalendarEvent:
    """Midnight-only entries are all-day; API date-time ends are exclusive."""
    try:
        start = datetime.fromisoformat(row["startDate"])
        end = datetime.fromisoformat(row["endDate"]) if row.get("endDate") else None
    except (KeyError, TypeError, ValueError):
        raise InvalidResponse("Invalid calendar date") from None
    all_day = start.time() == time.min and (end is None or end.time() == time.min)
    if all_day:
        start_value = start.date()
        end_value = end.date() if end else start_value + timedelta(days=1)
        if end_value <= start_value:
            end_value = start_value + timedelta(days=1)
    else:
        start_value = (
            start.replace(tzinfo=SCHOOL_TZ) if start.tzinfo is None else start.astimezone(SCHOOL_TZ)
        )
        end_value = (
            (end.replace(tzinfo=SCHOOL_TZ) if end.tzinfo is None else end.astimezone(SCHOOL_TZ))
            if end
            else start_value + timedelta(hours=1)
        )
        if end_value <= start_value:
            raise InvalidResponse("Calendar end precedes start")
    parts = [plain_text(row.get("description"))]
    for task in row.get("subtasks") or []:
        text = plain_text(task.get("description"))
        if text and text not in parts:
            parts.append(text)
    uid = sha256(f"{student_id}:{row['id']}:{row['startDate']}".encode()).hexdigest()[:32]
    return CalendarEvent(
        start=start_value,
        end=end_value,
        summary=plain_text(row.get("title")) or "eBichelchen",
        description="\n\n".join(filter(None, parts)) or None,
        uid=uid,
    )


def events_in_range(
    rows: list[dict], student_id: str, start: datetime, end: datetime
) -> list[CalendarEvent]:
    """Return overlapping events in order; exact end boundaries are excluded."""
    events = [to_event(row, student_id) for row in rows]
    tz = start.tzinfo or SCHOOL_TZ
    return sorted(
        (
            event
            for event in events
            if as_datetime(event.end, tz) > start and as_datetime(event.start, tz) < end
        ),
        key=lambda event: (as_datetime(event.start, tz), event.summary),
    )
