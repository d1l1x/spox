import asyncio
from datetime import time
from typing import Tuple

# from dataclasses import dataclass
from enum import Enum
import math

from ib_async import (
    Option,
    ComboLeg,
    Bag,
)
from .core import (
    OptionStrategy,
    Right,
)
from spox.core.helper import total_seconds
from spox.core.orders import FillProgression


class SpreadType(Enum):
    CREDIT = 1
    DEBIT = 2


# @dataclass(frozen=True, slots=True)
# class Sspread:
#     right: Right
#     stype: SpreadType
#     spec: VerticalSpec
#     contract_spec: OptionContractSpec


class Spread(OptionStrategy):
    """
    Builder for constructing put option spreads.

    This component encapsulates the logic required to identify and
    construct a put vertical (credit/debit spread) for a given underlying
    contract. It selects option strikes based on model delta and a
    fixed spread width, using live or delayed market data from
    Interactive Brokers.

    The builder is context-aware and obtains its IB connection and
    logger from the provided StrategyContext. It contains no scheduling
    or execution logic and is intended to be invoked by a strategy
    or task.

    Attributes:
        spec (VerticalSpec):
            Configuration object that defines the strike selection
            parameters.

        opt (OptionFactory):
            Factory responsible for creating option contracts using
            a predefined option contract specification (symbol,
            trading class, exchange, etc.).
    """
    def __init__(self, right: Right, type: SpreadType, *args):
        super().__init__(*args)
        self.right = right
        self.type = type

    def _offset_strike(self, short_strike: float) -> float:
        """
        Compute long-leg strike from short-leg strike given spread kind and right.
        """
        width = self.spec.width

        if self.right == Right.PUT:
            return short_strike - width if self.type == SpreadType.CREDIT else short_strike + width
        else:  # Right.CALL
            return short_strike + width if self.type == SpreadType.CREDIT else short_strike - width

    async def build(self) -> Tuple[Option, Option]:
        spot_ticker = await self.ib.reqTickersAsync(self.underlying)
        spot = spot_ticker[0].marketPrice()
        if spot is None or math.isnan(spot):
            self.log.error(f"No valid spot price for {self.underlying}: {spot_ticker}")
            return Option(), Option()

        self.log.info("Search for matching strikes")
        strikes = self._get_strike_candidates(spot, self.right, inc=self.spec.inc)

        short_contracts = await self._get_contracts(
            dte=self.spec.short_dte,
            right=self.right,
            strikes=strikes
            )

        short = await self._select_strike_delta(short_contracts)

        strike = self._offset_strike(short.strike)

        long_contracts = await self._get_contracts(
            dte=self.spec.long_dte,
            right=self.right,
            strikes=[strike]
            )
        long= long_contracts[0]

        self.ctx.log.info(f'Selected: short(strike={short.strike}) long(strike={long.strike})')

        return short, long


    async def buy(self, timeout:time, fill_progression:FillProgression|None = None):

        loop = asyncio.get_running_loop()
        deadline = loop.time() + total_seconds(timeout)

        trade = None

        while trade is None:

            if loop.time() >= deadline:
                self.log.warning(f'Deadline for trade execution exceeded')
                break

            short, long= await self.build()

            leg1 = ComboLeg(conId=long.conId, ratio=1, action="BUY", exchange="SMART")
            leg2 = ComboLeg(conId=short.conId, ratio=1, action="SELL", exchange="SMART")

            combo = Bag(
                symbol = self.opt.spec.symbol,
                exchange=self.opt.spec.exchange,
                currency=self.opt.spec.currency,
                comboLegs=[leg1, leg2]
                )

            tickers = await self.ib.reqTickersAsync(*[short, long])

            # For bull put spread
            for ticker in tickers:
                if ticker.contract.strike == short.strike:
                    bid = ticker.bid
                if ticker.contract.strike == long.strike:
                    ask = ticker.ask
            lmt = ask-bid

            trade = await self.om.limit_buy(combo, 1, lmt, progression=fill_progression)

        return trade