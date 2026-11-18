"""Browser half of an agent-orchestrated workflow. Never calls a solver."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from capsolver_mcp.runtime import Runtime
from capsolver_mcp.tools.tasks import tool_error


def register_pairing_tools(server: FastMCP, runtime: Runtime) -> None:
    @server.tool()
    async def browser_prepare_captcha(
        session_id: str,
        page_id: str,
        captcha_id: str | None = None,
        recipe: dict[str, Any] | None = None,
        task_overrides: dict[str, Any] | None = None,
        submit: bool = False,
        save_task_file: bool = False,
    ) -> dict[str, Any]:
        """Extract fresh parameters for core create_task. No paid call.

        Supply any required proxy fields separately in the core task payload.
        save_task_file stores large inputs locally (0600). The core must share
        this filesystem. Delete the file after use; it may contain page data.
        Retain captcha_id for browser_apply_solution. Recipe validation occurs
        before spending credit. Read the official task documentation first.
        """
        try:
            return await runtime.browser.prepare(
                session_id,
                page_id,
                captcha_id=captcha_id,
                recipe=recipe,
                task_overrides=task_overrides,
                submit=submit,
                save_task_file=save_task_file,
            )
        except Exception as exc:
            return {**tool_error(exc), "stage": "prepare"}

    @server.tool()
    async def browser_apply_solution(
        session_id: str,
        page_id: str,
        captcha_id: str,
        solution: dict[str, Any],
        submit: bool = False,
    ) -> dict[str, Any]:
        """Apply the full core-MCP solution to a prepared challenge; optionally submit and verify.

        Does not solve, query or charge. Rejects stale or already-used prepared
        challenges. verified=true requires a configured business/page condition.
        """
        try:
            return await runtime.browser.apply(session_id, page_id, captcha_id, solution, submit=submit)
        except Exception as exc:
            return {**tool_error(exc), "stage": "apply"}

    @server.tool()
    async def browser_evaluate(
        session_id: str,
        page_id: str,
        expression: str,
        frame_selector: str | None = None,
    ) -> dict[str, Any]:
        """Execute JavaScript in the selected page/frame for custom integrations.

        Code can read or change the page. No Node.js or host filesystem access is
        supplied. Return only necessary data; do not return passwords or tokens
        to logs. This is a privileged browser operation, not a read-only tool.
        """
        try:
            import asyncio
            import json

            session, page = runtime.browser.get(session_id, page_id)
            async with session.locks[page_id]:
                frame = page.main_frame
                if frame_selector:
                    element = await page.locator(frame_selector).element_handle()
                    frame = await element.content_frame() if element else None
                    if frame is None:
                        raise ValueError("Frame selector did not resolve to an iframe.")
                result = await asyncio.wait_for(frame.evaluate(expression), timeout=15)
                if len(json.dumps(result)) > 100_000:
                    raise ValueError("Result exceeds 100000 characters; return a smaller selection.")
                return {"ok": True, "result": result}
        except Exception as exc:
            return {**tool_error(exc), "stage": "evaluate"}

    @server.tool()
    async def browser_network_requests(session_id: str, page_id: str) -> dict[str, Any]:
        """Read the last 100 page-response summaries, with response IDs and capture states.

        Query values, bodies and raw headers are omitted. Enable capture before
        navigation, then use browser_get_response to read private local evidence.
        Explicit browser_api_request responses are returned by that tool instead.
        """
        try:
            session, _ = runtime.browser.get(session_id, page_id)
            return {"ok": True, "responses": list(session.network.get(page_id, []))}
        except Exception as exc:
            return tool_error(exc)
