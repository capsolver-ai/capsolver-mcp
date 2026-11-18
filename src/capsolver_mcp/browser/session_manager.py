"""Managed and attached Chromium sessions."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse, urlsplit
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager

from capsolver_mcp.browser.adapters import CAPTURE_SCRIPT, EXTRACT_SCRIPT, apply_solution, extract_recipe, fingerprint
from capsolver_mcp.browser.capture import ResponseCapture, capture_options, safe_url

if TYPE_CHECKING:
    from capsolver_mcp.runtime import Runtime


def is_loopback_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme in {"about", "data", "blob"}:
        return True
    try:
        return parsed.scheme in {"http", "https", "ws", "wss"} and (
            parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
        )
    except ValueError:
        return False


@dataclass
class BrowserSession:
    browser: Any
    context: Any
    owned: bool
    pages: dict[str, Any] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    challenges: dict[str, dict[str, Any]] = field(default_factory=dict)
    network: dict[str, deque[dict[str, Any]]] = field(default_factory=dict)
    captures: dict[str, ResponseCapture] = field(default_factory=dict)
    evidence_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    request_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    request_context: Any = None
    closing: bool = False
    close_task: Any = None
    cleanup_done: set[str] = field(default_factory=set)
    video_paths: list[str] = field(default_factory=list)
    shutdown_steps: list[dict[str, Any]] = field(default_factory=list)


class BrowserManager:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.sessions: dict[str, BrowserSession] = {}
        self._playwright: Any = None
        self._manager_lock = asyncio.Lock()
        self.last_shutdown: dict[str, Any] = {}
        self.cleanup_timeout = 5.0

    async def _guard_route(self, route: Any) -> None:
        if is_loopback_url(route.request.url):
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    def _url(self, url: str) -> None:
        if urlparse(url).scheme not in {"http", "https", "about"}:
            raise ValueError("Only HTTP(S) pages or about:blank can be opened.")
        if self.runtime.settings.offline and not is_loopback_url(url):
            raise ValueError("Offline browser sessions allow loopback pages only.")

    def _request_url(self, url: str) -> None:
        self._url(url)
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("Session requests require HTTP(S) without embedded credentials.")
        if parsed.hostname == "api.capsolver.com":
            raise ValueError("Use the core MCP for CapSolver API calls and task recovery.")

    async def open(
        self,
        url: str = "about:blank",
        *,
        user_agent: str | None = None,
        headless: bool = True,
        cdp_endpoint: str | None = None,
        cdp_target_id: str | None = None,
        record_video: bool = False,
        response_capture: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._url(url)
        if cdp_target_id and not cdp_endpoint:
            raise ValueError("cdp_target_id requires a CDP endpoint.")
        options = capture_options(response_capture) if response_capture is not None else None
        async with self._manager_lock:
            if len(self.sessions) >= self.runtime.settings.max_browser_sessions:
                raise ValueError("Browser session limit reached. Close a session first.")
            if self._playwright is None:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
            browser = context = None
            owned = cdp_endpoint is None
            try:
                if cdp_endpoint:
                    if record_video:
                        raise ValueError("Video recording is available for managed sessions only.")
                    if self.runtime.settings.offline and not is_loopback_url(cdp_endpoint):
                        raise ValueError("Offline attachment requires a loopback CDP endpoint.")
                    if user_agent:
                        raise ValueError("Attaching cannot change an existing browser's User-Agent.")
                    if urlparse(cdp_endpoint).scheme not in {"http", "https", "ws", "wss"}:
                        raise ValueError("CDP endpoint must be an HTTP(S) or WebSocket URL.")
                    browser = await self._playwright.chromium.connect_over_cdp(cdp_endpoint, timeout=15000)
                    if not browser.contexts:
                        raise ValueError("The attached browser has no accessible context.")
                    if cdp_target_id:
                        page = await self._cdp_page(browser, cdp_target_id)
                        context = page.context
                    else:
                        context = browser.contexts[0]
                        page = next((p for p in context.pages if p.url == url), None) if url != "about:blank" else None
                        page = page or (context.pages[0] if context.pages else await context.new_page())
                    if self.runtime.settings.offline and not is_loopback_url(page.url):
                        raise ValueError("Offline attachment cannot operate an external page.")
                else:
                    browser = await self._playwright.chromium.launch(
                        headless=headless,
                        args=[
                            "--disable-background-networking",
                            "--disable-component-update",
                            "--no-first-run",
                            *(["--disable-http2"] if self.runtime.settings.browser_disable_http2 else []),
                        ],
                    )
                    video_dir = self.runtime.settings.state_dir / "videos"
                    if record_video:
                        video_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                    context = await browser.new_context(
                        user_agent=user_agent,
                        service_workers="block",
                        viewport={"width": 1280, "height": 720},
                        record_video_dir=str(video_dir) if record_video else None,
                        record_video_size={"width": 1280, "height": 720} if record_video else None,
                    )
                    page = await context.new_page()
                context.set_default_timeout(10000)
                await context.add_init_script(CAPTURE_SCRIPT)
                if self.runtime.settings.offline:
                    await context.route("**/*", self._guard_route)
                    if hasattr(context, "route_web_socket"):
                        await context.route_web_socket("**/*", lambda socket: socket.close())
                session_id, page_id = uuid.uuid4().hex, uuid.uuid4().hex
                session = BrowserSession(browser, context, owned)
                session.pages[page_id] = page
                session.locks[page_id] = asyncio.Lock()
                self._track_network(session, page_id, page)
                if options:
                    session.captures[page_id].configure(options)
                if url != "about:blank" and page.url != url:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self.sessions[session_id] = session
                return {
                    "ok": True,
                    "session_id": session_id,
                    "page_id": page_id,
                    "url": page.url,
                    "owned": owned,
                    "response_capture": dict(session.captures[page_id].options),
                    "execution_mode": "offline_simulated" if self.runtime.settings.offline else "provider",
                }
            except BaseException:
                if "session" in locals():
                    for capture in session.captures.values():
                        await capture.aclose()
                if browser:
                    await browser.close()  # CDP close disconnects; it does not terminate the remote browser.
                raise

    async def _cdp_page(self, browser: Any, target_id: str) -> Any:
        for context in browser.contexts:
            for page in context.pages:
                connection = await context.new_cdp_session(page)
                try:
                    info = await connection.send("Target.getTargetInfo")
                    if info["targetInfo"]["targetId"] == target_id:
                        return page
                finally:
                    await connection.detach()
        raise ValueError("The requested CDP tab is no longer open.")

    def _track_network(self, session: BrowserSession, page_id: str, page: Any) -> None:
        session.network[page_id] = deque(maxlen=100)
        capture = ResponseCapture(self.runtime.settings.state_dir / "browser-evidence" / session.evidence_id / page_id)
        session.captures[page_id] = capture

        def on_response(response: Any) -> None:
            parsed = urlsplit(response.url)
            if parsed.scheme not in {"http", "https"}:
                return
            session.network[page_id].append(capture.observe(response))

        page.on("response", on_response)

    async def add_init_script(self, session_id: str, page_id: str, script: str) -> dict[str, Any]:
        if not script.strip() or len(script.encode()) > 100_000:
            raise ValueError("script must be nonempty and at most 100000 bytes.")
        session, page = self.get(session_id, page_id)
        async with session.locks[page_id]:
            capture = session.captures[page_id]
            record = capture.record_script(script)
            try:
                await page.add_init_script(script=script)
            except BaseException:
                capture.scripts.pop(record["script_id"])
                from pathlib import Path

                Path(record["script_file"]).unlink(missing_ok=True)
                raise
            return {"ok": True, **record,
                    "applies_to": "future navigations and child frames of this page",
                    "already_loaded_content_changed": False}

    async def configure_capture(self, session_id: str, page_id: str, options: dict[str, Any]) -> dict[str, Any]:
        session, _ = self.get(session_id, page_id)
        async with session.locks[page_id]:
            return {"ok": True, "capture": session.captures[page_id].configure(options),
                    "note": "Only future matching page responses are captured. No requests are replayed."}

    async def get_response(self, session_id: str, page_id: str, response_id: str, **options: Any) -> dict[str, Any]:
        session, _ = self.get(session_id, page_id)
        return {"ok": True, **await session.captures[page_id].get(response_id, **options)}

    @asynccontextmanager
    async def _request_transport(self, session: BrowserSession, allow_direct: bool) -> AsyncIterator[Any]:
        if session.owned:
            yield session.context.request
            return
        if not allow_direct:
            raise ValueError("Set allow_direct=true to make a separate direct request from a CDP attachment.")
        # CDP does not inherit the external browser's transport. Synchronize only changed cookies.
        if session.request_context is not None:
            await session.request_context.dispose()
            session.request_context = None
        before = await session.context.cookies()
        context = await self._playwright.request.new_context(
            storage_state={"cookies": before, "origins": []},
        )
        session.request_context = context
        try:
            yield context
        finally:
            try:
                after = (await context.storage_state())["cookies"]
                def key(cookie: Mapping[str, Any]) -> tuple[str, str, str, str | None]:
                    return cookie["name"], cookie["domain"], cookie["path"], cookie.get("partitionKey")
                old, new = {key(c): c for c in before}, {key(c): c for c in after}
                changed = [c for k, c in new.items() if old.get(k) != c]
                for name, domain, path, _ in old.keys() - new.keys():
                    await session.context.clear_cookies(name=name, domain=domain, path=path)
                if changed:
                    await session.context.add_cookies(changed)
            finally:
                await context.dispose()
                session.request_context = None

    async def api_request(
        self, session_id: str, page_id: str, url: str, *, method: str = "GET",
        headers: dict[str, str] | None = None, data: dict[str, Any] | str | None = None,
        timeout_ms: int = 15000, follow_redirects: bool = False,
        max_body_bytes: int = 1_000_000, include_body: bool = True, allow_direct: bool = False,
    ) -> dict[str, Any]:
        self._request_url(url)
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ValueError("Unsupported HTTP method.")
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 30000:
            raise ValueError("timeout_ms must be between 1 and 30000.")
        capture_options({"max_body_bytes": max_body_bytes})
        if data is not None and len(str(data).encode()) > 1_000_000:
            raise ValueError("Request data exceeds 1000000 bytes.")
        session, page = self.get(session_id, page_id)
        async with session.request_lock, session.locks[page_id], self._request_transport(session, allow_direct) as transport:
            chain = []
            current_headers = dict(headers or {})
            # A CDP connection does not inherit the owner's context UA in its
            # APIRequestContext. Read the selected tab, preserving an explicit
            # caller override, rather than sending Playwright's default UA.
            if not any(key.lower() == "user-agent" for key in current_headers):
                current_headers["User-Agent"] = await page.evaluate("navigator.userAgent")
            deadline = time.monotonic() + timeout_ms / 1000
            for index in range(6):
                self._request_url(url)  # APIRequestContext is not covered by page.route.
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    raise TimeoutError("Session request timed out.")
                attempt = session.captures[page_id].begin_request(url, method, current_headers, data)
                try:
                    response = await transport.fetch(
                        url, method=method, headers=current_headers, data=data,
                        timeout=remaining_ms, max_redirects=0, max_retries=0,
                    )
                except Exception as exc:
                    from capsolver_mcp.tools.tasks import tool_error

                    session.captures[page_id].failure(attempt, "delivery_unknown", exc)
                    return {**tool_error(exc), "stage": "session_request", **attempt,
                            "is_new_request": True, "automatic_retry": False,
                            "note": "A delivery error does not prove a state-changing request was not received."}
                try:
                    record = await session.captures[page_id].save_request(response, {
                        "url": url, "method": method, "supplied_headers": current_headers,
                        "supplied_data": data, "headers_complete": False,
                        "note": "Cookies are context-managed; the selected page UA is explicit unless overridden.",
                    }, max_body_bytes, row=attempt)
                    chain.append({"response_id": record["response_id"], "url": safe_url(url), "status": response.status})
                    location = response.headers.get("location")
                    if not follow_redirects or response.status not in {301, 302, 303, 307, 308} or not location:
                        detail = await session.captures[page_id].get(record["response_id"], include_body=include_body)
                        return {"ok": True, "http_ok": response.ok, **detail, "redirect_chain": chain,
                                "is_new_request": True, "page_navigated": False,
                                "request_transport": "managed_context" if session.owned else "explicit_direct",
                                "note": "Cookies are shared or synchronized for this separate request."}
                    if index == 5:
                        raise ValueError("Session request redirect limit reached.")
                    target = urljoin(url, location)
                    if urlsplit(target)[:2] != urlsplit(url)[:2]:
                        current_headers = {k: v for k, v in current_headers.items()
                                           if k.lower() not in {"authorization", "cookie", "proxy-authorization", "host"}}
                    if response.status == 303 or (response.status in {301, 302} and method == "POST"):
                        method, data = "GET", None
                        current_headers = {k: v for k, v in current_headers.items()
                                           if k.lower() not in {"content-type", "content-length"}}
                    url = target
                finally:
                    await response.dispose()
        raise ValueError("Session request did not complete.")

    def get(self, session_id: str, page_id: str) -> tuple[BrowserSession, Any]:
        if session_id not in self.sessions or page_id not in self.sessions[session_id].pages:
            raise KeyError("Browser session or page not found.")
        session = self.sessions[session_id]
        if session.closing:
            raise ValueError("Browser session is closing or cleanup failed; retry browser_close.")
        page = session.pages[page_id]
        if page.is_closed():
            raise ValueError("The browser page is closed.")
        return session, page

    async def inspect(self, session_id: str, page_id: str) -> dict[str, Any]:
        session, page = self.get(session_id, page_id)
        async with session.locks[page_id]:
            for p in session.context.pages:
                if p not in session.pages.values():
                    identifier = uuid.uuid4().hex
                    session.pages[identifier] = p
                    session.locks[identifier] = asyncio.Lock()
                    self._track_network(session, identifier, p)
            fields = await page.locator("input,textarea,select,button").evaluate_all("""els => els.map(e=>({
                tag:e.tagName.toLowerCase(),type:e.type||'',name:e.name||'',id:e.id||'',
                label:e.getAttribute('aria-label')||e.placeholder||e.innerText||'',
                value:['password','hidden'].includes(e.type)||!e.getClientRects().length
                    ||getComputedStyle(e).visibility==='hidden'?'[REDACTED]':e.value||''})).slice(0,200)""")
            return {
                "ok": True,
                "url": page.url,
                "title": await page.title(),
                "fields": fields,
                "text": (await page.locator("body").inner_text())[:12000],
                "tables": await page.locator("table").evaluate_all(
                    "els=>els.slice(0,10).map(t=>[...t.rows].slice(0,200).map(r=>[...r.cells].map(c=>c.innerText.slice(0,2000))))"
                ),
                "pages": [{"page_id": key, "url": p.url, "closed": p.is_closed()} for key, p in session.pages.items()],
            }

    async def action(self, session_id: str, page_id: str, action: str, options: dict[str, Any]) -> dict[str, Any]:
        session, page = self.get(session_id, page_id)
        async with session.locks[page_id]:
            if action == "navigate":
                self._url(options["url"])
                await page.goto(options["url"], wait_until="domcontentloaded")
            elif action in {"fill", "click", "press", "select"}:
                locator = page.locator(options["selector"])
                if await locator.count() != 1:
                    raise ValueError("Action selector must match exactly one element.")
                if action == "fill":
                    await locator.fill(options["value"])
                elif action == "click":
                    await locator.click()
                elif action == "press":
                    await locator.press(options["key"])
                else:
                    await locator.select_option(options["value"])
            elif action == "wait":
                await page.locator(options["selector"]).wait_for(
                    state=options.get("state", "visible"), timeout=min(max(options.get("timeout_ms", 10000), 1), 30000)
                )
            elif action == "scroll":
                await page.mouse.wheel(options.get("x", 0), options.get("y", 500))
            elif action == "screenshot":
                directory = self.runtime.settings.state_dir / "screenshots"
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                path = directory / (uuid.uuid4().hex + ".png")
                await page.screenshot(path=str(path), full_page=options.get("full_page", False))
                return {"ok": True, "path": str(path)}
            else:
                raise ValueError("Unsupported browser action.")
            return {"ok": True, "url": page.url}

    async def detect(self, session_id: str, page_id: str) -> dict[str, Any]:
        session, page = self.get(session_id, page_id)
        async with session.locks[page_id]:
            return await self._detect(session, page, page_id)

    async def _detect(self, session: BrowserSession, page: Any, page_id: str) -> dict[str, Any]:
        found = []
        # Avoid leaking accumulated challenge inputs from previous detections.
        session.challenges = {
            k: v for k, v in session.challenges.items()
            if v["page_id"] != page_id or (
                "prepared_task" in v and not v.get("consumed")
                and time.time() - v["prepared_at"] < 300
            )
        }
        for frame in page.frames:
            try:
                items = await frame.evaluate(EXTRACT_SCRIPT)
            except Exception:
                continue  # Detached or not-yet-loaded frames cannot supply stable inputs.
            for item in items:
                try:
                    entry = self.runtime.catalog.get(item["task"]["type"])
                except ValueError:
                    continue
                identifier = uuid.uuid4().hex
                revision = item.get("revision", "")
                record = {
                    **item,
                    "frame": frame,
                    "page_id": page_id,
                    "fingerprint": fingerprint(item["task"], revision, frame.url),
                }
                session.challenges[identifier] = record
                found.append(
                    {
                        "captcha_id": identifier,
                        "task": item["task"],
                        "frame_url": frame.url,
                        "adapter": entry["browser_adapter"],
                        "proxy_policy": entry["proxy_policy"],
                    }
                )
        return {"ok": True, "captchas": found, "url": page.url}

    async def _still_current(self, record: dict[str, Any], page: Any, recipe: dict[str, Any] | None) -> bool:
        frame = record["frame"]
        if frame.is_detached():
            return False
        if binding := record.get("challenge_binding"):
            challenge_frame = binding["frame"]
            if challenge_frame.is_detached() or challenge_frame.url != binding["url"]:
                return False
            try:
                # The same Frame object and URL can survive a document reload.
                # A document's time origin changes when that document is replaced.
                if await challenge_frame.evaluate("performance.timeOrigin") != binding["document_origin"]:
                    return False
            except Exception:
                return False  # Navigation/detachment while checking is not fresh evidence.
        if recipe:
            task = await extract_recipe(page, frame, recipe, local_only=self.runtime.settings.offline)
            return bool(fingerprint(task, "", frame.url) == record["fingerprint"])
        items = await frame.evaluate(EXTRACT_SCRIPT)
        return any(fingerprint(i["task"], i.get("revision", ""), frame.url) == record["fingerprint"] for i in items)

    async def _condition(self, page: Any, verification: dict[str, Any]) -> bool:
        if verification.get("selector"):
            locator = page.locator(verification["selector"])
            if await locator.count() != 1 or not await locator.is_visible():
                return False
            if "text" in verification and verification["text"] not in await locator.inner_text():
                return False
            return True
        if verification.get("url_pattern"):
            return bool(re.search(verification["url_pattern"], page.url))
        return False

    @staticmethod
    def _validate_verification(verification: dict[str, Any]) -> None:
        timeout = verification.get('timeout_ms', 10000)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 30000:
            raise ValueError('Verification timeout_ms must be between 1 and 30000.')
        if "response" in verification:
            spec = verification["response"]
            if (
                not isinstance(spec, dict)
                or not isinstance(spec.get("url_pattern"), str)
                or not spec["url_pattern"]
                or not isinstance(spec.get("json_path"), str)
                or not spec["json_path"]
                or any(not k for k in spec["json_path"].split("."))
            ):
                raise ValueError(
                    "Response verification requires url_pattern and a business json_path; HTTP status alone is insufficient."
                )
            re.compile(spec["url_pattern"])
        if verification.get("url_pattern"):
            re.compile(verification["url_pattern"])

    async def _prepare_locked(
        self,
        session: BrowserSession,
        page: Any,
        page_id: str,
        captcha_id: str | None,
        recipe: dict[str, Any] | None,
        task_overrides: dict[str, Any] | None,
        submit: bool,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        recipe = recipe or {}
        if recipe.get("task"):
            frame = page.main_frame
            if recipe.get("frame_selector"):
                frame_element = await page.locator(recipe["frame_selector"]).element_handle()
                frame = await frame_element.content_frame() if frame_element else None
                if frame is None:
                    raise ValueError("Recipe frame was not found.")
            task = await extract_recipe(page, frame, recipe, local_only=self.runtime.settings.offline)
            record = {
                "frame": frame,
                "page_id": page_id,
                "task": task,
                "fingerprint": fingerprint(task, "", frame.url),
            }
        else:
            if captcha_id is None:
                detections = await self._detect(session, page, page_id)
                if len(detections["captchas"]) != 1:
                    raise ValueError(
                        "Select a captcha_id or supply a recipe when the page has zero or multiple captchas."
                    )
                captcha_id = detections["captchas"][0]["captcha_id"]
            selected_record = session.challenges.get(captcha_id)
            if not selected_record or selected_record["page_id"] != page_id:
                raise ValueError("Captcha selection is stale or belongs to another page.")
            record = selected_record
            task = dict(record["task"])
        original_entry = self.runtime.catalog.get(task["type"])
        task.update(task_overrides or {})
        entry = self.runtime.catalog.get(task["type"])
        if entry["browser_adapter"] != original_entry["browser_adapter"]:
            raise ValueError("Task override cannot switch the selected captcha to another family.")
        if entry["browser_adapter"] in {"datadome", "cloudflare_challenge"}:
            actual_ua = await page.evaluate("navigator.userAgent")
            if task.get("userAgent", actual_ua) != actual_ua:
                raise ValueError("Solver User-Agent must match the current browser.")
            task["userAgent"] = actual_ua
            if recipe.get("include_html"):
                task["html"] = await page.content()
        self.runtime.catalog.validate(task, defer_proxy=True)
        if entry["browser_adapter"] == "datadome":
            matching_frames = [f for f in page.frames if not f.is_detached() and f.url == task["captchaUrl"]]
            if len(matching_frames) != 1:
                raise ValueError("DataDome captchaUrl must match exactly one loaded challenge frame. Reacquire the current challenge.")
            if "challenge_binding" not in record:
                challenge_frame = matching_frames[0]
                record["challenge_binding"] = {
                    "frame": challenge_frame, "url": task["captchaUrl"],
                    "document_origin": await challenge_frame.evaluate("performance.timeOrigin"),
                }
        application = recipe.get("application", {})
        if application.get("interaction"):
            spec = application["interaction"]
            size = spec.get("image_size")
            if (
                not isinstance(size, list)
                or len(size) != 2
                or any(not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0 for n in size)
            ):
                raise ValueError("Recognition interactions require two finite positive image dimensions.")
            if task.get("module") in {"slider_1", "rotate_1", "rotate_2"} and not spec.get("handle_selector"):
                raise ValueError("Drag/rotation recipes require a handle_selector before submission.")
            if task.get("module") in {"rotate_1", "rotate_2"}:
                scale = spec.get("pixels_per_degree")
                if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
                    raise ValueError("Rotation recipes require finite positive pixels_per_degree.")
        if submit and not application.get("submit_selector") and not application.get("reload"):
            raise ValueError("Submitting requires an explicit submit_selector or reload action in the recipe.")
        selectors = list(application.get("fields", {}).values())
        if submit and application.get("submit_selector"):
            selectors.append(application["submit_selector"])
        if application.get("interaction"):
            selectors.append(application["interaction"]["selector"])
            if application["interaction"].get("handle_selector"):
                selectors.append(application["interaction"]["handle_selector"])
        for selector in selectors:
            if await record["frame"].locator(selector).count() != 1:
                raise ValueError("Recipe selector must match exactly one element before submitting a task.")
        if entry["browser_adapter"] in {
            "ocr",
            "vision",
            "recaptcha_image",
            "aws_image",
            "geetest",
            "botdeflector",
        } and not any(application.get(key) for key in ("fields", "callback", "interaction")):
            raise ValueError("This captcha requires an explicit application recipe before submitting a task.")
        if not await self._still_current(record, page, recipe if recipe.get("task") else None):
            raise ValueError("The page challenge changed. Detect or extract fresh parameters before submitting.")
        verification = recipe.get("verification", {})
        self._validate_verification(verification)
        return record, task, recipe

    async def prepare(
        self,
        session_id: str,
        page_id: str,
        *,
        captcha_id: str | None = None,
        recipe: dict[str, Any] | None = None,
        task_overrides: dict[str, Any] | None = None,
        submit: bool = False,
        save_task_file: bool = False,
    ) -> dict[str, Any]:
        """Extract one challenge without contacting a solver or reading its key."""
        from copy import deepcopy
        import json
        import os

        session, page = self.get(session_id, page_id)
        async with session.locks[page_id]:
            session.challenges = {
                k: v
                for k, v in session.challenges.items()
                if not v.get("consumed") and time.time() - v.get("prepared_at", time.time()) < 300
            }
            if len(session.challenges) >= 128:
                raise ValueError("Prepared challenge limit reached. Close the session or wait for expiry.")
            record, task, recipe = await self._prepare_locked(
                session, page, page_id, captcha_id, recipe, task_overrides, submit
            )
            identifier = uuid.uuid4().hex
            session.challenges[identifier] = {
                **record,
                "prepared_task": deepcopy(task),
                "recipe": deepcopy(recipe),
                "prepared_at": time.time(),
            }
            output: dict[str, Any] = {
                "ok": True,
                "captcha_id": identifier,
                "task": task,
                "user_agent": await page.evaluate("navigator.userAgent"),
                "provider_called": False,
            }
            if save_task_file:
                directory = self.runtime.settings.state_dir / "task-inputs"
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                path = directory / (identifier + ".json")
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as handle:
                    json.dump(task, handle)
                output.pop("task")
                output["task_file"] = str(path.resolve())
            return output

    async def apply(
        self,
        session_id: str,
        page_id: str,
        captcha_id: str,
        solution: dict[str, Any],
        *,
        submit: bool = False,
    ) -> dict[str, Any]:
        """Apply a caller-supplied result to its original prepared challenge."""
        session, page = self.get(session_id, page_id)
        async with session.locks[page_id]:
            record = session.challenges.get(captcha_id)
            if not record or record["page_id"] != page_id or "prepared_task" not in record:
                raise ValueError("Call browser_prepare_captcha for this page before applying a result.")
            if time.time() - record["prepared_at"] >= 300 or record.get("consumed"):
                raise ValueError("Prepared challenge expired or was already applied; extract a fresh challenge.")
            if not solution:
                raise ValueError("A nonempty solution from the core MCP is required.")
            recipe, task = record["recipe"], record["prepared_task"]
            self._validate_verification(recipe.get("verification", {}))
            if submit and not any(recipe.get("application", {}).get(k) for k in ("reload", "submit_selector")):
                raise ValueError("Submitting requires an explicit recipe action.")
            preexisting = await self._condition(page, recipe.get("verification", {}))
            response = {
                "ok": True,
                "solution_received": True,
                "provider_called": False,
                "applied": False,
                "verified": False,
                "verification": "verification_unknown",
            }
            result = await self._apply_locked(
                page, record, task, solution, recipe, submit, preexisting, response, attached=not session.owned
            )
            if result["applied"]:
                record["consumed"] = True
            return result

    async def _apply_locked(
        self,
        page: Any,
        record: dict[str, Any],
        task: dict[str, Any],
        solution: dict[str, Any],
        recipe: dict[str, Any],
        submit: bool,
        preexisting_success: bool,
        response: dict[str, Any],
        *,
        attached: bool,
    ) -> dict[str, Any]:
        verification = recipe.get("verification", {})
        stage = "apply"
        try:
            if not await self._still_current(record, page, recipe if recipe.get("task") else None):
                return {**response, "ok": False, "error": {"code": "STALE_CHALLENGE"}}
            applied = await apply_solution(page, record["frame"], task, solution, recipe, record, attached=attached)
            response.update(applied)
            if not applied["applied"]:
                return {**response, "ok": False, "error": {"code": "APPLICATION_RECIPE_REQUIRED"}}
            stage = "verify"
            if submit:
                application = recipe.get("application", {})
                if not application.get("submit_selector") and not application.get("reload"):
                    raise ValueError("Submitting requires an explicit submit_selector or reload action in the recipe.")

                async def submit_action() -> None:
                    if application.get("reload"):
                        # Optional deferred resources may outlive the accepted
                        # page. Judge the explicit success condition after the
                        # new document commits instead of awaiting those assets.
                        await page.reload(wait_until="commit")
                    else:
                        await record["frame"].locator(application["submit_selector"]).click()

                if verification.get("response"):
                    spec = verification["response"]
                    async with page.expect_response(
                        lambda r: bool(re.search(spec["url_pattern"], r.url)), timeout=verification.get('timeout_ms', 10000)
                    ) as event:
                        await submit_action()
                    backend = await event.value
                    accepted = backend.status == spec.get("status", 200)
                    if accepted and spec.get("json_path"):
                        try:
                            value = await backend.json()
                        except ValueError:
                            value = None
                        present = True
                        for key in spec["json_path"].split("."):
                            if not isinstance(value, dict) or key not in value:
                                present = False
                                break
                            value = value[key]
                        accepted = accepted and present and value == spec.get("equals", True)
                    response.update(
                        verified=accepted, verification="backend_accepted" if accepted else "backend_rejected"
                    )
                    if not accepted:
                        response["ok"] = False
                else:
                    await submit_action()
            if (
                not response["verified"]
                and not preexisting_success
                and verification
                and not verification.get("response")
            ):
                deadline = time.monotonic() + verification.get('timeout_ms', 10000) / 1000
                while time.monotonic() < deadline:
                    if await self._condition(page, verification):
                        response.update(verified=True, verification="configured_success_condition")
                        break
                    await asyncio.sleep(0.1)
                if not response['verified']:
                    response['verification'] = 'configured_condition_timeout'
            response["url"] = page.url
            return response
        except Exception as exc:
            from capsolver_mcp.tools.tasks import tool_error

            return {**response, **tool_error(exc), "stage": stage}

    async def _close_session(self, key: str, session: BrowserSession) -> list[str]:
        session.closing = True
        failed: set[str] = set()

        async def step(name: str, operation: Callable[[], Awaitable[Any]]) -> bool:
            if name in session.cleanup_done:
                return True
            started = time.monotonic()
            try:
                await asyncio.wait_for(operation(), self.cleanup_timeout)
            except Exception as exc:
                failed.add(name)
                session.shutdown_steps.append({"stage": name, "outcome": "failed",
                    "error_type": type(exc).__name__, "elapsed_ms": round((time.monotonic() - started) * 1000)})
                return False
            session.cleanup_done.add(name)
            session.shutdown_steps.append({"stage": name, "outcome": "completed",
                "elapsed_ms": round((time.monotonic() - started) * 1000)})
            return True

        for page_id, capture in session.captures.items():
            await step("capture:" + page_id, capture.aclose)
        if session.request_context is not None:
            if await step("request_context", session.request_context.dispose):
                session.request_context = None
        if session.owned:
            for page_id, page in session.pages.items():
                if page.video:
                    async def video_path(page: Any = page) -> None:
                        path = await page.video.path()
                        if path not in session.video_paths:
                            session.video_paths.append(path)
                    await step("video:" + page_id, video_path)
            await step("context", session.context.close)
        elif self.runtime.settings.offline:
            await step("offline_route", lambda: session.context.unroute("**/*", self._guard_route))
        # Browser.close on CDP disconnects only. Never close the external context.
        browser_closed = await step("browser", session.browser.close)
        if browser_closed and session.owned:
            # Closing the owned browser releases a context whose close failed.
            failed.discard("context")
            session.cleanup_done.add("context")
        self.last_shutdown[key] = {
            "complete": not failed, "retryable": bool(failed),
            "video_finalization": "confirmed" if session.owned and not any(
                row["stage"] == "context" and row["outcome"] == "failed" for row in session.shutdown_steps
            ) and "context" in session.cleanup_done else "unconfirmed",
            "steps": list(session.shutdown_steps),
        }
        # Bound diagnostics without retaining page data or browser handles.
        while len(self.last_shutdown) > 100:
            del self.last_shutdown[next(iter(self.last_shutdown))]
        if failed:
            raise RuntimeError("Browser cleanup incomplete; retry browser_close. Failed stages: " + ", ".join(sorted(failed)))
        self.sessions.pop(key, None)
        return list(session.video_paths)

    async def close(self, session_id: str | None = None) -> list[str]:
        videos, failures = [], []
        ids = [session_id] if session_id else list(self.sessions)
        for key in ids:
            session = self.sessions.get(key)
            if session is None:
                raise KeyError("Session not found.")
            if session.close_task is None or session.close_task.done():
                session.closing = True
                session.close_task = asyncio.create_task(self._close_session(key, session))
            try:
                # Caller cancellation must not strand a half-closed session.
                videos.extend(await asyncio.shield(session.close_task))
            except Exception as exc:
                failures.append(str(exc))
        async with self._manager_lock:
            if not self.sessions and self._playwright:
                await asyncio.wait_for(self._playwright.stop(), self.cleanup_timeout)
                self._playwright = None
        if failures:
            raise RuntimeError("; ".join(failures))
        return videos
