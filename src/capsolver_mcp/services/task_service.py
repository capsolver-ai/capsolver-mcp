"""Generic submission/query lifecycle, independent of captcha type and MCP."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import re
import time
import uuid
from copy import deepcopy
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from capsolver_mcp.api import ApiClient, ApiError
from capsolver_mcp.storage.task_store import TaskStore


class TaskService:
    """Persist metadata only; ready solutions live in a bounded memory cache.

    Catalog validation and MCP registration belong to step 3. External task IDs
    cannot silently borrow a fresh five-minute creation window.
    """

    def __init__(
        self,
        api: ApiClient,
        store: TaskStore,
        *,
        account_key: str,
        scope: str = "local",
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll_interval: float = 3,
        max_queries: int = 120,
        max_age: float = 300,
        cache_size: int = 256,
    ) -> None:
        if not account_key:
            raise ValueError("An account key is required for task ownership.")
        if not math.isfinite(poll_interval) or poll_interval < 3:
            raise ValueError("Polling interval must be at least three seconds.")
        if not 1 <= max_queries <= 120 or not 0 < max_age <= 300 or cache_size < 1:
            raise ValueError("Invalid provider limits or cache size.")
        self.api, self.store = api, store
        self.scope = hmac.new(account_key.encode(), scope.encode(), hashlib.sha256).hexdigest()
        self._digest_key = account_key.encode()
        self.clock, self.sleep = clock, sleep
        self.poll_interval, self.max_queries, self.max_age = poll_interval, max_queries, max_age
        self.cache_size = cache_size
        self._solutions: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    def _cached(self, request_id: str) -> dict[str, Any] | None:
        now = self.clock()
        for key, (expiry, _) in list(self._solutions.items()):
            if expiry <= now:
                del self._solutions[key]
        cached = self._solutions.get(request_id)
        return cached[1] if cached is not None else None

    def _remember(self, record: dict[str, Any], solution: dict[str, Any]) -> None:
        self._cached(record["request_id"])
        self._solutions[record["request_id"]] = (self.clock() + self.max_age, deepcopy(solution))
        self._solutions.move_to_end(record["request_id"])
        while len(self._solutions) > self.cache_size:
            self._solutions.popitem(last=False)

    def _view(
        self, record: dict[str, Any], *, error: str | None = None, api_error: ApiError | None = None
    ) -> dict[str, Any]:
        solution = self._cached(record["request_id"])
        state = record["state"]
        if state == "submitting":
            record = self.store.expire_submission(
                self.scope, record["request_id"], self.clock(), legacy_timeout=self.api.timeout
            )
            state = record["state"]
        if state == "ready" and solution is None:
            state = "result_unavailable"
            error = error or "RESULT_NOT_CACHED"
        error_data = {"code": error or record["error_code"]} if error or record["error_code"] else None
        if error_data is not None and api_error is not None:
            error_data.update(api_error.safe_details())
        return {
            "ok": error is None and record["error_code"] is None and state in {"ready", "processing", "submitting"},
            "state": state,
            "request_id": record["request_id"],
            "task_id": record["task_id"],
            "solution": deepcopy(solution),
            "query_count": record["query_count"],
            "retry_after": max(0, record["next_query_at"] - self.clock()),
            "error": error_data,
        }

    async def create_task(
        self,
        task: dict[str, Any],
        *,
        request_id: str | None = None,
        app_id: str | None = None,
        callback_url: str | None = None,
        endpoint: str = "createTask",
    ) -> dict[str, Any]:
        if endpoint not in ("createTask", "getToken"):
            raise ValueError("Unsupported paid task endpoint.")
        if not isinstance(task, dict) or not isinstance(task.get("type"), str) or not task["type"].strip():
            raise ValueError("Task must be an object with a nonempty type.")
        request_id = str(uuid.uuid4()) if request_id is None else request_id
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
            raise ValueError("Request ID must contain 1-128 letters, digits, underscores or hyphens.")
        payload: dict[str, Any] = {"task": task}
        if app_id is not None:
            payload["appId"] = app_id
        if callback_url is not None:
            payload["callbackUrl"] = callback_url
        try:
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError):
            raise ValueError("Task payload must contain finite JSON values.") from None
        payload = json.loads(canonical)
        fingerprint = hmac.new(self._digest_key, (endpoint + canonical).encode(), hashlib.sha256).hexdigest()
        now = self.clock()
        record, claimed = self.store.claim(
            self.scope, request_id, fingerprint, now,
            submission_deadline=now + self.api.timeout_for(endpoint) + 1,
        )
        if not claimed:
            return self._view(record)
        try:
            data = await self.api.post(endpoint, payload)
            task_id = data.get("taskId")
            if task_id is not None and (
                not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", task_id)
            ):
                raise ApiError("INVALID_RESPONSE", "Invalid task ID.", submission_unknown=True)
            if data.get("status") == "ready" and isinstance(data.get("solution"), dict):
                record = self.store.update(self.scope, request_id, task_id=task_id, mode="sync", state="ready")
                self._remember(record, data["solution"])
                return self._view(record)
            if not task_id:
                raise ApiError("INVALID_RESPONSE", "Missing task ID.", submission_unknown=True)
            record = self.store.update(self.scope, request_id, task_id=task_id, state="processing")
            return self._view(record)
        except ApiError as exc:
            record = self.store.update(
                self.scope,
                request_id,
                state="acceptance_unknown" if exc.submission_unknown else "failed",
                error_code=exc.code,
            )
            return self._view(record, api_error=exc)
        except BaseException:
            self.store.update(self.scope, request_id, state="acceptance_unknown", error_code="SUBMISSION_INTERRUPTED")
            raise

    def get_request(self, request_id: str) -> dict[str, Any]:
        """Recover submission state without creating a new paid task."""
        return self._view(self.store.get(self.scope, request_id))

    async def get_task_result(self, task_id: str) -> dict[str, Any]:
        record = self.store.by_task_id(self.scope, task_id)
        if record["state"] not in {"processing", "ready"}:
            return self._view(record)
        if record["state"] == "ready" and (self._cached(record["request_id"]) is not None or record["mode"] == "sync"):
            return self._view(record)
        if self.clock() - record["created_at"] >= self.max_age:
            return self._view(
                self.store.update(self.scope, record["request_id"], state="expired", error_code="TASK_EXPIRED")
            )
        if record["query_count"] >= self.max_queries:
            return self._view(record, error="QUERY_LIMIT_REACHED")
        if not self.store.reserve_query(
            self.scope,
            record["request_id"],
            self.clock(),
            lease=max(self.poll_interval, self.api.timeout + 1),
            max_queries=self.max_queries,
            max_age=self.max_age,
        ):
            return self._view(self.store.get(self.scope, record["request_id"]))
        completed = False
        failure: ApiError | None = None
        try:
            data = await self.api.post("getTaskResult", {"taskId": task_id})
            if data.get("taskId") not in (None, task_id):
                raise ApiError("INVALID_RESPONSE", "Task ID does not match.", retryable=True)
            status = data.get("status")
            if status == "ready" and isinstance(data.get("solution"), dict):
                record = self.store.update(self.scope, record["request_id"], state="ready", error_code=None)
                self._remember(record, data["solution"])
            elif status in ("idle", "processing"):
                record = self.store.update(self.scope, record["request_id"], state="processing", error_code=None)
            elif status == "failed":
                record = self.store.update(
                    self.scope, record["request_id"], state="failed", error_code="PROVIDER_TASK_FAILED"
                )
            else:
                raise ApiError("INVALID_RESPONSE", "Task status or solution is invalid.", retryable=True)
            completed = True
        except ApiError as exc:
            failure = exc
            record = self.store.update(
                self.scope,
                record["request_id"],
                state=record["state"] if exc.retryable else "failed",
                error_code=exc.code,
            )
            completed = True
        finally:
            if completed:
                record = self.store.update(
                    self.scope, record["request_id"], next_query_at=self.clock() + self.poll_interval
                )
        return self._view(record, api_error=failure)

    async def wait_for_result(
        self, task_id: str, *, timeout: float = 120, poll_interval: float | None = None
    ) -> dict[str, Any]:
        if not math.isfinite(timeout) or timeout < 0 or timeout > 300:
            raise ValueError("Wait timeout must be between zero and 300 seconds.")
        if poll_interval is not None and (not math.isfinite(poll_interval) or not 0 < poll_interval <= 300):
            raise ValueError("Poll interval must be greater than zero and at most 300 seconds.")
        deadline = self.clock() + timeout
        next_poll = 0.0
        while True:
            record = self.store.by_task_id(self.scope, task_id)
            if (
                record["state"] not in {"processing", "ready"}
                or self._cached(record["request_id"]) is not None
                or (record["state"] == "ready" and record["mode"] == "sync")
            ):
                return self._view(record)
            remaining = min(deadline - self.clock(), record["created_at"] + self.max_age - self.clock())
            if remaining <= 0:
                if self.clock() - record["created_at"] >= self.max_age:
                    return await self.get_task_result(task_id)
                return self._view(record, error="WAIT_TIMEOUT")
            delay = max(0, max(record["next_query_at"], next_poll) - self.clock())
            if delay:
                await self.sleep(min(delay, remaining))
                continue
            try:
                result = await asyncio.wait_for(self.get_task_result(task_id), timeout=remaining)
            except asyncio.TimeoutError:
                return self._view(self.store.by_task_id(self.scope, task_id), error="WAIT_TIMEOUT")
            if result["state"] not in {"processing", "result_unavailable"}:
                return result
            if result["error"] and result["error"]["code"] == "QUERY_LIMIT_REACHED":
                return result
            if poll_interval is not None:
                next_poll = self.clock() + poll_interval
