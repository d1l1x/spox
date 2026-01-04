from __future__ import annotations
from dataclasses import dataclass
import logging
from zoneinfo import ZoneInfo
from typing import Optional, List

from ib_async import IB, Contract

@dataclass(slots=True)
class StrategyContext:
    ib: IB
    log: logging.Logger
    tz: ZoneInfo
    instruments: List[Contract]
    account: Optional[str] = None