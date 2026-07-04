from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from .models import AiDecision, AiSettings, AiTestResponse, ProductCandidate
from .runtime_logs import runtime_logs


class AiClient:
    def __init__(self) -> None:
        self._last_request_at = 0.0
        self._lock = asyncio.Lock()

    async def analyze(
        self,
        settings: AiSettings,
        task_description: str,
        product: ProductCandidate,
        analyze_images: bool,
        knowledge_base_content: str | None = None,
    ) -> AiDecision | None:
        if settings.api_url is None or not settings.api_key:
            return None

        async with self._lock:
            await self._respect_rate_limit(settings.request_interval_seconds)
            self._last_request_at = time.monotonic()

        prompt = self._build_prompt(task_description, product, knowledge_base_content)
        system_content = (
            "你是一个二手交易商品筛选助手。只返回 JSON，不要 Markdown。\n"
            "JSON 字段必须是 is_target_product(boolean), "
            "worth_percent(0-100整数), reason(string)。\n"
            "worth_percent 表示这个商品是否值得联系购买的综合百分比。\n\n"
            "【通用判定规则】：\n"
            "1. 这是二手商品候选筛选，不是严苛验真。用户写的型号、版本、配置通常表示偏好和搜索目标，"
            "不要因为信息不完整、卖家描述口语化、缺少序列号或不能 100% 确认，就直接判 0 分。\n"
            "2. 型号相近或同产品线的商品也可以给中等分，尤其是价格、成色、图片和卖家信息有联系价值时。"
            "只有明确属于不同产品线、明显不是目标品类、核心型号确定冲突，或存在严重故障/风险时，才给很低分。\n"
            "3. 如果商品标题或描述包含多个互相冲突的型号、品牌或品类，优先相信有上下文的具体描述、实拍图和明确参数，"
            "警惕卖家堆砌关键词引流，但不要仅因出现引流词就否定商品。\n"
            "4. worth_percent 应综合匹配度、价格、成色、风险信号、信息完整度和联系价值评分；"
            "明显不匹配给 0-20 分，疑似相关但信息不足给 30-60 分，目标接近且值得问卖家给 60-85 分，"
            "高度匹配且价格/成色有优势给 85 分以上。\n"
            "5. is_target_product 表示“值得作为候选继续看/联系”，不是“已完全确认型号”。"
            "只要商品大概率属于目标范围或相近可接受范围，就可以为 true。\n"
            "6. 如果用户提供了知识库，只把它当作当前品类的参考资料；知识库与商品信息冲突时，以商品标题、描述和图片中的实际证据为准。"
        )
        messages = [
            {
                "role": "system",
                "content": system_content,
            },
            {"role": "user", "content": self._message_content(prompt, product, analyze_images)},
        ]
        payload = {
            "model": settings.model_name,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        }

        data = await self._post_chat_completions_with_timeout_retry(
            settings,
            headers,
            payload,
            product.title,
        )
        if data is None:
            return None
        content = str(data["choices"][0]["message"]["content"])
        return self._parse_decision(content)

    async def test_connection(self, settings: AiSettings) -> AiTestResponse:
        api_url = str(settings.api_url) if settings.api_url is not None else None
        if settings.api_url is None:
            return AiTestResponse(
                ok=False,
                api_url=None,
                request_url=None,
                model_name=settings.model_name,
                api_key_configured=bool(settings.api_key),
                error="请先填写 API 地址",
            )
        request_url = self._chat_completions_url(str(settings.api_url))
        if not settings.api_key:
            return AiTestResponse(
                ok=False,
                api_url=api_url,
                request_url=request_url,
                model_name=settings.model_name,
                api_key_configured=False,
                error="请先填写 API Key",
            )

        payload = {
            "model": settings.model_name,
            "messages": [
                {"role": "system", "content": "你是连接测试助手。"},
                {"role": "user", "content": "请只回复 ok"},
            ],
            "temperature": 0,
            "max_tokens": 10,
        }
        headers = {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        }
        started_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    request_url,
                    headers=headers,
                    json=payload,
                )
                latency_ms = int((time.monotonic() - started_at) * 1000)
                response.raise_for_status()
                data = response.json()
            preview = str(data["choices"][0]["message"]["content"])[:120]
            return AiTestResponse(
                ok=True,
                api_url=api_url,
                request_url=request_url,
                model_name=settings.model_name,
                api_key_configured=True,
                latency_ms=latency_ms,
                response_preview=preview,
            )
        except httpx.HTTPStatusError as exc:
            return AiTestResponse(
                ok=False,
                api_url=api_url,
                request_url=request_url,
                model_name=settings.model_name,
                api_key_configured=True,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:300]}",
            )
        except Exception as exc:
            return AiTestResponse(
                ok=False,
                api_url=api_url,
                request_url=request_url,
                model_name=settings.model_name,
                api_key_configured=True,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                error=str(exc),
            )

    async def _respect_rate_limit(self, interval_seconds: float | None) -> None:
        if interval_seconds is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < interval_seconds:
            await asyncio.sleep(interval_seconds - elapsed)

    async def _post_chat_completions_with_timeout_retry(
        self,
        settings: AiSettings,
        headers: dict[str, str],
        payload: dict[str, Any],
        product_title: str,
    ) -> dict[str, Any] | None:
        request_url = self._chat_completions_url(str(settings.api_url))
        retry_delays = [8, 20]
        for attempt in range(len(retry_delays) + 1):
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(
                        request_url,
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    response_data = response.json()
                    return response_data if isinstance(response_data, dict) else None
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429:
                    raise
                if attempt >= len(retry_delays):
                    runtime_logs.add(
                        "warning",
                        "ai",
                        f"AI 接口限流 429，已跳过本商品分析：{product_title[:60]}",
                    )
                    return None
                delay = self._retry_after_seconds(exc.response) or retry_delays[attempt]
                runtime_logs.add(
                    "warning",
                    "ai",
                    f"AI 接口限流 429，{delay:.0f} 秒后重试：{product_title[:60]}",
                )
                await asyncio.sleep(delay)
            except httpx.TimeoutException:
                if attempt >= len(retry_delays):
                    runtime_logs.add(
                        "warning",
                        "ai",
                        f"AI 请求连续超时，已跳过本商品分析：{product_title[:60]}",
                    )
                    return None
                delay = retry_delays[attempt]
                runtime_logs.add(
                    "warning",
                    "ai",
                    f"AI 请求超时，{delay} 秒后重试：{product_title[:60]}",
                )
                await asyncio.sleep(delay)
        return None

    def _retry_after_seconds(self, response: httpx.Response) -> float | None:
        retry_after = response.headers.get("retry-after")
        if retry_after is None:
            return None
        try:
            return max(1.0, min(float(retry_after), 120.0))
        except ValueError:
            return None

    def _chat_completions_url(self, api_url: str) -> str:
        trimmed = api_url.rstrip("/")
        if trimmed.endswith("/chat/completions"):
            return trimmed
        if re.search(r"/v\d+$", trimmed):
            return f"{trimmed}/chat/completions"
        if "/api/paas/v4" in trimmed:
            return f"{trimmed}/chat/completions"
        return urljoin(f"{trimmed}/", "v1/chat/completions")

    def _build_prompt(
        self,
        task_description: str,
        product: ProductCandidate,
        knowledge_base_content: str | None,
    ) -> str:
        parts = [
            "我要找的产品：",
            task_description,
        ]
        if knowledge_base_content:
            parts.extend(
                [
                    "",
                    "当前任务可参考的知识库：",
                    knowledge_base_content,
                ]
            )
        parts.extend(
            [
                "",
                "闲鱼搜索到的商品：",
                f"标题：{product.title}",
                f"价格：{product.price or '未知'}",
                f"所在地：{product.location or '未知'}",
                f"描述：{product.description or '无'}",
                f"链接：{product.url}",
                "",
                "请判断这是不是我要的那个产品，并给出值不值得联系购买的百分比。",
            ]
        )
        return "\n".join(parts)

    def _message_content(
        self,
        prompt: str,
        product: ProductCandidate,
        analyze_images: bool,
    ) -> str | list[dict[str, Any]]:
        if not analyze_images or not product.image_urls:
            return prompt
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_url in product.image_urls[:4]:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        return content

    def _parse_decision(self, content: str) -> AiDecision:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.S)
            if match is None:
                raise
            parsed = json.loads(match.group(0))
        return AiDecision.model_validate(parsed)


ai_client = AiClient()
