from __future__ import annotations

import asyncio
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import BrowserContext, Page, TimeoutError, async_playwright

from .ai import ai_client
from .models import (
    Account,
    AccountStatus,
    AppSettings,
    MonitorTask,
    ProductCandidate,
    ProductResult,
    TaskStatus,
)
from .notifier import wechat_notifier
from .runtime_logs import runtime_logs
from .storage import store
from .terminal_qr import image_bytes_to_terminal_blocks, save_image_bytes

GOOFISH_HOME_URL = "https://www.goofish.com/"
GOOFISH_SEARCH_URL = "https://www.goofish.com/search?q={keyword}"
GOOFISH_LOGIN_URL = "https://www.goofish.com/login"
AUTH_COOKIE_NAMES = {"cookie2", "_tb_token_", "unb", "lgc", "sgcookie", "tracknick"}
VERIFY_HINTS = ("验证码", "安全验证", "滑块", "环境异常", "访问受限", "频繁")
BLOCKED_HINTS = ("非法访问", "请使用正常浏览器访问闲鱼", "正常浏览器访问闲鱼")
STRONG_BLOCKED_HINTS = ("请使用正常浏览器访问闲鱼", "正常浏览器访问闲鱼")
STRONG_VERIFY_HINTS = ("验证码", "安全验证", "环境异常", "访问受限")
WEAK_VERIFY_HINTS = ("非法访问", "滑块", "频繁")
CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


def browser_headless_enabled(settings: AppSettings, task: MonitorTask | None = None) -> bool:
    env_value = os.getenv("GOOFISH_BROWSER_HEADLESS", "").strip().lower()
    if env_value in {"1", "true", "yes", "on"}:
        return True
    if env_value in {"0", "false", "no", "off"}:
        return False
    if task is not None and task.browser_headless is not None:
        return task.browser_headless
    if sys.platform.startswith("linux") and not os.getenv("DISPLAY"):
        return True
    return settings.browser.headless


async def setup_stealth_context(context: BrowserContext) -> None:
    """Inject standard browser finger-print overrides to bypass basic headless detection."""
    await context.add_init_script("""
        // 1. Hide navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // 2. Mock languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en']
        });

        // 3. Mock WebGL vendor & renderer
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            // UNMASKED_VENDOR_WEBGL
            if (parameter === 37445) {
                return 'Intel Inc.';
            }
            // UNMASKED_RENDERER_WEBGL
            if (parameter === 37446) {
                return 'Intel(R) Iris(TM) Plus Graphics 640';
            }
            return getParameter.apply(this, arguments);
        };

        // 4. Mock plugins & mimeTypes
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer' }
            ]
        });
        Object.defineProperty(navigator, 'mimeTypes', {
            get: () => [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }
            ]
        });

        // 5. Mock window.chrome
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };

        // 6. Mock permissions
        const originalQuery = navigator.permissions.query;
        navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    """)


