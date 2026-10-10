# ontic-pages

Simple HTML hosting for the Ontic Labs team. Publish a folder or one HTML file
under a name, and it is served at `https://pages.onticlabs.io/<name>/`, inside a
slim bar (title menu with the versions, comments, Share panel), from its own host
`https://<name>.pages.onticlabs.io/`. Each page is private (only you), ontic (the
signed-in team, the default) or public (anyone with the link). Each publish is a
new version; nothing is ever deleted. The owner can also fix text right on the
page in the browser (no Edit button: it is always on for them); Save writes that as a new
version too.

The only "provenance" is metadata: who published, when, an optional
description, any `--meta key=value` you pass (for example `model=sha256:...`), and
the git remote, branch, commit and dirty flag of the
directory you publish from. Nothing is checked against anything.

It does not depend on ontic-cli.

## Install

It comes with the ontic CLI as `ontic pages` (the same command as `ontic-pages`):

```sh
uv tool install --force git+https://github.com/onticlabs/cli
ontic pages login     # once a month: sign in with Google in the browser
```

On its own: `uv tool install 'ontic-pages @ git+https://github.com/onticlabs/ontic-pages'`.

Nobody needs a bucket key. The command line talks to the gateway at
`https://pages.onticlabs.io`, signed in as you; the gateway alone holds the bucket key (write,
never delete). File bytes go straight from your machine to the bucket with short-lived upload
URLs the gateway hands out, so they never pass through the server.

## Sign in

```sh
ontic-pages login     # opens https://pages.onticlabs.io/_cli/login?code=...
# Check that the browser shows the code ending in ab3F, then click Allow.
# signed in as you@onticlabs.io (for 30 days; the token is in ~/.config/ontic-pages/token)
ontic-pages whoami    # you@onticlabs.io
ontic-pages logout    # forget the token on this machine
```

`login` makes a random code, opens the login page in your browser (signed in with your
`@onticlabs.io` Google account like every page) and waits up to 5 minutes. The page shows who
you are and the last four characters of the code; Allow only if they match what your terminal
printed. The terminal then gets a token for 30 days, kept in `~/.config/ontic-pages/token`
(mode 600). On a machine without a browser, open the printed link on the same machine yourself.
When the token expires, any command says `run ontic-pages login`.

## Use

```sh
# Publish a folder (it should have an index.html) or one .html file (served as index.html).
ontic-pages publish ./report --name depth-eval --description "Depth eval, Oct 7" \
    --meta model=sha256:9f1c... --meta dataset=point-clouds-arctic --visibility ontic
# uploading 12/12 files, 3.4/3.4 MB
# published depth-eval version 20261007T153000Z (12 files)
# https://pages.onticlabs.io/depth-eval/

ontic-pages list                     # the pages you may open, their visibility and current version
ontic-pages list --name depth-eval   # its versions, newest first, * marks the current one
ontic-pages info depth-eval          # everything page.json says, plus the versions
ontic-pages set-current depth-eval 20261007T153000Z   # serve an older (or newer) version
ontic-pages share depth-eval public  # private, ontic or public
ontic-pages url depth-eval           # its URL
ontic-pages pull depth-eval ./current   # download the current version (--version for another)
```

### Comments

Signed-in viewers comment on a page in the bar: each thread is attached to an element of the
page (a paragraph, a heading, a figure, a table cell), with replies, resolve and reopen. The command line reads and answers them, so an agent can work through the feedback
before it publishes the next version:

```sh
ontic-pages comments depth-eval          # the open threads: short id, where, every comment
ontic-pages comments depth-eval --all    # resolved ones too (--json: everything as JSON)
ontic-pages comment depth-eval 3f9a1c "Fixed in the new version"   # reply; - reads stdin
ontic-pages resolve depth-eval 3f9a1c    # or --reopen
```

A thread id may be shortened to its first characters (at least 4) while it stays unique. Anyone
who may open a page and is signed in may read and add comments; signed out, even on a public
page, there are none. Only its author deletes a comment, and it stays as "deleted". Comments
always go through the gateway (never `--direct`); when the gateway says too many changes (20 a
minute), these commands wait and try again.

