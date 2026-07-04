from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ai import ai_client
from .browser import login_manager, monitor_runner
from .models import (
    Account,
    AccountCreate,
    AiSettings,
    AiTestResponse,
    AppSettings,
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    LoginStartResponse,
    MonitorTask,
    MonitorTaskCreate,
    MonitorTaskUpdate,
    NotifySettings,
    NotifyTestRequest,
    ProductResult,
    ResultFilter,
    RunTaskResponse,
    RuntimeLogEntry,
    TaskStatus,
)
from .notifier import wechat_notifier
from .runtime_logs import runtime_logs
from .scheduler import scheduler
from .storage import store


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(title="AI Goofish Monitor", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIST_DIR = Path("frontend/dist")
FRONTEND_INDEX = FRONTEND_DIST_DIR / "index.html"


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/logs")
async def list_runtime_logs(after_id: int | None = None, limit: int = 300) -> list[RuntimeLogEntry]:
    return runtime_logs.list(after_id=after_id, limit=limit)


@app.delete("/api/logs")
async def clear_runtime_logs() -> dict[str, bool]:
    runtime_logs.clear()
    return {"deleted": True}


@app.get("/api/accounts")
async def list_accounts() -> list[Account]:
    return await store.accounts.all()


@app.post("/api/accounts")
async def create_account(payload: AccountCreate) -> Account:
    account = Account(name=payload.name)
    return await store.accounts.upsert(account)


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str) -> dict[str, bool]:
    deleted = await store.accounts.delete(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"deleted": True}


@app.post("/api/accounts/{account_id}/login")
async def start_login(account_id: str) -> LoginStartResponse:
    account = await store.accounts.get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    asyncio.create_task(login_manager.start_login(account))
    return LoginStartResponse(account=account, message="已打开登录浏览器，请扫码确认")


@app.get("/api/accounts/{account_id}/login-qrcode")
async def get_login_qrcode(account_id: str) -> FileResponse:
    account = await store.accounts.get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    candidates = [
        Path("data/login-qrcode") / f"{account_id}.png",
        Path("data/login-qrcode") / f"{account_id}-page.png",
    ]
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        raise HTTPException(status_code=404, detail="登录二维码还未生成")
    latest = max(existing, key=lambda path: path.stat().st_mtime)
    return FileResponse(
        latest,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/tasks")
async def list_tasks() -> list[MonitorTask]:
    return await store.tasks.all()


@app.post("/api/tasks")
async def create_task(payload: MonitorTaskCreate) -> MonitorTask:
    task = MonitorTask(**payload.model_dump())
    return await store.tasks.upsert(task)


@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, payload: MonitorTaskUpdate) -> MonitorTask:
    task = await store.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="监控任务不存在")
    updated = task.model_copy(update=payload.model_dump(exclude_unset=True))
    return await store.tasks.upsert(updated)


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str) -> dict[str, bool]:
    deleted = await store.tasks.delete(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="监控任务不存在")
    return {"deleted": True}


@app.get("/api/knowledge-bases")
async def list_knowledge_bases() -> list[KnowledgeBase]:
    return await store.knowledge_bases.all()


@app.post("/api/knowledge-bases")
async def create_knowledge_base(payload: KnowledgeBaseCreate) -> KnowledgeBase:
    knowledge_base = KnowledgeBase(**payload.model_dump())
    return await store.knowledge_bases.upsert(knowledge_base)


@app.patch("/api/knowledge-bases/{knowledge_base_id}")
async def update_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseUpdate,
) -> KnowledgeBase:
    knowledge_base = await store.knowledge_bases.get(knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    updated = knowledge_base.model_copy(
        update={
            **payload.model_dump(exclude_unset=True),
            "updated_at": datetime.utcnow(),
        }
    )
    return await store.knowledge_bases.upsert(updated)


@app.delete("/api/knowledge-bases/{knowledge_base_id}")
async def delete_knowledge_base(knowledge_base_id: str) -> dict[str, bool]:
    deleted = await store.knowledge_bases.delete(knowledge_base_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="知识库不存在")

    tasks = await store.tasks.all()
    changed = False
    for task in tasks:
        if task.knowledge_base_id == knowledge_base_id:
            task.knowledge_base_id = None
            changed = True
    if changed:
        await store.tasks.replace_all(tasks)
    return {"deleted": True}


@app.post("/api/tasks/{task_id}/run")
async def run_task(task_id: str) -> RunTaskResponse:
    task = await store.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="监控任务不存在")
    asyncio.create_task(monitor_runner.run_task(task_id))
    return RunTaskResponse(task=task, message="监控任务已开始运行")


@app.post("/api/tasks/{task_id}/start")
async def start_task(task_id: str) -> RunTaskResponse:
    task = await store.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="监控任务不存在")
    if task.status != TaskStatus.RUNNING:
        task.enabled = True
        task.last_error = None
        task.last_run_at = datetime.utcnow()
        task.next_run_at = None
        task = await store.tasks.upsert(task)
        asyncio.create_task(monitor_runner.run_task(task_id))
    return RunTaskResponse(task=task, message="监控任务已启动")


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str) -> RunTaskResponse:
    try:
        task = await monitor_runner.stop_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunTaskResponse(task=task, message="监控任务已停止")


@app.get("/api/settings")
async def get_settings() -> AppSettings:
    return await store.settings.get()


@app.put("/api/settings")
async def update_settings(payload: AppSettings) -> AppSettings:
    return await store.settings.set(payload)


@app.post("/api/settings/ai/test")
async def test_ai_settings(payload: AiSettings) -> AiTestResponse:
    return await ai_client.test_connection(payload)


@app.post("/api/settings/notify/test")
async def test_notify_settings(payload: NotifyTestRequest | NotifySettings) -> dict[str, bool]:
    notify_settings = payload.settings if isinstance(payload, NotifyTestRequest) else payload
    save_settings = payload.save if isinstance(payload, NotifyTestRequest) else False
    try:
        await wechat_notifier.test_wechat_work_webhook(notify_settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if save_settings:
        settings = await store.settings.get()
        await store.settings.set(settings.model_copy(update={"notify": notify_settings}))
    return {"ok": True}


@app.get("/api/results")
async def list_results(
    result_filter: Annotated[ResultFilter, Query(alias="filter")] = "all",
    task_id: str | None = None,
) -> list[ProductResult]:
    results = await store.results.all()
    if task_id:
        results = [item for item in results if item.task_id == task_id]
    if result_filter == "recommended":
        results = [item for item in results if item.recommended]
    elif result_filter == "not_recommended":
        results = [item for item in results if item.decision is not None and not item.recommended]
    elif result_filter == "unanalyzed":
        results = [item for item in results if item.decision is None]
    return results


@app.delete("/api/results")
async def clear_results(task_id: str | None = None) -> dict[str, bool]:
    if task_id is None:
        await store.results.replace_all([])
        return {"deleted": True}
    results = await store.results.all()
    await store.results.replace_all([item for item in results if item.task_id != task_id])
    return {"deleted": True}


if FRONTEND_DIST_DIR.exists():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend(path: str) -> FileResponse:
        requested = FRONTEND_DIST_DIR / path
        if path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_INDEX)
