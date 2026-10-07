# ontic-pages: agent notes

Simple HTML hosting for the team: `ontic-pages publish|list|set-current|url|gateway`.
See README.md for what it does and deploy/README.md for how it is hosted.

## Layout

- `src/ontic_pages/config.py`: config file and environment variables.
- `src/ontic_pages/store.py`: bucket layout, the S3 calls, content types, name rules.
- `src/ontic_pages/publish.py`: collecting files, git metadata, writing a version.
- `src/ontic_pages/info.py`: the facts behind `ontic-pages info` and the gateway's `/<name>/_info` page.
- `src/ontic_pages/gateway.py`: the read-only HTTP server (stdlib `http.server`).
- `src/ontic_pages/cli.py`: argparse commands.
- `scripts/migrate_old_pages.py`: one-off copy of the old `ontic pages` jobs into this layout.
- `tests/`: pytest, against `tests/fake_s3.py` (an in-memory fake of the few boto3 calls used).
- `deploy/`: container image, Quadlet units, Caddy and oauth2-proxy config, deploy scripts.

## Rules

- Use uv for everything: `uv run pytest -q`, `uv run ruff check`, `uv add <pkg>`. Never bare python or pip.
- Never import the `ontic` package or depend on ontic-cli. This tool stands alone. The one
  exception is `scripts/migrate_old_pages.py`, a one-off bridge that reads the old system; run it
  with `uv run --with /path/to/cli scripts/migrate_old_pages.py`. Never import ontic in `src/`.
- Standard library first. The only runtime dependency is boto3; ask before adding another.
- Keep it small. Provenance is metadata in `page.json`, never checked.
- The tool never deletes anything from the bucket.
- Add or update a test for every behavior change; when you use a new boto3 call, add it to the fake.
- Never commit `deploy/secrets.env` or any credential.
- Never use em dashes in any text.
