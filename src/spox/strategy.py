import asyncio
from abc import ABC, abstractmethod
import logging

from dataclasses import dataclass
from zoneinfo import ZoneInfo
from typing import Awaitable, Optional, Callable, List

from ib_async import (
    IB,
    Contract
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.base import BaseTrigger

from zoneinfo import ZoneInfo

from spox.core.context import StrategyContext
from spox.core.market_data import MarketDataTypeManager, MarketDataType


Task = Callable[[StrategyContext], Awaitable[None]]


@dataclass(frozen=True)
class IBConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 42
    readonly: bool = False 


class StrategyError(Exception):
    pass


class StrategyBase(ABC):

    def __init__(
        self,
        instruments: List[Contract],
        name: str,
        *,
        ib: Optional[IB] = None,
        logger: Optional[logging.Logger] = None,
        conn: Optional[IBConnectionConfig] = None,
        account: Optional[str] = None,
        tz: Optional[ZoneInfo] = None,
        md_type: int|None = None,
    ) -> None:

        if not isinstance(instruments, list): 
            raise TypeError(f"{self.__class__}: `instruments` must be a list of contracts")
        else:
            self.instruments = instruments
        self.name = name
        self.ib: IB = ib or IB()
        self.conn = conn or IBConnectionConfig()
        self.account = account 
        self.tz = tz or ZoneInfo("America/New_York")

        self.log = logger or logging.getLogger(f"strategy.{self.name}")

        self.ctx = StrategyContext(
            ib=self.ib,
            log=self.log,
            account=self.account,
            tz=self.tz,
            instruments=self.instruments
            )

        self.md = MarketDataTypeManager(
            self.ctx,
            prefer_liquid_hours=True,
            md_type=md_type or MarketDataType.LIVE.value)

    async def connect(self) -> None:
        if self.ib.isConnected():
            self.log.debug("Already connected to IB.")
            return

        self.log.info(
            "Connecting to IB (host=%s, port=%s, clientId=%s)...",
            self.conn.host,
            self.conn.port,
            self.conn.client_id,
        )

        while not self.ib.isConnected():
            try:
                await self.ib.connectAsync(
                    host=self.conn.host,
                    port=self.conn.port,
                    clientId=self.conn.client_id,
                    readonly=self.conn.readonly,
                )
            except Exception as e:
                self.log.warning(f'Connection error: {e}, retrying in 5s')
                await asyncio.sleep(5)
            else:
                self.log.info("Connected to IB.")

    def disconnect(self) -> None:
        if not self.ib.isConnected():
            return
        try:
            self.ib.disconnect()
        finally:
            self.log.info("Disconnected from IB.")

    @abstractmethod
    async def run(self):
        raise NotImplementedError


class ScheduledStrategy(StrategyBase):

    def __init__(self, instruments:List[Contract], name:str, *, trigger:BaseTrigger, scheduler=None, **kwargs):
        super().__init__(instruments, name, **kwargs)
        self.trigger = trigger
        # self.tz comes from super class
        self.scheduler = scheduler or AsyncIOScheduler(timezone=self.tz)

        self._trades: List[Task] = []


    def add_trade(self, trade: Task) -> None:
        self._trades.append(trade)

    async def run(self):

        if not self._trades:
            raise StrategyError('No trades: self._tasks is empty. Use add_task.')

        for t in self._trades:

            async def runner(trade=t):
                await self.connect()

                for i in self.instruments:
                    await self.md.ensure_md_type(i)

                await trade(self.ctx)

            self.scheduler.add_job( runner, trigger=self.trigger, name=self.name)

        self.scheduler.start()

        try:
            await asyncio.Event().wait()
        finally:
            self.disconnect()