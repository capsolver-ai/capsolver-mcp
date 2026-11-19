# Changelog

## [0.2.0]

- Split solving and browser operations into independent MCP services. The core
  offers 15 tools for schemas, documentation, provider calls, and recovery.
- Add the optional Python browser service with 13 tools. The Patchright
  companion offers 66 native tools, or 79 with the same-tab workflow enabled.
- Keep `CAPSOLVER_API_KEY` as the API key setting for upgrading clients.
- Add a keyless offline mode, synchronous reCAPTCHA token requests, task
  polling, and request status. An unknown submission is not retried automatically.
- Keep browser preparation, result application, and website acceptance
  separately observable. Support original response capture and browser context
  HTTP requests.
- Remove the legacy integrated browser tools and the `capsolver-core` runtime
  dependency. See the [upgrade guide](docs/migration.md) for replacements.

## [0.1.3] - 2026-09-18

### Added

- GitHub Actions workflow that publishes `server.json` to the MCP Registry
  using Actions OIDC, triggered by `v*` tags or manual dispatch.
- `tests/test_version.py`, which checks that `server.json` agrees with the
  package version and that the `mcp-name:` registry marker is still in
  `README.md`.

### Changed

- `capsolver_mcp.__version__` is now read from the installed package metadata
  instead of being hard-coded, making `pyproject.toml` the single source of
  truth for the release version.

### Documentation

- Rewrote the MCP Registry section of `PUBLISHING.md` around the Actions
  workflow. The local `mcp-publisher login github` device flow cannot claim the
  organization namespace, so it is no longer part of the release process.
- Noted the official MCP Registry listing in `README.md`.

## [0.1.2] - 2026-09-17

### Added

- Added `server.json` for MCP Registry publication (name, version, packages,
  transport).
- Added `mcp-name: io.github.capsolver-ai/capsolver-mcp` marker to README for
  registry validation.
- Added MCP Registry publishing steps to `PUBLISHING.md`.

## [0.1.1] - 2026-09-09

### Documentation

- Updated the publishing checklist for repeatable PyPI and TestPyPI releases.
- Replaced hard-coded release examples with version variables to reduce manual
  update errors.
- Clarified clean-environment install checks, including MCP SDK 1.x verification.

## [0.1.0] - 2026-09-01

### Added

- Initial public release of `capsolver-mcp`.
- MCP server exposing CapSolver captcha-solving tools.
- Support for stdio, SSE, and streamable HTTP transports.
- Optional browser-based tools behind the `browser` extra.
- Client configuration guide for Claude Desktop, Claude Code, Cursor,
  Windsurf, Cline, and remote HTTP clients.
- `capsolver-mcp` CLI entry point.

