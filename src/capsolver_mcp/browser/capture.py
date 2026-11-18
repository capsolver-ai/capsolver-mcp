"""Private local response evidence. Page capture and new requests stay distinct."""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import hashlib
import json
import os
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc.split("@")[-1], parsed.path, "", ""))


def capture_options(options: dict[str, Any] | None) -> dict[str, Any]:
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options) - {"enabled", "url_patterns", "max_body_bytes", "max_responses"}:
        raise ValueError("Unknown response capture options.")
    result = {"enabled": True, "url_patterns": [], "max_body_bytes": 1_000_000, "max_responses": 20, **options}
    if not isinstance(result["enabled"], bool):
        raise ValueError("enabled must be boolean.")
    patterns = result["url_patterns"]
    if not isinstance(patterns, list) or len(patterns) > 20 or any(
        not isinstance(p, str) or not p or len(p) > 2048 for p in patterns
    ):
        raise ValueError("url_patterns must contain at most 20 nonempty glob patterns.")
    for name, maximum in (("max_body_bytes", 2_000_000), ("max_responses", 50)):
        if type(result[name]) is not int or not 1 <= result[name] <= maximum:
            raise ValueError(f"{name} must be between 1 and {maximum}.")
    return result


class ResponseCapture:
    """Bound retained bodies and pending jobs; never put raw headers in summaries."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.options = capture_options({"enabled": False})
        self.records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.jobs: dict[str, asyncio.Task[None]] = {}
        self.saved: OrderedDict[str, int] = OrderedDict()
        self.scripts: dict[str, dict[str, Any]] = {}
        self.closed = False

    def configure(self, options: dict[str, Any]) -> dict[str, Any]:
        self.options = capture_options(options)
        return dict(self.options)

    def _write(self, path: Path, data: bytes) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)

    def _evict(self, identifier: str) -> None:
        job = self.jobs.get(identifier)
        if job and not job.done():
            job.cancel()
        self.saved.pop(identifier, None)
        row = self.records.get(identifier)
        if row:
            for key in ("body_file", "metadata_file"):
                path = row.pop(key, None)
                if path:
                    Path(path).unlink(missing_ok=True)
            row["capture_state"] = "evicted"

    def record_script(self, script: str) -> dict[str, Any]:
        if len(self.scripts) >= 20:
            raise ValueError("Init script limit reached. Open a new page/session to reset it.")
        identifier = uuid.uuid4().hex
        path = self.directory / f"init-{identifier}.js"
        self._write(path, script.encode())
        record = {"script_id": identifier, "script_file": str(path),
                  "script_sha256": hashlib.sha256(script.encode()).hexdigest()}
        self.scripts[identifier] = record
        return dict(record)

    def failure(self, row: dict[str, Any], state: str, error: BaseException) -> None:
        row["capture_state"] = state
        path = row.get("metadata_file")
        if path and Path(path).exists():
            try:
                metadata = json.loads(Path(path).read_text())
                metadata.update(capture_state=state, body_state=state,
                                capture_error={"type": type(error).__name__, "message": str(error)[:4000]})
                self._write(Path(path), json.dumps(metadata, ensure_ascii=True, indent=2).encode())
            except (OSError, ValueError):
                row["evidence_update_failed"] = True

    def _new(self, url: str, status: int, method: str, source: str) -> dict[str, Any]:
        row: dict[str, Any] = {"response_id": uuid.uuid4().hex, "url": safe_url(url), "status": status,
               "method": method, "source": source, "captured_at": time.time(), "capture_state": "disabled"}
        self.records[row["response_id"]] = row
        while len(self.records) > 100:
            identifier = next(iter(self.records))
            self._evict(identifier)
            self.records.pop(identifier)
        return row

    def observe(self, response: Any) -> dict[str, Any]:
        row = self._new(response.url, response.status, response.request.method, "original_response")
        options = dict(self.options)
        if self.closed or not options["enabled"] or (
            options["url_patterns"] and not any(fnmatch.fnmatchcase(response.url, p) for p in options["url_patterns"])
        ):
            return row
        if len(self.jobs) >= options["max_responses"]:
            row["capture_state"] = "skipped_busy"
            return row
        row["capture_state"] = "pending"

        async def save() -> None:
            try:
                request = response.request
                request_headers = await request.all_headers()
                post_data = request.post_data_buffer
                await self._save(row, response, options, {
                    "url": request.url, "method": request.method, "headers": request_headers,
                    "post_data_base64": base64.b64encode(post_data[:16000]).decode() if post_data else None,
                    "post_data_truncated": bool(post_data and len(post_data) > 16000),
                })
            except asyncio.CancelledError as exc:
                self.failure(row, "cancelled", exc)
                raise
            except Exception as exc:
                self.failure(row, "unavailable", exc)
                row["reason"] = "Original response body could not be read; it was not requested again."

        job = asyncio.create_task(save())
        self.jobs[row["response_id"]] = job
        job.add_done_callback(lambda _: self.jobs.pop(row["response_id"], None))
        return row

    def begin_request(self, url: str, method: str, headers: dict[str, str], data: Any) -> dict[str, Any]:
        row = self._new(url, 0, method, "session_request")
        row["capture_state"] = "request_started"
        metadata_file = self.directory / f"{row['response_id']}.json"
        request = {"url": url, "method": method, "supplied_headers": headers, "supplied_data": data,
                   "headers_complete": False,
                   "note": "Context-managed Cookie/UA headers are not enumerated here."}
        self._write(metadata_file, json.dumps({"source": "session_request", "request": request,
                                              "delivery_state": "unknown_until_response"}, indent=2).encode())
        row["metadata_file"] = str(metadata_file)
        return row

    async def _save(self, row: dict[str, Any], response: Any, options: dict[str, Any], request: dict[str, Any]) -> None:
        headers = await response.all_headers() if hasattr(response, "all_headers") else response.headers
        content_type = headers.get("content-type", "")
        identifier = row["response_id"]
        metadata_file = self.directory / f"{identifier}.json"
        metadata = {"response_id": identifier, "source": row["source"], "request": request,
                    "response": {"url": response.url, "status": response.status, "headers": headers},
                    "body_state": "pending"}
        self._write(metadata_file, json.dumps(metadata, ensure_ascii=True, indent=2).encode())
        row["metadata_file"] = str(metadata_file)
        # Do not wait forever for streaming bodies. Playwright buffers other bodies;
        # these limits bound retained evidence, not its transport buffer.
        if "text/event-stream" in content_type.lower():
            row["capture_state"] = "skipped_stream"
            metadata["body_state"] = "skipped_stream"
            self._write(metadata_file, json.dumps(metadata, ensure_ascii=True, indent=2).encode())
            return
        body = await asyncio.wait_for(response.body(), timeout=15)
        retained = body[:options["max_body_bytes"]]
        if identifier not in self.records or self.closed:
            return
        while self.saved and (len(self.saved) >= options["max_responses"] or sum(self.saved.values()) + len(retained) > 16_000_000):
            self._evict(next(iter(self.saved)))
        body_file = self.directory / f"{identifier}.body"
        truncated = len(retained) != len(body)
        metadata = {"response_id": identifier, "source": row["source"], "request": request,
                    "response": {"url": response.url, "status": response.status, "headers": headers},
                    "body_file": str(body_file), "body_bytes": len(body), "stored_bytes": len(retained),
                    "truncated": truncated, "stored_sha256": hashlib.sha256(retained).hexdigest(),
                    "body_state": "truncated" if truncated else "saved",
                    "body_representation": "Playwright response body bytes; content decoding may already be applied"}
        self._write(body_file, retained)
        self._write(metadata_file, json.dumps(metadata, ensure_ascii=True, indent=2).encode())
        self.saved[identifier] = len(retained)
        row.update(capture_state="truncated" if truncated else "saved", body_file=str(body_file),
                   metadata_file=str(metadata_file), body_bytes=len(body), stored_bytes=len(retained),
                   truncated=truncated, content_type=content_type, stored_sha256=metadata["stored_sha256"])

    async def save_request(self, response: Any, request: dict[str, Any], max_body_bytes: int,
                           row: dict[str, Any] | None = None) -> dict[str, Any]:
        options = capture_options({"max_body_bytes": max_body_bytes})
        row = row if row is not None else self._new(response.url, response.status, request["method"], "session_request")
        row["status"] = response.status
        row["capture_state"] = "pending"
        try:
            await self._save(row, response, options, request)
        except Exception as exc:
            self.failure(row, "unavailable", exc)
            row["reason"] = "New request response body could not be saved; no retry was made."
        return dict(row)

    async def get(self, identifier: str, *, include_body: bool = False, offset: int = 0,
                  limit: int = 16000, encoding: str = "text") -> dict[str, Any]:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 48000:
            raise ValueError("offset must be nonnegative and limit must be between 1 and 48000 bytes.")
        if encoding not in {"text", "base64"}:
            raise ValueError("encoding must be text or base64.")
        if identifier not in self.records:
            raise KeyError("Response not retained for this page.")
        job = self.jobs.get(identifier)
        if job:
            try:
                await asyncio.wait_for(asyncio.shield(job), timeout=2)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                if not job.cancelled():
                    raise
        result = dict(self.records[identifier])
        if include_body and result.get("body_file"):
            with Path(result["body_file"]).open("rb") as stream:
                stream.seek(offset)
                body = stream.read(limit)
            result.update(body=base64.b64encode(body).decode() if encoding == "base64" else body.decode("utf-8", errors="replace"),
                          encoding=encoding, offset=offset, next_offset=offset + len(body),
                          has_more=offset + len(body) < result["stored_bytes"])
        return result

    async def aclose(self) -> None:
        jobs = list(self.jobs.values())
        if jobs:
            _, pending = await asyncio.wait(jobs, timeout=2)
            for job in pending:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
        self.closed = True
