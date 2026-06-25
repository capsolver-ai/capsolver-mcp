# capsolver-mcp

MCP Server for [CapSolver](https://capsolver.com) — expose captcha-solving capabilities to AI agents via the [Model Context Protocol](https://modelcontextprotocol.io).

See the [capsolver-ai](https://github.com/capsolver-ai/capsolver-ai) hub repo for integration examples and the full documentation.

For detailed MCP client setup (Claude Desktop, Claude Code, Cursor, Windsurf, Cline, and more), see [docs/mcp-integration.md](docs/mcp-integration.md).

## Install

```bash
pip install capsolver-mcp
pip install capsolver-mcp[browser]   # with Playwright support (for detect/solve_on_page)
```

All tools read the API key from the environment:

```bash
# bash / zsh
export CAPSOLVER_API_KEY="your-capsolver-api-key"

# PowerShell
$env:CAPSOLVER_API_KEY = "your-capsolver-api-key"

# cmd
set CAPSOLVER_API_KEY=your-capsolver-api-key
```

## Usage

### CLI

```bash
# stdio (default — for local MCP clients like Claude Desktop)
capsolver-mcp

# SSE (for remote / HTTP access)
capsolver-mcp --transport sse --host 0.0.0.0 --port 8000

# Streamable HTTP (MCP 2025-03-26 spec)
capsolver-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

#### CLI options

```
capsolver-mcp [OPTIONS]

  --transport {stdio,sse,streamable-http}
                              Transport protocol (default: stdio)
  --host HOST                 Bind host for SSE/HTTP transports (default: 127.0.0.1)
  --port PORT                 Bind port for SSE/HTTP transports (default: 8000)
  --api-key KEY               API key (fallback: CAPSOLVER_API_KEY env)
  --name NAME                 Server name (default: capsolver)
```

### Programmatic

```python
from capsolver_mcp.server import create_server

server = create_server(
    api_key="your-key",       # or set CAPSOLVER_API_KEY env var
    server_name="capsolver",  # name advertised to MCP clients
    host="127.0.0.1",         # bind host for SSE / HTTP transports
    port=8000,                # bind port for SSE / HTTP transports
)
server.run(transport="sse")   # or "stdio" or "streamable-http"
```

> **Note:** `host` and `port` are constructor parameters on `create_server()`
> (forwarded to `FastMCP`), matching the MCP Python SDK (>=1.0) API.

## Configure in Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "capsolver": {
      "command": "capsolver-mcp",
      "env": {
        "CAPSOLVER_API_KEY": "your-key"
      }
    }
  }
}
```

## Available tools

| Tool | Browser? | Description |
|---|---|---|
| `solve_captcha` | No | Solve a captcha by type + site params (token mode) |
| `detect_captchas` | Yes | Scan a page URL and list present captcha types |
| `solve_on_page` | Yes | Detect + solve + autofill all captchas on a page |
| `get_balance` | No | Check account balance and packages |
| `get_supported_captchas` | No | List all supported captcha types and handlers |

Browser-based tools (`detect_captchas`, `solve_on_page`) require the `browser` extra:

```bash
pip install capsolver-mcp[browser]
playwright install chromium
```

## Development

```bash
git clone https://github.com/capsolver-ai/mcp-capsolver.git
cd mcp-capsolver
uv sync --all-extras          # or: pip install -r requirements-dev.txt
uv run pytest                 # run tests
uv run ruff check src tests   # lint
```

## License

ISC
