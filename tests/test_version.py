"""Guard against version drift between the package and the MCP Registry metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import capsolver_mcp

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_JSON = REPO_ROOT / "server.json"


@pytest.fixture(scope="module")
def server_json() -> dict:
    if not SERVER_JSON.exists():
        pytest.skip("server.json is only present in the source tree")
    return json.loads(SERVER_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def package_version() -> str:
    # __version__ falls back to this sentinel when the package is not installed,
    # in which case there is no real version to compare server.json against.
    if capsolver_mcp.__version__ == "0.0.0.dev0":
        pytest.skip("capsolver-mcp is not installed; no metadata version to compare")
    return capsolver_mcp.__version__


def test_server_json_version_matches_package(server_json: dict, package_version: str) -> None:
    assert server_json["version"] == package_version


def test_server_json_package_version_matches_package(server_json: dict, package_version: str) -> None:
    assert server_json["packages"][0]["version"] == package_version


def test_server_json_name_matches_readme_marker(server_json: dict) -> None:
    """The registry validates package ownership via this marker in the PyPI description."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"mcp-name: {server_json['name']}" in readme
