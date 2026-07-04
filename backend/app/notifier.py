from __future__ import annotations

import asyncio

import httpx

from .models import AppSettings, NotificationRecord, NotifySettings, ProductResult
from .runtime_logs import runtime_logs
from .storage import store


class WechatNotifier:
    def notify_product_background(self, settings: AppSettings, result: ProductResult) -> None:
        if not self._should_notify(settings, result, log_skip=False):
            return
        decision = result.decision
        if decision is not None:
            runtime_logs.add(
                "info",
                "notify",
                f"命中微信提醒阈值 {decision.worth_percent}%：{result.product.title[:60]}",
            )
        task = asyncio.create_task(self.maybe_notify_product(settings, result))
        task.add_done_callback(self._log_background_error)

    async def maybe_notify_product(self, settings: AppSettings, result: ProductResult) -> None:
        if not self._should_notify(settings, result, log_skip=True):
            return
        decision = result.decision
        if decision is None:
            return

        notify = settings.notify
        if await self._already_sent(result):
            runtime_logs.add(
                "info",
                "notify",
                f"商品已发送过微信提醒，跳过：{result.product.title[:60]}",
            )
            return

        try:
            await self._send_wechat_work_webhook(notify, result)
        except Exception as exc:
            runtime_logs.add(
                "error",
                "notify",
                f"微信提醒发送失败：{result.product.title[:60]}；{exc}",
            )
            return

        record = NotificationRecord(
            task_id=result.task_id,
            product_url=result.product.url,
            worth_percent=decision.worth_percent,
        )
        await store.notifications.upsert(record)
        runtime_logs.add(
            "info",
            "notify",
            f"已发送微信提醒 {decision.worth_percent}%：{result.product.title[:60]}",
        )

    async def test_wechat_work_webhook(self, notify: NotifySettings) -> None:
        if not notify.webhook_url:
            raise ValueError("请先填写企业微信机器人 Webhook")
        content = "\n".join(
            [
                "### 闲鱼监控测试提醒",
                "> 企业微信机器人已连接成功。",
                "",
                f"当前提醒阈值：{notify.threshold_percent}%",
            ]
        )
        await self._post_markdown(notify.webhook_url, content, notify.mention_mobile)

    async def _already_sent(self, result: ProductResult) -> bool:
        records = await store.notifications.all()
        return any(
            record.task_id == result.task_id and record.product_url == result.product.url
            for record in records
        )

    async def _send_wechat_work_webhook(
        self,
        notify: NotifySettings,
        result: ProductResult,
    ) -> None:
        decision = result.decision
        if decision is None:
            return
        product = result.product
        content = "\n".join(
            [
                "### 闲鱼高分商品提醒",
                f"> 推荐度：{decision.worth_percent}%",
                f"> 任务：{result.task_title}",
                f"> 商品：{self._escape_markdown(product.title)}",
                f"> 价格：{self._escape_markdown(product.price or '价格未知')}",
                "",
                "**AI 评价**",
                self._escape_markdown(decision.reason),
                "",
                f"[打开商品]({product.url})",
            ]
        )
        await self._post_markdown(notify.webhook_url, content, notify.mention_mobile)

    async def _post_markdown(
        self,
        webhook_url: str,
        content: str,
        mention_mobile: str | None,
    ) -> None:
        if mention_mobile:
            content = f"{content}\n\n<@{mention_mobile}>"
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content[:4096],
            },
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
            data = response.json()
        if data.get("errcode") != 0:
            raise ValueError(str(data))

    def _escape_markdown(self, value: str) -> str:
        return value.replace("\n", " ").strip()

    def _should_notify(
        self,
        settings: AppSettings,
        result: ProductResult,
        *,
        log_skip: bool,
    ) -> bool:
        notify = settings.notify
        if not notify.enabled:
            if log_skip:
                runtime_logs.add("debug", "notify", "微信提醒未启用，跳过发送")
            return False
        if not notify.webhook_url:
            if log_skip:
                runtime_logs.add(
                    "warning",
                    "notify",
                    "微信提醒已启用，但未填写企业微信机器人 Webhook",
                )
            return False
        if result.decision is None:
            return False
        return result.decision.worth_percent >= notify.threshold_percent

    def _log_background_error(self, task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except Exception as exc:
            runtime_logs.add("error", "notify", f"微信提醒后台任务异常：{exc}")


wechat_notifier = WechatNotifier()
