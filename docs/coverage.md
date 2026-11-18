# capsolver-mcp coverage

Use `list_task_types` for the 25 entries in the built-in catalog.
Use `get_task_schema(task_type)` to check exact inputs, result fields,
proxy requirements and endpoints. `get_supported_tasks` can also report
official documentation references when online. The catalog describes what
the solver can submit; the browser can prepare and apply results only when
it can read the target challenge and use an appropriate page adapter or recipe.

| Family | What to check before running |
| --- | --- |
| reCAPTCHA v2 and v3, including Enterprise | Match the exact task variant. Where a v3 workflow depends on score, action or hostname, verify these on the site backend. M1 is a separate variant. |
| Cloudflare Turnstile | Use the current site key and widget settings. |
| Cloudflare Challenge | Use the current challenge and a matching sticky proxy session. Verify that the protected page is accessible after application. |
| AWS WAF | Match the challenge parameters and proxy policy for the selected token variant. Classification is a separate task. |
| DataDome | Use the current slider challenge and matching proxy and browser identity. A cookie result alone does not establish site acceptance. Device Check has no general acceptance claim. |
| GeeTest v3 and v4 | Use fresh parameters for the selected version. |
| MTCaptcha | The proxyless path has a site acceptance record. Check the selected proxy variant separately. |
| ImageToText, visual classification and VisionEngine | Check the exact recognition module and image encoding. Output can be text, a classification, or interaction data. |
| BotDeflector token | The catalog includes `AntiBotdeflectorTaskProxyLess`. Live API and browser end-to-end verification are pending. The VisionEngine `botdeflector` module is a separate image recognition feature. |

`get_token` is limited to the eight standard and Enterprise reCAPTCHA
variants covered by the [getToken API](https://docs.capsolver.com/en/guide/api-getToken/).
Use `create_task` for other cataloged types. Start browser QA on a page you
control or have permission to test. A provider-ready result is separate from
successful result application and from the target site's decision.
