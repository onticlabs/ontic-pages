# Deploying the gateway: `https://pages.onticlabs.io/<name>/`

The gateway runs on the team box (`ontic-vps`, 159.195.206.154) behind the same
Caddy and the same kind of Google sign-in that Olympus and Atlas use.

    pages.onticlabs.io/oauth2/*  browser -> caddy :443 -> pages-oauth2-proxy 127.0.0.1:4190  (Google sign-in)
    pages.onticlabs.io/*         browser -> caddy :443 -> pages-gateway 127.0.0.1:8790       (listing, bar, API)
    <name>.pages.onticlabs.io/*  browser -> caddy :443 -> pages-gateway 127.0.0.1:8790       (the page itself)
    gateway -> pages-oauth2-proxy (http://oauth2-proxy:4180/oauth2/auth, pages network): who is this cookie?
    gateway -> bucket ontic-pages (its own private B2 bucket), read and write key, no delete

| File | What it is |
|---|---|
| `pages.caddy` | the Caddy site, installed as `/etc/caddy/conf.d/pages.caddy` |
| `pages-gateway.container` | the gateway as a Podman Quadlet unit (`pages-gateway.service`) |
| `pages-oauth2-proxy.container` | Google sign-in in front of it (`pages-oauth2-proxy.service`) |
| `pages.network` | the bridge the two containers share |
| `Dockerfile`, `Dockerfile.dockerignore` | the image: this repo in a venv, uid 10003 |
| `oauth2-proxy.cfg.example` | the oauth2-proxy config; `pages.sh` fills in the secrets |
| `secrets.env.example` | the one file you fill in (copy to `secrets.env`, never commit it) |
| `pages.sh` | on the box, as root: `check`, `install`, `status` |
| `deploy.sh` | on the laptop: the whole deploy in one command |

## Deploy

```sh
cp deploy/secrets.env.example deploy/secrets.env && chmod 600 deploy/secrets.env
$EDITOR deploy/secrets.env
deploy/deploy.sh ontic-vps check     # changes nothing on the box
deploy/deploy.sh ontic-vps           # check, then install
deploy/deploy.sh ontic-vps status    # or: logs
```

`deploy.sh` refuses an unpushed branch, clones or fast-forwards
`/opt/ontic-pages` on the box, copies `secrets.env` over ssh (mode 600, never
printed), runs `pages.sh check` and `pages.sh install`, then checks
`http://127.0.0.1:8790/_health` on the box. `install` writes
`/etc/ontic-pages/gateway.env` and `/etc/ontic-pages/oauth2-proxy.cfg`, builds
`localhost/ontic-pages:latest`, installs the three units, starts them, installs
the Caddy site, validates and reloads Caddy. It never edits
`/etc/caddy/Caddyfile` (`check` refuses until it has the global `on_demand_tls`
option, see One-time setup) and never restarts Caddy. The box takes a password, so
set `ATLAS_SSH_ASKPASS` to the askpass program for the run, as for the old
deploy.

## One-time setup

1. **Deploy key.** The box needs read access to `onticlabs/ontic-pages`, behind the ssh alias
   `github-ontic-pages` (the box has one deploy key per repository):

   ```sh
   vps 'ssh-keygen -t ed25519 -N "" -C ontic-vps-pages-deploy -f /root/.ssh/ontic_pages_deploy && printf "\nHost github-ontic-pages\n  HostName github.com\n  User git\n  IdentityFile /root/.ssh/ontic_pages_deploy\n  IdentitiesOnly yes\n" >> /root/.ssh/config && cat /root/.ssh/ontic_pages_deploy.pub'
   gh repo deploy-key add <(echo '<the ssh-ed25519 line>') --repo onticlabs/ontic-pages --title "ontic-vps pages"
   ```

2. **Bucket key: read and write, no delete.** The Share panel lets a page's owner
   change its visibility, so the gateway writes `<name>/visibility` (and nothing
   else). The `ontic-pages-publish` key has exactly the right capabilities
   (`listBuckets,listFiles,readFiles,writeFiles`, scoped to the bucket); reuse it, or
   make one for the gateway alone:

   ```sh
   b2 key create --bucket ontic-pages ontic-pages-gateway-rw listBuckets,listFiles,readFiles,writeFiles
   ```

   Its two values go into `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` of `secrets.env`.
   The read-only `ontic-pages-gateway` key is no longer enough.

3. **Google OAuth.** The redirect URI `https://pages.onticlabs.io/oauth2/callback`
   is already on the client the old deploy used; reuse its id, secret and cookie secret.

4. **DNS.** Two A records to 159.195.206.154: `pages` (exists) and the wildcard
   `*.pages` for the page hosts. Check that the wildcard still exists (it was slated
   for deletion after the path-based deploy) and add it back at Namecheap if not:
   `dig +short anything.pages.onticlabs.io` must print 159.195.206.154.

5. **Caddy global option.** Page hosts get their certificates on demand, and Caddy
   must ask the gateway first. That is a global option in `/etc/caddy/Caddyfile`
   (a site file cannot set it); `pages.sh check` refuses to go on without it. As root
   on the box (`vps`), this one line adds it to the global options block (or creates
   that block), validates, and puts the old file back if validation fails:

   ```sh
   f=/etc/caddy/Caddyfile; cp -a "$f" "$f.bak-pages" && awk 'BEGIN{a="\ton_demand_tls {\n\t\task http://127.0.0.1:8790/_tls-ask\n\t}"} !d && /^[ \t]*(#|$)/ {print; next} !d {d=1; if ($0 ~ /^[ \t]*\{[ \t]*$/) {print; print a; next} print "{\n" a "\n}\n"} {print}' "$f.bak-pages" > "$f" && caddy validate --config "$f" --adapter caddyfile || cp -a "$f.bak-pages" "$f"
   ```

   Run it only if `grep -n _tls-ask /etc/caddy/Caddyfile` finds nothing (a second
   `on_demand_tls` block would fail validation and be rolled back). Caddy picks it up
   with the `systemctl reload caddy` that `pages.sh install` does.

## Who can open what

Each page has a visibility in `<name>/visibility` in the bucket: `private`, `ontic`
(the default when the file is absent) or `public`. The gateway decides every request
itself, the shell and the page's files alike, and before every answer (304s too):

- **Who.** The gateway asks oauth2-proxy: `GET /oauth2/auth` with only the request's
  `Cookie` header. 202 with `X-Auth-Request-Email` is signed in; anything else is
  signed out; no answer is a 503 for anything that is not public. The answer is kept
  for 5 seconds per cookie. Identity headers in a request are never read (and Caddy
  strips them). `set_xauthrequest = true` in `oauth2-proxy.cfg.example` must stay.
- **The cookie reaches every page host** because oauth2-proxy sets it for
  `.pages.onticlabs.io` (`cookie_domains`), and `whitelist_domains` lets sign-in return
  to a page host.
- **Rules.** `public`: anyone, signed in or not. `ontic`: an `@onticlabs.io` email.
  `private`: the `published_by` of the current version. Signed out, a page load
  redirects to `/oauth2/start?rd=<the page>`; signed in but not allowed is 403. The
  listing at `/` and `/<name>/_info` always need sign-in.
- **Writes** (`POST /_api/pages/<name>/visibility`, the owner only) are taken on the
  apex only, and only with `Sec-Fetch-Site: same-origin`, `Origin:
  https://pages.onticlabs.io` and a JSON body, 20 per minute per person. A page's own
  scripts run on `<name>.pages.onticlabs.io`, which is same-site, so the browser would
  send the viewer's cookie with their requests; these checks are what stop a page from
  acting as the person looking at it.
- **Only Caddy reaches the gateway**, on the box's loopback (`127.0.0.1:8790`). Caddy
  answers `/_tls-ask` with 404 on both public sites; the gateway answers it only for
  a Host that is neither the apex nor a page host.

## What changed with the bar (phase 1)

- **A page host again.** Content is served from `<name>.pages.onticlabs.io`, its own
  browser origin, so a page's scripts cannot read the bar or another page. The apex
  shows the bar around a frame of it. Opening a page host directly redirects to the
  bar; `?raw=1` opens it without the bar.
- **On-demand certificates and `/_tls-ask` are back** (Caddy global option, wildcard
  DNS record, see One-time setup).
- **oauth2-proxy no longer proxies.** It serves `/oauth2/*` only (`upstreams =
  static://404`, `set_xauthrequest = true`), sets its cookie for `.pages.onticlabs.io`
  and has the network alias `oauth2-proxy`. The gateway is started with
  `--auth-url http://oauth2-proxy:4180/oauth2/auth`.
- **The gateway key can write** (no delete), for the Share panel.
- **Memory cache.** Up to 256 MB of version files (each up to 4 MB) in memory, with
  ETags; versions are immutable, so a version's own address is cached for a year.
- **Old links.** `/public/<name>/...` redirects to `/<name>/...`, which now works
  without sign-in for public pages.

## What changed from the old `ontic pages` deploy

- **Same names.** Units, image name, ports (8790, 4190), network
  (`ontic-pages`, 172.31.241.0/24), uid 10003 and `/etc/ontic-pages` are the
  same, so `install` replaces the old deploy in place. Checkout moves from
  `/opt/ontic-cli` to `/opt/ontic-pages`.
- **Pages by name**, `https://pages.onticlabs.io/<name>/` and
  `https://<name>.pages.onticlabs.io/`, not by job id. Old `<job-id>` links stop working.
- **No disk cache, no comments database, no broker identity, no announce index.**
  Visibility is per page, and private means "only the publisher", with no share lists.
- **Merged scripts.** `install-secrets.sh` is folded into `pages.sh`.
  `secrets.env` has fewer keys: no B2_READ_*, no mirror, no broker token; the
  bucket key is in `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

Cleanup after the first deploy, by hand, when you are happy with it:

- Back up the old comments: `sqlite3 /var/cache/ontic-pages/comments.sqlite3 ".backup /root/pages-comments-$(date +%F).sqlite3"`,
  then remove `/var/cache/ontic-pages` (the new gateway does not mount it).
- Delete the old `jobs/` read key. Keep the `*.pages` DNS record.
- `/opt/ontic-cli` is no longer used by pages.

## Logs

`journalctl -u pages-gateway -f` (one line per request: time, email, request,
status) and `journalctl -u pages-oauth2-proxy -f`.
