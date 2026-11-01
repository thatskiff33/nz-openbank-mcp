# Publishing nz-openbank-mcp

Releases go to PyPI and GitHub Releases from `.github/workflows/release.yml`,
authenticated with **Trusted Publishing** (OIDC). No API tokens are stored.

The Claude Code plugin (`plugin/.mcp.json`) and the Desktop Extension
(`mcpb/manifest.json`) launch `uvx --from nz-openbank-mcp==X.Y.Z nz-openbank-mcp`,
pinned to the release version. `scripts/check_packaging.py` fails CI if a pin
drifts from `pyproject.toml`.

## One-time setup

Already done for this repository; repeat only if it is moved or renamed.

1. Trusted publishers, on https://pypi.org and https://test.pypi.org
   (**Your account -> Publishing**; for an existing project, **Manage ->
   Publishing**):

   | Field             | PyPI              | TestPyPI          |
   | ----------------- | ----------------- | ----------------- |
   | PyPI Project Name | `nz-openbank-mcp` | `nz-openbank-mcp` |
   | Owner             | `thatskiff33`     | `thatskiff33`     |
   | Repository name   | `nz-openbank-mcp` | `nz-openbank-mcp` |
   | Workflow filename | `release.yml`     | `release.yml`     |
   | Environment name  | `pypi`            | `testpypi`        |

   A pending publisher does not reserve the name; the first publish to each
   index creates the project and binds the publisher.

2. GitHub environments (**Settings -> Environments**):
   - `pypi`: required reviewer (the maintainer); deployment tags `v*` only.
   - `testpypi`: deployment tags `v*` only; no reviewer, so dry runs are not
     blocked.

3. Tag rulesets (**Settings -> Rules -> Rulesets**), both targeting
   `refs/tags/v*`:
   - `release tags: immutable`: restrict updates and deletions, no bypass.
   - `release tags: admins create`: restrict creations, repository admins
     bypass.

## Cutting a release

1. **Bump the version** in a PR. These must match, and CI enforces it:
   - `pyproject.toml` `[project] version`
   - `plugin/.claude-plugin/plugin.json` `version`
   - `mcpb/manifest.json` `version`
   - the `nz-openbank-mcp==X.Y.Z` pin in `plugin/.mcp.json` and in
     `mcpb/manifest.json` `server.mcp_config.args`

   Once merged, the plugin on `main` points at a version PyPI does not have
   yet, so finish the release promptly.

2. **Tag the merge commit on `main`** and push the tag:

   ```bash
   git switch main && git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

3. **Dry run on TestPyPI** from the tag:

   ```bash
   gh workflow run release.yml --ref vX.Y.Z
   gh run watch "$(gh run list --workflow release.yml --event workflow_dispatch \
     --branch vX.Y.Z --limit 1 --json databaseId -q '.[0].databaseId')"
   ```

   Then check that the TestPyPI wheel installs and imports. Only the wheel
   comes from TestPyPI; its dependencies resolve from PyPI:

   ```bash
   uvx pip download --no-deps --index-url https://test.pypi.org/simple/ \
     -d /tmp/testpypi "nz-openbank-mcp==X.Y.Z"
   uvx --from /tmp/testpypi/nz_openbank_mcp-X.Y.Z-py3-none-any.whl \
     python -c "import nz_openbank_mcp; print(nz_openbank_mcp.__version__)"
   ```

   TestPyPI never accepts the same version twice; a failed dry run after a
   successful upload needs a new patch version.

4. **Publish the GitHub Release** for the tag:

   ```bash
   gh release create vX.Y.Z --verify-tag --generate-notes
   ```

5. **Approve the `pypi` deployment** in the Actions run when it pauses.

Jobs:

- `ci-gate` requires a `v*` tag whose commit is on `main` with a successful
  `ci.yml` push run. It waits up to about 25 minutes if that run is still in
  progress. Tag the merge commit itself; a commit whose push run was skipped
  cannot be released.
- `build` asserts the pyproject version matches the tag, runs
  `scripts/check_packaging.py`, then `uv build`.
- `publish-testpypi` (dispatch only) uploads to TestPyPI.
- `build-mcpb` packs `nz-openbank-mcp-X.Y.Z.mcpb` with a pinned
  `@anthropic-ai/mcpb`, asserts the manifest version matches the tag, and
  checks the packed manifest matches `mcpb/manifest.json`.
- `upload-assets` (release only, after `publish`) attaches the wheel, sdist and
  `.mcpb` to the GitHub Release. It is the only job with repository write access.
- `publish` (release only) waits for `pypi` environment approval, then
  publishes to PyPI.

After publishing, `uvx nz-openbank-mcp` and `pip install nz-openbank-mcp`
resolve the new version. Plugin users pick up the new pin on their next
marketplace update. Desktop users download the new `.mcpb` from
https://github.com/thatskiff33/nz-openbank-mcp/releases.

## Manual publish (fallback)

Use only if Trusted Publishing is unavailable:

```bash
rm -rf dist/
uv build
uv publish  # reads UV_PUBLISH_TOKEN
```

Create a project-scoped token at https://pypi.org/manage/account/token/, use it
once, and delete it afterwards.

## Version policy

Semver. Until 1.0:

- `0.x.y` -> `0.x.(y+1)` for bug fixes and additive changes
- `0.x.y` -> `0.(x+1).0` for breaking changes (tool removals, tool signature
  changes, environment-variable renames, safety-default flips)

Document every breaking change in the GitHub release notes.

## Yanking a bad release

On https://pypi.org/manage/project/nz-openbank-mcp/releases/, open the release's
**Options -> Yank** and give a reason such as "Broken refresh handling, use
X.Y.(Z+1)".

Yanking hides the version from new installs but does not remove it; pinned
installs, including the plugin and Desktop Extension pins, still resolve.
Follow up with a patched release and bump the pins.
