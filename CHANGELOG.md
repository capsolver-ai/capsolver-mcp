# Changelog

All notable changes to this project will be documented in this file.

This project follows semantic versioning where practical. Public releases are
tagged in Git as `vX.Y.Z` and published to PyPI with the same version.

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

