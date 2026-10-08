# ontic-pages

Simple HTML hosting for the Ontic Labs team. Publish a folder or one HTML file
under a name, and it is served at `https://pages.onticlabs.io/<name>/`, inside a
slim bar (title menu with the versions, Share panel), from its own host
`https://<name>.pages.onticlabs.io/`. Each page is private (only you), ontic (the
signed-in team, the default) or public (anyone with the link). Each publish is a
new version; nothing is ever deleted.

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
| `bucket` | `ONTIC_PAGES_BUCKET` | the S3-compatible bucket, default `ontic-pages` |
| `endpoint` | `ONTIC_PAGES_ENDPOINT` | its S3 endpoint, default `https://s3.eu-central-003.backblazeb2.com` |
| `region` | `ONTIC_PAGES_REGION` | its region, default `eu-central-003` |
| `prefix` | `ONTIC_PAGES_PREFIX` | key prefix, default none (pages sit at the bucket root) |
| `url` | `ONTIC_PAGES_URL` | where the gateway is (its scheme and host, the apex), default `https://pages.onticlabs.io` |
| `content_suffix` | `ONTIC_PAGES_CONTENT_SUFFIX` | pages are served from `<name>.<content_suffix>`; default the host of `url` |
| `email` | `ONTIC_PAGES_EMAIL` | who you are, recorded as `published_by`; default git `user.email`, else `$USER` |
| `access_key_id` | `AWS_ACCESS_KEY_ID` | key id |
| `secret_access_key` | `AWS_SECRET_ACCESS_KEY` | key secret |

The team uses its own private Backblaze B2 bucket, `ontic-pages`, and the defaults
point at it, so the only thing to configure is a key:

```toml
# ~/.config/ontic-pages/config.toml  (chmod 600: it holds the key)
access_key_id = "<key id>"
secret_access_key = "<application key>"
```

Without credentials in either place, boto3's usual lookup applies (`AWS_PROFILE`,
`~/.aws/credentials`).

### Keys

Two keys, both scoped to the `ontic-pages` bucket, created with the `b2` command
line (`uv tool install b2`, then `b2 account authorize` with a key that may create
keys). Neither can delete files, which matches the tool: it never deletes.

```sh
# For publishing (people and agents): read and write.
b2 key create --bucket ontic-pages ontic-pages-publish listBuckets,listFiles,readFiles,writeFiles
# For the gateway on the team box: also read and write (the Share panel writes
# <name>/visibility), so the publish key's capabilities, under its own name.
b2 key create --bucket ontic-pages ontic-pages-gateway-rw listBuckets,listFiles,readFiles,writeFiles
```

