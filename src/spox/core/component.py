from __future__ import annotations
from abc import ABC
from .context import StrategyContext

class Component(ABC):
    def __init__(self, ctx: StrategyContext) -> None:
        self.ctx = ctx

    @property
    def ib(self):
        return self.ctx.ib

    @property
    def log(self):
        return self.ctx.log

    @property
    def account(self):
        return self.ctx.account

    @property
    def tz(self):
        return self.ctx.tz