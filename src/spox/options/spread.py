from typing import Tuple

from dataclasses import dataclass
from enum import Enum

from ib_async import Contract
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

    async def build(self) -> Tuple[Contract|None, Contract|None]:
        spot_ticker = await self.ib.reqTickersAsync(self.underlying)
        spot = spot_ticker[0].marketPrice()
        if spot is None:
            self.log.error("No spot price for %s", self.underlying)
            return None, None

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