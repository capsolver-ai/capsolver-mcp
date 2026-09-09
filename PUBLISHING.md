# Publishing

This checklist is for maintainers releasing `capsolver-mcp` from the official
open-source repository to TestPyPI and PyPI.

Release `capsolver-core` first. This package depends on `capsolver-core`.

Set the release version once before running the commands:

```powershell
$version = "0.1.1"
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

