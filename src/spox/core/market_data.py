from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Tuple, Optional
from enum import Enum

from spox.core.component import Component  # the ctx-based Component from earlier


class MarketDataType(int, Enum):
    LIVE = 1
    FROZEN = 2
    DELAYED = 3
    DELAYED_FROZEN = 4


@dataclass(slots=True)
class SessionSchedule:
    tz: ZoneInfo
    intervals: List[Tuple[datetime, datetime]]  # [ (start_dt, end_dt), ... ]

    def is_open(self) -> bool:
        now = datetime.now(tz=self.tz)
        return any(start <= now <= end for start, end in self.intervals)


class MarketDataTypeManager(Component):
    """
    Determines if a contract's exchange/session is currently open.
    Switches market data type only when needed.
    """

    def __init__(self, ctx, *, prefer_liquid_hours: bool = True):
        super().__init__(ctx)
        self.prefer_liquid_hours = prefer_liquid_hours
        self._cache_key: Optional[tuple] = None
        self._cache: Optional[SessionSchedule] = None
        self._current_md_type: Optional[int] = None

    async def ensure_md_type_for_now(self, contract, *, open_type: int = MarketDataType.LIVE.value, closed_type: int = MarketDataType.FROZEN.value) -> int:
        sched = await self._get_schedule(contract)
        now = datetime.now(self.tz)

        desired = open_type if sched.is_open() else closed_type
        if desired != self._current_md_type:
            self.ib.reqMarketDataType(desired)
            self._current_md_type = desired
            self.log.info("Market data type set to %s (%s)", desired, "OPEN" if desired == open_type else "CLOSED")
        else:
            self.log.debug("Market data type unchanged (%s)", desired)

        return desired

    async def _get_schedule(self, contract) -> SessionSchedule:
        # cache per-contract per-date
        # qualifying may change conId, so qualify first
        await self.ib.qualifyContractsAsync(contract)

        # Use conId + YYYYMMDD in exchange tz as cache key
        details_list = await self.ib.reqContractDetailsAsync(contract)
        if not details_list:
            raise ValueError("No contract details returned")

        d = details_list[0]
        tz = ZoneInfo(d.timeZoneId) if d.timeZoneId else self.tz
        today = datetime.now(tz).strftime("%Y%m%d")
        cache_key = (getattr(contract, "conId", None), today, self.prefer_liquid_hours)

        if self._cache_key == cache_key and self._cache is not None:
            return self._cache

        hours_str = (d.liquidHours if self.prefer_liquid_hours else d.tradingHours) or ""
        intervals = self._parse_hours(hours_str, tz, today)

        sched = SessionSchedule(tz=tz, intervals=intervals)
        self._cache_key = cache_key
        self._cache = sched
        return sched

    @staticmethod
    def _parse_hours(hours_str: str, tz: ZoneInfo, day_yyyymmdd: str) -> List[Tuple[datetime, datetime]]:
        """
        IB format examples:
          '20250101:CLOSED;20250102:0930-1600;20250103:0930-1600'
          Sometimes multiple sessions: '20250102:0930-1600,1700-2000'
        """
        intervals: List[Tuple[datetime, datetime]] = []

        for dayseg in hours_str.split(";"):
            if not dayseg:
                continue
            date_part, sess_part = dayseg.split(":", 1)
            if date_part != day_yyyymmdd:
                continue
            if sess_part == "CLOSED":
                return []

            # handle multiple sessions separated by comma
            for session in sess_part.split(","):
                start_hm, end_hm = session.split("-", 1)

                start_dt = datetime(
                    int(date_part[0:4]), int(date_part[4:6]), int(date_part[6:8]),
                    int(start_hm[0:2]), int(start_hm[2:4]),
                    tzinfo=tz,
                )
                end_dt = datetime(
                    int(date_part[0:4]), int(date_part[4:6]), int(date_part[6:8]),
                    int(end_hm[0:2]), int(end_hm[2:4]),
                    tzinfo=tz,
                )
                intervals.append((start_dt, end_dt))

        return intervals