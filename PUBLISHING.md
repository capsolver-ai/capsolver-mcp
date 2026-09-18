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
- `pyproject.toml` has `version = "$version"`. This is the single source of
  truth: `capsolver_mcp.__version__` is derived from the installed package
  metadata and must not be edited by hand.
- `server.json` has the same `version` in both the top-level field and the
  `packages[0].version` field. `tests/test_version.py` checks this against the
  installed package version, so `uv run pytest` catches drift before release.
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

Pushing a `v*` tag also triggers the MCP Registry workflow, so commit the
updated `server.json` **before** pushing the tag or the publish step fails its
version check. See [MCP Registry](#mcp-registry) below.

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

Registry publication runs from GitHub Actions, not from a local machine. The
workflow is `.github/workflows/publish-mcp-registry.yml`; it authenticates with
GitHub Actions OIDC and runs `mcp-publisher publish`. Do not publish with the
local `mcp-publisher login github` device flow — see
[Why OIDC and not a local login](#why-oidc-and-not-a-local-login) below.

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
- The workflow is present on the default branch of the official repository.
  OIDC derives the namespace from the repository owner, so the workflow must
  run in `capsolver-ai/capsolver-mcp` to claim `io.github.capsolver-ai/*`.
- GitHub Actions is enabled for the repository and the organization.
- For full releases: the new PyPI version is live (the registry validates that
  the package exists on PyPI and carries the marker).

No secrets or tokens are needed. The workflow requests `id-token: write` and
GitHub mints the OIDC token at run time.

### Full release (PyPI + Registry)

Follow the PyPI release steps above, then after verifying the PyPI upload:

1. Update `server.json` `version` (top-level and `packages[0].version`) to
   match the new PyPI version.
2. Commit and push `server.json`.
3. Push the release tag: `git push origin "v$version"`. The workflow triggers
   on `v*` tags and fails fast if the tag does not match both version fields
   in `server.json`.
4. Verify:
   `curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.capsolver-ai/capsolver-mcp"`

If the tag was already pushed before `server.json` was ready, trigger the
workflow manually instead: Actions → "Publish to MCP Registry" → Run workflow.
A tag push event is not replayed.

### Registry-only update (no PyPI release)

When only `server.json` metadata changes (e.g. description, env vars):

1. Edit `server.json` — no version bump needed if the PyPI package version
   has not changed.
2. Commit and push `server.json`.
3. Actions → "Publish to MCP Registry" → Run workflow on `main`.

### Why OIDC and not a local login

`mcp-publisher login github` grants only the personal namespace
(`io.github.<user>/*`) and never the organization namespace, so publishing
`io.github.capsolver-ai/capsolver-mcp` from a local shell fails with a 403.
This is an upstream defect, not a misconfiguration: public organization
membership, Owner role, and organization third-party access policy all make no
difference. Confirmed during the 0.1.2 release; see
[#1527](https://github.com/modelcontextprotocol/registry/issues/1527),
[#1537](https://github.com/modelcontextprotocol/registry/issues/1537), and
[#1551](https://github.com/modelcontextprotocol/registry/issues/1551).

The device flow authenticates against a private GitHub App that holds no
organization-member read permission, so the registry's org-role lookup
(`GET /user/memberships/orgs`) is rejected and the server silently degrades to
"no admin orgs". OIDC does not use that code path at all — it reads the
`repository_owner` claim from the Actions token and grants
`io.github.<owner>/*` directly.

If the local flow is ever fixed upstream, it can be used for registry-only
metadata updates. Until then, treat Actions as the only supported path.

### Notes

- A "Registry validation failed for package" error means the ownership marker
  is missing from the published PyPI description — republish to PyPI with the
  marker in `README.md` before retrying.
- Downstream registries (GitHub MCP Registry, mcp.so, etc.) pull from the
  upstream registry automatically; no separate submission is needed.
- The official registry is still in preview. Breaking schema changes and data
  resets are possible, so re-check the schema revision and the API path before
  each release.

