# ontic-pages

Simple HTML hosting for the Ontic Labs team. Publish a folder or one HTML file
under a name, and it is served at `https://pages.onticlabs.io/<name>/`. Each page
is private (only you), ontic (the signed-in team, the default) or public (anyone
with the link). Each publish is a new version; nothing is ever deleted.

The only "provenance" is metadata: who published, when, an optional
description, any `--meta key=value` you pass (for example `model=sha256:...`), and
the git remote, branch, commit and dirty flag of the
directory you publish from. Nothing is checked against anything.

It does not depend on ontic-cli.

## Install

```sh
uv tool install 'ontic-pages @ git+https://github.com/onticlabs/ontic-pages'
```

## Configure

Set environment variables, or put the same values in `~/.config/ontic-pages/config.toml`
(environment variables win):

| config.toml key | environment variable | meaning |
|---|---|---|
| `bucket` | `ONTIC_PAGES_BUCKET` | the S3-compatible bucket |
| `endpoint` | `ONTIC_PAGES_ENDPOINT` | its S3 endpoint URL |
| `region` | `ONTIC_PAGES_REGION` | its region |
| `prefix` | `ONTIC_PAGES_PREFIX` | key prefix, default `pages/` |
| `url` | `ONTIC_PAGES_URL` | where the gateway is, default `https://pages.onticlabs.io` |
| `email` | `ONTIC_PAGES_EMAIL` | who you are, recorded as `published_by`; default git `user.email`, else `$USER` |
| `access_key_id` | `AWS_ACCESS_KEY_ID` | key id |
| `secret_access_key` | `AWS_SECRET_ACCESS_KEY` | key secret |

The team uses Backblaze B2, the same bucket the old `ontic pages` used:

```toml
# ~/.config/ontic-pages/config.toml  (chmod 600 if it holds the key)
bucket = "ontic-r3"
endpoint = "https://s3.eu-central-003.backblazeb2.com"
region = "eu-central-003"
access_key_id = "..."
secret_access_key = "..."
```

Without credentials in either place, boto3's usual lookup applies (`AWS_PROFILE`,
`~/.aws/credentials`). Publishing needs a key that can read, list and write
under `pages/`. It does not need delete rights.

## Use

```sh
# Publish a folder (it should have an index.html) or one .html file (served as index.html).
ontic-pages publish ./report --name depth-eval --description "Depth eval, Oct 7" \
    --meta model=sha256:9f1c... --meta dataset=point-clouds-arctic --visibility ontic
# published depth-eval version 20261007T153000Z (12 files)
# https://pages.onticlabs.io/depth-eval/

ontic-pages list                     # every page, its visibility and current version
ontic-pages list --name depth-eval   # its versions, newest first, * marks the current one
ontic-pages info depth-eval          # everything page.json says, plus the versions
ontic-pages set-current depth-eval 20261007T153000Z   # serve an older (or newer) version
ontic-pages share depth-eval public  # private, ontic or public
ontic-pages url depth-eval           # the /public/ URL for public pages
```

Page names are lowercase letters, digits, `.`, `_` and `-`, and `public` is
reserved. Publishing again
under the same name adds a version and makes it current. Hidden files (`.git`,
`.DS_Store`) are skipped. Links inside a page should be relative (`img/a.png`,
not `/img/a.png`), because the page lives under `/<name>/`.

## Who can open a page

| visibility | who | URL |
|---|---|---|
| `private` | only the publisher of the current version, signed in with that Google account | `/<name>/` |
| `ontic` (default) | anyone signed in with an `@onticlabs.io` Google account | `/<name>/` |
| `public` | anyone with the link, no sign-in | `/public/<name>/` (and `/<name>/` when signed in) |

Visibility belongs to the page, not to a version. `publish --visibility` sets it;
a later publish without the flag keeps it. `share <name> <level>` changes it.
For `private`, the publisher is matched by email, so publish with the address you
sign in with (`ONTIC_PAGES_EMAIL`, or `git config user.email`); `publish` and
`share` print who that is. The info page (`/<name>/_info`) always needs sign-in,
even for public pages.

## In the bucket

    pages/<name>/current                 the current version id
    pages/<name>/visibility              private, ontic or public (absent means ontic)
    pages/<name>/<version>/page.json     the metadata
    pages/<name>/<version>/...           the files

### page.json

| field | what it is |
|---|---|
| `name` | the page name |
| `version` | the version id, a UTC timestamp like `20261007T153000Z` |
| `published_at` | the same time in ISO 8601 |
| `published_by` | `ONTIC_PAGES_EMAIL`, else git `user.email`, else `$USER` |
| `description` | from `--description`, may be empty |
| `meta` | map of strings from `--meta key=value` |
| `git` | `{remote, branch, commit, dirty}` of the directory you published from, or null outside a git repo |
| `files` | how many files the version has |

`page.json` is also served as `/<name>/page.json`, and the gateway answers
`/<name>/_info`, so a top-level `page.json` or `_info` in your folder is refused.

## The gateway

`ontic-pages gateway --port 8790` serves the bucket: `GET /` lists the pages you
may open (name, visibility badge, description, publish time, publisher, a link to
its info page; long names and descriptions are cut, the full text shows on hover),
`GET /<name>/...` serves files of the current version with the right content
type, `index.html` for folders, Range requests for video, and 404 otherwise.
`GET /<name>/_info` is a plain HTML page with what page.json says (visibility,
metadata, git remote and commit linked to GitHub) and every version, the
current one marked. `GET /public/<name>/...` serves public pages without
sign-in. The gateway does no sign-in itself: on the team box Caddy sends
`/public/*` straight to it and everything else through oauth2-proxy (Google
sign-in, `@onticlabs.io` only), and the gateway decides from the
`X-Forwarded-Email` header oauth2-proxy sets. See [deploy/README.md](deploy/README.md).

To look at pages locally, run it with your own key, tell it who you are (there is
no oauth2-proxy to say so), and open `http://127.0.0.1:8790/`:

```sh
ontic-pages gateway --port 8790 --local-as you@onticlabs.io
```

## What the old `ontic pages` had that this does not

The old `ontic pages` in ontic-cli made each page a job in the provenance
store: provenance was recorded and checked, versions were chained jobs with
`rollback`, `--from` inputs were linked to jobs, and there were a Share panel,
a viewer frame, pinned comments on the page, a subdomain per page
(`<job-id>.pages.onticlabs.io`), a verified disk cache and a landing page fed
by announcements. None of that is here. `set-current` replaces rollback, and
`share` with three levels replaces the Share panel. That code lives on the
ontic-cli branch `main-with-pages-and-viewer`.

`scripts/migrate_old_pages.py` copies the old pages into this layout (server-side
copies, nothing deleted). It reads the old system, so it is the one file here that
imports ontic-cli:

```sh
uv run --with /path/to/cli scripts/migrate_old_pages.py --mapping migration-mapping.json          # dry run
uv run --with /path/to/cli scripts/migrate_old_pages.py --mapping migration-mapping.json --write  # copy
```

The dry run writes nothing to the bucket. Edit the names in the mapping before `--write`
if you want other names.

## Still to update elsewhere

The agent skill at `~/.claude/skills/ontic-pages` (a chezmoi-managed dotfile)
still describes the old `ontic pages publish`. It must be changed to
`ontic-pages publish --name <name>` in the chezmoi source.
