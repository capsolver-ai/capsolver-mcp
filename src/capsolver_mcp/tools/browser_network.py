"""Page acquisition tools. These never create or query a solver task."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from capsolver_mcp.runtime import Runtime
from capsolver_mcp.tools.tasks import tool_error


def register_acquisition_tools(server: FastMCP, runtime: Runtime) -> None:
    @server.tool()
    async def browser_add_init_script(session_id: str, page_id: str, script: str) -> dict[str, Any]:
        """Install JS statements before future page/frame scripts. No reload or immediate execution.

        Pass an invoked expression or statements, not an uninvoked arrow function.
        Register before navigation; use an idempotent wrapper. Order relative to
        other init scripts is unspecified. Code has page privileges, not host IO.
        """
        try:
            return await runtime.browser.add_init_script(session_id, page_id, script)
        except Exception as exc:
            return {**tool_error(exc), "stage": "init_script"}

    @server.tool()
    async def browser_capture_responses(
        session_id: str, page_id: str, enabled: bool = True,
        url_patterns: list[str] | None = None, max_body_bytes: int = 1_000_000, max_responses: int = 20,
    ) -> dict[str, Any]:
        """Capture future original response bodies to private local files, without refetching.

        URL filters are case-sensitive globs; empty means all HTTP(S) responses.
        Prefer narrow filters. For the very first navigation set response_capture
        in browser_open. Disable stops future capture and retains existing files.
        Bodies are Playwright-decoded bytes, not raw compressed wire traffic.
        """
        try:
            return await runtime.browser.configure_capture(session_id, page_id, {
                "enabled": enabled, "url_patterns": url_patterns or [],
                "max_body_bytes": max_body_bytes, "max_responses": max_responses,
            })
        except Exception as exc:
            return {**tool_error(exc), "stage": "capture"}

    @server.tool()
    async def browser_get_response(
        session_id: str, page_id: str, response_id: str, include_body: bool = False,
        offset: int = 0, limit: int = 16000, encoding: str = "text",
    ) -> dict[str, Any]:
        """Read retained response evidence. No network request is made.

        Default returns safe metadata and private file paths. include_body exposes
        selected bytes to the caller; use only needed fields, or read files locally.
        Source distinguishes original_response from session_request. Pending,
        truncated, skipped and evicted records are not complete response bodies.
        """
        try:
            return await runtime.browser.get_response(
                session_id, page_id, response_id, include_body=include_body, offset=offset, limit=limit, encoding=encoding,
            )
        except Exception as exc:
            return {**tool_error(exc), "stage": "response"}

    @server.tool()
    async def browser_api_request(
        session_id: str, page_id: str, url: str, method: str = "GET",
        headers: dict[str, str] | None = None, data: dict[str, Any] | str | None = None,
        timeout_ms: int = 15000, follow_redirects: bool = False,
        max_body_bytes: int = 1_000_000, include_body: bool = True, allow_direct: bool = False,
    ) -> dict[str, Any]:
        """Make a NEW request with context cookies and UA; save local evidence.

        This is not original page traffic, a browser navigation or JS execution.
        The page state and TLS/client-hint fingerprint may differ. No retry is
        performed; POST/other state changes need existing user authorization.
        Redirects are opt-in and checked individually. HTTP errors are recorded
        as http_ok=false; request delivery is distinct from business acceptance.
        The CapSolver API host is blocked; paid tasks must use the core ledger.
        For CDP attachments, allow_direct=true explicitly permits a separate direct
        request with cookie synchronization. Use page operations and response capture
        for traffic through the externally configured browser.
        """
        try:
            return await runtime.browser.api_request(
                session_id, page_id, url, method=method, headers=headers, data=data,
                timeout_ms=timeout_ms, follow_redirects=follow_redirects,
                max_body_bytes=max_body_bytes, include_body=include_body, allow_direct=allow_direct,
            )
        except Exception as exc:
            return {**tool_error(exc), "stage": "session_request", "is_new_request": True, "automatic_retry": False}
