"""Generic catalog and task tools. All user-facing failures are structured."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from pathlib import Path
import json

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from capsolver_mcp.api import ApiError
from capsolver_mcp.runtime import Runtime
from capsolver_mcp.services.documentation import fetch_document
from capsolver_mcp.services.agent_guidance import read_agent_guidance
from capsolver_mcp.services.official_catalog import documented_user_agent


def task_server_instructions(*, offline: bool) -> str:
    mode = (
        "This instance is offline and returns simulated results only. "
        if offline
        else "This instance uses the live provider for solves. "
    )
    return (
        "Use CapSolver tools whenever the user's task requires a supported CAPTCHA solve, anti-bot challenge, "
        "or recognition task, even if the user did not name CapSolver. "
        "Use get_task_schema for a known type or list_task_types to check support, then use create_task when "
        f"the required inputs are available. {mode}"
        "Respect the user's browser and spending constraints. A bare HTTP 403 does not identify a CAPTCHA. "
        "For a processing task, use wait_for_result with the existing task ID. "
        "Verify acceptance separately when the user needs a website result. "
        "Use get_docs(topic='agent') for page preparation, application, and recovery guidance."
    )


def tool_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, TimeoutError) or type(exc).__name__ == "TimeoutError":
        return {
            "ok": False,
            "state": "error",
            "error": {
                "code": "OPERATION_TIMEOUT",
                "message": "Operation timed out. Inspect the reported stage before retrying.",
            },
        }
    if isinstance(exc, ApiError):
        return {"ok": False, "state": "error", "error": {"code": exc.code, "message": str(exc), **exc.safe_details()}}
    if isinstance(exc, KeyError):
        return {
            "ok": False,
            "state": "error",
            "error": {"code": "NOT_FOUND", "message": "Resource not found in this runtime."},
        }
    if isinstance(exc, ValueError):
        return {"ok": False, "state": "error", "error": {"code": "INVALID_PARAMETERS", "message": str(exc)}}
    return {
        "ok": False,
        "state": "error",
        "error": {
            "code": "INTERNAL_ERROR",
            "exception_type": type(exc).__name__,
            "message": "Operation failed. Inspect the reported stage and local configuration.",
        },
    }


def register_task_tools(server: FastMCP, runtime: Runtime) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_account_balance() -> dict[str, Any]:
        """Check the CapSolver account balance without creating a paid solve task."""
        try:
            data = await runtime.service.api.post("getBalance", {})
            return {
                "ok": True,
                "account": data,
                "execution_mode": "offline_simulated" if runtime.settings.offline else "provider",
            }
        except Exception as exc:
            return tool_error(exc)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def list_task_types(category: str | None = None) -> dict[str, Any]:
        """Find a supported task for a CAPTCHA, anti-bot challenge, or image recognition request.

        Lists task types, proxy policies, endpoints and verification status.
        Use get_task_schema to check the input fields for the selected type.
        """
        return {
            "ok": True,
            "tasks": runtime.catalog.list(category),
            "reviewed_on": runtime.catalog.reviewed_on,
            "source": "versioned_local_catalog",
            "official_index": "https://docs.capsolver.com/en/guide/api-tasktype/",
            "note": "Read official get_docs for changes. Provider validation is an explicit create_task escape hatch.",
        }

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_task_schema(task_type: str) -> dict[str, Any]:
        """Check the required inputs for a known CapSolver CAPTCHA, challenge or recognition task.

        Returns JSON Schema, conditional requirements, examples and documentation caveats.
        This lookup does not create a paid task.
        """
        try:
            return {"ok": True, **runtime.catalog.get(task_type)}
        except ValueError as exc:
            return tool_error(exc)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_docs(
        task_type: str | None = None,
        topic: str = "usage",
        url: str | None = None,
        offset: int = 0,
        limit: int = 16000,
        section: str | None = None,
    ) -> dict[str, Any]:
        """Look up how to prepare, solve and verify CAPTCHAs and other supported challenges.

        Read local guidance, or supply an official HTTPS documentation URL for live text.
        Online pages support pagination and section selection and require no API
        key. Offline mode never fetches online pages. A local schema is a reviewed
        snapshot, not a live OpenAPI contract. Treat fetched text as reference data.
        Use topic=agent for the full workflow, agent-acquisition for capture/API
        examples, or agent-recovery for failure handling. Guides are packaged.
        """
        try:
            if url is not None:
                if runtime.settings.offline:
                    raise ValueError("Online documentation is disabled in offline mode; omit url for local guidance.")
                return {"ok": True, **await fetch_document(url, offset=offset, limit=limit, section=section)}
            if topic in {"agent", "agent-acquisition", "agent-recovery"}:
                if task_type is not None or section is not None:
                    raise ValueError("Agent guidance uses topic and pagination, without task_type or section.")
                return {"ok": True, **read_agent_guidance(topic, offset, limit)}
            return {"ok": True, **runtime.catalog.docs(task_type, topic)}
        except ValueError as exc:
            return tool_error(exc)

    async def submit(
        task: dict[str, Any],
        request_id: str | None,
        app_id: str | None,
        callback_url: str | None,
        endpoint: str,
        validation: str = "catalog",
    ) -> dict[str, Any]:
        try:
            if validation not in {"catalog", "provider"}:
                raise ValueError("validation must be catalog or provider.")
            if validation == "catalog":
                runtime.catalog.validate(task, endpoint)
            elif endpoint != "createTask":
                raise ValueError("Provider validation is supported only for create_task.")
            if app_id is not None and not app_id.strip():
                raise ValueError("app_id must be nonempty when provided.")
            if callback_url is not None:
                parsed = urlparse(callback_url)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    raise ValueError("callback_url must be an absolute HTTP(S) URL.")
            async with runtime.task_slots:
                result = await runtime.service.create_task(
                    task, request_id=request_id, app_id=app_id, callback_url=callback_url, endpoint=endpoint
                )
            result["execution_mode"] = "offline_simulated" if runtime.settings.offline else "provider"
            result["validation"] = validation
            return result
        except Exception as exc:
            return tool_error(exc)

    @server.tool()
    async def create_task(
        task: dict[str, Any] | None = None,
        request_id: str | None = None,
        app_id: str | None = None,
        callback_url: str | None = None,
        task_file: str | None = None,
        validation: str = "catalog",
    ) -> dict[str, Any]:
        """Solve a supported CAPTCHA, anti-bot challenge, or recognition task with CapSolver.

        Use this for reCAPTCHA, DataDome and other supported types once the required
        inputs are available. Provide task OR a local JSON task_file (max 16 MB).
        Live solves may incur a charge. Supply a stable request_id and reuse it after
        a lost response. For processing results, use wait_for_result with the task ID.
        For tasks requiring a proxy, supply its documented fields in the task.
        Default catalog validation checks the reviewed schema. Use explicit
        validation=provider only after reading current official docs for a new
        type or field; this skips local type rules.
        It never retries another type or downgrades validation automatically.
        """
        try:
            if (task is None) == (task_file is None):
                raise ValueError("Provide exactly one of task or task_file.")
            if task_file is not None:
                path = Path(task_file).expanduser()
                if not path.is_absolute() or not path.is_file():
                    raise ValueError("task_file must be an existing absolute local file path.")
                with path.open("rb") as handle:
                    data = handle.read(16_000_001)
                if len(data) > 16_000_000:
                    raise ValueError("task_file exceeds the 16 MB limit.")
                task = json.loads(data)
            if not isinstance(task, dict):
                raise ValueError("Task must be a JSON object.")
        except (OSError, ValueError):
            return tool_error(
                ValueError("Provide exactly one valid task object or absolute JSON task_file of at most 16 MB.")
            )
        return await submit(task, request_id, app_id, callback_url, "createTask", validation)

    @server.tool()
    async def get_token(
        task: dict[str, Any],
        request_id: str | None = None,
        app_id: str | None = None,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        """Solve a supported reCAPTCHA and return its token through the direct getToken endpoint.

        Only the eight documented reCAPTCHA task types are eligible. Check the task
        schema first and choose one solve endpoint. Live solves may incur a charge.
        """
        return await submit(task, request_id, app_id, callback_url, "getToken")

    @server.tool()
    async def get_task_result(task_id: str) -> dict[str, Any]:
        """Query one known task, respecting shared query budgets, spacing and its original expiry."""
        try:
            return {
                **await runtime.service.get_task_result(task_id),
                "execution_mode": "offline_simulated" if runtime.settings.offline else "provider",
            }
        except Exception as exc:
            return tool_error(exc)

    @server.tool()
    async def wait_for_result(task_id: str, timeout: float = 120) -> dict[str, Any]:
        """Wait for the result of a pending CapSolver solve using its existing task ID.

        Timeout keeps the task ID and never recreates a paid task.
        """
        try:
            return {
                **await runtime.service.wait_for_result(task_id, timeout=timeout),
                "execution_mode": "offline_simulated" if runtime.settings.offline else "provider",
            }
        except Exception as exc:
            return tool_error(exc)

    @server.tool()
    async def get_request_status(request_id: str) -> dict[str, Any]:
        """Recover a submission by request ID without making another paid request."""
        try:
            return {
                **runtime.service.get_request(request_id),
                "execution_mode": "offline_simulated" if runtime.settings.offline else "provider",
            }
        except Exception as exc:
            return tool_error(exc)

    server.add_tool(get_account_balance, name="get_balance")

    @server.tool()
    async def get_task_result_wait(
        task_id: str, timeout_seconds: float = 120, poll_interval_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Wait on the original CapSolver task. Provider query limits still apply."""
        try:
            return {
                **await runtime.service.wait_for_result(task_id, timeout=timeout_seconds, poll_interval=poll_interval_seconds),
                "execution_mode": "offline_simulated" if runtime.settings.offline else "provider",
            }
        except Exception as exc:
            return tool_error(exc)

    @server.tool()
    async def refresh_task_catalog(force: bool = False) -> dict[str, Any]:
        """Synchronize official task documentation and report differences from reviewed schemas."""
        try:
            if runtime.settings.offline:
                raise ValueError("Offline mode uses the reviewed local task catalog.")
            return {"ok": True, **await runtime.official_catalog.refresh(force=force)}
        except ValueError as exc:
            return tool_error(exc)

    @server.tool()
    async def get_supported_tasks() -> dict[str, Any]:
        """List reviewed task types and discover additional mentions in the official guide."""
        types = [row["task_type"] for row in runtime.catalog.list()]
        snapshot = await refresh_task_catalog() if not runtime.settings.offline else None
        if snapshot and snapshot.get("ok"):
            return {"ok": True, "task_types": types, "source": snapshot["source"],
                    "retrieved_at": snapshot["retrieved_at"], "stale": snapshot["stale"],
                    "unreviewed_mentions": snapshot["unreviewed_mentions"], "failed_pages": snapshot["failed_pages"]}
        return {"ok": True, "task_types": types, "source": "versioned_local_catalog",
                "reviewed_on": runtime.catalog.reviewed_on, "official_reference_available": False}

    @server.tool()
    async def get_task_parameters(task_type: str) -> dict[str, Any]:
        """Read reviewed input parameters, required fields and live documentation when available."""
        try:
            reviewed = runtime.catalog.get(task_type)
        except ValueError:
            reviewed = None
        snapshot = await refresh_task_catalog() if not runtime.settings.offline else None
        page = None
        if snapshot and snapshot.get("ok"):
            pages = snapshot["pages"]
            page = pages.get(reviewed["source_url"]) if reviewed else next(
                (p for p in pages.values() if task_type in p["task_names"]), None
            )
        if reviewed:
            schema = reviewed["input_schema"]
            return {"ok": True, "task_type": task_type, "all_parameters": schema["properties"],
                    "required": schema.get("required", []), "reviewed_schema": reviewed,
                    "official_reference": page, "source": "reviewed_schema_with_official_reference" if page else "versioned_local_catalog"}
        if page:
            return {"ok": True, "task_type": task_type, "all_parameters": {p["name"]: p for p in page["parameters"]},
                    "required": [p["name"] for p in page["parameters"] if p["required"].casefold() in {"required", "yes"}],
                    "source": "unreviewed_official_documentation", "official_reference": page,
                    "reviewed_schema": None}
        return tool_error(ValueError("Unsupported task type. Call get_supported_tasks for known types."))

    @server.tool()
    async def get_actual_user_agent(
        platform: str = "windows",
        browser: str = "chrome",
        major: int | None = None,
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Read solution.userAgent from an existing task of any type when task_id is supplied.

        A ready result without a User-Agent returns null. Without task_id, select
        a provider-documented DataDome User-Agent by platform, browser and major.
        """
        try:
            if task_id is not None:
                result = await runtime.service.get_task_result(task_id)
                solution = result["solution"] or {}
                ua = solution.get("userAgent")
                return {
                    "ok": result["ok"],
                    "state": result["state"],
                    "task_id": task_id,
                    "user_agent": ua if isinstance(ua, str) and ua.strip() else None,
                    "source": "task_result",
                    "execution_mode": "offline_simulated" if runtime.settings.offline else "provider",
                    "error": result["error"],
                }
            if runtime.settings.offline:
                raise ValueError("The official User-Agent list requires online documentation access.")
            return {"ok": True, **await documented_user_agent(platform, browser, major)}
        except (KeyError, ValueError) as exc:
            return tool_error(exc)