Anyone with an `@onticlabs.io` account may create a page; only its owner (the publisher of the
current version) may publish a new version of it, `share` it or `set-current`. A publish uploads
up to 8 files at a time (each retried twice), at most 5000 files and 5 GB per version; nothing
becomes visible until every file is in the bucket with the size announced.

`pull` writes every file of a version but `page.json` into a new or empty folder (default
`./<name>`), downloaded straight from the bucket with short-lived URLs the gateway hands out. Use
it to see what is published now, for example after someone fixed text in the browser.

### Edit text in place

The owner of a page, looking at its current version in the bar, can fix its text right there:
there is no Edit button, editing is always on for them. Every element that holds nothing but
text (paragraphs, headings, list items, table cells, captions, ...) can be clicked into and typed
over, with a text cursor and a light outline only while the pointer or the focus is on it.
Interactive elements are never editable, nor anything inside them (links, buttons, `summary`,
labels, form fields, elements with a `role` such as button or link, `onclick`, a `tabindex` (a
container's `tabindex="-1"` aside), a pointer cursor, or the page's own `contenteditable`), so
links, buttons and app controls work as usual. A text counts as changed only once someone typed in it, so text the page's own scripts
update is never counted. Non-owners, and older versions, get nothing editable.

The bar shows nothing about editing until a text changed; then "N changes", Save and Discard
(its tooltip: "Text only. Saved as a new version; older versions stay in the title menu.").
Discard asks first, in the bar. Cmd+S or Ctrl+S, in the page or the bar, saves; Escape in an
edited text leaves it. Closing or reloading the tab with unsaved changes asks first. Comment mode
pauses editing (a click makes a comment) and leaving it resumes. Save writes a new version and
the page fades over to it; while there are unsaved changes, a version published meanwhile waits
until they are saved or discarded.

The gateway finds each changed text in the HTML file's source (its text only, not tags, scripts,
styles or the title; as written or with `&amp;`-style references) and replaces just the changed
part, escaped. Each text must be there exactly once (a text that fills a whole element wins over
the same words inside a longer one); if any change cannot be placed (written by a script, or
there several times), nothing is saved and the bar says which. A save on a version that is no
longer current (published meanwhile) is refused: reload and edit again. The new version copies
every other file inside the bucket (server side), has the edited HTML file, and a `page.json`
with you as `published_by`, the old description, git and meta, plus `edited_from=<the version
you edited>` in meta. So before publishing a page again from its source, check
`ontic-pages info <name>` for `edited_from` and carry those edits over (`pull` it and compare).

### Without the gateway: `--direct`

Admins with a bucket key can skip the gateway: `publish`, `list`, `info`, `pull`, `share` and
`set-current` take `--direct` (or set `ONTIC_PAGES_DIRECT=1`) and then read and write the bucket
with your own key. `published_by` is then `ONTIC_PAGES_EMAIL`, else git `user.email`, and the
owner rules above are not checked. The key goes in the config below.

## Agent skill

`ontic-pages` installs its own skill for Claude Code and Codex, so agents know how to write and
publish a page. Every command except `gateway` and `skill` copies it to
`<CLAUDE_CONFIG_DIR or ~/.claude>/skills/ontic-pages/SKILL.md` and
`<CODEX_HOME or ~/.codex>/skills/ontic-pages/SKILL.md`, but only where that agent folder already
exists (it is never created). Reinstalling the tool runs no code, so this keeps the skill current
after an update. It prints one line to stderr on a first install and nothing otherwise.

The installed copy has a marker line (an HTML comment) after the frontmatter. A copy with the
marker is rewritten whenever it differs from the bundled text; delete the marker line to keep
your own edits. A copy without it, or a symlinked `SKILL.md`, is left alone.
`ONTIC_AGENT_SKILLS=0` turns the sync off.

```sh
ontic-pages skill             # where it is installed and whether it is current
ontic-pages skill --install   # write ours, also over your own copy (never over a symlink)
ontic-pages skill --print     # the bundled text
```

The text lives in `src/ontic_pages/skills/ontic-pages/SKILL.md`.

## Configure

Set environment variables, or put the same values in `~/.config/ontic-pages/config.toml`
(environment variables win). Only `url` matters for the default mode; the rest is for
`--direct` and for running the gateway.

