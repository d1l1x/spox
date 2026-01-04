from enum import Enum
from abc import abstractmethod
from typing import Tuple
import numpy as np
from dataclasses import dataclass
import math
from pandas import DataFrame

import talib
from ib_async import (
    util,
    Contract
)

from .component import Component


class MAType(Enum):
    SMA = 1
    EMA = 2
    DEMA = 3
    WMA = 4

_TALIB_MA = {
    MAType.SMA: talib.SMA,
    MAType.EMA: talib.EMA,
    MAType.DEMA: talib.DEMA,
    MAType.WMA: talib.WMA,
}


class BarSize(str, Enum):
    SEC_5 = "5 secs"
    SEC_15 = "15 secs"
    MIN_1 = "1 min"
    MIN_5 = "5 mins"
    MIN_15 = "15 mins"
    HOUR_1 = "1 hour"
    DAY_1 = "1 day"

BAR_SECONDS: dict[BarSize, int] = {
    BarSize.SEC_5: 5,
    BarSize.SEC_15: 15,
    BarSize.MIN_1: 60,
    BarSize.MIN_5: 5 * 60,
    BarSize.MIN_15: 15 * 60,
    BarSize.HOUR_1: 60 * 60,
    BarSize.DAY_1: 24 * 60 * 60,
}


@dataclass(frozen=True, slots=True)
class HistorySpec:
    bar_size: BarSize
    length: int                      # MA period in number of bars
    warmup_bars: int = 50            # extra bars so MA stabilizes
    what_to_show: str = "TRADES"
    use_rth: bool = True

    def duration_str(self) -> str:
        """
        Compute an IB durationStr that should provide at least
        (length + warmup_bars) bars for the given bar size.

        This is an approximation. We pad generously to avoid
        "not enough bars" failures.
        """
        bars_needed = self.length + self.warmup_bars
        seconds_needed = bars_needed * BAR_SECONDS[self.bar_size]

        # Convert seconds_needed into an IB duration string with padding.
        # IB supports: S, D, W, M, Y.
        if seconds_needed <= 60 * 60:
            # up to 1 hour -> seconds
            return f"{int(seconds_needed)} S"

        days = math.ceil(seconds_needed / (24 * 60 * 60))
        # add a safety cushion for weekends/holidays when useRTH=True
        days = int(days * 1.6) + 2

        if days <= 6:
            return f"{days} D"
        if days <= 60:
            weeks = math.ceil(days / 7)
            return f"{weeks} W"
        if days <= 365:
            months = math.ceil(days / 30)
            return f"{months} M"
        years = math.ceil(days / 365)
        return f"{years} Y"


class Filter(Component):

    def __init__(self, ctx, history:HistorySpec = HistorySpec(bar_size=BarSize.DAY_1, length=1)):
        super().__init__(ctx)
        self.history = history

    async def _req_historical_data(self, contract) -> DataFrame|None:

        bars = await self.ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=self.history.duration_str(),
            barSizeSetting=self.history.bar_size.value,
            whatToShow=self.history.what_to_show,
            useRTH=self.history.use_rth,
        )

        if len(bars) < self.history.length:
            raise ValueError(
                f"Not enough historical bars: got {len(bars)}. "
                f"Needed {self.history.length} "
                f"({self.history.bar_size.value})."
            )

        return util.df(bars)


    @abstractmethod
    async def evaluate(self) -> bool:
        raise NotImplementedError


class CloseAboveMovingAverage(Filter):

    def __init__(
        self,
        ctx,
        contract: Contract,
        history: HistorySpec,
        *,
        ma_type: MAType = MAType.SMA,
    ) -> None:
        super().__init__(ctx, history)
        self.contract = contract
        self.ma_type = ma_type

    async def evaluate(self) -> bool:

        df = await self._req_historical_data(self.contract)
        close = df["close"].to_numpy()

        ma_func = _TALIB_MA.get(self.ma_type)
        if ma_func is None:
            raise ValueError(f"Unsupported MAType: {self.ma_type}")

        ma = ma_func(close, timeperiod=self.history.length)

        self.ctx.log.info(f"Filter ({self.__class__.__name__}): " 
                          f"Close={close[-1]:.2f}, "
                          f"MA={ma[-1] :.2f}")

        ready = close[-1] > ma[-1]

        self.ctx.log.info(f"Filter ({self.__class__.__name__}): {ready}")

        return ready


class MoveUpFromOpen(Filter):

    def __init__(
        self,
        ctx,
        contract: Contract,
        val: float,
        history: HistorySpec,
    ) -> None:
        super().__init__(ctx, history)
        self.contract = contract
        self.value = val

    async def evaluate(self) -> bool:

        df = await self._req_historical_data(self.contract)
        move_pct = (df.close - df.open) / df.open

        self.ctx.log.info(f"Filter ({self.__class__.__name__}): " 
                          f"Open={df.open.tail(1).values[0]:.2f}, "
                          f"Close={df.close.tail(1).values[0]:.2f}, "
                          f"Move={move_pct.tail(1).values[0] * 100:.4f}%")

        ready = move_pct.tail(1).values[0] >= self.value

        self.ctx.log.info(f"Filter ({self.__class__.__name__}): {ready}")

        return ready