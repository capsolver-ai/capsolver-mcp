"""Read packaged, versioned agent guidance without a provider credential."""

import json
from pathlib import Path
from typing import Any


def read_agent_guidance(topic: str, offset: int = 0, limit: int = 16000) -> dict[str, Any]:
    if topic not in {"agent", "agent-acquisition", "agent-recovery"}:
        raise ValueError("Unknown agent guidance topic.")
    if offset < 0 or not 1 <= limit <= 20000:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 20000.")
    path = Path(__file__).resolve().parents[1] / "guidance.json"
    content = json.loads(path.read_text(encoding="utf-8"))[topic]
    chunk = content[offset:offset + limit]
    return {"source": "packaged_agent_guidance", "topic": topic, "text": chunk,
            "offset": offset, "total_characters": len(content),
            "next_offset": offset + len(chunk) if offset + len(chunk) < len(content) else None}
