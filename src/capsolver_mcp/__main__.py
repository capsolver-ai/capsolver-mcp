"""Entry point for ``python -m capsolver_mcp`` and the ``capsolver-mcp`` console script.

Usage:
    # stdio transport (default, for local MCP clients like Claude Desktop)
    capsolver-mcp

    # SSE transport (for remote access)
    capsolver-mcp --transport sse --host 0.0.0.0 --port 8000

    # Streamable HTTP transport (MCP 2025-03-26 spec)
    capsolver-mcp --transport streamable-http --host 0.0.0.0 --port 8000

Environment variables:
    CAPSOLVER_API_KEY   — your CapSolver API key (required for solving tools)
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CapSolver MCP Server — expose captcha-solving tools via Model Context Protocol.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol: stdio (default), sse, or streamable-http.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind for SSE/HTTP transports (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind for SSE/HTTP transports (default: 8000).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="CapSolver API key. Falls back to CAPSOLVER_API_KEY env var.",
    )
    parser.add_argument(
        "--name",
        default="capsolver",
        help="Server name advertised to MCP clients (default: capsolver).",
    )

    args = parser.parse_args()

    from capsolver_mcp.server import create_server

    server = create_server(
        api_key=args.api_key,
        server_name=args.name,
        host=args.host,
        port=args.port,
    )

    if args.transport == "sse":
        server.run(transport="sse")
    elif args.transport == "streamable-http":
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
