# MCP Client Configuration Guide

This guide covers how to connect the CapSolver MCP server to your AI development tools via the Model Context Protocol.

For Python framework integrations (OpenAI, LangChain, LlamaIndex, etc.), see [capsolver-agent integration docs](https://github.com/capsolver-ai/agent-capsolver/blob/main/docs/agent-integration.md).

## Quick Start

Install and run in one command:

```bash
# After publishing to PyPI:
uvx capsolver-mcp

# Or install globally:
pip install capsolver-mcp
capsolver-mcp
```

Set your API key:

```bash
export CAPSOLVER_API_KEY="CAP-XXXXXX"
```

That's it. The MCP server starts in **stdio** mode, ready for any MCP client to connect.

---

## MCP Client Configurations

All clients below use the same JSON structure. The only difference is **where** the config file lives.

### Claude Desktop

| Platform | Config Path |
|----------|-------------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "capsolver": {
      "command": "capsolver-mcp",
      "env": {
        "CAPSOLVER_API_KEY": "CAP-XXXXXX"
      }
    }
  }
}
```

Or use `uvx` (no global install needed):

```json
{
  "mcpServers": {
    "capsolver": {
      "command": "uvx",
      "args": ["capsolver-mcp"],
      "env": {
        "CAPSOLVER_API_KEY": "CAP-XXXXXX"
      }
    }
  }
}
```

After saving, restart Claude Desktop. The capsolver tools will appear automatically.

### Claude Code (CLI)

Add via command line:

```bash
claude mcp add capsolver -e CAPSOLVER_API_KEY=CAP-XXXXXX -- uvx capsolver-mcp
```

Or edit `~/.claude.json` directly:

```json
{
  "mcpServers": {
    "capsolver": {
      "type": "stdio",
      "command": "uvx",
      "args": ["capsolver-mcp"],
      "env": {
        "CAPSOLVER_API_KEY": "CAP-XXXXXX"
      }
    }
  }
}
```

Manage servers:

```bash
claude mcp list        # view configured servers
claude mcp remove capsolver  # remove
```

### Cursor

| Scope | Config Path |
|-------|-------------|
| Global | `~/.cursor/mcp.json` |
| Project | `.cursor/mcp.json` |

```json
{
  "mcpServers": {
    "capsolver": {
      "command": "uvx",
      "args": ["capsolver-mcp"],
      "env": {
        "CAPSOLVER_API_KEY": "CAP-XXXXXX"
      }
    }
  }
}
```

Or configure via UI: **Settings → Tools & MCP → New MCP Server**.

> **Windows note:** If `uvx` or `npx` doesn't work directly, use:
> ```json
> {
>   "command": "cmd",
>   "args": ["/c", "uvx", "capsolver-mcp"],
>   "env": { "CAPSOLVER_API_KEY": "CAP-XXXXXX" }
> }
> ```

### Windsurf

| Platform | Config Path |
|----------|-------------|
| macOS | `~/.codeium/windsurf/mcp_config.json` |
| Windows | `%USERPROFILE%\.codeium\windsurf\mcp_config.json` |

```json
{
  "mcpServers": {
    "capsolver": {
      "command": "uvx",
      "args": ["capsolver-mcp"],
      "env": {
        "CAPSOLVER_API_KEY": "CAP-XXXXXX"
      }
    }
  }
}
```

Or via UI: `Cmd/Ctrl + Shift + P` → **MCP: Add Server**.

### Cline (VS Code Extension)

Open VS Code settings → search "Cline MCP" → edit `cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "capsolver": {
      "command": "uvx",
      "args": ["capsolver-mcp"],
      "env": {
        "CAPSOLVER_API_KEY": "CAP-XXXXXX"
      }
    }
  }
}
```

### Remote / HTTP Mode (Any Client)

For clients that support HTTP transport (Cursor, Windsurf, Cline, etc.), start the server in SSE or streamable-http mode:

```bash
# SSE transport
capsolver-mcp --transport sse --host 0.0.0.0 --port 8000

# Streamable HTTP (MCP 2025-03-26 spec)
capsolver-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

Then configure the client with the URL:

```json
{
  "mcpServers": {
    "capsolver": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

For remote SSE via proxy (when the server is behind a network boundary):

```json
{
  "mcpServers": {
    "capsolver": {
      "command": "npx",
      "args": ["mcp-remote", "https://your-server.com/sse"]
    }
  }
}
```

---

## Available Tools

Once connected, any MCP client gets access to these 5 tools:

| Tool | Browser? | Description |
|------|----------|-------------|
| `solve_captcha` | No | Solve a captcha by type + site params (token mode) |
| `detect_captchas` | Yes | Scan a page URL and list present captcha types |
| `solve_on_page` | Yes | Detect + solve + autofill all captchas on a page |
| `get_balance` | No | Check account balance and packages |
| `get_supported_captchas` | No | List all supported captcha types and handlers |

Browser-based tools require `pip install capsolver-mcp[browser]` and `playwright install chromium`.

---

## Programmatic MCP Server

For embedding the MCP server in your own application:

```python
from capsolver_mcp.server import create_server

server = create_server(
    api_key="your-key",
    server_name="capsolver",
    host="127.0.0.1",
    port=8000,
)
server.run(transport="streamable-http")
```

---

## Troubleshooting

**"command not found: capsolver-mcp"**
Install first: `pip install capsolver-mcp` or use `uvx capsolver-mcp`.

**"CAPSOLVER_API_KEY is not set"**
Add `"env": {"CAPSOLVER_API_KEY": "CAP-XXXXXX"}` to your MCP config.

**Server connects but tools return errors**
Check your API key is valid and has balance: `capsolver balance`.

**Browser tools fail with "playwright is required"**
Install browser support: `pip install capsolver-mcp[browser]` then `playwright install chromium`.

**Windows: command fails to execute**
Use `cmd /c` wrapper:
```json
{ "command": "cmd", "args": ["/c", "capsolver-mcp"] }
```
