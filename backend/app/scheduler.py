from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta

from .browser import monitor_runner
from .models import MonitorInterval, TaskStatus
from .storage import store


class TaskScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await self._tick()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=20)

    async def _tick(self) -> None:
        now = datetime.utcnow()
        tasks = await store.tasks.all()
        changed = False
        for task in tasks:
            if not task.enabled or task.interval == MonitorInterval.NONE:
                if task.next_run_at is not None:
                    task.next_run_at = None
                    changed = True
                continue
            seconds = task.interval.seconds
            if seconds is None:
                continue
            baseline = task.last_run_at or task.created_at
            due_at = baseline + timedelta(seconds=seconds)
            if task.next_run_at != due_at:
                task.next_run_at = due_at
                changed = True
            if now >= due_at and task.status != TaskStatus.RUNNING:
                asyncio.create_task(monitor_runner.run_task(task.id, scheduled=True))
        if changed:
            await store.tasks.replace_all(tasks)


scheduler = TaskScheduler()
