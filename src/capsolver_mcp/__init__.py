"""CapSolver MCP Server — expose captcha-solving capabilities via Model Context Protocol.

Supports both stdio (local) and SSE (remote) transports.
"""

from importlib.metadata import PackageNotFoundError, version as _version

from capsolver_mcp.server import create_server

__all__ = ["create_server"]

try:
    __version__ = _version("capsolver-mcp")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0.dev0"
