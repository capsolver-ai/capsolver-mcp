"""Runtime settings loaded from the process environment."""

from __future__ import annotations

import os
import json
import math
from dataclasses import dataclass, field
from pathlib import Path


SERVER_NAME = "capsolver-mcp"


@dataclass
class Settings:
    api_key: str = field(default="", repr=False)
    offline: bool = False
    state_dir: Path = field(default_factory=lambda: Path.home() / ".local/state/capsolver-mcp")
    max_browser_sessions: int = 4
    max_parallel_tasks: int = 4
    get_token_timeout: float = 120
    browser_disable_http2: bool = False
    http_tokens: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.get_token_timeout) or not 0 < self.get_token_timeout <= 120:
            raise ValueError("getToken timeout must be between 0 and 120 seconds.")

    @classmethod
    def load(
        cls, api_key: str | None = None, *, offline: bool | None = None, load_api_key: bool = True
    ) -> Settings:
        simulated = offline if offline is not None else os.environ.get("CAPSOLVER_OFFLINE") == "1"
        key = (api_key or os.environ.get("CAPSOLVER_API_KEY", "")) if load_api_key else ""
        try:
            tokens = json.loads(os.environ.get("CAPSOLVER_HTTP_TOKENS_JSON", "{}"))
            if not isinstance(tokens, dict):
                raise ValueError
            if os.environ.get("CAPSOLVER_HTTP_TOKEN"):
                tokens["operator"] = os.environ["CAPSOLVER_HTTP_TOKEN"]
            if any(
                not isinstance(k, str)
                or not k
                or not isinstance(v, str)
                or len(v) < 16
                or any(not 33 <= ord(c) <= 126 for c in v)
                for k, v in tokens.items()
            ):
                raise ValueError
            if len(set(tokens.values())) != len(tokens):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(
                "HTTP tokens must map nonempty operators to unique tokens of at least 16 visible ASCII characters."
            ) from None
        return cls(
            get_token_timeout=float(os.environ.get("CAPSOLVER_GET_TOKEN_TIMEOUT", "120")),
            api_key="offline-simulation-key" if simulated and load_api_key else key,
            offline=simulated,
            browser_disable_http2=os.environ.get('CAPSOLVER_BROWSER_DISABLE_HTTP2') == '1',
            state_dir=Path(
                os.environ.get("CAPSOLVER_STATE_DIR", str(Path.home() / ".local/state/capsolver-mcp"))
            ).expanduser(),
            http_tokens=tokens,
        )
