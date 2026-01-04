import asyncio
from dataclasses import dataclass
from datetime import time
from ib_async import (
    Contract,
    LimitOrder,
    OrderStatus,
    Trade
)

from spox.core.component import Component
from spox.core.context import StrategyContext
from spox.core.helper import total_seconds


@dataclass(frozen=True, slots=True)
class FillProgression:
    attempts: int = 3
    wait: time = time(second=5)
    adjustment: float = 0.05


class OrderManager(Component):

    def __init__(self, ctx: StrategyContext) -> None:
        super().__init__(ctx)

    async def _on_complete_fill(self, trade):
        self.log.info(f"Order {trade.order.orderId} filled")
        # TODO
        # Implement: Save completed orders in database

    async def _onOrderUpdate(self, trade):
        self.log.info(f"Order {trade.order.orderId} updated: {trade.orderStatus.status}")

    async def limit_buy(
        self,
        contract: Contract,
        qty: int,
        limit: float,
        order_ref: str = 'SP0X',
        progression: FillProgression | None = None
    ) -> Trade | None:

        order = LimitOrder("BUY", qty, limit, tif='DAY', orderRef=order_ref)

        self.ctx.log.info(f"Place limit order: {order}")
        trade = self.ib.placeOrder(contract, order)
        trade.filledEvent += self._on_complete_fill

        # progression = progression or getattr(self, "fill_progression", None)
        if progression and progression.attempts > 0:
            attempts = progression.attempts
            while attempts > 0:
                await asyncio.sleep(total_seconds(progression.wait))

                if trade.orderStatus.status == OrderStatus.Filled:
                    return trade
                if trade.orderStatus.status == OrderStatus.Cancelled:
                    return None

                order.lmtPrice -= progression.adjustment
                self.log.info(
                    f"Adjust order {order.orderId} to limit {order.lmtPrice} "
                    f"(attempt {progression.attempts - attempts + 1}/{progression.attempts})"
                )
                self.ib.placeOrder(contract, order)
                attempts -= 1

            await asyncio.sleep(total_seconds(progression.wait))
            if trade.orderStatus.status == OrderStatus.Filled:
                return trade
            else:
                self.log.info(f"Cancel order {order.orderId} after {progression.attempts} attempts")
                self.ib.cancelOrder(order)
                return None

        return trade
