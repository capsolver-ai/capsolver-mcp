# Contributing

Thank you for your interest in `capsolver-mcp`.

This repository is maintained by the CapSolver team. Issues and pull requests
are welcome when they are focused on bugs, documentation, compatibility, or
small improvements to the public MCP server surface.

## Before You Start

- Search existing issues before opening a new one.
- Open an issue before starting a large change or adding support for a new MCP
  client.
- Do not include real API keys, cookies, private URLs, MCP client configs,
  prompts, tool traces, or customer data in issues, tests, examples, or
  screenshots.
- Keep examples token-mode focused and use placeholder credentials.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src tests
uv run mypy src
```

If you do not use `uv`, install the development dependencies from
`requirements-dev.txt` and run the equivalent commands with Python.

## Pull Requests

Pull requests should include:

- A clear description of the change.
- Tests or a short explanation of why tests are not needed.
- Documentation updates for user-facing behavior.

Maintainers may close changes that are outside the public MCP server scope or
require private service-side details.

