"""CapSolver MCP Server — tool definitions and server factory.

Exposes five tools via MCP:
  - solve_captcha:        Token-mode solve (no browser required)
  - detect_captchas:      Detect captcha types on a page (requires browser session)
  - solve_on_page:        Detect + solve + autofill on a page (requires browser session)
  - get_balance:          Check account balance
  - get_supported_captchas: List supported captcha types
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from capsolver_core import Capsolver, CaptchaInfo, CaptchaType
from capsolver_core.captcha.types import Solution
from capsolver_core.core.errors import CapsolverError, CapsolverTimeoutError, NetworkError, RateLimitError


def _get_capsolver(api_key: str | None = None) -> Capsolver:
    """Construct a Capsolver instance, reading API key from env if not provided."""
    key = api_key or os.environ.get("CAPSOLVER_API_KEY", "")
    return Capsolver(api_key=key)


def _solution_to_dict(sol: Solution) -> dict[str, Any]:
    """Serialize a Solution to a JSON-friendly dict."""
    return {
        "captcha_type": sol.captcha_type.value,
        "token": sol.token,
        "expire_time": sol.expire_time,
        "user_agent": sol.user_agent,
    }


def _error_response(exc: Exception) -> dict[str, Any]:
    """Build a consistent error dict from an exception.

    Extracts structured fields from CapsolverError when available so that
    AI agents can programmatically inspect error_id, error_code, http_status
    and task_id instead of parsing free-form error strings.
    """
    base: dict[str, Any] = {"success": False, "error": str(exc)}
    if isinstance(exc, CapsolverTimeoutError) and exc.task_id is not None:
        base["task_id"] = exc.task_id
    if isinstance(exc, NetworkError) and exc.cause is not None:
        base["cause"] = str(exc.cause)
    if isinstance(exc, RateLimitError):
        base["error_type"] = "rate_limit"
    if isinstance(exc, CapsolverError):
        if exc.error_id is not None:
            base["error_id"] = exc.error_id
        if exc.error_code:
            base["error_code"] = exc.error_code
        if exc.error_description:
            base["error_description"] = exc.error_description
        if exc.http_status is not None:
            base["http_status"] = exc.http_status
    return base


def create_server(
    api_key: str | None = None,
    server_name: str = "capsolver",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """Create and configure the MCP server with all CapSolver tools.

    Args:
        api_key: CapSolver API key. Falls back to CAPSOLVER_API_KEY env var.
        server_name: Name advertised to MCP clients.
        host: Bind host for SSE / HTTP transports.
        port: Bind port for SSE / HTTP transports.

    Returns:
        A configured FastMCP server instance.
    """
    server = FastMCP(server_name, host=host, port=port)
    capsolver = _get_capsolver(api_key)

    # ── Tool 1: solve_captcha (token mode) ────────────────────────

    @server.tool()
    async def solve_captcha(
        captcha_type: str,
        website_url: str,
        website_key: str,
        version: str | None = None,
        page_action: str | None = None,
        min_score: float | None = None,
        invisible: bool | None = None,
        enterprise: bool | None = None,
        s_token: str | None = None,
        cdata: str | None = None,
        proxy: str | None = None,
        user_agent: str | None = None,
        timeout: float | None = None,
        polling_interval: float | None = None,
    ) -> dict[str, Any]:
        """Solve a captcha in token mode — no browser required.

        CapSolver will create a task on its server, solve the captcha challenge,
        and return the solution token. Use this when you only need the token to
        submit to a target website (e.g. via form POST or API call).

        Args:
            captcha_type: One of "reCaptchaV2", "reCaptchaV3", "cloudflare".
            website_url: The full URL of the page where the captcha appears.
            website_key: The site key / public key / data-sitekey of the captcha widget.
            version: reCAPTCHA version hint ("v2" or "v3"). Usually auto-detected.
            page_action: reCAPTCHA v3 action name (e.g. "login", "submit").
            min_score: reCAPTCHA v3 minimum score threshold (0.0–1.0).
            invisible: Whether the reCAPTCHA widget uses invisible mode.
            enterprise: Whether to use the Enterprise API variant.
            s_token: Enterprise s_token for stoken-based verification.
            cdata: Cloudflare Turnstile custom data parameter.
            proxy: Proxy in "user:pass@host:port" or "host:port" format.
            user_agent: Custom User-Agent string to use during solving.
            timeout: Maximum seconds to wait for a solution (default: 120).
            polling_interval: Seconds between status polls (default: 5).

        Returns:
            {"success": True, "solution": {...}} on success.
            {"success": False, "error": "...", "error_id": ..., "error_code": "...", "http_status": ...} on failure.
        """
        try:
            ct = CaptchaType(captcha_type)
        except ValueError:
            return {
                "success": False,
                "error": f"Unsupported captcha type: {captcha_type}. Supported: {[t.value for t in CaptchaType]}",
            }

        info = CaptchaInfo(
            type=ct,
            website_url=website_url,
            website_key=website_key,
            version=version,
            page_action=page_action,
            min_score=min_score,
            invisible=invisible,
            enterprise=enterprise,
            s=s_token,
            cdata=cdata,
            proxy=proxy,
            user_agent=user_agent,
        )

        from capsolver_core.core.client import WaitOptions

        wait_opts = None
        if timeout is not None or polling_interval is not None:
            wait_opts = WaitOptions(timeout=timeout, polling_interval=polling_interval)

        try:
            solution = await capsolver.solve(info, wait_options=wait_opts)
            return {"success": True, "solution": _solution_to_dict(solution)}
        except Exception as e:
            return _error_response(e)

    # ── Tool 2: detect_captchas (browser mode) ────────────────────

    @server.tool()
    async def detect_captchas(page_url: str) -> dict[str, Any]:
        """Detect which captcha types are present on a given page URL.

        Opens the page in a headless browser and inspects the DOM to identify
        captcha widgets (reCAPTCHA, Cloudflare Turnstile).
        Requires playwright to be installed.

        Args:
            page_url: The full URL of the page to inspect.

        Returns:
            {"success": True, "url": "...", "detected_captchas": ["reCaptchaV2", ...]} on success.
            {"success": False, "error": "..."} on failure.
        """
        try:
            driver = await _launch_browser_session(page_url)
        except ImportError:
            return {
                "success": False,
                "error": "Browser automation not available. Install with: pip install capsolver-mcp[browser]",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to open page: {e}"}

        try:
            detected = await capsolver.detect(driver)
            return {
                "success": True,
                "url": page_url,
                "detected_captchas": [t.value for t in detected],
            }
        except Exception as e:
            return _error_response(e)
        finally:
            await _close_browser_session(driver)

    # ── Tool 3: solve_on_page (browser mode) ──────────────────────

    @server.tool()
    async def solve_on_page(
        page_url: str,
        autofill: bool = True,
        timeout: float | None = None,
        polling_interval: float | None = None,
    ) -> dict[str, Any]:
        """Detect, solve, and optionally autofill all captchas on a page.

        One-shot operation: opens the page in a headless browser, detects captcha
        widgets, solves them via the CapSolver API, and injects the solution tokens
        back into the page DOM.

        Requires playwright to be installed.

        Args:
            page_url: The full URL of the page containing captchas.
            autofill: If True, inject solved tokens into the page (default: True).
            timeout: Maximum seconds to wait per captcha (default: 120).
            polling_interval: Seconds between status polls (default: 5).

        Returns:
            {"success": True, "url": "...", "results": [{"captcha_type": "...", "solved": true, "token": "...", "filled": true}, ...]}
            {"success": False, "error": "..."} on failure.
        """
        try:
            driver = await _launch_browser_session(page_url)
        except ImportError:
            return {
                "success": False,
                "error": "Browser automation not available. Install with: pip install capsolver-mcp[browser]",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to open page: {e}"}

        try:
            from capsolver_core.capsolver import SolveOnPageOptions

            opts = SolveOnPageOptions(
                autofill=autofill,
                throw_on_error=False,
                timeout=timeout,
                polling_interval=polling_interval,
            )
            results = await capsolver.solve_on_page(driver, options=opts)
            return {
                "success": True,
                "url": page_url,
                "results": [
                    {
                        "captcha_type": (r.info.type.value),
                        "solved": r.solution is not None,
                        "token": r.solution.token if r.solution else None,
                        "filled": r.filled,
                        "error": r.error,
                    }
                    for r in results
                ],
            }
        except Exception as e:
            return _error_response(e)
        finally:
            await _close_browser_session(driver)

    # ── Tool 4: get_balance ───────────────────────────────────────

    @server.tool()
    async def get_balance() -> dict[str, Any]:
        """Get the current CapSolver account balance.

        Returns:
            {"success": True, "balance": 5.67, "packages": [...]} on success.
            {"success": False, "error": "...", "error_id": ..., "error_code": "..."} on failure.
        """
        try:
            balance = await capsolver.get_balance()
            return {"success": True, "balance": balance.balance, "packages": balance.packages}
        except Exception as e:
            return _error_response(e)

    # ── Tool 5: get_supported_captchas ────────────────────────────

    @server.tool()
    async def get_supported_captchas() -> dict[str, Any]:
        """List all captcha types supported by this CapSolver instance.

        Returns the registered handler names and all available captcha type values.
        No parameters required.
        """
        handlers = capsolver.get_supported_captchas()
        captcha_types = [t.value for t in CaptchaType]
        return {
            "success": True,
            "registered_handlers": handlers,
            "captcha_types": captcha_types,
        }

    return server


# ── Browser session helpers ───────────────────────────────────────


async def _launch_browser_session(page_url: str) -> Any:
    """Launch a headless browser and navigate to the given URL.

    Returns a PageDriver wrapping the Playwright page.
    Raises ImportError if playwright is not installed.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise

    from capsolver_core.browser.adapter import from_playwright_page

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)

    # Captcha widgets (reCAPTCHA api.js, Turnstile) load asynchronously after
    # DOMContentLoaded. Wait for the network to settle so their scripts can
    # register before we detect — bounded so pages with long-lived
    # connections don't hang. Best-effort: ignore timeout.
    try:
        await page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass

    driver = from_playwright_page(page)
    # Stash references for cleanup
    setattr(driver, "_pw", pw)
    setattr(driver, "_browser", browser)
    return driver


async def _close_browser_session(driver: Any) -> None:
    """Clean up browser resources."""
    try:
        if hasattr(driver, "_browser") and driver._browser:
            await driver._browser.close()
        if hasattr(driver, "_pw") and driver._pw:
            await driver._pw.stop()
    except Exception:
        pass
