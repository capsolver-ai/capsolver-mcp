# Publishing

This checklist is for maintainers releasing `capsolver-mcp` from the official
open-source repository to TestPyPI and PyPI.

Release `capsolver-core` first. This package depends on `capsolver-core`.

Set the release version once before running the commands:

```powershell
$version = "0.1.2"
$package = "capsolver-mcp"
$module = "capsolver_mcp"
$command = "capsolver-mcp"
```

## Preconditions

- The public repository contains the exact code and documentation intended for
  release.
- The matching `capsolver-core` release has already passed TestPyPI testing
  before this package is tested.
- The matching `capsolver-core` release is already available on PyPI before
  this package is formally published.
- `pyproject.toml` has `version = "$version"`.
- `src/capsolver_mcp/__init__.py` exposes the same `__version__`.
- `server.json` has the same `version` in both the top-level field and the
  `packages[0].version` field.
- `server.json` targets the current `server.schema.json` revision and uses
  camelCase field names (see [MCP Registry](#mcp-registry) below).
- `CHANGELOG.md` has a release entry for `$version` with the correct date.
- The `mcp` dependency remains pinned to the MCP SDK 1.x line unless the code
  has been migrated to the 2.x API.
- `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, and `SUPPORT.md`
  are present.
- Documentation examples use placeholder credentials only.
- The tree does not contain `.venv`, `uv.lock`, caches, local path overrides,
  real API keys, browser profiles, MCP client configs with secrets, prompts,
  tool traces, or private service data.
- `git status` is clean before building release artifacts.

## Verify Locally

Run the source checks before building:

```powershell
uv run pytest
uv run ruff check src tests
uv run mypy src
```

## Build and Check

Build fresh distributions and check the package metadata:

```powershell
Remove-Item .\dist -Recurse -Force -ErrorAction SilentlyContinue
uv build

$dist = Get-ChildItem -Path .\dist\*.whl, .\dist\*.tar.gz |
  Select-Object -ExpandProperty FullName
uvx twine check $dist
```

Inspect the source distribution and wheel before upload. Confirm that no
private files, local paths, secrets, browser profiles, caches, MCP client
configs with secrets, prompts, tool traces, or test output are included.

## TestPyPI Test Release

Upload the exact checked distribution files to TestPyPI first:

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-TestPyPI-token"
uvx twine upload --repository-url https://test.pypi.org/legacy/ $dist
```

Install from TestPyPI in a clean environment and smoke-test the import path and
CLI. Use PyPI as an extra index so normal third-party dependencies can still
resolve:

```powershell
python -m pip install --no-cache-dir `
  --index-url https://test.pypi.org/simple/ `
  --extra-index-url https://pypi.org/simple/ `
  "$package==$version"

python -c "import $module; print($module.__version__)"
python -m pip show mcp
& $command --help
```

Confirm that `python -m pip show mcp` reports an MCP SDK 1.x version. PyPI and
TestPyPI distributions cannot be overwritten. If the test upload is wrong, fix
the issue and publish a new version.

## Formal PyPI Release

After TestPyPI passes and the matching `capsolver-core` release is available
from PyPI, upload the same checked distribution files to PyPI:

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-PyPI-token"
uvx twine upload --repository-url https://upload.pypi.org/legacy/ $dist
```

Then verify installation from PyPI in a clean environment:

```powershell
python -m pip install --no-cache-dir "$package==$version"
python -c "import $module; print($module.__version__)"
python -m pip show mcp
& $command --help
```

Confirm that `python -m pip show mcp` reports an MCP SDK 1.x version.

Clear token environment variables after publishing:

```powershell
Remove-Item Env:\TWINE_USERNAME -ErrorAction SilentlyContinue
Remove-Item Env:\TWINE_PASSWORD -ErrorAction SilentlyContinue
```

## Tag and GitHub Release

When the PyPI release is verified, create and push the release tag from the
official public repository:

```powershell
git tag "v$version"
git push origin main
git push origin "v$version"
```

Create a GitHub Release for `v$version` using the matching `CHANGELOG.md`
entry.

Prefer PyPI Trusted Publishing from the official public GitHub repository for
future releases. If manual upload is used, use a project-scoped PyPI API token
instead of an account password.

## MCP Registry

MCP Registry publication is **independent of PyPI releases**. The two flows
are decoupled:

| Change type | PyPI release? | Registry update? |
| --- | --- | --- |
| Code / features / bug fixes | Yes | Yes (after PyPI) |
| README or docs changes | Yes | No |
| `server.json` metadata only (description, env vars) | No | Yes |
| Dependency changes | Yes | Yes (after PyPI) |

Registry validation checks that a `mcp-name: io.github.capsolver-ai/capsolver-mcp`
line appears in the PyPI package description, which is built from `README.md`.
The marker was first added in 0.1.2 and **must be kept in `README.md` for every
future release** — removing it breaks package ownership validation on the next
registry publish.

### Prerequisites

- `server.json` exists at the repository root, targets the current schema
  revision, and uses camelCase field names. Field names moved from snake_case
  to camelCase (`registry_type` → `registryType`, `environment_variables` →
  `environmentVariables`, `website_url` → `websiteUrl`, `required` →
  `isRequired`, …) and the publisher-set `status` field was removed — the
  registry manages `status` itself. Documents using the older format are
  rejected. Check the
  [schema changelog](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/CHANGELOG.md)
  before each release and update `$schema` when a newer revision ships.
- `README.md` contains the `mcp-name:` marker matching the `name` field in
  `server.json`.
- The `mcp-publisher` CLI is installed:

  ```powershell
  $arch = if ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -eq "Arm64") { "arm64" } else { "amd64" }
  Invoke-WebRequest -Uri "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_windows_$arch.tar.gz" -OutFile "mcp-publisher.tar.gz"
  tar xf mcp-publisher.tar.gz mcp-publisher.exe
  Remove-Item mcp-publisher.tar.gz
  mcp-publisher --help
  ```

  On macOS/Linux use `brew install mcp-publisher` or the release tarball.
- The publishing account can claim the namespace. `io.github.capsolver-ai/*`
  requires authenticating as a member of the `capsolver-ai` GitHub
  organization; a permission error means the account does not own the
  namespace.
- For full releases: the new PyPI version is live (the registry validates that
  the package exists on PyPI and carries the marker).

### Authenticate

The registry JWT is short-lived. Log in again whenever `mcp-publisher publish`
reports an invalid or expired token:

```powershell
mcp-publisher login github
```

This starts a GitHub device flow and prints a URL and a one-time code.

### Full release (PyPI + Registry)

Follow the PyPI release steps above, then after verifying the PyPI upload:

1. Update `server.json` `version` (top-level and `packages[0].version`) to
   match the new PyPI version.
2. Run `mcp-publisher login github`, then `mcp-publisher publish`.
3. Verify:
   `curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.capsolver-ai/capsolver-mcp"`
4. Commit and push `server.json`.

### Registry-only update (no PyPI release)

When only `server.json` metadata changes (e.g. description, env vars):

1. Edit `server.json` — no version bump needed if the PyPI package version
   has not changed.
2. Run `mcp-publisher login github`, then `mcp-publisher publish`.
3. Commit and push `server.json`.

### Notes

- A "Registry validation failed for package" error means the ownership marker
  is missing from the published PyPI description — republish to PyPI with the
  marker in `README.md` before retrying.
- Downstream registries (GitHub MCP Registry, mcp.so, etc.) pull from the
  upstream registry automatically; no separate submission is needed.
- The official registry is still in preview. Breaking schema changes and data
  resets are possible, so re-check the schema revision and the API path before
  each release.

