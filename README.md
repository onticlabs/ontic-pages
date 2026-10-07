# ontic-pages

Simple HTML hosting for the Ontic Labs team. Publish a folder or one HTML file
under a name, and it is served at `https://pages.onticlabs.io/<name>/` behind
Google sign-in. Each publish is a new version; nothing is ever deleted.

The only "provenance" is metadata: who published, when, an optional
description, any `--meta key=value` you pass (for example the hash of the model
a report shows), and the git remote, branch, commit and dirty flag of the
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
    --meta model=sha256:3f2a... --meta dataset=arctic-s01
# published depth-eval version 20261007T153000Z (12 files)
# https://pages.onticlabs.io/depth-eval/

ontic-pages list                     # every page and its current version
ontic-pages list --name depth-eval   # its versions, newest first, * marks the current one
ontic-pages set-current depth-eval 20261007T153000Z   # serve an older (or newer) version
ontic-pages url depth-eval
```

Page names are lowercase letters, digits, `.`, `_` and `-`. Publishing again
under the same name adds a version and makes it current. Hidden files (`.git`,
`.DS_Store`) are skipped. Links inside a page should be relative (`img/a.png`,
not `/img/a.png`), because the page lives under `/<name>/`.

In the bucket:

    pages/<name>/current                 the current version id
    pages/<name>/<version>/page.json     the metadata
    pages/<name>/<version>/...           the files

`page.json` holds `name`, `version`, `published_at`, `published_by` (git
`user.email`, else `$USER`), `description`, `meta`, `git` (`remote`, `branch`,
`commit`, `dirty`, or null outside a repo) and `files` (the count). It is
also served as `/<name>/page.json`, so a top-level `page.json` in your folder
is refused.

## The gateway

`ontic-pages gateway --port 8790` serves the bucket: `GET /` lists every page
(name, description, publish time, publisher), `GET /<name>/...` serves files
of the current version with the right content type, `index.html` for folders,
Range requests for video, and 404 otherwise. It does no sign-in. On the team
box it runs as a container behind oauth2-proxy (Google sign-in, `@onticlabs.io`
only) and Caddy, and only logs the `X-Forwarded-Email` header oauth2-proxy
sets. See [deploy/README.md](deploy/README.md).

To look at pages locally, run it with your own key and open
`http://127.0.0.1:8790/`:

```sh
ontic-pages gateway --port 8790
```

## What the old `ontic pages` had that this does not

The old `ontic pages` in ontic-cli made each page a job in the provenance
store: provenance was recorded and checked, versions were chained jobs with
`rollback`, pages had private, team or public visibility with a Share panel,
a viewer frame, pinned comments on the page, a subdomain per page
(`<job-id>.pages.onticlabs.io`), a verified disk cache and a landing page fed
by announcements. None of that is here. `set-current` replaces rollback. That
code lives on the ontic-cli branch `main-with-pages-and-viewer`.

## Still to update elsewhere

The agent skill at `~/.claude/skills/ontic-pages` (a chezmoi-managed dotfile)
still describes the old `ontic pages publish`. It must be changed to
`ontic-pages publish --name <name>` in the chezmoi source.