| config.toml key | environment variable | meaning |
|---|---|---|
| `url` | `ONTIC_PAGES_URL` | where the gateway is (its scheme and host, the apex), default `https://pages.onticlabs.io` |
| `direct` | `ONTIC_PAGES_DIRECT` | `1`: use your own bucket key, not the gateway |
| `bucket` | `ONTIC_PAGES_BUCKET` | the S3-compatible bucket, default `ontic-pages` |
| `endpoint` | `ONTIC_PAGES_ENDPOINT` | its S3 endpoint, default `https://s3.eu-central-003.backblazeb2.com` |
| `region` | `ONTIC_PAGES_REGION` | its region, default `eu-central-003` |
| `prefix` | `ONTIC_PAGES_PREFIX` | key prefix, default none (pages sit at the bucket root) |
| `content_suffix` | `ONTIC_PAGES_CONTENT_SUFFIX` | pages are served from `<name>.<content_suffix>`; default the host of `url` |
| `email` | `ONTIC_PAGES_EMAIL` | `--direct` only: recorded as `published_by`; default git `user.email`, else `$USER` |
| `access_key_id` | `AWS_ACCESS_KEY_ID` | key id (`--direct`, the gateway) |
| `secret_access_key` | `AWS_SECRET_ACCESS_KEY` | key secret (`--direct`, the gateway) |
| `token_secret` | `ONTIC_PAGES_TOKEN_SECRET` | the gateway only: signs the command line's tokens |

```toml
# ~/.config/ontic-pages/config.toml  (chmod 600 when it holds a key)
access_key_id = "<key id>"
secret_access_key = "<application key>"
```

Without credentials in either place, boto3's usual lookup applies (`AWS_PROFILE`,
`~/.aws/credentials`).

### Keys

Keys are scoped to the `ontic-pages` bucket, created with the `b2` command line
(`uv tool install b2`, then `b2 account authorize` with a key that may create keys). None can
delete files, which matches the tool: it never deletes.

```sh
# For the gateway on the team box: read and write (page.json, current, visibility, and the
# presigned upload URLs it signs for the files).
b2 key create --bucket ontic-pages ontic-pages-gateway-rw listBuckets,listFiles,readFiles,writeFiles
# Only for admins who use --direct: the same capabilities.
b2 key create --bucket ontic-pages ontic-pages-publish listBuckets,listFiles,readFiles,writeFiles
```

