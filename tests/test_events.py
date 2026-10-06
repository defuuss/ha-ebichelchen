from datetime import date, datetime
from zoneinfo import ZoneInfo

from custom_components.ebichelchen.events import events_in_range, to_event

TZ = ZoneInfo("Europe/Luxembourg")


def test_date_only_entry_and_subtasks():
    event = to_event(
        {
            "id": 1,
            "startDate": "2026-10-06T00:00:00",
            "endDate": None,
            "title": "Reading",
            "description": "<p>Bring a book</p>",
            "subtasks": [{"description": "Read chapter 2"}],
        },
        "123",
    )
    assert event.start == date(2026, 10, 6)
    assert event.end == date(2026, 10, 7)
    assert event.description == "Bring a book\n\nRead chapter 2"


def test_timed_event_has_luxembourg_timezone():
    event = to_event(
        {
            "id": 1,
            "startDate": "2026-11-03T19:30:00",
            "endDate": "2026-11-03T20:00:00",
            "title": "Meeting",
        },
        "123",
    )
    assert event.start.utcoffset().total_seconds() == 3600
    assert event.end.hour == 20


def test_exclusive_range_boundaries_and_sorting():
    rows = [
        {"id": day, "startDate": f"2026-10-{day:02}T00:00:00", "title": "Reading"}
        for day in [7, 5, 6, 8]
    ]
    events = events_in_range(
        rows, "123", datetime(2026, 10, 6, tzinfo=TZ), datetime(2026, 10, 8, tzinfo=TZ)
    )
    assert [e.start.day for e in events] == [6, 7]


def test_uid_survives_title_edit_but_separates_occurrences():
    row = {"id": 1, "startDate": "2026-10-06T00:00:00", "title": "Before"}
    a = to_event(row, "123")
    assert a.uid == to_event({**row, "title": "After"}, "123").uid
    assert a.uid != to_event({**row, "startDate": "2026-10-13T00:00:00"}, "123").uid


def test_all_day_uses_viewer_timezone_for_overlap():
    tz = ZoneInfo("America/New_York")
    events = events_in_range(
        [{"id": 1, "startDate": "2026-10-06T00:00:00"}],
        "123",
        datetime(2026, 10, 6, 23, tzinfo=tz),
        datetime(2026, 10, 7, tzinfo=tz),
    )
    assert len(events) == 1
