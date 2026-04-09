# Build + Publish

## Scaffold a new path

Use `init` before any of the `--path`-based path commands:

```bash
poetry run wayfinder path init my-path --kind monitor --applet --dir examples/paths
```

This creates `examples/paths/my-path/`.

Important:
- `path init` uses `--dir` for the base directory, not `--path`.
- The path slug is the last path segment that gets created under `--dir`.
- After scaffolding, change into the new path directory and use `--path .` for the rest of the workflow.

## Build a bundle

From your path directory (must contain `wfpath.yaml`):

```bash
poetry run wayfinder path fmt --path .
poetry run wayfinder path doctor --check --path .
poetry run wayfinder path render-skill --path .
poetry run wayfinder path build --path . --out dist/bundle.zip
```

Output includes the bundle sha256 and writes the zip to `--out`.

Notes:
- `build` and `publish` automatically rerun path validation and skill rendering before packaging.
- Generated skill exports are written under `.build/skills/...` and are not included in `bundle.zip`.
- `poetry run wayfinder path preview --check --path .` validates applet preview readiness without starting servers.

## Configure Paths API base URL

The CLI publishes to a Paths API base URL (no trailing `/api`).

Set one of:

- `config.json` → `system.paths_api_base_url`
- or env var: `WAYFINDER_PATHS_API_URL`

Example for local dev:

```bash
export WAYFINDER_PATHS_API_URL="http://localhost:8000"
```

## Publish

```bash
poetry run wayfinder path publish --path . --owner-wallet 0xYourWallet
```

Notes:
- Publishing requires a valid `WAYFINDER_API_KEY` (or `config.json` → `system.api_key`).
- `--owner-wallet` must match a wallet associated with your account (how ownership is enforced will evolve).

## Git hooks

Install path-focused pre-commit hooks into the current path directory:

```bash
poetry run wayfinder path hooks install --path .
```

That writes `.pre-commit-config.yaml` with:
- `wayfinder path fmt --path .`
- `wayfinder path doctor --check --path .`
- `wayfinder path preview --check --path .` on `pre-push`
