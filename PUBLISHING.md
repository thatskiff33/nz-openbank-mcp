# Publishing nz-openbank-mcp

Releases go to PyPI, npm and GitHub Releases from
`.github/workflows/release.yml`, authenticated with **Trusted Publishing**
(OIDC). No API tokens are stored.

Every host plugin under `plugin/` and the Desktop Extension
(`mcpb/manifest.json`) launch `uvx --from nz-openbank-mcp==X.Y.Z nz-openbank-mcp`,
pinned to the release version. They are generated from `plugin/plugin.base.toml`
by `scripts/sync_plugin_manifests.py`, which takes the version from
`pyproject.toml`; CI fails if a generated file is stale.

The npm package `nz-openbank-mcp` is a launcher generated the same way
(`npm/package.json`): `npx nz-openbank-mcp@X.Y.Z` runs `uvx --from
nz-openbank-mcp==X.Y.Z nz-openbank-mcp`. It has no dependencies and no
install scripts.

## One-time setup

Steps 1 to 4 are done for this repository; repeat them only if it is moved
or renamed. Step 5 is done once, on the day of the first npm release.

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
   - `npm`: the same as `pypi`, for the npm publish. A separate environment
     means a token minted for one index is never accepted by the other.
   - `testpypi`: deployment tags `v*` only; no reviewer, so dry runs are not
     blocked.

3. Tag rulesets (**Settings -> Rules -> Rulesets**), both targeting
   `refs/tags/v*`:
   - `release tags: immutable`: restrict updates and deletions, no bypass.
   - `release tags: admins create`: restrict creations, repository admins
     bypass.

4. Repository presentation (**Settings -> General -> Social preview**): upload
   `docs/assets/social-preview.png` (1280x640). GitHub has no API for this.

5. npm, by the owner of the npm account, on the day of the first npm
   release and just before approving it. `npm trust` was checked with npm
   11.16.0.

   1. `npm login`, signing in to the account that will own the package, and
      check that two-factor authentication is on for authorisation and writes.
   2. Claim the name. npm only accepts a trusted publisher for a package that
      already exists. From a folder outside this repository that holds only a
      `package.json` (name `nz-openbank-mcp`, version `0.0.0-placeholder.0`)
      and a README saying it holds no code:

      ```bash
      npm login
      npm publish --access public --tag placeholder
      npm deprecate nz-openbank-mcp@0.0.0-placeholder.0 "Placeholder with no code; use 0.1.8 or later"
      ```

   3. Add the trusted publisher, on the release day only: a new trusted
      publisher expires unless it completes a publish within 2 days (npm
      docs). If it expires, remove it (`npm trust list nz-openbank-mcp`, then
      `npm trust revoke nz-openbank-mcp --id=<id>`) and add it again. The
      environment is `npm`. Check that the listing shows `release.yml` and
      `npm` before approving the release:

      ```bash
      npm trust github nz-openbank-mcp --file release.yml --repo thatskiff33/nz-openbank-mcp --env npm --allow-publish
      npm trust list nz-openbank-mcp
      npm logout
      ```

      Or use the package's **Settings -> Trusted Publisher** page with the same
      owner, repository, workflow filename and environment.
   4. After the first release publishes from CI, sign in again: on the
      package's **Settings -> Publishing access** page, choose the option that
      requires two-factor authentication and disallows tokens (npm's docs call
      it "Require two-factor authentication and disallow tokens"). Publishing
      from CI is unaffected.
   5. Only once the first real release is on npm, remove the placeholder.
      Never do this while the placeholder is the only version: that deletes
      the package and its trusted publisher, and npm then blocks new versions
      for 24 hours. Do it within 72 hours of publishing the placeholder, while
      npm's [unpublish policy](https://docs.npmjs.com/policies/unpublish)
      allows it (no other package may depend on it):

      ```bash
      npm login
      npm dist-tag rm nz-openbank-mcp placeholder
      npm unpublish nz-openbank-mcp@0.0.0-placeholder.0
      npm logout
      ```

## Cutting a release

1. **Bump the version** in a PR:
   - `pyproject.toml` `[project] version`
   - `src/nz_openbank_mcp/__init__.py` `__version__`
   - `CHANGELOG.md`: rename `## Unreleased` to `## X.Y.Z - <date>`. The release
     build fails, even for the TestPyPI dry run, if this section is missing.
   - then regenerate every manifest and launch pin:

     ```bash
     uv run --no-project python scripts/sync_plugin_manifests.py
     ```

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

