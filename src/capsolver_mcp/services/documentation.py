"""Bounded, unauthenticated access to official CapSolver documentation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx


class _Article(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.article: list[str] = []
        self.depth = 0
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip += 1
        if tag == "main":
            self.depth += 1
        prefix = "\n" + "#" * int(tag[1]) + " " if re.fullmatch(r"h[1-6]", tag) else "\n"
        if tag in {"p", "div", "li", "tr", "pre", "br", "main"} or re.fullmatch(r"h[1-6]", tag):
            self.handle_data(prefix)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        if tag == "main":
            self.depth = max(0, self.depth - 1)
        if tag in {"td", "th"}:
            self.handle_data(" | ")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)
            if self.depth:
                self.article.append(data)

    def text(self) -> str:
        return re.sub(r"\n[ \t]*\n+", "\n\n", "".join(self.article or self.parts)).strip()


def validate_doc_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "docs.capsolver.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Only HTTPS docs.capsolver.com URLs without credentials, query or fragment are allowed.")


async def read_official_resource(url: str, client: httpx.AsyncClient | None = None) -> tuple[str, str, str]:
    """Return bounded content, its MIME type and the validated final URL."""
    owned = client is None
    client = client or httpx.AsyncClient(trust_env=False, timeout=15, follow_redirects=False)
    try:
        for _ in range(4):
            validate_doc_url(url)
            async with client.stream("GET", url, follow_redirects=False, timeout=15) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                data = bytearray()
                async for body_chunk in response.aiter_bytes():
                    data.extend(body_chunk)
                    if len(data) > 2_000_000:
                        raise ValueError("Documentation response exceeds the 2 MB limit.")
                return bytes(data).decode("utf-8", errors="replace"), response.headers.get("content-type", ""), url
        raise ValueError("Documentation redirect limit exceeded.")
    except httpx.HTTPError:
        raise ValueError("Official documentation is unavailable. Use the local catalog and retry docs later.") from None
    finally:
        if owned:
            await client.aclose()


async def fetch_document(
    url: str,
    *,
    offset: int = 0,
    limit: int = 16000,
    section: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    if offset < 0 or not 1 <= limit <= 20000:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 20000.")
    if section is not None and not section.strip():
        raise ValueError("section must be nonempty.")
    content, mime_type, url = await read_official_resource(url, client)
    if "html" in mime_type:
        parser = _Article()
        parser.feed(content)
        content = parser.text()
    headings = list(re.finditer(r"^(#{1,6})[ \t]+(.+)$", content, re.MULTILINE))
    outline = [m.group(2).strip() for m in headings]
    if section is not None:
        chosen = next((i for i, m in enumerate(headings) if section.lower() in m.group(2).lower()), None)
        if chosen is None:
            raise ValueError("Section not found; read the outline without a section filter.")
        match = headings[chosen]
        end = next((m.start() for m in headings[chosen + 1 :] if len(m.group(1)) <= len(match.group(1))), len(content))
        content = content[match.start() : end]
    chunk = content[offset : offset + limit]
    return {
        "source": "official_online_document",
        "url": url,
        "text": chunk,
        "outline": outline,
        "offset": offset,
        "total_characters": len(content),
        "next_offset": offset + len(chunk) if offset + len(chunk) < len(content) else None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "note": "Reference data only. Local schema support and real website acceptance are tracked separately.",
    }
