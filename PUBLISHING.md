# Publishing

Release target: `capsolver-mcp` version `0.1.0`, prepared for public release on
2026-09-01.

This checklist is for maintainers syncing the prepared public files to the
official open-source repository, testing the package on TestPyPI, and then
publishing the final package to PyPI.

Publish `capsolver-core==0.1.0` first. This package depends on
`capsolver-core>=0.1.0`.

## Preconditions

- The source is the prepared public copy, not a private development checkout.
- `capsolver-core==0.1.0` has already passed TestPyPI testing before this
  package is tested.
- `capsolver-core==0.1.0` is already available on PyPI before this package is
  formally published.
- `pyproject.toml` has `version = "0.1.0"`.
- `CHANGELOG.md` has `## [0.1.0] - 2026-09-01`.
- `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, and `SUPPORT.md`
  are present.
- Documentation examples use placeholder credentials only.
- The tree does not contain `.git`, `.venv`, `uv.lock`, caches, local path
  overrides, real API keys, browser profiles, MCP client configs with secrets,
  prompts, tool traces, or private service data.

## Sync to the Official Open-Source Repository

Copy this directory into the official `capsolver-mcp` public repository working
tree, then review the diff before committing.

```bash
git status
git diff
git add .
git commit -m "Release v0.1.0"
git status
```

Do not tag until the build, TestPyPI upload, and install test have passed.

## Verify Locally

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src tests
uv run mypy src
```

## Build and Check

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

Inspect the source distribution and wheel before upload. Confirm that no
private files, local paths, secrets, browser profiles, caches, MCP client
configs with secrets, prompts, tool traces, or test output are included.

## TestPyPI Test Release

Upload the exact distribution files to TestPyPI first.

```bash
python -m twine upload --repository testpypi dist/*
```

Install from TestPyPI in a clean environment and smoke-test the CLI import path.
Use PyPI as an extra index so normal third-party dependencies can still resolve.

```bash
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ capsolver-mcp==0.1.0
python -c "import capsolver_mcp; print(capsolver_mcp.__version__)"
capsolver-mcp --help
```

PyPI and TestPyPI distributions cannot be overwritten. If the test upload is
wrong, fix the issue and publish a new version.

## Formal PyPI Release

After TestPyPI passes and `capsolver-core==0.1.0` is available from PyPI, upload
the same checked distribution files to PyPI.

```bash
python -m twine upload dist/*
```

Then verify installation from PyPI.

```bash
python -m pip install capsolver-mcp==0.1.0
python -c "import capsolver_mcp; print(capsolver_mcp.__version__)"
capsolver-mcp --help
```

## Tag and GitHub Release

When the PyPI release is verified, create the release tag and push it from the
official public repository.

```bash
git tag v0.1.0
git push origin main
git push origin v0.1.0
```

Create a GitHub Release for `v0.1.0` using the `CHANGELOG.md` entry.

Prefer PyPI Trusted Publishing from the official public GitHub repository for
future releases. If manual upload is used, use a project-scoped PyPI API token
instead of an account password.

