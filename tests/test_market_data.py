from datetime import datetime
from zoneinfo import ZoneInfo

from spox.core import market_data
from spox.core.market_data import MarketDataTypeManager, SessionSchedule


def test_parse_hours_single_session_same_day():
    tz = ZoneInfo("UTC")
    hours = "20250102:0930-1600;20250103:0930-1600"

    intervals = MarketDataTypeManager._parse_hours(hours, tz, "20250103")

    assert len(intervals) == 1
    start, end = intervals[0]
    assert start == datetime(2025, 1, 3, 9, 30, tzinfo=tz)
    assert end == datetime(2025, 1, 3, 16, 0, tzinfo=tz)


def test_parse_hours_multiple_sessions():
    tz = ZoneInfo("UTC")
    hours = "20250103:0930-1200,1300-1600"

    intervals = MarketDataTypeManager._parse_hours(hours, tz, "20250103")

    assert len(intervals) == 2
    assert intervals[0] == (
        datetime(2025, 1, 3, 9, 30, tzinfo=tz),
        datetime(2025, 1, 3, 12, 0, tzinfo=tz),
    )
    assert intervals[1] == (
        datetime(2025, 1, 3, 13, 0, tzinfo=tz),
        datetime(2025, 1, 3, 16, 0, tzinfo=tz),
    )


def test_parse_hours_closed_day_returns_empty():
    tz = ZoneInfo("UTC")
    intervals = MarketDataTypeManager._parse_hours("20250103:CLOSED", tz, "20250103")

    assert intervals == []


def test_parse_hours_ignores_other_days():
    tz = ZoneInfo("UTC")
    intervals = MarketDataTypeManager._parse_hours("20250102:0930-1600", tz, "20250103")

    assert intervals == []


def test_session_schedule_is_open(monkeypatch):
    tz = ZoneInfo("UTC")
    schedule = SessionSchedule(
        tz=tz,
        intervals=[
            (datetime(2025, 1, 3, 10, 0, tzinfo=tz), datetime(2025, 1, 3, 12, 0, tzinfo=tz)),
            (datetime(2025, 1, 3, 14, 0, tzinfo=tz), datetime(2025, 1, 3, 16, 0, tzinfo=tz)),
        ],
    )
    fixed_now = datetime(2025, 1, 3, 11, 0, tzinfo=tz)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(market_data, "datetime", FixedDatetime)

    assert schedule.is_open() is True


def test_session_schedule_is_closed(monkeypatch):
    tz = ZoneInfo("UTC")
    schedule = SessionSchedule(
        tz=tz,
        intervals=[
            (datetime(2025, 1, 3, 10, 0, tzinfo=tz), datetime(2025, 1, 3, 12, 0, tzinfo=tz)),
            (datetime(2025, 1, 3, 14, 0, tzinfo=tz), datetime(2025, 1, 3, 16, 0, tzinfo=tz)),
        ],
    )
    fixed_now = datetime(2025, 1, 3, 13, 0, tzinfo=tz)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(market_data, "datetime", FixedDatetime)

    assert schedule.is_open() is False
