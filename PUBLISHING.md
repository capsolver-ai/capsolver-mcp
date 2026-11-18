# Publish capsolver-mcp

The Python package is published to PyPI. The official MCP Registry entry
points to the core PyPI package; it does not distribute the browser companion.
Ship the Patchright tarball and source ZIP as GitHub Release assets.

1. Check that the Python version in `pyproject.toml`, the Patchright package
   and lockfile versions, and both versions in `server.json` match the release.
   Retain the same `mcp-name` marker in `docs/pypi.md` and `README.md`.
   The PyPI description in `docs/pypi.md` links the package to the Registry
   namespace. Review the corresponding changelog and upgrade guide.
2. Build wheel and sdist from a clean checkout with `python -m build`.
   Check both with `python -m twine check --strict dist/*`. Inside
   `browser-patchright`, run `npm ci --ignore-scripts`, `npm run build`,
   and `npm pack`. The companion is distributed as a tarball; it remains
   private in npm metadata.
3. Install the built wheel and tarball in fresh environments. Confirm the
   package and handshake versions, 15 core tools, 13 Python browser tools,
   and 66/79 Patchright tools. Check a keyless simulated request and, where
   an API key is available, a live balance call. Record checksums for the
   exact artifacts.
4. From an authorized publisher environment, upload the verified Python
   files to PyPI using Trusted Publishing or a project-scoped credential
   (`python -m twine upload dist/*.whl dist/*.tar.gz`). TestPyPI can be used
   for rehearsal with a separate credential. Install the exact version from
   the public index in a fresh environment and verify it before publishing
   Registry metadata. Published filenames cannot be reused.
5. On the official repository, tag the exact reviewed release commit
   (for example, `v0.2.0`). The tag runs the GitHub OIDC Registry workflow.
   It checks public PyPI before publishing the manifest and verifies the
   registered version after publication. If it fails, fix the cause and
   rerun against the same verified tag.
6. Create the GitHub Release from the matching changelog, attach the
   source ZIP, browser tarball and checksums, and verify the download links.
   Publish the official docs and site copy once all public installation
   links resolve to the released artifacts.

The Registry manifest is STDIO only. A local Streamable HTTP address is
not a public or hosted MCP endpoint.
