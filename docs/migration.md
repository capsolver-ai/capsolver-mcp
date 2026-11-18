# Upgrade from capsolver-mcp 0.1.x

1. Back up the existing MCP configuration. Record the version and keep the
   old environment available until your smoke test passes.
2. Install the latest release in a new environment with
   `python -m pip install --upgrade capsolver-mcp`. For uvx, use `capsolver-mcp`
   as the package argument and refresh the cache with `uvx --upgrade capsolver-mcp --help`.
   If your 0.1.x STDIO entry uses `command: "capsolver-mcp"` and
   `env.CAPSOLVER_API_KEY`, keep that configuration. If it uses
   `CAPSOLVER_API_KEY_FILE`, remove the old field and set
   `env.CAPSOLVER_API_KEY` to the API key itself. File paths are invalid here.
   The standalone MCP no longer requires `capsolver-core`. Other applications
   can still use their own SDK installation.
3. Remove any pilot-only `--mode compatibility` argument and
   `[compatibility]` extra. For browser features, install and register the
   [independent browser service](mcp-integration.md#choose-a-browser-service).
4. Restart the client and reopen the chat. Confirm that it discovers 15 core
   tools. Call `get_account_balance` before creating a task.

| Legacy tool | Current equivalent |
| --- | --- |
| `get_balance` | The alias remains. Read the new response at `account.balance`. |
| `get_supported_captchas` | `list_task_types` for local types, then `get_task_schema(task_type)`. |
| `solve_captcha` | Send the provider-shaped `task` to `create_task` with a stable `request_id`. If processing, use `wait_for_result` with its `task_id`. Read the answer from `solution`. |
| `detect_captchas` | In the browser service, use `browser_open`, then `browser_detect_captchas` with its `session_id` and `page_id`. |
| `solve_on_page` | Prepare with `browser_prepare_captcha`; solve on core; apply with `browser_apply_solution`; verify the resulting page. The old one-call browser flow was removed. |

Map legacy `reCaptchaV2`, `reCaptchaV3`, and `cloudflare` inputs to the
relevant task types. The legacy `cloudflare` value meant Turnstile; use
`AntiTurnstileTaskProxyLess` for that widget. Read the task schema for the
current field names (for example, `websiteURL` and `websiteKey`).

## Roll back

Restore the previous client configuration and Python environment, or restore
`uvx capsolver-mcp==0.1.3`. Reconnect and verify the old tool list before
running legacy automation. Close active browser sessions first. Keep the new
service's task metadata and IDs if any submissions are still unsettled;
do not recreate them via 0.1.3.
