import asyncio
from abc import ABC, abstractmethod
import logging

from dataclasses import dataclass
from zoneinfo import ZoneInfo
from typing import Awaitable, Optional, Callable, List

from ib_async import (
    IB,
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.base import BaseTrigger

from zoneinfo import ZoneInfo

from spox.core.context import StrategyContext


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
        *,
        name: str,
        ib: Optional[IB] = None,
        logger: Optional[logging.Logger] = None,
        conn: Optional[IBConnectionConfig] = None,
        account: Optional[str] = None,
        tz: Optional[ZoneInfo] = None,
    ) -> None:
        self.name = name
        self.ib: IB = ib or IB()
        self.conn = conn or IBConnectionConfig()
        self.account = account 
        self.tz = tz or ZoneInfo("America/New_York")

        self.log = logger or logging.getLogger(f"strategy.{self.name}")

        self.ctx = StrategyContext(ib=self.ib, log=self.log, account=self.account, tz=self.tz)

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

    def __init__(self, trigger:BaseTrigger, scheduler=None, **kwargs):
        super().__init__(**kwargs)
        self.trigger = trigger
        # self.tz comes from super class
        self.scheduler = scheduler or AsyncIOScheduler(timezone=self.tz)

        self._tasks: List[Task] = []

    def add_task(self, task: Task) -> None:
        self._tasks.append(task)

    async def run(self):

        if not self._tasks:
            raise StrategyError('No tasks: self._tasks is empty. Use add_task.')

        for t in self._tasks:

            async def runner(task=t):
                await self.connect()
                await task(self.ctx)

            self.scheduler.add_job( runner, trigger=self.trigger, name=self.name)

        self.scheduler.start()

        try:
            await asyncio.Event().wait()
        finally:
            self.disconnect()