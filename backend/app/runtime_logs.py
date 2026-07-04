from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Literal

from .models import RuntimeLogEntry

LogLevel = Literal["debug", "info", "warning", "error"]


class RuntimeLogBuffer:
    def __init__(self, max_entries: int = 500) -> None:
        self._entries: deque[RuntimeLogEntry] = deque(maxlen=max_entries)
        self._next_id = 1

    def add(
        self,
        level: LogLevel,
        source: str,
        message: str,
    ) -> RuntimeLogEntry:
        entry = RuntimeLogEntry(
            id=self._next_id,
            timestamp=datetime.utcnow(),
            level=level,
            source=source,
            message=message,
        )
        self._next_id += 1
        self._entries.append(entry)
        return entry

    def list(self, after_id: int | None = None, limit: int = 300) -> list[RuntimeLogEntry]:
        entries = list(self._entries)
        if after_id is not None:
            entries = [entry for entry in entries if entry.id > after_id]
        return entries[-limit:]

    def clear(self) -> None:
        self._entries.clear()


runtime_logs = RuntimeLogBuffer()
