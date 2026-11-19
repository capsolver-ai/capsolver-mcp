# Contributing

For changes to the Python MCP, use Python 3.10 or later and install the
project into a fresh virtual environment. Run `python -m pip install '.[dev]'`,
then `python -m pytest` and `python -m ruff check src tests`. Test provider-free
behavior with `capsolver-mcp --offline`.

For Patchright changes, use Node.js 22. Run `npm ci --ignore-scripts` and
`npm run build` in `browser-patchright`. Connect the built entry point over
STDIO and verify tool discovery for the affected mode.

Describe the behavior change and its verification with your pull request.
Include sanitized repro steps; omit API keys, tokens, cookies, proxy credentials,
private logs and browser profiles. See [Publishing](PUBLISHING.md) for releases.