class BrowserLoginManager:
    def __init__(self) -> None:
        self._running: set[str] = set()

    async def start_login(self, account: Account) -> None:
        if account.id in self._running:
            return
        self._running.add(account.id)
        try:
            await self._login(account)
        finally:
            self._running.discard(account.id)

    async def _login(self, account: Account) -> None:
        settings = await store.settings.get()
        account.status = AccountStatus.LOGIN_WAITING
        account.last_error = None
        await store.accounts.upsert(account)
        runtime_logs.add("info", "login", f"账号 {account.name} 开始闲鱼扫码登录")

        user_data_dir = Path(settings.browser.user_data_dir) / account.id
        storage_state_path = Path("data/accounts") / f"{account.id}.json"
        storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_login_qr(account.id)

        try:
            async with async_playwright() as playwright:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=browser_headless_enabled(settings),
                    viewport={"width": 1280, "height": 900},
                    locale="zh-CN",
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    args=CHROMIUM_ARGS,
                )
                await setup_stealth_context(context)
                page = context.pages[0] if context.pages else await context.new_page()
                await self._open_goofish_login(page)
                await self._try_switch_to_goofish_qr_login(page)
                await self._print_qr_until_logged_in(context, page, account.id, settings)
                await context.storage_state(path=str(storage_state_path))
                await context.close()

            account.status = AccountStatus.LOGGED_IN
            account.storage_state_path = str(storage_state_path)
            account.last_login_at = datetime.utcnow()
            account.last_error = None
            runtime_logs.add("info", "login", f"账号 {account.name} 登录成功，登录态已保存")
        except Exception as exc:
            account.status = AccountStatus.FAILED
            account.last_error = str(exc)
            runtime_logs.add("error", "login", f"账号 {account.name} 登录失败：{exc}")
        await store.accounts.upsert(account)

    async def _open_goofish_login(self, page: Page) -> None:
        await page.goto(GOOFISH_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        if "goofish.com/login" in page.url:
            return
        for selector in ("a[href*='/login']", "text=登录"):
            try:
                login_links = page.locator(selector)
                if await login_links.count() > 0:
                    await login_links.first.click(timeout=5000)
                    await page.wait_for_timeout(2000)
                    return
            except Exception:
                continue
        await page.goto(GOOFISH_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

    async def _try_switch_to_goofish_qr_login(self, page: Page) -> None:
        selectors = [
            "text=闲鱼扫码登录",
            "text=闲鱼扫码",
            "text=扫码登录",
            "text=二维码登录",
            "text=使用闲鱼扫码",
            "text=APP扫码登录",
            ".qrcode-login",
            "#J_QRCodeLogin",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0:
                    await locator.click(timeout=2500)
                    await page.wait_for_timeout(1000)
                    return
            except Exception:
                continue

    async def _print_qr_until_logged_in(
        self,
        context: BrowserContext,
        page: Page,
        account_id: str,
        settings: AppSettings,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + settings.browser.login_timeout_seconds
        printed = False
        while asyncio.get_running_loop().time() < deadline:
            if await self._is_goofish_logged_in(context, page):
                return
            printed = await self._print_qr(page, account_id, show_terminal_preview=not printed) or printed
            await page.wait_for_timeout(3000)
        raise TimeoutError("等待闲鱼扫码登录超时，请重新点击扫码登录")

    def _clear_login_qr(self, account_id: str) -> None:
        for suffix in ("", "-page"):
            path = Path("data/login-qrcode") / f"{account_id}{suffix}.png"
            try:
                path.unlink(missing_ok=True)
            except Exception:
                continue

    async def _has_auth_cookie(self, context: BrowserContext) -> bool:
        cookies = await context.cookies()
        names = {cookie.get("name") for cookie in cookies}
        return bool(names & AUTH_COOKIE_NAMES)

    async def _is_goofish_logged_in(self, context: BrowserContext, page: Page) -> bool:
        if not await self._has_auth_cookie(context):
            return False
        if "goofish.com/login" in page.url or "login.taobao.com" in page.url:
            return False
        try:
            visible_login_entry = await page.evaluate(
                """
                () => {
                  const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden'
                      && style.display !== 'none'
                      && rect.width > 0
                      && rect.height > 0;
                  };
                  const loginEntries = Array.from(
                    document.querySelectorAll('a[href*="/login"], a[href*="login"], button')
                  ).filter((el) => /登录|扫码/.test(el.innerText || el.textContent || ''));
                  return loginEntries.some(isVisible);
                }
                """
            )
            page_text = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False
        if visible_login_entry:
            return False
            page_title = await page.title()
            if self._matched_visible_block_hint(page.url, page_title, page_text) is not None:
                return False
        return "goofish.com" in page.url

    async def _print_qr(self, page: Page, account_id: str, show_terminal_preview: bool = True) -> bool:
        element_selectors = [
            "canvas",
            "img[src*='qr']",
            "img[src*='QRCode']",
            "[class*='qrcode']",
            "[id*='qrcode']",
            "[class*='qr-code']",
        ]
        for selector in element_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    continue
                image = await locator.screenshot(timeout=3000)
                qr_path = Path("data/login-qrcode") / f"{account_id}.png"
                save_image_bytes(qr_path, image)
                if show_terminal_preview:
                    runtime_logs.add("info", "login", f"已保存登录二维码截图：{qr_path}")
                    print("\n请用闲鱼 App 扫码登录。二维码预览如下，图片文件：", qr_path)
                    print(image_bytes_to_terminal_blocks(image))
                return True
            except Exception:
                continue
        image = await page.screenshot(full_page=True)
        qr_path = Path("data/login-qrcode") / f"{account_id}-page.png"
        save_image_bytes(qr_path, image)
        if show_terminal_preview:
            runtime_logs.add("warning", "login", f"未定位二维码元素，已保存登录页截图：{qr_path}")
            print("\n未能定位二维码元素，已保存登录页截图：", qr_path)
        return True


class MonitorRunner:
    def __init__(self) -> None:
        self._state_lock = asyncio.Lock()
        self._results_lock = asyncio.Lock()
        self._active_tasks: dict[str, asyncio.Task[object]] = {}
        self._busy_accounts: set[str] = set()

    async def run_task(self, task_id: str, scheduled: bool = False) -> MonitorTask:
        account: Account | None = None
        current_task = asyncio.current_task()

        async with self._state_lock:
            task = await store.tasks.get(task_id)
            if task is None:
                raise ValueError("监控任务不存在")

            existing_task = self._active_tasks.get(task_id)
            if existing_task is not None and not existing_task.done():
                return task

            if current_task is not None:
                self._active_tasks[task_id] = current_task

        try:
            async with self._state_lock:
                account = await self._select_account(exclude_account_ids=self._busy_accounts)
                self._busy_accounts.add(account.id)

            task.status = TaskStatus.RUNNING
            task.last_error = None
            await store.tasks.upsert(task)
            run_type = "定时" if scheduled else "手动"
            runtime_logs.add(
                "info",
                "task",
                f"{run_type}运行任务「{task.title}」，关键词：{task.keyword}，页数：{task.pages}",
            )

            settings = await store.settings.get()
            runtime_logs.add("info", "task", f"任务「{task.title}」使用账号：{account.name}")
            results = await self._search_and_analyze(task, account, settings)
            task.last_run_at = datetime.utcnow()
            task.status = TaskStatus.IDLE
            runtime_logs.add(
                "info",
                "task",
                f"任务「{task.title}」完成，处理 {len(results)} 条结果",
            )
        except asyncio.CancelledError:
            latest = await store.tasks.get(task_id)
            task = latest or task
            task.status = TaskStatus.IDLE
            task.enabled = False
            task.last_error = None
            runtime_logs.add("warning", "task", f"任务「{task.title}」已手动停止")
            await store.tasks.upsert(task)
            raise
        except Exception as exc:
            task.status = TaskStatus.IDLE if scheduled else TaskStatus.FAILED
            if scheduled:
                task.last_run_at = datetime.utcnow()
            task.last_error = str(exc)
            runtime_logs.add(
                "warning" if scheduled else "error",
                "task",
                f"任务「{task.title}」本次运行失败：{exc}",
            )
        finally:
            async with self._state_lock:
                if self._active_tasks.get(task_id) is current_task:
                    self._active_tasks.pop(task_id, None)
                if account is not None:
                    self._busy_accounts.discard(account.id)

        await store.tasks.upsert(task)
        return task

    async def stop_task(self, task_id: str) -> MonitorTask:
        task = await store.tasks.get(task_id)
        if task is None:
            raise ValueError("监控任务不存在")

        active_task = self._active_tasks.get(task_id)
        if active_task is not None and not active_task.done():
            active_task.cancel()

        task.enabled = False
        task.status = TaskStatus.IDLE
        task.next_run_at = None
        task.last_error = None
        await store.tasks.upsert(task)
        runtime_logs.add("warning", "task", f"任务「{task.title}」已请求停止")
        return task

    async def _select_account(self, exclude_account_ids: set[str] | None = None) -> Account:
        exclude_account_ids = exclude_account_ids or set()
        accounts = await store.accounts.all()
        logged_in = [
            account
            for account in accounts
            if account.status == AccountStatus.LOGGED_IN and account.storage_state_path
        ]
        if not logged_in:
            raise ValueError("没有可用的已登录账号，请先扫码登录")
        available = [account for account in logged_in if account.id not in exclude_account_ids]
        if not available:
            raise ValueError("没有空闲的已登录账号，请添加并登录更多账号后再同时运行多个任务")
        return min(available, key=lambda item: item.last_login_at or item.created_at)

    async def _search_and_analyze(
        self,
        task: MonitorTask,
        account: Account,
        settings: AppSettings,
    ) -> list[ProductResult]:
        storage_state_path = account.storage_state_path
        if storage_state_path is None:
            raise ValueError("账号登录态不存在")

        results: list[ProductResult] = []
        seen_urls: set[str] = set()
        last_page = None
        knowledge_base_content = await self._knowledge_base_content(task)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=browser_headless_enabled(settings, task),
                args=CHROMIUM_ARGS,
            )
            context = await browser.new_context(
                storage_state=storage_state_path,
                viewport={"width": 1366, "height": 900},
                locale="zh-CN",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            )
            await setup_stealth_context(context)
            page = await context.new_page()
            try:
                for page_number in range(1, task.pages + 1):
                    last_page = page
                    candidates = await self._collect_page_candidates(
                        page,
                        task,
                        settings,
                        page_number,
                    )
                    fresh_candidates = [
                        candidate for candidate in candidates if candidate.url not in seen_urls
                    ]
                    for candidate in fresh_candidates:
                        seen_urls.add(candidate.url)
                    runtime_logs.add(
                        "info",
                        "search",
                        f"搜索页 {page_number}/{task.pages} 新增 "
                        f"{len(fresh_candidates)} 个候选商品",
                    )
                    for index, candidate in enumerate(fresh_candidates, start=1):
                        runtime_logs.add(
                            "info",
                            "ai",
                            f"分析第 {page_number} 页商品 {index}/{len(fresh_candidates)}："
                            f"{candidate.title[:60]}",
                        )
                        detail_candidate = await self._enrich_candidate_from_detail(
                            page,
                            candidate,
                            settings,
                        )
                        result = await self._analyze_candidate(
                            task,
                            settings,
                            detail_candidate,
                            knowledge_base_content,
                        )
                        results.append(result)
                        wechat_notifier.notify_product_background(settings, result)
                        await self._merge_results([result])
                        runtime_logs.add(
                            "info",
                            "task",
                            f"任务「{task.title}」已写入单个商品结果：{candidate.title[:60]}",
                        )
                    await self._human_pause(settings)
                if not results:
                    diagnosis = ""
                    if last_page is not None:
                        diagnosis = await self._diagnose_empty_search(last_page, settings)
                    raise ValueError(
                        "没有提取到真实商品链接。"
                        f"{diagnosis}"
                        "已停止本次监控，避免把分类导航误当成商品。"
                    )
            finally:
                await browser.close()

        return results

    async def _analyze_candidate(
        self,
        task: MonitorTask,
        settings: AppSettings,
        candidate: ProductCandidate,
        knowledge_base_content: str | None,
    ) -> ProductResult:
        decision = await ai_client.analyze(
            settings.ai,
            task.description,
            candidate,
            task.analyze_images,
            knowledge_base_content,
        )
        if decision is None:
            runtime_logs.add("warning", "ai", "AI 设置不完整，本商品跳过分析")
        else:
            runtime_logs.add(
                "info",
                "ai",
                f"AI 评分 {decision.worth_percent}%：{candidate.title[:60]}",
            )
        return ProductResult(
            task_id=task.id,
            task_title=task.title,
            keyword=task.keyword,
            product=candidate,
            decision=decision,
            recommended=bool(decision and decision.worth_percent >= 50),
        )

    async def _knowledge_base_content(self, task: MonitorTask) -> str | None:
        if not task.knowledge_base_id:
            return None
        knowledge_base = await store.knowledge_bases.get(task.knowledge_base_id)
        if knowledge_base is None:
            runtime_logs.add(
                "warning",
                "task",
                f"任务「{task.title}」绑定的知识库不存在，已跳过知识库内容",
            )
            return None
        return knowledge_base.content

    async def _collect_page_candidates(
        self,
        page: Page,
        task: MonitorTask,
        settings: AppSettings,
        page_number: int,
    ) -> list[ProductCandidate]:
        url = GOOFISH_SEARCH_URL.format(keyword=quote(task.keyword))
        if page_number > 1:
            url = f"{url}&page={page_number}"
        runtime_logs.add("info", "search", f"打开搜索页 {page_number}/{task.pages}：{url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3500)
        await self._select_latest_sort(page, page_number)
        page_candidates = await self._extract_products(page)
        runtime_logs.add(
            "info",
            "search",
            f"搜索页 {page_number}/{task.pages} 提取到 {len(page_candidates)} 个候选商品",
        )
        if not page_candidates:
            await self._raise_if_visible_blocked(page, settings)
        return page_candidates

    async def _select_latest_sort(self, page: Page, page_number: int) -> None:
        try:
            clicked = await page.evaluate(
                """
                () => {
                  const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden'
                      && style.display !== 'none'
                      && rect.width > 0
                      && rect.height > 0;
                  };
                  const textOf = (el) => String(el.innerText || el.textContent || '')
                    .replace(/\\s+/g, ' ')
                    .trim();
                  const candidates = Array.from(
                    document.querySelectorAll('[class*="search-select-container"], button, a')
                  ).filter((el) => isVisible(el) && textOf(el) === '新发布');
                  const target = candidates[0];
                  if (!target) return false;
                  target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                  target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                  target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                  target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                  return true;
                }
                """
            )
            if clicked:
                runtime_logs.add("info", "search", f"搜索页 {page_number} 已切换到新发布排序")
                await page.wait_for_timeout(2500)
            else:
                runtime_logs.add("warning", "search", f"搜索页 {page_number} 未找到新发布排序按钮")
        except Exception as exc:
            runtime_logs.add("warning", "search", f"搜索页 {page_number} 切换新发布排序失败：{exc}")

    async def _enrich_candidate_from_detail(
        self,
        page: Page,
        candidate: ProductCandidate,
        settings: AppSettings,
    ) -> ProductCandidate:
        try:
            runtime_logs.add("info", "search", f"打开商品详情页：{candidate.url}")
            await page.goto(candidate.url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)
            await self._raise_if_visible_blocked(page, settings)
            image_urls = await self._extract_detail_images(page)
            if image_urls:
                runtime_logs.add(
                    "info",
                    "search",
                    f"详情页提取到 {len(image_urls)} 张商品图：{candidate.title[:60]}",
                )
                return candidate.model_copy(update={"image_urls": image_urls})
            runtime_logs.add("warning", "search", f"详情页没有提取到商品图：{candidate.title[:60]}")
        except Exception as exc:
            runtime_logs.add(
                "warning",
                "search",
                f"商品详情页图片提取失败，保留无图结果：{candidate.title[:60]}；{exc}",
            )
        return candidate.model_copy(update={"image_urls": []})

    async def _collect_candidates(
        self,
        page: Page,
        task: MonitorTask,
        settings: AppSettings,
    ) -> list[ProductCandidate]:
        candidates: dict[str, ProductCandidate] = {}
        for page_number in range(1, task.pages + 1):
            page_candidates = await self._collect_page_candidates(page, task, settings, page_number)
            for candidate in page_candidates:
                candidates.setdefault(candidate.url, candidate)
            await self._human_pause(settings)
        collected = list(candidates.values())
        runtime_logs.add("info", "search", f"去重后共有 {len(collected)} 个候选商品")
        if not collected:
            diagnosis = await self._diagnose_empty_search(page, settings)
            raise ValueError(
                "没有提取到真实商品链接。"
                f"{diagnosis}"
                "已停止本次监控，避免把分类导航误当成商品。"
            )
        return collected

    async def _extract_detail_images(self, page: Page) -> list[str]:
        raw_urls = await page.evaluate(
            """
            () => {
              const normalizeUrl = (value) => {
                if (!value) return '';
                const trimmed = String(value).trim();
                if (
                  !trimmed ||
                  trimmed.startsWith('data:') ||
                  trimmed.startsWith('blob:')
                ) return '';
                if (trimmed.startsWith('//')) return `${location.protocol}${trimmed}`;
                try {
                  return new URL(trimmed, location.href).href;
                } catch {
                  return '';
                }
              };
              const imageKey = (url) => normalizeUrl(url)
                .replace(/_\\d+x10000q?90?\\.jpg_\\.webp$/i, '_Q90.jpg_.webp')
                .replace(/_\\d+x\\d+q?90?\\.jpg_\\.webp$/i, '_Q90.jpg_.webp')
                .replace(/_\\d+x10000\\.jpg_\\.webp$/i, '_Q90.jpg_.webp');
              const preferOriginalUrl = (url) => normalizeUrl(url)
                .replace(/_\\d+x10000q?90?\\.jpg_\\.webp$/i, '_Q90.jpg_.webp')
                .replace(/_\\d+x\\d+q?90?\\.jpg_\\.webp$/i, '_Q90.jpg_.webp')
                .replace(/_\\d+x10000\\.jpg_\\.webp$/i, '_Q90.jpg_.webp');
              const isUsableImageUrl = (value) => {
                const url = normalizeUrl(value);
                if (!url) return false;
                const lower = url.toLowerCase();
                if (/[-/]\\d{1,2}[-x_]\\d{1,2}(?:\\.|_|-|$)/.test(lower)) return false;
                if (
                  /spacer|blank|transparent|pixel|placeholder|avatar|icon|logo/.test(lower)
                ) return false;
                if (
                  !/\\.(avif|webp|png|jpe?g)(?:[?#]|$)/.test(lower) &&
                  !/(alicdn|taobao|xianyu|goofish)/.test(lower)
                ) {
                  return false;
                }
                return true;
              };
              const srcsetUrls = (value) => String(value || '')
                .split(',')
                .map(part => part.trim().split(/\\s+/)[0])
                .filter(Boolean);
              const collectImgUrls = (img) => {
                const urls = [
                  img.currentSrc,
                  img.src,
                  img.getAttribute('src'),
                  img.getAttribute('data-src'),
                  img.getAttribute('data-ks-lazyload'),
                  img.getAttribute('data-lazy-src'),
                  img.getAttribute('data-original'),
                  img.getAttribute('data-img'),
                ];
                const srcset = img.srcset || img.getAttribute('data-srcset') || '';
                urls.push(...srcsetUrls(srcset));
                return urls;
              };
              const candidates = [];
              const push = (value, rect, sourceOrder, priority) => {
                const url = normalizeUrl(value);
                if (!isUsableImageUrl(url)) return;
                candidates.push({
                  url: preferOriginalUrl(url),
                  key: imageKey(url),
                  top: rect ? rect.top : 0,
                  left: rect ? rect.left : 0,
                  width: rect ? rect.width : 0,
                  height: rect ? rect.height : 0,
                  area: rect ? rect.width * rect.height : 0,
                  sourceOrder,
                  priority,
                });
              };

              const mainWindow = document.querySelector('[class*="item-main-window"]');
              if (mainWindow) {
                Array.from(mainWindow.querySelectorAll('img')).forEach((img, index) => {
                  const rect = img.getBoundingClientRect();
                  const classChain = [];
                  let node = img;
                  for (let depth = 0; depth < 5 && node; depth += 1) {
                    classChain.push(String(node.className || ''));
                    node = node.parentElement;
                  }
                  const chain = classChain.join(' ');
                  const isProductCarousel =
                    /carousel|slick|ant-image|item-main-window-list|fadeInImg/.test(chain);
                  if (!isProductCarousel) return;
                  let priority = 4;
                  if (/slick-active|slick-current/.test(chain)) {
                    priority = 0;
                  } else if (/ant-image/.test(chain)) {
                    priority = 1;
                  } else if (/carousel|slick/.test(chain) && !/slick-cloned/.test(chain)) {
                    priority = 2;
                  } else if (/item-main-window-list|fadeInImg/.test(chain)) {
                    priority = 3;
                  }
                  for (const url of collectImgUrls(img)) {
                    push(url, rect, index, priority);
                  }
                });
              }

              if (candidates.length === 0) {
                Array.from(document.images).forEach((img, index) => {
                  if (img.closest('[class*="feeds-"], [class*="item-feeds"]')) return;
                  if (img.closest('[class*="avatar"], [class*="logo"], [class*="header"]')) return;
                  const rect = img.getBoundingClientRect();
                  if (!rect || rect.width < 120 || rect.height < 120) return;
                  if (rect.top < -20 || rect.top > Math.max(window.innerHeight * 1.2, 1000)) return;
                  for (const url of collectImgUrls(img)) {
                    push(url, rect, index, 10);
                  }
                });
              }

              if (candidates.length === 0) {
                const backgroundElements = document.querySelectorAll('[style*="background"]');
                Array.from(backgroundElements).forEach((element, index) => {
                  if (element.closest('[class*="feeds-"], [class*="item-feeds"]')) return;
                  const rect = element.getBoundingClientRect();
                  if (!rect || rect.width < 120 || rect.height < 120) return;
                  const style = String(element.getAttribute('style') || '');
                  const match = style.match(/url\\(["']?([^"')]+)["']?\\)/i);
                  if (match) push(match[1], rect, 10000 + index, 20);
                });
              }

              const seen = new Set();
              return candidates
                .sort((a, b) => {
                  if (a.priority !== b.priority) return a.priority - b.priority;
                  return a.sourceOrder - b.sourceOrder;
                })
                .filter(item => {
                  if (!item.key || seen.has(item.key)) return false;
                  seen.add(item.key);
                  return true;
                })
                .map(item => item.url)
                .slice(0, 8);
            }
            """
        )
        return [url for url in raw_urls if isinstance(url, str)]

    async def _extract_products(self, page: Page) -> list[ProductCandidate]:
        raw_items = await page.evaluate(
            """
            () => {
              const anchors = Array.from(document.querySelectorAll('a[href]'));
              const items = [];
              const badPathnames = new Set([
                '/',
                '/login',
                '/search',
                '/im',
                '/mach-feeds',
              ]);
              const isProductHref = (href) => {
                try {
                  const url = new URL(href);
                  const host = url.hostname.toLowerCase();
                  const path = url.pathname.toLowerCase();
                  if (!/(goofish|xianyu|taobao)/i.test(host)) return false;
                  if (badPathnames.has(path)) return false;
                  if (/\\/search|\\/login|\\/im|\\/mach-feeds|\\/help|\\/category/.test(path)) {
                    return false;
                  }
                  if (/\\/item|\\/detail|item\\.htm|idle/.test(path)) return true;
                  return url.searchParams.has('id') && !url.searchParams.has('machId');
                } catch {
                  return false;
                }
              };
              const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
              for (const anchor of anchors) {
                const href = anchor.href || '';
                const text = normalize(anchor.innerText || anchor.textContent || '');
                if (!href || text.length < 4) continue;
                if (!isProductHref(href)) continue;
                const root = anchor.closest('[class*="item"], [class*="card"], li, div') || anchor;
                const rootText = normalize(root.innerText || text);
                const priceMatch = rootText.match(/(¥|￥)\\s*\\d+(?:\\.\\d+)?/);
                if (!priceMatch && rootText.length < 8) continue;
                items.push({
                  title: text.slice(0, 120),
                  price: priceMatch ? priceMatch[0] : null,
                  location: null,
                  description: rootText.slice(0, 600),
                  url: href,
                  image_urls: [],
                });
              }
              return items.slice(0, 60);
            }
            """
        )
        products: list[ProductCandidate] = []
        for item in raw_items:
            try:
                products.append(ProductCandidate.model_validate(item))
            except Exception:
                continue
        return products

    async def _raise_if_visible_blocked(self, page: Page, settings: AppSettings) -> None:
        if not settings.browser.stop_on_verification:
            return
        matched = await self._detect_blocked_page(page)
        if matched is not None:
            raise ValueError(f"页面像是验证或访问受限（{matched}），已停止本次监控以保护账号")

    async def _diagnose_empty_search(self, page: Page, settings: AppSettings) -> str:
        visible_text = await self._visible_text(page)
        page_title = await self._page_title(page)
        matched = self._matched_visible_block_hint(page.url, page_title, visible_text)
        if settings.browser.stop_on_verification and matched is not None:
            return f"页面像是验证或访问受限（{matched}）。"
        if "goofish.com/login" in page.url or "login" in page.url:
            return "当前页面像是登录页，可能账号登录态失效。"
        runtime_logs.add(
            "warning",
            "search",
            "搜索页没有提取到商品，但未命中明确拦截信号。"
            f"标题：{page_title or '未知'}；URL：{page.url}",
        )
        return "可能是页面结构变化、搜索无结果，或当前账号看到的结果需要滚动/等待后才加载。"

    async def _visible_text(self, page: Page) -> str:
        try:
            return await page.locator("body").inner_text(timeout=3000)
        except Exception:
            return ""

    async def _page_title(self, page: Page) -> str:
        try:
            return await page.title()
        except Exception:
            return ""

    async def _detect_blocked_page(self, page: Page) -> str | None:
        visible_text = await self._visible_text(page)
        page_title = await self._page_title(page)
        return self._matched_visible_block_hint(page.url, page_title, visible_text)

    def _matched_visible_block_hint(
        self,
        page_url: str,
        page_title: str,
        visible_text: str,
    ) -> str | None:
        compact_text = " ".join(visible_text.split())
        compact_title = " ".join(page_title.split())
        combined = f"{compact_title} {compact_text}"
        for hint in STRONG_BLOCKED_HINTS:
            if hint in compact_text:
                return hint
        for hint in STRONG_VERIFY_HINTS:
            if hint in compact_title:
                return hint
        matched_strong = [hint for hint in STRONG_VERIFY_HINTS if hint in compact_text]
        matched_weak = [hint for hint in WEAK_VERIFY_HINTS if hint in combined]
        if matched_strong and (
            len(compact_text) < 1000 or matched_weak or self._looks_like_verify_url(page_url)
        ):
            return matched_strong[0]
        if "非法访问" in compact_title:
            return "非法访问"
        if compact_text.startswith("非法访问"):
            return "非法访问"
        return None

    def _looks_like_verify_url(self, page_url: str) -> bool:
        lowered = page_url.lower()
        return any(token in lowered for token in ("punish", "verify", "captcha", "sec", "risk"))

    async def _human_pause(self, settings: AppSettings) -> None:
        lower = settings.browser.min_page_delay_seconds
        upper = max(settings.browser.max_page_delay_seconds, lower)
        await asyncio.sleep(random.uniform(lower, upper))

    async def _merge_results(self, new_results: list[ProductResult]) -> None:
        async with self._results_lock:
            existing = await store.results.all()
            seen = {(item.task_id, item.product.url): item for item in existing}
            for result in new_results:
                seen[(result.task_id, result.product.url)] = result
            merged = sorted(seen.values(), key=lambda item: item.fetched_at, reverse=True)
            await store.results.replace_all(merged[:1000])


login_manager = BrowserLoginManager()
monitor_runner = MonitorRunner()
