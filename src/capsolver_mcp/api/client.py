"""Single-attempt HTTP transport. Paid requests are never replayed implicitly."""

from __future__ import annotations

import asyncio
import math
import re
from typing import Any

import httpx

_PROVIDER_HINTS = {
    "UNSUPPORTED_SITE_KEY": "The provider does not support this site key. Use a supported authorized fixture or request provider configuration.",
    "UNSUPPORTED_USER_AGENT": "The provider rejected the user agent. Use a provider-supported stable Chrome UA consistently in the browser and task.",
    "PROVIDER_SOLVER_FAILURE": "The provider accepted the task but its solver failed. Preserve the task ID and subcode; do not infer a cause or recreate automatically.",
}


def _classify_provider_error(description: Any) -> tuple[str | None, int | None]:
    """Map known descriptions to fixed hints; never return provider text."""
    if not isinstance(description, str):
        return None, None
    lowered = description.lower()
    if "the sitekey is not supported" in lowered:
        return "UNSUPPORTED_SITE_KEY", None
    if "unsupported useragent" in lowered or "unsupported user-agent" in lowered:
        return "UNSUPPORTED_USER_AGENT", None
    match = re.search(r"failed to solve the captcha:\s*([0-9]{1,5})\b", lowered)
    if match:
        return "PROVIDER_SOLVER_FAILURE", int(match[1])
    return None, None


class ApiError(Exception):
    """Safe diagnostics without provider bodies or underlying exception text."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        submission_unknown: bool = False,
        http_status: int | None = None,
        reason_code: str | None = None,
        provider_subcode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.submission_unknown = submission_unknown
        self.http_status = http_status
        self.reason_code = reason_code
        self.provider_subcode = provider_subcode

    def safe_details(self) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if self.http_status is not None:
            details["http_status"] = self.http_status
        if self.reason_code in _PROVIDER_HINTS:
            details.update(reason=self.reason_code, hint=_PROVIDER_HINTS[self.reason_code])
            if self.reason_code == "PROVIDER_SOLVER_FAILURE" and isinstance(self.provider_subcode, int):
                details["provider_subcode"] = self.provider_subcode
        return details


class ApiClient:
    """Call known endpoints without redirects, implicit retries or environment proxies.

    Callers own injected AsyncClients; aclose() only closes a client created here.
    """

    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None, timeout: float = 30,
                 get_token_timeout: float = 120) -> None:
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("Request timeout must be between 0 and 120 seconds.")
        if not math.isfinite(get_token_timeout) or not 0 < get_token_timeout <= 120:
            raise ValueError("getToken timeout must be between 0 and 120 seconds.")
        self._api_key = api_key
        self.timeout = timeout
        self.get_token_timeout = get_token_timeout
        self._client = client
        self._owns_client = client is None

    def timeout_for(self, endpoint: str) -> float:
        return self.get_token_timeout if endpoint == "getToken" else self.timeout

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if endpoint not in {"createTask", "getTaskResult", "getToken", "getBalance"}:
            raise ValueError("Unsupported provider endpoint.")
        if not self._api_key:
            raise ApiError("MISSING_API_KEY", "A CapSolver API key is required.")
        if "clientKey" in payload:
            raise ValueError("Credentials must come from runtime configuration.")
        paid = endpoint in {"createTask", "getToken"}
        request_timeout = self.timeout_for(endpoint)
        if self._client is None:
            self._client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
        try:
            response = await asyncio.wait_for(
                self._client.post(
                    "https://api.capsolver.com/" + endpoint,
                    json={**payload, "clientKey": self._api_key},
                    timeout=request_timeout,
                    follow_redirects=False,
                ),
                timeout=request_timeout,
            )
        except (httpx.RequestError, asyncio.TimeoutError):
            raise ApiError(
                "NETWORK_ERROR",
                "The provider request did not return a response.",
                retryable=not paid,
                submission_unknown=paid,
            ) from None
        try:
            data = response.json()
        except ValueError:
            data = None
        status = response.status_code
        if isinstance(data, dict) and data.get("errorId"):
            candidate = data.get("errorCode")
            code = (
                candidate
                if isinstance(candidate, str) and re.fullmatch(r"ERROR_[A-Z0-9_]{1,80}", candidate)
                else "PROVIDER_ERROR"
            )
            reason, subcode = _classify_provider_error(data.get("errorDescription"))
            raise ApiError(
                code,
                "The provider rejected the request.",
                retryable=not paid and status == 429,
                http_status=status,
                reason_code=reason,
                provider_subcode=subcode,
            )
        if status != 200:
            raise ApiError(
                "HTTP_ERROR",
                "The provider returned an unexpected HTTP status.",
                retryable=not paid and (status == 429 or status >= 500),
                submission_unknown=paid,
                http_status=status,
            )
        if not isinstance(data, dict) or data.get("errorId") != 0:
            raise ApiError(
                "INVALID_RESPONSE",
                "The provider response is not a valid result envelope.",
                retryable=not paid,
                submission_unknown=paid,
            )
        return data
