"""In-memory simulated provider. Never represents real CAPTCHA acceptance."""

from __future__ import annotations

import json
from typing import Any

import httpx


def simulated_solution(task: dict[str, Any]) -> dict[str, Any]:
    name = task["type"]
    if name == "ImageToTextTask":
        return {"answers": ["DEMO"] * len(task["images"])} if task.get("module") == "number" else {"text": "DEMO"}
    if name == "ReCaptchaV2Classification":
        return {"type": "multi", "objects": [0, 2], "size": 3}
    if name == "AwsWafClassification":
        return {"objects": [0, 2]} if task["question"].startswith("aws:grid:") else {"box": [40, 40]}
    if name == "VisionEngine":
        module = task["module"]
        if module == "botdeflector":
            return {"points": [[40, 40], [80, 40]]}
        if module == "slider_1":
            return {"distance": 60}
        if module.startswith("rotate"):
            return {"angle": 90}
        if module == "shein":
            return {"rects": [{"x1": 20, "y1": 20, "x2": 60, "y2": 60}]}
        return {"text": "DEMO"}
    if name == "GeeTestTaskProxyLess":
        if "captchaId" in task:
            return {
                "captcha_id": task["captchaId"],
                "captcha_output": "SIMULATED",
                "gen_time": "0",
                "lot_number": "SIMULATED",
                "pass_token": "SIMULATED",
            }
        return {"challenge": task["challenge"], "validate": "SIMULATED", "seccode": "SIMULATED"}
    if name.startswith("ReCaptcha"):
        return {"gRecaptchaResponse": "SIMULATED_TOKEN", "userAgent": "SIMULATED_UA"}
    if name == "DatadomeSliderTask":
        return {"cookie": "datadome=SIMULATED_COOKIE; Path=/"}
    if name.startswith("AntiAwsWaf"):
        return {"cookie": "SIMULATED_AWS_TOKEN"}
    if name == "AntiCloudflareTask":
        return {"cookies": {"cf_clearance": "SIMULATED_COOKIE"}, "token": "SIMULATED_COOKIE"}
    return {"token": "SIMULATED_TOKEN"}


class OfflineProvider:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        if request.url.path == "/getBalance":
            return httpx.Response(200, json={"errorId": 0, "balance": 0, "packages": [], "simulated": True})
        if request.url.path == "/getTaskResult":
            task = self.tasks[data["taskId"]]
            return httpx.Response(
                200,
                json={"errorId": 0, "status": "ready", "taskId": data["taskId"], "solution": simulated_solution(task)},
            )
        task = data["task"]
        task_id = f"offline-{len(self.tasks) + 1}"
        self.tasks[task_id] = task
        immediate = task["type"] in {
            "ImageToTextTask",
            "VisionEngine",
            "ReCaptchaV2Classification",
            "AwsWafClassification",
        }
        result: dict[str, Any] = {"errorId": 0, "taskId": task_id}
        if immediate or request.url.path == "/getToken":
            result.update(status="ready", solution=simulated_solution(task))
        return httpx.Response(200, json=result)
