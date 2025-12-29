from __future__ import annotations
from typing import List, Literal, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta

import asyncio

from ib_async import Option, Contract, Ticker

from spox.core.component import Component

class Right(str, Enum):
    CALL = "C"
    PUT = "P"


@dataclass(frozen=True, slots=True)
class OptionContractSpec:
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    trading_class: Optional[str] = None


class OptionFactory:
    def __init__(self, spec: OptionContractSpec):
        self.spec = spec

    def make(self, *, expiry: str, strike: float, right: Right) -> Option:
        return Option(
            self.spec.symbol,
            expiry,
            strike,
            right.value,
            self.spec.exchange,
            currency=self.spec.currency,
            tradingClass=self.spec.trading_class,
        )


@dataclass(slots=True, frozen=True)
class VerticalSpec:
    """
    Specification for constructing a vertical (credit or debit spread).

    This class defines the parameters used to select option strikes when
    building a spread. It is intended to be consumed by
    option spread builders.

    Attributes:
        target_delta (float):
            Target option delta for the primary leg. The builder will
            select the option whose model delta is closest to this
            value (e.g., -0.15 (put) or +0.15 (call)).

        width (float):
            Distance in strike price between the short and long legs.
            For example, a width of 50 results in a 50-point wide vertical.

        short_dte (int, optional):
            Days to expiration for the short leg. If None, use the
            current trading day. Defaults to 0.

        inc (int, optional):
            Strike increment used when generating candidate strikes.
            Defaults to 5.

        strikes_down (int, optional):
            Number of strikes below the current spot price to consider
            when searching for the optimal primary leg. Defaults to 20.

        long_dte (int, optional):
            Days to expiration for the long leg. If None, falls back to
            the short leg's `dte`. Defaults to 0.
    """
    target_delta: float
    width: float
    short_dte: int = 0
    long_dte: int = 0
    inc: int = 5
    strikes_down: int = 20

    
