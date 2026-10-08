# ontic-pages: agent notes

Simple HTML hosting for the team: `ontic-pages publish|list|set-current|url|gateway`.
See README.md for what it does and deploy/README.md for how it is hosted.

## Layout

- `src/ontic_pages/config.py`: config file and environment variables.
- `src/ontic_pages/store.py`: bucket layout, the S3 calls, content types, name rules.
- `src/ontic_pages/publish.py`: collecting files, git metadata, writing a version.
- `src/ontic_pages/info.py`: the facts behind `ontic-pages info`, the gateway's `/<name>/_info` page
  and the short-name helper.
- `src/ontic_pages/gateway.py`: the HTTP server (stdlib `http.server`): routing on the apex and
  on page hosts (`<name>.<suffix>`), the API, file answers with ETags. Sign-in stays in
  oauth2-proxy.
- `src/ontic_pages/auth.py`: who is asking (the oauth2-proxy `/oauth2/auth` subrequest, or
  `--local-as`), the access rule, the write rate limit. Never read identity request headers.
- `src/ontic_pages/cache.py`: the in-memory caches (version files, page state).
- `src/ontic_pages/shell.py` and `src/ontic_pages/static/`: the bar (shell HTML, bar.js,
  bar.css) and the bridge script added to framed HTML. Static files are package data, served
  at content-hashed URLs. User text goes into the bar with textContent, never innerHTML.
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
