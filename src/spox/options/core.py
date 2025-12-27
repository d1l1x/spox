from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ib_async import Option

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