Each prints a key id and an application key once; they go into
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (or the config file above, or the
gateway's `deploy/secrets.env`).

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
For `private`, the publisher is matched by email: through the gateway that is always the
address you signed in with; with `--direct` it is `ONTIC_PAGES_EMAIL` (or `git config
user.email`), so use the address you sign in with. `publish` and `share` print who that is. The info page (`/<name>/_info`) always needs sign-in,
even for public pages.

## In the bucket

    <name>/current                 the current version id
    <name>/visibility              private, ontic or public (absent means ontic)
    <name>/comments.json           the comment threads, written by the gateway only
    <name>/<version>/page.json     the metadata
    <name>/<version>/...           the files

at the root of the `ontic-pages` bucket, or under `ONTIC_PAGES_PREFIX` when set.

`comments.json` is `{"threads": [...]}`; a thread has `id`, `version` (the one it was made on),
`anchor` (where on the page: path, a CSS selector, the point within that element, a snippet of
its text, document x, y and, on newer threads, the element's tag name), `created_by`, `created_at`, `resolved_at`, `resolved_by` and
`comments` (`id`, `author`, `body`, `created_at`, `deleted`). The gateway reads and rewrites the
whole file under a lock per page and keeps it in memory for a few seconds; the bucket keeps the
old copies. A deleted comment keeps its place with an empty body.

### page.json

| field | what it is |
|---|---|
| `name` | the page name |
| `version` | the version id, a UTC timestamp like `20261007T153000Z` |
| `published_at` | the same time in ISO 8601 |
| `published_by` | the signed-in email (with `--direct`: `ONTIC_PAGES_EMAIL`, else git `user.email`, else `$USER`) |
| `description` | from `--description`, may be empty |
| `meta` | map of strings from `--meta key=value`; a version saved from text edited in the bar adds `edited_from` (the version it was edited from) |
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
  page facts as JSON, `/_api/pages/<name>/versions/<version>` one version's details for the
  bar's Details panel (signed in), and `POST /_api/pages/<name>/visibility` changes visibility
  (owner only, from the bar or the command line); `POST /_api/pages/<name>/edits` saves text
  edited in the bar (owner only). `/_api/pages/<name>/comments` reads the comment threads and
  takes new ones, replies, resolve and delete (signed in, from the bar or the command line). The
  command line uses the rest of `/_api/` (list, info, current, publish, files for `pull`) and
  `/_cli/login`; see `gateway.py` for the routes.
- **The page's own host** (`<name>.pages.onticlabs.io`): `/<path>` serves the
  current version's files (content types, `index.html` for folders, Range requests
  for video, ETags and 304s), `/_v/<version>/<path>` a given version, cached for a
  year. Opened directly in a browser it redirects to the bar; `?raw=1` opens it
  without the bar.

The bar: the home link, the title menu (who published, when, the description, the
versions, Copy link, Open without the bar, Details, All pages), an "old version"
marker, the info button (Details), the comment button (signed in only), the edit counter with
Save and Discard (the owner, only once a text changed; see Edit text in place), your initial (or
Sign in), and Share (owner, general access, Copy link). Escape or a click elsewhere, in the page
too, closes a menu.

The info button (an "i" in a circle, left of the comment button) and the title menu's Details
item open the Details panel about the version you are looking at (the current one or an old
one): the description, who published it and when, the version id, visibility, git (remote,
branch, commit, linked to GitHub for a github.com remote, and a marker for uncommitted changes),
"Edited in the browser from" with a link to that version, the file count and every `--meta`
pair. Values can be copied; only http(s) values become links. Escape closes it and puts focus
back on the info button. It needs sign-in, like `/<name>/_info`, which stays as the plain page
behind its "Open as a page" link; signed out, the panel says so.

Comments: the comment button turns on comment mode and shows how many threads are open; its
menu has Show all comments (a side panel, a bottom sheet on phones) and Show resolved. In
comment mode the element under the pointer gets an outline (with its corners) and a small label
naming it (tag and the start of its text); the document itself and wrappers covering most of the
view are skipped, small inline elements count. A click attaches a new thread to that element
and opens the composer next to it, the element still outlined. Pins sit where each thread
points within its element and follow it while the page scrolls, resizes or changes; a pin whose
element is gone (or whose text changed) falls back to its old position only on the version it
was made on, else the thread is listed in the panel only. Opening a thread (its pin, its card in
the panel, or a `#comment=<id>` link) outlines its element and brings it into view; the pointer
on a pin or a card outlines it too, and each card names its element. A pin opens the thread: Resolve or Reopen, Copy link (`#comment=<id>` opens it), delete your own
comment, reply (Enter sends, Shift+Enter is a new line). The bar refreshes them every 30
seconds while visible. The page itself never sees comment text or emails, only the pins and
which one to outline. The page fades in once it is ready, a spinner shows only when it takes a while, and when a new version is
published while you look, it fades in where you were. The gateway adds one small
script (the bridge) to a page's HTML when it is shown in the bar, and only then;
stored files are never changed. A plain click on a link to `https://pages.onticlabs.io/...`
inside a page (another page, the listing) opens it in the whole tab: the bridge hands it to the
bar, since the apex refuses to be shown in a frame.

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

To try the command line against it, give it a token secret and point the command line there
(with `--local-as`, Allow on the login page signs you in as that address):

```sh
ONTIC_PAGES_TOKEN_SECRET="$(openssl rand -base64 32)" ontic-pages gateway --port 8790 --local-as you@onticlabs.io
ONTIC_PAGES_URL=http://localhost:8790 ontic-pages login
```

Without `ONTIC_PAGES_TOKEN_SECRET` the gateway answers 503 to the command line's routes.
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
by announcements. The bar, the Share panel (three levels), a host per page (by
name) and pinned comments (now in the bucket, not a database on the box) are back.
`set-current` replaces rollback. That code lives on the
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
