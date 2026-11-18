"""Cache official CapSolver task tables separately from executable schemas."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from capsolver_mcp.catalog import Catalog
from capsolver_mcp.services.documentation import fetch_document, read_official_resource, validate_doc_url

INDEX = "https://docs.capsolver.com/en/guide/api-tasktype/"
DATADOME = "https://docs.capsolver.com/en/guide/captcha/datadome/"
TASK_NAME = re.compile(r"\b(?:[A-Za-z][A-Za-z0-9]{2,60}(?:Task(?:Proxy[Ll]ess)?|Classification)|VisionEngine)\b")
TASK_PATH = re.compile(r"/en/guide/(?:captcha|recognition)/[A-Za-z0-9_-]+/?")
FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,64}")


class TaskPage(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.main = 0
        self.inert = 0
        self.links: set[str] = set()
        self.tables: list[list[list[str]]] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.text: list[str] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a" and (href := dict(attrs).get("href")):
            self.links.add(href)
        if tag == "main":
            self.main += 1
        if not self.main:
            return
        if tag in {"script", "style"}:
            self.inert += 1
        if self.inert:
            return
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if not self.main:
            return
        if tag in {"script", "style"}:
            self.inert = max(0, self.inert - 1)
        if self.inert:
            return
        if tag == "main":
            self.main -= 1
        elif tag in {"td", "th"} and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None

    def handle_data(self, data: str) -> None:
        if self.main and not self.inert:
            self.text.append(data)
            if self.cell is not None:
                self.cell.append(data)

    def parameters(self) -> list[dict[str, str]]:
        for table in self.tables:
            if not table:
                continue
            header = [x.casefold() for x in table[0]]
            if len(header) < 3 or "required" not in header or "type" not in header:
                continue
            if not any(row and row[0] == "type" for row in table[1:]):
                continue
            return [
                {"name": row[0], "type": row[1], "required": row[2], "description": row[3] if len(row) > 3 else ""}
                for row in table[1:]
                if len(row) >= 3 and FIELD.fullmatch(row[0])
            ]
        return []

    def task_names(self, fields: list[dict[str, str]]) -> list[str]:
        declaration = " ".join(f["description"] for f in fields if f["name"] == "type")
        examples = re.findall(r"[\"']type[\"']\s*:\s*[\"']([^\"']+)[\"']", "".join(self.text))
        names = set(TASK_NAME.findall(declaration))
        names.update(name for name in examples if TASK_NAME.fullmatch(name))
        return sorted(names)


class OfficialCatalog:
    def __init__(self, local: Catalog) -> None:
        self.local = local
        self._lock = asyncio.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._refresh_after = 0.0

    async def refresh(self, *, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            if not force and self._snapshot and time.monotonic() < self._refresh_after:
                return self._snapshot
            try:
                snapshot = await asyncio.wait_for(self._load(), timeout=40)
            except (ValueError, TimeoutError):
                if self._snapshot is not None:
                    return {**self._snapshot, "stale": True, "refresh_error": "Official documentation unavailable."}
                raise ValueError("Official documentation unavailable. Use the reviewed local task catalog.") from None
            self._snapshot = snapshot
            self._refresh_after = time.monotonic() + (300 if snapshot["failed_pages"] else 3600)
            return snapshot

    async def _load(self) -> dict[str, Any]:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=15) as client:
            html, _, url = await read_official_resource(INDEX, client)
            pages = set()
            for link in TaskPage(html).links:
                candidate = urljoin(url, link)
                if not TASK_PATH.fullmatch(urlsplit(candidate).path):
                    continue
                try:
                    validate_doc_url(candidate)
                except ValueError:
                    continue
                pages.add(candidate)
            if not 1 <= len(pages) <= 40:
                raise ValueError("Unexpected official task index structure.")
            capacity = asyncio.Semaphore(5)

            async def load(page_url: str) -> tuple[str, dict[str, Any]]:
                async with capacity:
                    body, _, source = await read_official_resource(page_url, client)
                parsed = TaskPage(body)
                parameters = parsed.parameters()
                return page_url, {"url": source, "parameters": parameters, "task_names": parsed.task_names(parameters)}

            order = sorted(pages)
            results = await asyncio.gather(*(load(page) for page in order), return_exceptions=True)
        available = dict(item for item in results if isinstance(item, tuple))
        if not available:
            raise ValueError("No official task pages could be read.")
        known = {r["task_type"] for r in self.local.list()}
        documented = {name for item in available.values() for name in item["task_names"]}
        differences = {}
        for name in sorted(known):
            local = self.local.get(name)
            page = available.get(local["source_url"])
            if not page or not page["parameters"]:
                continue
            live = {field["name"] for field in page["parameters"]}
            reviewed = set(local["input_schema"]["properties"])
            if live - reviewed or reviewed - live:
                differences[name] = {"documented_only": sorted(live - reviewed), "reviewed_only": sorted(reviewed - live)}
        return {"source": "official_documentation", "index": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "stale": False, "failed_pages": [page for page in order if page not in available], "pages": available,
                "reviewed_types": sorted(known), "documented_type_mentions": sorted(documented),
                "unreviewed_mentions": sorted(documented - known), "field_differences": differences}


async def documented_user_agent(platform: str, browser: str, major: int | None) -> dict[str, Any]:
    section = {("windows", "chrome"): "Windows Chrome", ("windows", "firefox"): "Windows Firefox",
               ("mac", "chrome"): "Mac Chrome"}.get((platform.lower(), browser.lower()))
    if section is None:
        raise ValueError("Use windows/chrome, windows/firefox, or mac/chrome.")
    source = await fetch_document(DATADOME, section=section)
    family = "Firefox" if browser.lower() == "firefox" else "Chrome"
    supported = []
    for line in source["text"].splitlines():
        value = line.strip()
        match = re.search(rf"\b{family}/(\d+)\.[0-9.]+", value)
        if value.startswith("Mozilla/5.0 (") and match and len(value) < 300:
            supported.append((int(match[1]), value))
    versions = sorted({version for version, _ in supported}, reverse=True)
    matching = sorted((entry for entry in supported if major is None or major == entry[0]), reverse=True)
    if not matching:
        raise ValueError(f"No documented User-Agent for this selection. Available major versions: {versions}.")
    version, ua = matching[0]
    return {"user_agent": ua, "major": version, "supported_majors": versions, "task_type": "DatadomeSliderTask",
            "platform": platform.lower(), "browser": browser.lower(), "source": source["url"],
            "retrieved_at": source["retrieved_at"], "requires_matching_browser": True}
