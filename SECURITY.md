# Security Policy

## Supported Versions

Security fixes are provided for the latest public release line.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Reporting a Vulnerability

Please do not open public issues for vulnerabilities, leaked credentials, or
reports that include private target URLs, API keys, MCP client configuration,
tool traces, or customer data.

Report security issues by emailing `dev@capsolver.ai` with:

- The affected package and version.
- A concise description of the issue.
- Reproduction steps or a minimal proof of concept.
- The impact you believe the issue has.

We will acknowledge valid reports as soon as possible and coordinate a fix or
mitigation before public disclosure.

## Handling API Keys and MCP Configuration

Never commit real `CAPSOLVER_API_KEY` values, MCP client configs containing
secrets, browser profiles, cookies, or captured tokens. Documentation examples
must use placeholder values only.

