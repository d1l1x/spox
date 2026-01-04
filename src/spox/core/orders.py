from ib_async import (
    Contract,
    LimitOrder,
    Trade
)

from spox.core.component import Component
from spox.core.context import StrategyContext

class OrderManager(Component):

    def __init__(self, ctx: StrategyContext) -> None:
        super().__init__(ctx)

    async def _on_complete_fill(self, trade):
        self.log.info(f"Order {trade.order.orderId} filled")
        # TODO
        # Implement: Save completed orders in database

    async def _onOrderUpdate(self, trade):
        self.log.info(f"Order {trade.order.orderId} updated: {trade.orderStatus.status}")

    async def limit_buy(self, contract:Contract, qty: int, limit:float, order_ref:str = 'SP0X') -> Trade:

        order = LimitOrder("BUY", qty, limit, tif='DAY', orderRef=order_ref)

        self.ctx.log.info(f"Place limit order: {order}")
        trade = self.ib.placeOrder(contract, order)
        trade.filledEvent += self._on_complete_fill

        return trade