4. **Publish** from the tag. The release notes come from the
   `## X.Y.Z - <date>` section of `CHANGELOG.md`:

   ```bash
   gh workflow run release.yml --ref vX.Y.Z -f publish=true
   ```

5. **Approve the `pypi` and `npm` deployments** in the Actions run when it
   pauses; tick both environments in the one review dialog. That releases
   both `publish` (PyPI) and `publish-npm`.

Do not create the GitHub Release by hand. Releases are immutable once
published, so the workflow creates it as a draft, attaches the files and only
then publishes it.

Jobs:

- `ci-gate` requires a `v*` tag whose commit is on `main` with a successful
  `ci.yml` push run. It waits up to about 25 minutes if that run is still in
  progress. Tag the merge commit itself; a commit whose push run was skipped
  cannot be released.
- `build` asserts the pyproject version matches the tag, runs
  `scripts/check_packaging.py`, extracts the `## X.Y.Z - <date>` section of
  `CHANGELOG.md` as the release notes (failing if it is missing), then runs
  `uv build` with the hash-pinned build backend in `.github/build-constraints/`.
- `build-mcpb` packs `nz-openbank-mcp-X.Y.Z.mcpb` with a pinned
  `@anthropic-ai/mcpb`, asserts the manifest version matches the tag, and
  checks with `scripts/check_mcpb_bundle.py` that every file in the bundle
  matches `mcpb/`.
- `build-npm` packs the npm launcher, checks with
  `scripts/check_npm_tarball.py` that the tarball holds exactly the files in
  `npm/` at the tag's version, and passes the tarball's name and sha256 to
  later jobs as job outputs.
- `publish-testpypi` (dry run only, after `build` and `build-mcpb`) uploads to
  TestPyPI. `publish-npm-dry-run` (dry run only) runs the npm publish command
  with `--dry-run`, which sends nothing.
- `github-release` (publish only, after `publish` and `publish-npm`, so its
  notes never announce an npm version that failed) attests the wheel, sdist
  and `.mcpb`, creates the GitHub Release as a draft with those files and the
  changelog section as notes, then publishes it as the latest release. It is
  the only job with repository write access.
- `publish` (publish only, after `build`, `build-mcpb` and `build-npm`) waits
  for `pypi` environment approval, then publishes to PyPI. Nothing is
  published unless every build and the changelog check passed.
- `publish-npm` (publish only, after the same builds; waits for `npm`
  environment approval) checks the tarball against the
  `build-npm` sha256, waits until PyPI serves the wheel this run built (so the
  launcher never points at a missing release), then runs `npm publish
  --provenance` by trusted publishing, with the exact Node version set in
  `NPM_NODE_VERSION`. If the PyPI upload failed, it times out and nothing
  reaches npm. The npm jobs run no repository code: they only pack, check and
  publish.
- `publish-image` (publish only, after `publish`) builds the amd64 and arm64
  image from the wheel the `build` job made, after checking that its sha256
  matches the file on PyPI (the image build runs no build backend), pushes it to `ghcr.io/thatskiff33/nz-openbank-mcp` tagged `X.Y.Z`,
  `X.Y` and `latest`, and attests its provenance. The first push creates the
  package as private; set it to public once under the package's settings.
- `publish-registry` (publish only, after `publish` and `publish-npm`) verifies a pinned
  `mcp-publisher` with cosign, logs in with GitHub OIDC and publishes
  `server.json` to the [MCP Registry](https://registry.modelcontextprotocol.io).
  The registry confirms ownership through the `mcp-name:` comment in
  `README.md` for PyPI, so that line must ship in the PyPI description, and
  through `mcpName` in `npm/package.json` for npm. It retries while the new
  releases propagate.

After publishing, `uvx nz-openbank-mcp`, `pip install nz-openbank-mcp` and
`npx nz-openbank-mcp` resolve the new version, and the registry lists it under
`io.github.thatskiff33/nz-openbank-mcp`. Plugin users pick up the new pin on their next
marketplace update. Desktop users download the new `.mcpb` from
https://github.com/thatskiff33/nz-openbank-mcp/releases.

## If the npm publish fails

npm never accepts the same version twice. If `publish-npm` fails after PyPI
succeeded, fix the cause (often an expired or missing trusted publisher, see
one-time setup step 5) and re-run only the failed jobs from the same workflow
run. The re-run waits for a new `npm` approval. `publish-registry` and
`github-release` (with the `.mcpb` download) wait until npm succeeds.

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

For npm, deprecate the launcher version instead
(`npm deprecate nz-openbank-mcp@X.Y.Z "Use X.Y.(Z+1)"`); npm allows
unpublishing only under its unpublish policy.
