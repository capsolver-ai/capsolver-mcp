<!-- mcp-name: io.github.capsolver-ai/capsolver-mcp -->

# capsolver-mcp

Connect an MCP client to CapSolver for CAPTCHA solving, image recognition,
task polling, and recovery. The core server exposes 15 tools. Add a separate
browser service when you need to collect a challenge and apply the solution in
the same tab.

Install the core with Python 3.10 or later:

```sh
python -m pip install --upgrade capsolver-mcp
```

For local STDIO, configure the client to run `capsolver-mcp` and set
`CAPSOLVER_API_KEY` on the server process.
To test without a key, add `--offline`. Call `get_account_balance` after
connecting; a simulated response reports `execution_mode: offline_simulated`.

- [Client setup](https://github.com/capsolver-ai/capsolver-mcp/blob/main/docs/mcp-integration.md)
- [Supported tasks](https://github.com/capsolver-ai/capsolver-mcp/blob/main/docs/coverage.md)
- [Upgrade from 0.1.x](https://github.com/capsolver-ai/capsolver-mcp/blob/main/docs/migration.md)
- [Troubleshooting](https://github.com/capsolver-ai/capsolver-mcp/blob/main/docs/troubleshooting.md)
- [Release notes and browser companion](https://github.com/capsolver-ai/capsolver-mcp/releases/latest)
