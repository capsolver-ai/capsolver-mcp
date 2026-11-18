"""Session-based browser tools, with explicit recipe and submission controls."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from capsolver_mcp.runtime import Runtime
from capsolver_mcp.tools.tasks import tool_error


def register_browser_tools(server: FastMCP, runtime: Runtime) -> None:
    @server.tool()
    async def browser_open(
        url: str = "about:blank",
        user_agent: str | None = None,
        headless: bool = True,
        cdp_endpoint: str | None = None,
        cdp_target_id: str | None = None,
        record_video: bool = False,
        response_capture: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Open a managed session or attach to an explicit Chromium CDP endpoint; return stable page IDs."""
        try:
            return await runtime.browser.open(
                url,
                user_agent=user_agent,
                headless=headless,
                cdp_endpoint=cdp_endpoint,
                cdp_target_id=cdp_target_id,
                record_video=record_video,
                response_capture=response_capture,
            )
        except Exception as exc:
            return tool_error(exc)

    @server.tool()
    async def browser_inspect(session_id: str, page_id: str) -> dict[str, Any]:
        """Inspect current pages and form fields. Password and hidden values are redacted."""
        try:
            return await runtime.browser.inspect(session_id, page_id)
        except Exception as exc:
            return tool_error(exc)

    @server.tool()
    async def browser_action(
        session_id: str, page_id: str, action: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Navigate, fill, click, press, select, wait, scroll or save a local screenshot on a persistent page."""
        try:
            return await runtime.browser.action(session_id, page_id, action, options or {})
        except Exception as exc:
            return tool_error(exc)

    @server.tool()
    async def browser_detect_captchas(session_id: str, page_id: str) -> dict[str, Any]:
        """Detect known widgets and captured dynamic parameters in page frames. Custom pages may need recipes."""
        try:
            return await runtime.browser.detect(session_id, page_id)
        except Exception as exc:
            return tool_error(exc)

    @server.tool()
    async def browser_close(session_id: str) -> dict[str, Any]:
        """Close a managed session or disconnect from an attached browser."""
        try:
            videos = await runtime.browser.close(session_id)
            return {"ok": True, "video_paths": videos, "shutdown": runtime.browser.last_shutdown.get(session_id)}
        except Exception as exc:
            return {**tool_error(exc), "shutdown": runtime.browser.last_shutdown.get(session_id)}
