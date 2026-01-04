from typing import Tuple

from dataclasses import dataclass
from enum import Enum
import math

from ib_async import (
    Contract,
    Option,
    ComboLeg,
    Bag,
    LimitOrder
)
from .core import (
    OptionStrategy,
    Right,
    OptionContractSpec,
    VerticalSpec
)


class SpreadType(Enum):
    CREDIT = 1
    DEBIT = 2


@dataclass(frozen=True, slots=True)
class Sspread:
    right: Right
    stype: SpreadType
    spec: VerticalSpec
    contract_spec: OptionContractSpec


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

    async def buy(self):

        short, long= await self.build()

        leg1 = ComboLeg()
        leg1.conId = long.conId
        leg1.ratio = 1
        leg1.action = "BUY"
        leg1.exchange = "SMART"
        leg2 = ComboLeg()
        leg2.conId = short.conId
        leg2.ratio = 1
        leg2.action = "SELL"
        leg2.exchange = "SMART"

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

        await self.om.limit_buy(combo, 1, lmt)