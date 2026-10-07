# Deploying the gateway: `https://pages.onticlabs.io/<name>/`

The gateway runs on the team box (`ontic-vps`, 159.195.206.154) behind the same
Caddy and the same kind of Google sign-in that Olympus and Atlas use.

    /public/*, /_health  browser -> caddy :443 -> pages-gateway 127.0.0.1:8790                 (no sign-in)
    everything else     browser -> caddy :443 -> pages-oauth2-proxy 127.0.0.1:4190 -> pages-gateway (pages network)
    gateway -> bucket ontic-r3, prefix pages/, READ-ONLY key

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
`/etc/caddy/Caddyfile` and never restarts Caddy. The box takes a password, so
set `ATLAS_SSH_ASKPASS` to the askpass program for the run, as for the old
deploy.

## One-time setup

1. **Deploy key.** The box needs read access to `onticlabs/ontic-pages`, behind the ssh alias
   `github-ontic-pages` (the box has one deploy key per repository):

   ```sh
   vps 'ssh-keygen -t ed25519 -N "" -C ontic-vps-pages-deploy -f /root/.ssh/ontic_pages_deploy && printf "\nHost github-ontic-pages\n  HostName github.com\n  User git\n  IdentityFile /root/.ssh/ontic_pages_deploy\n  IdentitiesOnly yes\n" >> /root/.ssh/config && cat /root/.ssh/ontic_pages_deploy.pub'
   gh repo deploy-key add <(echo '<the ssh-ed25519 line>') --repo onticlabs/ontic-pages --title "ontic-vps pages"
   ```

2. **Read-only bucket key.** Bucket `ontic-r3`, prefix `pages/`, capabilities
   `readFiles,listFiles` only. The old gateway key was limited to `jobs/`, so it
   cannot be reused.

   ```sh
   b2 key create --bucket ontic-r3 --name-prefix 'pages/' ontic-pages-gateway readFiles,listFiles
   ```

   Its two values go into `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` of `secrets.env`.

3. **Google OAuth.** The redirect URI `https://pages.onticlabs.io/oauth2/callback`
   is already on the client the old deploy used; reuse its id, secret and cookie secret.

4. **DNS.** The A record `pages` -> 159.195.206.154 already exists.

## Who can open what

Each page has a visibility in `pages/<name>/visibility`: `private`, `ontic`
(the default when the file is absent) or `public`. The gateway stays a plain
file server; access follows from routing plus one header:

- Caddy sends `/public/*` and `/_health` straight to the gateway, skipping
  oauth2-proxy. On `/public/<name>/` the gateway serves only public pages and
  redirects every other page to `/<name>/`, which goes through sign-in.
  `/public/<name>/_info` also redirects: metadata stays behind sign-in.
- Everything else goes through oauth2-proxy (Google sign-in, `@onticlabs.io`
  only), which sets `X-Forwarded-Email`. `ontic` pages need that header to end
  in `@onticlabs.io` (`--email-domain`), `private` pages need it to equal the
  `published_by` of the current version, `public` pages need nothing. Otherwise
  the answer is 403. The listing at `/` hides private pages from everyone but
  their publisher.

Because the gateway decides on `X-Forwarded-Email`, two things must hold:

1. **oauth2-proxy sets it.** `pass_user_headers = true` in
   `oauth2-proxy.cfg.example` does that; keep it. Caddy strips the header from
   every incoming request on both routes, so a browser cannot send its own.
2. **Only Caddy and oauth2-proxy can reach the gateway.** Its port is published
   on the box's loopback only (`127.0.0.1:8790`, for Caddy) and is reachable on
   the `ontic-pages` podman network (for oauth2-proxy). Never publish it on a
   public interface: anyone who can reach it can claim any email. Root on the
   box can, which is accepted.

## What changed from the old `ontic pages` deploy

- **Path-based, one host.** Pages live at `https://pages.onticlabs.io/<name>/`,
  not `https://<job-id>.pages.onticlabs.io/`. No wildcard site, no on-demand
  certificates, no `tls-ask` endpoint. Old `<job-id>` links stop working.
- **Sign-in in front, not inside.** oauth2-proxy proxies to the gateway (as for
  Olympus). The gateway never talks to oauth2-proxy; it only reads
  `X-Forwarded-Email` (see above). Visibility is per page, not per version, and
  private means "only the publisher", with no share lists. Public pages live
  under `/public/<name>/`, not on their own subdomain.
- **Stateless gateway.** No disk cache, no comments database, no broker
  identity, no announce index. It reads `current` and the files from the bucket
  (and keeps `current` for 5 seconds).
- **Same names.** Units, image name, ports (8790, 4190), network
  (`ontic-pages`, 172.31.241.0/24), uid 10003 and `/etc/ontic-pages` are the
  same, so `install` replaces the old deploy in place. Checkout moves from
  `/opt/ontic-cli` to `/opt/ontic-pages`.
- **Merged scripts.** `install-secrets.sh` is folded into `pages.sh`.
  `secrets.env` has fewer keys: no B2_READ_*, no mirror, no broker token; the
  bucket key is in `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

Cleanup after the first deploy, by hand, when you are happy with it:

- Back up the old comments: `sqlite3 /var/cache/ontic-pages/comments.sqlite3 ".backup /root/pages-comments-$(date +%F).sqlite3"`,
  then remove `/var/cache/ontic-pages` (the new gateway does not mount it).
- Remove the `on_demand_tls { ask http://127.0.0.1:8790/_ontic/tls-ask }` block
  from the global options of `/etc/caddy/Caddyfile` (harmless if left).
- Delete the `*.pages` DNS record at Namecheap and the old `jobs/` read key.
- `/opt/ontic-cli` is no longer used by pages.

## Logs

`journalctl -u pages-gateway -f` (one line per request: time, email, request,
status) and `journalctl -u pages-oauth2-proxy -f`.