Each prints a key id and an application key once; they go into
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (or the config file above, or the
gateway's `deploy/secrets.env`).

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
ontic-pages url depth-eval           # its URL
```

Page names are lowercase letters, digits, `.` and `-`, starting and ending with
a letter or digit (each page is also a host name); `public`, `oauth2` and
`page.json` are reserved. Publishing again under the same name adds a version and
makes it current. Hidden files (`.git`, `.DS_Store`) are skipped, and a top-level
`_v` folder is refused (`/_v/<version>/` addresses versions). A page sits at the
root of its own host, so `/img/a.png` and `img/a.png` both work.

## Who can open a page

| visibility | who | URL |
|---|---|---|
| `private` | only the publisher of the current version, signed in with that Google account | `/<name>/` |
| `ontic` (default) | anyone signed in with an `@onticlabs.io` Google account | `/<name>/` |
| `public` | anyone with the link, no sign-in | `/<name>/` (old `/public/<name>/` links redirect there) |

Visibility belongs to the page, not to a version. `publish --visibility` sets it;
a later publish without the flag keeps it. `share <name> <level>`, or the Share
panel in the bar (for the page's owner), changes it.
For `private`, the publisher is matched by email, so publish with the address you
sign in with (`ONTIC_PAGES_EMAIL`, or `git config user.email`); `publish` and
`share` print who that is. The info page (`/<name>/_info`) always needs sign-in,
even for public pages.

## In the bucket

    <name>/current                 the current version id
    <name>/visibility              private, ontic or public (absent means ontic)
    <name>/<version>/page.json     the metadata
    <name>/<version>/...           the files

at the root of the `ontic-pages` bucket, or under `ONTIC_PAGES_PREFIX` when set.

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

`ontic-pages gateway` serves the bucket on two kinds of host:

- **The apex** (`pages.onticlabs.io`): `/` lists the pages you may open;
  `/<name>/<path>` is the bar around a frame showing `<path>` of the page, and
  `/<name>/_v/<version>/<path>` the same for one version; `/<name>/_info` is a plain
  page with what page.json says and every version; `/_api/pages/<name>` gives the
  page facts as JSON, and `POST /_api/pages/<name>/visibility` changes visibility
  (owner only, from the bar only).
- **The page's own host** (`<name>.pages.onticlabs.io`): `/<path>` serves the
  current version's files (content types, `index.html` for folders, Range requests
  for video, ETags and 304s), `/_v/<version>/<path>` a given version, cached for a
  year. Opened directly in a browser it redirects to the bar; `?raw=1` opens it
  without the bar.

The bar: the home link, the title menu (who published, when, the description, the
versions, Copy link, Open without the bar, Page info, All pages), an "old version"
marker, your initial (or Sign in), and Share (owner, general access, Copy link).
Escape or a click elsewhere, in the page too, closes a menu. The page fades in once
it is ready, a spinner shows only when it takes a while, and when a new version is
published while you look, it fades in where you were. The gateway adds one small
script (the bridge) to a page's HTML when it is shown in the bar, and only then;
stored files are never changed.

Sign-in is not done here: oauth2-proxy owns `/oauth2/*`, and the gateway asks it who
a request's cookie belongs to. See [deploy/README.md](deploy/README.md).

To look at pages locally, run it with your own key and tell it who you are (there is
no oauth2-proxy to say so); it then answers at `http://localhost:<port>/` with
pages at `http://<name>.localhost:<port>/` (browsers send `*.localhost` to this
machine):

```sh
ontic-pages gateway --port 8790 --local-as you@onticlabs.io
# open http://localhost:8790/
```

`--url` and `--content-suffix` set the apex and the page hosts otherwise
(`ONTIC_PAGES_URL`, `ONTIC_PAGES_CONTENT_SUFFIX`); `--cache-mb` (256) and
`--cache-file-mb` (4) size the memory cache of version files; `--auth-url` is
oauth2-proxy's `/oauth2/auth`.

## What the old `ontic pages` had that this does not

The old `ontic pages` in ontic-cli made each page a job in the provenance
store: provenance was recorded and checked, versions were chained jobs with
`rollback`, `--from` inputs were linked to jobs, and there were a Share panel,
a viewer frame, pinned comments on the page, a subdomain per page
(`<job-id>.pages.onticlabs.io`), a verified disk cache and a landing page fed
by announcements. The bar, the Share panel (three levels) and a host per page (by
name) are back; comments are not yet. `set-current` replaces rollback. That code lives on the
ontic-cli branch `main-with-pages-and-viewer`.

`scripts/migrate_old_pages.py` copies the old pages from the old jobs in `ontic-r3`
into the `ontic-pages` bucket (nothing deleted). It reads the old system, so it is
the one file here that imports ontic-cli. No key reads both buckets, so each file
is read with your signed-in ontic session and uploaded with the ontic-pages
read-write key:

```sh
# dry run: reads only, writes migration-mapping.json (keeps the names already in it)
uv run --with /path/to/cli scripts/migrate_old_pages.py --mapping migration-mapping.json

# copy, with the read-write key for ontic-pages
AWS_ACCESS_KEY_ID=<key id> AWS_SECRET_ACCESS_KEY=<application key> \
  uv run --with /path/to/cli scripts/migrate_old_pages.py --mapping migration-mapping.json --write
```

Edit the names in the mapping before `--write` if you want other names. A re-run
skips versions already copied. `--source-bucket` and `--dest-bucket` default to
`ontic-r3` and `ontic-pages`; with equal buckets it copies server side instead.

## Still to update elsewhere

The agent skill at `~/.claude/skills/ontic-pages` (a chezmoi-managed dotfile)
still describes the old `ontic pages publish`. It must be changed to
`ontic-pages publish --name <name>` in the chezmoi source.
