"""CapSolver MCP Server — expose captcha-solving capabilities via Model Context Protocol.

Supports both stdio (local) and SSE (remote) transports.
"""

from capsolver_mcp.server import create_server

__all__ = ["create_server"]
__version__ = "0.1.0"
