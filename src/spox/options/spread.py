import asyncio
from typing import List, Tuple
from datetime import datetime
from dataclasses import dataclass

from ib_async import Contract, Ticker
from spox.core.component import Component
from .core import OptionFactory, Right, OptionContractSpec


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

        inc (int, optional):
            Strike increment used when generating candidate strikes.
            Defaults to 5.

        strikes_down (int, optional):
            Number of strikes below the current spot price to consider
            when searching for the optimal primary leg. Defaults to 20.
    """
    target_delta: float
    width: float
    inc: int = 5
    strikes_down: int = 20



class PutVerticalBuilder(Component):
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

    def __init__(self, ctx, spec: VerticalSpec, option_contract_spec: OptionContractSpec):
        """
        Initialize the put vertical builder.

        Args:
            ctx (StrategyContext):
                Shared strategy context providing access to the IB
                connection, logger, etc.

            spec (VerticalSpec):
                Specification describing how the spread should
                be constructed (e.g., target delta and width).

            option_contract_spec (OptionContractSpec):
                Specification defining the option contract parameters
                such as symbol, exchange, currency, and trading class.
        """
        super().__init__(ctx)
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

    async def build(self, underlying: Contract) -> tuple(Contract|None, Contract|None):
        """
        Construct a short put vertical spread for a given underlying.

        This method selects a short put option whose model delta is
        closest to the configured target delta, then constructs a
        corresponding long put leg at a fixed strike distance below
        the short leg to form a vertical spread.

        The method performs the following steps:
          1. Requests the current spot price of the underlying.
          2. Generates candidate put strikes below the spot price.
          3. Requests option market data and waits for model greeks.
          4. Selects the optimal short put based on delta proximity.
          5. Constructs and qualifies the long put leg.

        Args:
            underlying (Contract):
                The underlying IB contract (e.g., index or stock)
                for which the put vertical should be constructed.

        Returns:
            tuple[Contract | None, Contract | None]:
                A tuple containing the short put contract and the long
                put contract. Returns (None, None) if the spot price
                is unavailable or if a valid spread cannot be
                constructed.

        Raises:
            Exception:
                Propagates exceptions raised by Interactive Brokers
                API calls (e.g., contract qualification or market data
                requests).

        Notes:
            - The expiration date is currently set to the current
              trading day (YYYYMMDD). Consider injecting an expiry
              selection policy for production use.
            - This method assumes that the appropriate market data
              type (live, delayed, or frozen) has already been
              configured upstream.
            - If no suitable option with model greeks is found, the
              behavior is undefined and may raise a ValueError from
              the selection logic.
        """
        spot_ticker = await self.ib.reqTickersAsync(underlying)
        spot = spot_ticker[0].marketPrice()
        if spot is None:
            self.log.error("No spot price for %s", underlying)
            return None, None

        today_str = datetime.now().strftime("%Y%m%d")
        _ = await self.ib.reqSecDefOptParamsAsync(
            underlying.symbol, "", underlying.secType, underlying.conId
        )

        inc = self.spec.inc
        strikes = [spot - spot % inc - i * inc for i in range(self.spec.strikes_down)]

        # TODO: allow for other expirations based on the additonal parameter "dte"
        contracts = [ self.opt.make(expiry=today_str, strike=k, right=Right.PUT) for k in strikes ]
        await self.ib.qualifyContractsAsync(*contracts)
        tickers = await self.ib.reqTickersAsync(*contracts)

        await self.wait_for_greeks(tickers, timeout=3.0)

        best = min(
            (t for t in tickers if t.modelGreeks),
            key=lambda t: (abs(t.modelGreeks.delta - self.spec.target_delta), -t.bid),
        )
        short_put = best.contract
        long_put = self.opt.make(expiry=short_put.lastTradeDateOrContractMonth,
                                 strike=short_put.strike - self.spec.width,
                                 right=Right.PUT)

        await self.ib.qualifyContractsAsync(long_put)
        return short_put, long_put