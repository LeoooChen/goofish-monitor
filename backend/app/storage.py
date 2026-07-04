from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, TypeAdapter

from .models import Account, AppSettings, KnowledgeBase, MonitorTask, NotificationRecord, ProductResult

T = TypeVar("T", bound=BaseModel)


class JsonCollection(Generic[T]):
    def __init__(self, path: Path, model_type: type[T]) -> None:
        self.path = path
        self._adapter = TypeAdapter(list[model_type])  # type: ignore[valid-type]
        self._lock = asyncio.Lock()

    async def all(self) -> list[T]:
        async with self._lock:
            return self._read_unlocked()

    async def replace_all(self, items: list[T]) -> None:
        async with self._lock:
            self._write_unlocked(items)

    async def upsert(self, item: T) -> T:
        async with self._lock:
            items = self._read_unlocked()
            for index, existing in enumerate(items):
                if self._item_id(existing) == self._item_id(item):
                    items[index] = item
                    self._write_unlocked(items)
                    return item
            items.append(item)
            self._write_unlocked(items)
            return item

    async def delete(self, item_id: str) -> bool:
        async with self._lock:
            items = self._read_unlocked()
            kept = [item for item in items if self._item_id(item) != item_id]
            if len(kept) == len(items):
                return False
            self._write_unlocked(kept)
            return True

    async def get(self, item_id: str) -> T | None:
        async with self._lock:
            for item in self._read_unlocked():
                if self._item_id(item) == item_id:
                    return item
            return None

    def _item_id(self, item: T) -> str:
        return str(item.model_dump()["id"])

    def _read_unlocked(self) -> list[T]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return self._adapter.validate_python(raw)

    def _write_unlocked(self, items: list[T]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = [item.model_dump(mode="json") for item in items]
        self.path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def get(self) -> AppSettings:
        async with self._lock:
            if not self.path.exists():
                settings = AppSettings()
                self._write_unlocked(settings)
                return settings
            return AppSettings.model_validate_json(self.path.read_text(encoding="utf-8"))

    async def set(self, settings: AppSettings) -> AppSettings:
        async with self._lock:
            self._write_unlocked(settings)
            return settings

    def _write_unlocked(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")


class AppStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.accounts = JsonCollection(data_dir / "accounts.json", Account)
        self.tasks = JsonCollection(data_dir / "tasks.json", MonitorTask)
        self.knowledge_bases = JsonCollection(data_dir / "knowledge_bases.json", KnowledgeBase)
        self.results = JsonCollection(data_dir / "results.json", ProductResult)
        self.notifications = JsonCollection(data_dir / "notifications.json", NotificationRecord)
        self.settings = SettingsStore(data_dir / "settings.json")


store = AppStore(Path("data"))
