---
name: ontic-pages
description: Make, publish and share an ontic page (a hosted HTML page for the team). Use whenever the user asks for an ontic page, a page to publish or share with the team, or a report, gallery, dashboard or viewer to host. Pages are published with `ontic pages publish`, never to claude.ai.
---

# Ontic pages

An ontic page is plain HTML served at `https://pages.onticlabs.io/<name>/` under a slim bar
(title menu with versions and info, comments, Share), behind the team Google sign-in unless it
is public.
The tool is `ontic pages` (onticlabs/ontic-pages, installed with the ontic CLI; `ontic-pages` is
the same command). It is independent of the ontic CLI's store: no provenance integration, only metadata you pass with `--meta`.
When the user asks for a page, report, gallery or dashboard, make an ontic page, not a claude.ai
artifact. Never publish to claude.ai unless the user asks for that explicitly.

## Setup

Do not install or reinstall the tool yourself. If `ontic pages` is not found, ask the user to
install it:

```bash
uv tool install --force git+https://github.com/onticlabs/cli
```

If a command says "not signed in, or the sign-in expired", ask the user to run
`ontic pages login` (it opens the browser and needs their click); do not look for keys or tokens
elsewhere. `ontic pages whoami` shows who is signed in.

This skill is installed by the ontic CLI and refreshed on every `ontic` run;
`ontic pages skill` shows where it is installed and whether it is current.

## Write the page like an artifact

If the `artifact-design` skill is available (Claude Code), load it before writing (and
`artifact-diagramming` when the page needs diagrams) and follow it as you would for an artifact.
Codex has neither; then follow these plain rules:

- Light and dark: colors as CSS variables on `:root`, redefined under
  `@media (prefers-color-scheme: dark)`; give `body` an explicit background.
- Works at phone width: a `<meta name="viewport">` tag, 16px side gutters, no horizontal page
  scroll.
- A short `<title>` that names the page; put the explanation in `--description`.

Either way, these differ from a claude.ai artifact:

- Write a complete HTML document (`<!doctype html>`, `<head>`, `<body>`); nothing wraps it.
- Relative supporting files next to `index.html` (CSS, scripts, JSON, images, video) are fine,
  because the whole folder is served from the page's own host.
- Links and sources must be relative (`assets/a.png`), never root-absolute (`/assets/a.png`).
- Any CDN works. Pages are static: no server, no database. Data goes in the page or in
  relative JSON files.
- Do not put a `page.json`, `_info` or top-level `_v` folder in the page folder; they are reserved.

## Publish

1. Write the page into its own folder: `index.html` plus any assets (or one `.html` file, which
   becomes `index.html`).
2. Pick a name: lowercase letters, digits, `.` and `-`, starting with a letter or digit, short
   (it is the URL and a host name, so no `_`). Publishing again under the same name adds a
   version and makes it current; only the page's owner (its publisher) may do that.
3. Publish, from the repo the page came from (git remote, branch and commit are recorded):

   ```bash
   ontic pages publish ./report --name depth-eval --description "Depth eval, Oct 7"
   ontic pages publish report.html --name depth-eval            # single file
   ontic pages publish ./report --name depth-eval --meta model=sha256:9f1c... --meta dataset=point-clouds-arctic
   ```

   `--meta key=value` (repeatable) records what the page was made from. It is metadata only.
4. Give the user the printed link.

## Visibility

A new page is `ontic`: anyone signed in with an `@onticlabs.io` Google account can open it.
Change it only when the user asks:

```bash
ontic pages publish ./report --name depth-eval --visibility private   # only the publisher
ontic pages share depth-eval public      # anyone with the link, no sign-in
ontic pages share depth-eval ontic       # back to the team
```

Visibility belongs to the page, not to a version. The link is the same at every level.
The owner can also change it from the Share button in the bar.

## Versions

```bash
ontic pages list                        # every page you can open, visibility, current version
ontic pages list --name depth-eval      # its versions, newest first, * marks the current one
ontic pages info depth-eval             # page.json plus the versions (also Page info in the bar)
ontic pages set-current depth-eval 20261007T153000Z   # serve an older version again
```

Nothing is ever deleted. To change a page published earlier, fix the files and publish again
under the same name; open viewers see the new version without reloading. In a new session, find
the name with `ontic pages list`; never guess it from a file name.

The owner can also fix text in the browser (Edit in the bar), which saves a new version, so your
last published files may not be the newest. Before publishing a page again, run
`ontic pages info <name>`: if the current version's meta has `edited_from`, download it with
`ontic pages pull <name> /tmp/<name>-current`, compare its HTML with your source
(`diff -r`), carry those text changes into the source (or the code that generates it), then
publish.

## Comments

Signed-in viewers pin comments to points on a page, reply and resolve them in the bar. They are
feedback for you. Before publishing a new version of an existing page:

1. Read the open threads: `ontic pages comments <name>` (`--all` adds resolved ones, `--json`
   gives everything as JSON). Each thread shows a short id, where on the page it points (path
   and the quoted text) and every comment with its author.
2. Address each open comment in the page.
3. Publish the new version.
4. Reply to every thread you handled, saying what you changed (or why you did not), and resolve
   the ones you fixed:

   ```bash
   ontic pages comment depth-eval 3f9a1c "Fixed: the table now uses meters"
   ontic pages resolve depth-eval 3f9a1c
   ontic pages resolve depth-eval 3f9a1c --reopen   # if it was resolved by mistake
   ```

   A thread id may be shortened to its first characters while it stays unique. A long reply can
   come from stdin: `ontic pages comment <name> <id> - < reply.txt`. Leave threads you did not
   address open, and tell the user about them.

`--direct` (or `ONTIC_PAGES_DIRECT=1`) talks to the bucket with a key instead of the gateway;
only for admins who hold one. Do not use it unless the user asks.