class OptionStrategy(Component):

    def __init__(self, ctx, underlying:Contract ,spec: VerticalSpec, option_contract_spec: OptionContractSpec):
        """
        Initialize the put vertical builder.

        Args:
            ctx (StrategyContext):
                Shared strategy context providing access to the IB
                connection, logger, etc.

            underlying (Contract):
                Contract of the underlying symbol

            spec (VerticalSpec):
                Specification describing how the spread should
                be constructed (e.g., target delta and width).

            option_contract_spec (OptionContractSpec):
                Specification defining the option contract parameters
                such as symbol, exchange, currency, and trading class.
        """
        super().__init__(ctx)
        self.underlying = underlying
        self.spec = spec
        self.opt = OptionFactory(option_contract_spec)

    async def wait_for_greeks(self, tickers: List[Ticker], timeout: float = 3.0) -> bool:
        """
        Wait for model greeks to become available on a set of tickers.

        This method asynchronously polls the provided tickers until
        all of them have populated model greeks or until the timeout
        is reached. It is designed to be safe for use within an
        asyncio event loop.

        Args:
            tickers (List[Ticker]):
                Ticker objects returned by `reqTickersAsync` for which
                model greeks are required.

            timeout (float, optional):
                Maximum time in seconds to wait for greeks to become
                available. Defaults to 3.0 seconds.

        Returns:
            bool:
                True if model greeks became available for all tickers
                before the timeout expired, otherwise False.

        Notes:
            - This method does not raise if greeks are unavailable;
              callers should handle the False return value explicitly.
            - The polling interval is intentionally short to allow
              timely reaction to IB updates without blocking the event
              loop.
        """
        deadline = asyncio.get_running_loop().time() + timeout

        while asyncio.get_running_loop().time() < deadline:
            if all(getattr(t, "modelGreeks", None) for t in tickers):
                return True
            await asyncio.sleep(0.05)

        return False

    def _get_strike_candidates(self, start: float, right: Literal[Right], inc: int = 5) -> List[float]: # type: ignore
        """
        Generate a list of candidate option strikes around a starting price.

        For puts, strikes are generated below the starting price; for calls,
        strikes are generated above the starting price. Strikes are aligned
        to the specified increment and extend outward by `self.spec.strikes_down`
        steps.

        Args:
            start (float):
                Reference price used as the starting point for strike
                generation (typically the underlying spot price).

            right (Right):
                Option right indicating whether to generate put ("P") or
                call ("C") strikes.

            inc (int, optional):
                Strike increment to which candidate strikes are aligned.
                Defaults to 5.

        Returns:
            List[float]:
                List of candidate strikes ordered away from the starting
                point. Returns an empty list if `right` is unsupported.

        Notes:
            - For puts, the first strike is the nearest strike <= `start`
            aligned to `inc`, then decreasing by `inc`.
            - For calls, the first strike is the nearest strike >= `start`
            aligned to `inc`, then increasing by `inc`.
            - The number of strikes returned is controlled by
            `self.spec.strikes_down`.
        """
        if right == Right.PUT:
            return [start - start % inc - i * inc for i in range(self.spec.strikes_down)]

        if right == Right.CALL:
            return [start + start % inc + i * inc for i in range(self.spec.strikes_down)]

        return []

    async def _get_contracts(self, dte: int, right: Right, strikes: List[float]) -> List[Option]:
        """
        Create and qualify option contracts for a given set of strikes and expiry.

        This method constructs option contracts using the configured option
        factory, computes an expiry date based on the provided days-to-expiry
        (DTE), and qualifies all contracts via Interactive Brokers so they
        can be used for market data requests and order placement.

        Args:
            dte (int):
                Days to expiry relative to the current date. A value of 0
                uses today's date as the expiry string. A positive value
                adds the specified number of days.

            right (Right):
                Option right indicating put ("P") or call ("C") contracts.

            strikes (List[float]):
                Strike prices for which option contracts should be created.

        Returns:
            List[Option]:
                A list of qualified IB Option contracts corresponding to the
                given strikes and expiry.

        Raises:
            Exception:
                Propagates exceptions raised by IB qualification calls
                (e.g., connectivity issues or invalid contracts).

        Notes:
            - This function uses a naive calendar-day DTE (i.e., it does not
            adjust for weekends or market holidays). For production use,
            consider injecting an expiry policy that maps DTE to the next
            valid trading/expiration date.
            - Contract qualification is required to populate fields such as
            conId and to ensure the contracts are recognized by IB.
        """
        expiry_date = datetime.now().date()

        if dte > 0:
            expiry_date += timedelta(days=dte)
        expiry_str = expiry_date.strftime("%Y%m%d")

        contracts = [ self.opt.make(expiry=expiry_str, strike=k, right=right) for k in strikes ]

        await self.ib.qualifyContractsAsync(*contracts)

        return contracts


    async def _select_strike_delta(self, short_contracts: List[Option]) -> Contract|None:
        """
        Select the optimal option contract based on target delta and price.

        This method requests market data for a list of candidate option
        contracts, waits for model greeks to become available, and selects
        the contract whose delta is closest to the configured target delta.
        If multiple contracts have similar deltas, the contract with the
        highest bid price is preferred.

        Args:
            short_contracts (List[Option]):
                List of candidate option contracts from which the optimal
                leg should be selected.

        Returns:
            Option:
                The selected option contract that best matches the target
                delta criteria.

        Raises:
            ValueError:
                If no contract with available model greeks can be found
                among the provided candidates.

        Notes:
            - This method assumes that an appropriate market data type
            (live, delayed, or frozen) has already been configured.
            - The selection prioritizes delta accuracy first and premium
            (bid price) second.
            - Model greeks must be available for at least one contract;
            otherwise, the selection will fail.
        """
        tickers = await self.ib.reqTickersAsync(*short_contracts)

        await self.wait_for_greeks(tickers, timeout=3.0)

        best = min(
            (t for t in tickers if t.modelGreeks),
            key=lambda t: (abs(t.modelGreeks.delta - self.spec.target_delta), -t.bid),
        )
        return best.contract