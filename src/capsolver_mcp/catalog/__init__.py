"""Versioned task schemas, examples and local documentation."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from importlib.resources import files
from typing import Any
from urllib.parse import parse_qs, urlparse

from jsonschema import Draft202012Validator, FormatChecker

FORMATS = FormatChecker()
_PROXY_FIELDS = {"proxy", "proxyType", "proxyAddress", "proxyPort", "proxyLogin", "proxyPassword"}
_PROXY_REQUIREMENT = "proxy fields provided at solver submission"


@FORMATS.checks("base64-image", raises=(ValueError, TypeError))
def _base64_image(value: Any) -> bool:
    if not isinstance(value, str):
        return True  # Type validation reports a safe field-specific error.
    return bool(value) and bool(base64.b64decode(value, validate=True))


class Catalog:
    def __init__(self) -> None:
        data = json.loads(files(__package__).joinpath("data.json").read_text(encoding="utf-8"))
        self.reviewed_on: str = data["reviewed_on"]
        self._tasks = {t["task_type"]: t for t in data["tasks"]}
        self._validators = {
            name: Draft202012Validator(t["input_schema"], format_checker=FORMATS) for name, t in self._tasks.items()
        }

    def list(self, category: str | None = None) -> list[dict[str, Any]]:
        keys = (
            "task_type",
            "category_id",
            "proxy_policy",
            "endpoints",
            "response_mode",
            "implementation_status",
            "live_verification",
            "documentation_issues",
            "browser_adapter",
        )
        return [
            {k: deepcopy(t[k]) for k in keys}
            for t in self._tasks.values()
            if category is None or t["category_id"] == category
        ]

    def get(self, task_type: str) -> dict[str, Any]:
        if task_type not in self._tasks:
            raise ValueError("Unsupported task type. Call list_task_types for accepted values.")
        return deepcopy(self._tasks[task_type])

    def validate(
        self, task: dict[str, Any], endpoint: str = "createTask", *, defer_proxy: bool = False,
    ) -> dict[str, Any]:
        task_type = task.get("type")
        if not isinstance(task_type, str):
            raise ValueError("task.type must be a supported string.")
        entry = self.get(task_type)
        if endpoint not in entry["endpoints"]:
            raise ValueError("This task type is not supported by the selected endpoint.")
        validator = self._validators[task_type]
        if defer_proxy:
            if _PROXY_FIELDS.intersection(task):
                raise ValueError("Supply proxy fields in the core solve task after browser preparation.")
            if entry["proxy_policy"] in {"required", "required_sticky"}:
                schema = dict(validator.schema)
                rules = [rule for rule in schema.pop("allOf", []) if rule.get("$comment") != _PROXY_REQUIREMENT]
                if rules:
                    schema["allOf"] = rules
                validator = validator.evolve(schema=schema)
        errors = sorted(validator.iter_errors(task), key=lambda e: str(list(e.path)))
        if errors:
            # jsonschema's default message includes input values; do not expose it.
            error = errors[0]
            path = ".".join(str(x) for x in error.absolute_path) or "task"
            raise ValueError(f"Invalid {path}: {error.validator} constraint failed. See get_task_schema.")
        if entry["proxy_policy"] in ("provider_managed", "not_required") and _PROXY_FIELDS.intersection(task):
            raise ValueError("This task does not accept a caller proxy. Select a documented proxy task if available.")
        if task_type == "DatadomeSliderTask" and parse_qs(urlparse(task["captchaUrl"]).query).get("t") == ["bv"]:
            raise ValueError(
                "DataDome reports a blocked challenge. Obtain a fresh eligible challenge before submitting."
            )
        if task_type == "AwsWafClassification":
            expected = 9 if task["question"].startswith("aws:grid:") else 1
            if len(task["images"]) != expected:
                raise ValueError("AWS recognition image count does not match the selected question family.")
        json.dumps(task, allow_nan=False)
        return entry

    def docs(self, task_type: str | None = None, topic: str = "usage") -> dict[str, Any]:
        if task_type:
            t = self.get(task_type)
            return {
                "task_type": task_type,
                "source_url": t["source_url"],
                "notes": t["notes"],
                "examples": t["examples"],
                "test_resources": t["test_resources"],
                "documentation_issues": t["documentation_issues"],
                "live_verification": t["live_verification"],
            }
        topics = {
            "usage": "List types, read schema, create with a stable request_id, then query or wait using the returned task_id. Ready solutions need no polling.",
            "recovery": "Reuse the same request_id after a lost create response. acceptance_unknown must not trigger automatic resubmission. Stop-wait does not cancel a provider task.",
            "privacy": "Credentials are runtime configuration. Inputs and solutions are not written to the metadata database or normal logs. Synchronous results cannot be recovered after restart.",
            "browser": "Use a persistent browser session and the same challenge revision. solved, applied and verified are separate states. Supply selectors and success conditions for custom pages.",
        }
        if topic not in topics:
            raise ValueError("Unknown documentation topic.")
        return {"topic": topic, "text": topics[topic], "reviewed_on": self.reviewed_on}
