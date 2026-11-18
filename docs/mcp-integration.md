# capsolver-mcp installation and configuration

capsolver-mcp separates the CapSolver API from browser work. Use the core
service for task discovery, solving and recognition. Add one independent browser
service if the client needs to read a challenge from a live page or apply a result.

## Install the core server

Use Python 3.10 or newer. Install the package in the Python environment used by your MCP client.

```sh
python -m pip install --upgrade capsolver-mcp
```

From the extracted release source, create a fresh environment and install it:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m capsolver_mcp --help
```

On Windows use `py -3 -m venv .venv` and
`.\.venv\Scripts\python.exe` in place of `.venv/bin/python`.
Choose a Python 3.10 or newer executable if the system default is older.

## Connect over STDIO

In a client that accepts an `mcpServers` object, use this STDIO
configuration. In your local client settings, replace `YOUR_API_KEY` with your
actual CapSolver API key.

```json
{
  "mcpServers": {
    "capsolver": {
      "command": "capsolver-mcp",
      "env": {
        "CAPSOLVER_API_KEY": "YOUR_API_KEY"
      }
    }
  }
}
```

The client passes `env.CAPSOLVER_API_KEY` to the core process at startup.
An explicit `--api-key` takes precedence over the environment value.
If the client cannot find `capsolver-mcp`, set `command` to the executable's
absolute path in your Python environment. The independent browser MCP and
offline mode require no CapSolver API key.

To launch with uvx, set `command` to `"uvx"` and `args` to `["capsolver-mcp"]`. Use
the same `env.CAPSOLVER_API_KEY` setting.

For Codex, from the source checkout on macOS or Linux:

```sh
codex mcp add capsolver-mcp \
  --env 'CAPSOLVER_API_KEY=YOUR_API_KEY' \
  -- "$PWD/.venv/bin/python" -m capsolver_mcp
codex mcp list
```

Reconnect the client and call `get_account_balance`. A live response returns
`ok: true`, `execution_mode: provider`, and a numeric `account.balance`.
With no key set, the core can still connect and list tools. Calls that access
CapSolver return `Configure CAPSOLVER_API_KEY first.`. For a simulated
connection, pass `--offline`. The balance call reports
`execution_mode: offline_simulated`.

## Choose a browser service

- **Python browser (13 tools):** install the browser extra in the same environment
  (`.venv/bin/python -m pip install '.[browser]'` from source, or
  `python -m pip install --upgrade 'capsolver-mcp[browser]'` from PyPI).
  Run `python -m playwright install chromium` with that environment's Python.
  Add a separate STDIO entry with that Python and
  `["-m", "capsolver_mcp.browser_server"]` as arguments.
- **Patchright browser (66 native tools; 79 with the workflow):** use Node.js
  22 and Google Chrome. Build from the release source with `npm ci --ignore-scripts`
  and `npm run build` inside `browser-patchright`, or install the release
  tarball into a local Node project. Configure STDIO with `node` and the
  absolute path to `dist/index.js`. To enable the CapSolver workflow, append
  `--workflow-python` and the absolute path to the installed core Python.
  Start the browser, attach the active tab with `capsolver_browser_attach`,
  and use the returned IDs for the prefixed workflow tools.

The [official Registry entry](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.capsolver-ai%2Fcapsolver-mcp/versions/latest)
describes the core PyPI STDIO package.

## Choose a tool and read the result

| Stage | Tools | Check |
| --- | --- | --- |
| Connect | `get_account_balance` (`get_balance` alias) | Account and execution mode |
| Discover | `list_task_types`, `get_supported_tasks`, `get_task_schema`, `get_task_parameters` | Exact task type, required fields, endpoint, proxy policy |
| Read references | `get_docs`, `refresh_task_catalog` | Official references when online; packaged guidance via `get_docs(topic="agent")` |
| Submit | `create_task`, or `get_token` for eligible reCAPTCHA types | Generate and save a unique `request_id` before submitting and pass it to the tool. Some recognition tasks return immediately. |
| Wait | `get_task_result`, `wait_for_result`, `get_task_result_wait` | Poll the existing `task_id` if `state: processing`; timeouts are in seconds. |
| Read returned User-Agent | `get_actual_user_agent(task_id=...)` | Exact `solution.userAgent` from an existing task of any type, or `null` when the ready response omits it. Omit `task_id` for the documented DataDome lookup. |
| Recover | `get_request_status` | Look up the original request, especially after a lost response. |

A successful provider response has `state: ready` and a `solution`. In a
browser flow, call `browser_prepare_captcha` to get the task and prepared
challenge ID, solve it on the core service, then use `browser_apply_solution`
on the original page. If CapSolver returns `solution.userAgent`, the
`analyze_and_solve` prompt requires the Agent to use that exact User-Agent
when applying or submitting the token. If the current session cannot use
it, the Agent reports the mismatch and leaves the page untouched. Verify
a site-specific success marker or business response after submission.

See [coverage](coverage.md), [migration from 0.1.x](migration.md), and the
[troubleshooting guide](troubleshooting.md).
