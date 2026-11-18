"""Entry point for ``python -m capsolver_mcp`` and the ``capsolver-mcp`` console script.

Usage:
    # stdio transport (default, for local MCP clients like Claude Desktop)
    capsolver-mcp

    # Independent optional browser (no provider API key)
    capsolver-browser-mcp

    # SSE transport (for remote access)
    capsolver-mcp --transport sse --host 0.0.0.0 --port 8000

    # Streamable HTTP transport (MCP 2025-03-26 spec)
    capsolver-mcp --transport streamable-http --host 0.0.0.0 --port 8000

Environment variables:
    CAPSOLVER_API_KEY   — your CapSolver API key (required for solving tools)
"""

from __future__ import annotations

import argparse
import ipaddress

from capsolver_mcp.config import SERVER_NAME, Settings


def main(*, default_mode: str = "core") -> None:
    parser = argparse.ArgumentParser(
        description=f"{SERVER_NAME} exposes CAPTCHA solving tools via Model Context Protocol.",
    )
    parser.add_argument(
        "--mode",
        choices=["core", "browser"],
        default=default_mode,
        help="Core API (default) or independent browser.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use a simulated provider; no real solves or provider requests.",
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
        default=None,
        help=f"Server name advertised to MCP clients (default: {SERVER_NAME}, or capsolver-browser in browser mode).",
    )

    args = parser.parse_args()

    from capsolver_mcp.server import create_server
    from capsolver_mcp.runtime import Runtime

    settings = Settings.load(args.api_key, offline=True if args.offline else None, load_api_key=args.mode != "browser")
    if args.transport != "stdio":
        try:
            local = args.host == "localhost" or ipaddress.ip_address(args.host).is_loopback
        except ValueError:
            local = False
        if not local and not settings.http_tokens:
            parser.error("Non-loopback HTTP requires CAPSOLVER_HTTP_TOKEN or CAPSOLVER_HTTP_TOKENS_JSON.")

    server = create_server(
        api_key=args.api_key,
        server_name=args.name,
        host=args.host,
        port=args.port,
        runtime=Runtime(settings),
        mode=args.mode,
    )

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        import uvicorn
        from capsolver_mcp.security import BearerMiddleware

        app = server.sse_app() if args.transport == "sse" else server.streamable_http_app()
        uvicorn.run(BearerMiddleware(app, settings.http_tokens), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
