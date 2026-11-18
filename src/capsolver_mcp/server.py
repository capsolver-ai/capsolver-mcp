"""Factories for the independent core and browser MCP servers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock

import capsolver_mcp
from capsolver_mcp.config import SERVER_NAME, Settings
from capsolver_mcp.runtime import Runtime
from capsolver_mcp.tools.tasks import register_task_tools, task_server_instructions


def create_server(
    api_key: str | None = None,
    server_name: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    runtime: Runtime | None = None,
    mode: str = "core",
) -> FastMCP:
    """Create either the core or browser MCP server."""
    if mode not in {"core", "browser"}:
        raise ValueError("Unknown server mode.")
    name = server_name or ("capsolver-browser" if mode == "browser" else SERVER_NAME)
    runtime = runtime or Runtime(Settings.load(api_key, load_api_key=mode != "browser"))
    runtime.allow_tasks = mode == "core"
    runtime.allow_browser = mode == "browser"
    if mode == "browser":
        runtime.settings.api_key = ""

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Runtime]]:
        try:
            yield {"runtime": runtime}
        finally:
            await runtime.aclose()

    server = FastMCP(
        name,
        instructions=task_server_instructions(offline=runtime.settings.offline) if mode == "core" else None,
        host=host,
        port=port,
        lifespan=lifespan,
    )
    # FastMCP otherwise advertises the MCP SDK version in the handshake.
    server._mcp_server.version = capsolver_mcp.__version__
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    if mode == "core":
        register_task_tools(server, runtime)
        strict_tools = {"create_task", "get_token"}

        @server.prompt()
        def analyze_and_solve(url: str) -> str:
            """Plan an authorized page workflow across independent MCP servers."""
            return (
                f"Work on this authorized page: {url}. Read get_docs(topic='agent') first; use "
                "agent-acquisition and agent-recovery guidance as needed. Use a separate browser MCP to inspect the live page "
                "and extract fresh task parameters. Read list_task_types, get_task_schema and official get_docs. "
                "If the browser exposes capsolver_browser_attach, start Chromium with browser_start, attach the active tab before navigation, "
                "and use capsolver_ prefixed preparation, capture and application tools with the returned IDs. "
                "For dynamic parameters, open about:blank, install browser_add_init_script and configure "
                "browser_capture_responses before navigation, or set response_capture in browser_open. "
                "Read original bytes using browser_get_response. browser_api_request is a NEW context request, "
                "not original page traffic; do not substitute its data for a consumed one-time challenge. "
                "Keep the same browser session, proxy and User-Agent while preparing the task. Create one task with a stable "
                "request_id. If processing, wait using task_id; never recreate after a lost response. "
                "For any task type, if the CapSolver response includes solution.userAgent, use that exact "
                "User-Agent when applying or submitting the token. If the current session cannot use it, report the "
                "mismatch and leave the page untouched. To check a known task by ID, use "
                "get_actual_user_agent(task_id=...). "
                "Apply the complete solution with the browser MCP. Submit only when requested. "
                "Check an explicit business response or page success condition; HTTP 200 alone is insufficient. "
                "Distinguish provider ready, applied and website accepted. Save a reproducible integration "
                "without secrets. Stop on missing inputs or provider errors and report the failed step."
            )
    else:
        from capsolver_mcp.tools.browser import register_browser_tools
        from capsolver_mcp.tools.browser_pairing import register_pairing_tools
        from capsolver_mcp.tools.browser_network import register_acquisition_tools

        register_browser_tools(server, runtime)
        register_pairing_tools(server, runtime)
        register_acquisition_tools(server, runtime)
        strict_tools = {"browser_open"}
    allowed_fields: dict[str, set[str]] = {}
    for tool in server._tool_manager.list_tools():
        if tool.name in strict_tools:
            tool.parameters["additionalProperties"] = False
            allowed_fields[tool.name] = set(tool.parameters["properties"])

    # Keep FastMCP argument conversion, and reject retired or mistyped options
    # before these entry points can submit a task or start page traffic.
    @server._mcp_server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        if name in allowed_fields and arguments.keys() - allowed_fields[name]:
            raise ValueError(f"Unexpected arguments for {name}. See its tool schema.")
        return await server.call_tool(name, arguments)

    return server
