# capsolver-mcp troubleshooting

Find the stage where the problem starts.

- [Installation and tool discovery](#installation-and-tool-discovery)
- [API key and balance](#api-key-and-balance)
- [Task validation and provider errors](#task-validation-and-provider-errors)
- [Timeout or interrupted submission](#timeout-or-interrupted-submission)
- [Browser application and website verification](#browser-application-and-website-verification)

## Installation and tool discovery

| What you see | How to fix it | Confirm the fix |
| --- | --- | --- |
| `uvx: command not found`, Python not found, or `No module named capsolver_mcp` | Check the executable in the client's environment. Use its absolute path if the desktop client has a different PATH. For a local install, install the package with the same Python used to launch it. Use Python 3.10 or newer. | Run the configured command with `--help`, then reconnect. |
| STDIO handshake fails or the process exits | Check the client's JSON or TOML, the `command` and `args`, and the first error on stderr. A STDIO server may wait quietly for the client to initialize. | The client detects the core server and lists 15 tools. |
| Only five tools appear | Check for a 0.1.x installation or a duplicate server entry at another configuration scope. Point the client at the updated environment and open a new session. | Check for `get_task_schema` and `get_request_status`. |
| Core tools appear but the browser tools are missing | Register the browser service as a separate MCP entry. Install Playwright Chromium with the same Python as the browser server. For Patchright, check the built `dist/index.js`, Chrome, and the `--workflow-python` argument if you need the workflow tools. | Discover 13 Python browser tools or 66 native Patchright tools (79 with the workflow bridge). |

## API key and balance

A core server can connect over MCP before it has a usable CapSolver account
key. Call `get_account_balance` first. A missing key produces this response.

```json
{
  "ok": false,
  "state": "error",
  "error": {
    "code": "INVALID_PARAMETERS",
    "message": "Configure CAPSOLVER_API_KEY first."
  }
}
```

1. Set `CAPSOLVER_API_KEY` in the core service environment.
2. For live operation, remove `--offline` from the startup arguments and clear
   `CAPSOLVER_OFFLINE=1` if present. Restart the client and call
   `get_account_balance` again. Expect `ok: true`, `execution_mode: provider`,
   and a numeric `account.balance`.
3. To check the installation without a key, start with `--offline`.
   A successful check reports `execution_mode: offline_simulated`.

| What you see | What to check |
| --- | --- |
| `ERROR_KEY_DENIED_ACCESS` or provider `http_status: 401` | Check the key configured on the core process and restart it. |
| `ERROR_ZERO_BALANCE` or `ERROR_SETTLEMENT_FAILED` | Check the account balance and billing before creating another task. A balance call can connect successfully even with zero credit. |

## Task validation and provider errors

| What you see | How to fix it |
| --- | --- |
| `INVALID_PARAMETERS`, `ERROR_INVALID_TASK_DATA` or `ERROR_TASK_NOT_SUPPORTED` | Call `get_task_schema` with the exact task type, then check required fields, endpoint and proxy policy. Use `create_task` for types outside the `get_token` list. |
| `ERROR_INVALID_IMAGE` or `ERROR_PARSE_IMAGE_FAIL` | Check the input field and module in the task schema. Supply the required base64 image bytes, without a filesystem path or data URI prefix. |
| `ERROR_CAPTCHA_UNSOLVABLE` or a solver failure reason | Check the challenge inputs and preserve the error code, task ID and any `error.provider_subcode`. If a fresh challenge is needed, collect it from the target page before deciding whether to submit a new task. |
| `ERROR_RATE_LIMIT` | Reduce polling or submission frequency. Keep the original task ID and respect the returned `retry_after` when present. |
| `get_docs` cannot load an online page | Check access from the core process and use a supported official documentation URL. For offline guidance, omit `url` and call `get_docs` with `topic: "agent"`, or use `get_task_schema`. |

See the [CapSolver API error reference](https://docs.capsolver.com/en/guide/api-error/)
for the full provider error list.

## Timeout or interrupted submission

Generate and save a unique `request_id` before each submission. Pass it to `create_task` or `get_token`. Within the same account and operator, the same ID and identical parameters return the existing record. Changing parameters with that ID produces an error.

In live mode, request metadata stays in local SQLite across restarts when you reuse the same state directory, API key, and operator. Records have no automatic expiry. Provider result queries are limited to five minutes from submission and at most 120 queries. Solutions are cached in memory. A synchronous solution can become unavailable after restart or cache eviction. Simulation records are kept in memory and are cleared on restart.

| State or error | Next call or action |
| --- | --- |
| Missing response, `acceptance_unknown`, or `NOT_FOUND` | Call `get_request_status` with the saved `request_id`. If it returns a processing task, use that task ID. For `NOT_FOUND`, verify the request ID, state directory, API key, and operator. If the outcome remains uncertain, keep the ID and contact support before resubmitting. A new ID can create a second paid task. |
| `WAIT_TIMEOUT` with a task ID | Call `wait_for_result` again for the same task ID while the task remains queryable. A wait timeout does not cancel the task. |
| `TASK_EXPIRED` or `QUERY_LIMIT_REACHED` | Check the original request status. The service has reached its time or query limit for that result. |
| `RESULT_NOT_CACHED` | A solution can leave the memory cache after eviction or restart. For an asynchronous task, try `get_task_result` with the existing task ID while it remains queryable. |

Example tool arguments for recovery. Replace the placeholder with your saved ID.

```json
{"request_id": "your-original-request-id"}
```

## Browser application and website verification

1. For `STALE_CHALLENGE` or an expired prepared challenge, reacquire the
   challenge with `browser_prepare_captcha`. Keep the same tab and use the
   new challenge's parameters and ID for the new solve and application.
2. If the task requires a proxy, check its scheme, credentials, reachability
   and task format. Keep the browser session, proxy and User-Agent aligned
   when the task requires them. Check `get_task_schema` for that exact type.
3. If a ready result includes `solution.userAgent` that the current browser
   session cannot use, the Agent prompt directs the Agent to report the
   mismatch and leave the page untouched. To check the returned value,
   call `get_actual_user_agent(task_id=...)` for the original task. A ready
   result without a returned User-Agent yields `null`.
4. If `browser_apply_solution` returns `APPLICATION_RECIPE_REQUIRED`, check the
   application steps for the selected CAPTCHA. When `applied: true` but
   `verified: false`, check the site's own success marker or business response.
   If you supplied a verification condition, confirm it describes the result
   of the current action. `state: ready` means the provider returned a result.
   Use the site response to determine whether it was accepted.

For a support request, include the MCP and client versions, transport, failed
tool, error code, and task or request ID if available. Remove API keys, HTTP
tokens, cookies, proxy credentials and private page data from screenshots or logs.

[Back to installation and configuration](mcp-integration.md)
