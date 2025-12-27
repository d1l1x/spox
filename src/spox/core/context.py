from __future__ import annotations
from dataclasses import dataclass
import logging
from zoneinfo import ZoneInfo
from typing import Optional

from ib_async import IB

@dataclass(slots=True)
class StrategyContext:
    ib: IB
    log: logging.Logger
    tz: ZoneInfo
    account: Optional[str] = None