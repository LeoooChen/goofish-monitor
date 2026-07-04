from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def new_id() -> str:
    return uuid4().hex


class AccountStatus(StrEnum):
    PENDING = "pending"
    LOGIN_WAITING = "login_waiting"
    LOGGED_IN = "logged_in"
    FAILED = "failed"


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    name: str
    status: AccountStatus = AccountStatus.PENDING
    storage_state_path: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: datetime | None = None
    last_error: str | None = None


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)


class MonitorInterval(StrEnum):
    NONE = "none"
    M5 = "5m"
    M10 = "10m"
    M30 = "30m"
    H1 = "1h"

    @property
    def seconds(self) -> int | None:
        return {
            MonitorInterval.NONE: None,
            MonitorInterval.M5: 5 * 60,
            MonitorInterval.M10: 10 * 60,
            MonitorInterval.M30: 30 * 60,
            MonitorInterval.H1: 60 * 60,
        }[self]


class TaskStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    FAILED = "failed"


class MonitorTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    title: str = Field(min_length=1, max_length=100)
    keyword: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1200)
    knowledge_base_id: str | None = None
    pages: int = Field(default=1, ge=1, le=10)
    analyze_images: bool = False
    browser_headless: bool | None = None
    interval: MonitorInterval = MonitorInterval.NONE
    enabled: bool = True
    status: TaskStatus = TaskStatus.IDLE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_error: str | None = None


class MonitorTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    keyword: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1200)
    knowledge_base_id: str | None = None
    pages: int = Field(default=1, ge=1, le=10)
    analyze_images: bool = False
    browser_headless: bool | None = None
    interval: MonitorInterval = MonitorInterval.NONE
    enabled: bool = True


class MonitorTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=100)
    keyword: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=1200)
    knowledge_base_id: str | None = None
    pages: int | None = Field(default=None, ge=1, le=10)
    analyze_images: bool | None = None
    browser_headless: bool | None = None
    interval: MonitorInterval | None = None
    enabled: bool | None = None


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=200000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=200000)


class KnowledgeBaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, min_length=1, max_length=200000)


class AiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_url: HttpUrl | None = None
    api_key: str = ""
    model_name: str = "gpt-4o-mini"
    request_interval_seconds: float | None = Field(default=None, ge=0.2, le=120)

    @field_validator("api_key")
    @classmethod
    def trim_api_key(cls, value: str) -> str:
        return value.strip()


class AiTestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    api_url: str | None
    request_url: str | None = None
    model_name: str
    api_key_configured: bool
    latency_ms: int | None = None
    response_preview: str | None = None
    error: str | None = None


class BrowserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headless: bool = False
    login_timeout_seconds: int = Field(default=900, ge=60, le=3600)
    min_page_delay_seconds: float = Field(default=6, ge=2, le=120)
    max_page_delay_seconds: float = Field(default=14, ge=3, le=180)
    stop_on_verification: bool = True
    user_data_dir: str = "data/browser-profile"


class NotifySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    threshold_percent: int = Field(default=80, ge=0, le=100)
    webhook_url: str = ""
    mention_mobile: str | None = None

    @field_validator("webhook_url")
    @classmethod
    def trim_webhook_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("mention_mobile")
    @classmethod
    def trim_mention_mobile(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class NotifyTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: NotifySettings
    save: bool = False


class AuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=512)


class AuthStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    authenticated: bool


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai: AiSettings = Field(default_factory=AiSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)


class ProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    price: str | None = None
    location: str | None = None
    description: str | None = None
    url: str
    image_urls: list[str] = Field(default_factory=list)


class AiDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_target_product: bool
    worth_percent: int = Field(ge=0, le=100)
    reason: str


class ProductResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    task_id: str
    task_title: str
    keyword: str
    product: ProductCandidate
    decision: AiDecision | None = None
    recommended: bool = False
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class NotificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    task_id: str
    product_url: str
    worth_percent: int
    sent_at: datetime = Field(default_factory=datetime.utcnow)


class LoginStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: Account
    message: str


class RunTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: MonitorTask
    message: str


class RuntimeLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    timestamp: datetime
    level: Literal["debug", "info", "warning", "error"]
    source: str
    message: str


ResultFilter = Literal["all", "recommended", "not_recommended", "unanalyzed"]
