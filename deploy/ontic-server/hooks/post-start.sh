#!/bin/sh
# pages' own checks. Runs on the box as root after ontic-server's general
# checks passed (units ready, image IDs, /_health on loopback and through
# Caddy, /_api/me and /_api/pages turning away requests that are not signed
# in). Exit nonzero to fail the deploy. Gets APP, RELEASE, PREVIOUS_RELEASE,
# PHASE and ACTION in its environment and runs in the release's copy of
# deploy/ontic-server. Never prints a secret: the output goes to the deploy
# log. Settings are read from the running gateway's environment, one
# non-secret name at a time.
set -eu

fail() { echo "  FAIL     $*"; exit 1; }
ok() { echo "  ok       $*"; }
skip() { echo "  skip     $*"; }

gw_env() { podman exec pages-gateway printenv "$1" 2>/dev/null || true; }
status_of() { curl -sS -o /dev/null --max-time 10 -w '%{http_code} %{redirect_url}' "$@" 2>/dev/null || true; }

url=$(gw_env ONTIC_PAGES_URL)
apex=${url#https://}
apex=${apex%%/*}
[ -n "$apex" ] || fail "the gateway has no ONTIC_PAGES_URL"

# 1. The apex sends a browser without a session to sign-in, at this app's
# /oauth2/start (the general checks cannot declare this: an invalid
# bearer token on / gets 401, not a redirect).
got=$(status_of -H "Host: $apex" "http://127.0.0.1:8790/")
case "$got" in
"302 https://$apex/oauth2/start?"*) ok "/ on $apex redirects to /oauth2/start without a session" ;;
*) fail "/ on $apex answers ${got%%\?*}, expected 302 to https://$apex/oauth2/start" ;;
esac

# 2. That sign-in link works: through Caddy, /oauth2/* reaches this app's
# oauth2-proxy, which sends the browser on to Google. (The general checks of
# the "app" recipe never request /oauth2/*.) Before Caddy has a certificate
# for the apex (no DNS yet) there is no TLS answer, and this is skipped like
# the general HTTPS checks.
got=$(status_of --resolve "$apex:443:127.0.0.1" "https://$apex/oauth2/start?rd=https%3A%2F%2F$apex%2F")
case "$got" in
"302 https://accounts.google.com/"*) ok "/oauth2/start on $apex redirects to Google sign-in" ;;
000*) skip "/oauth2/start: no TLS answer for $apex yet (no certificate before DNS points here)" ;;
*) fail "/oauth2/start on $apex answers ${got%%\?*}, expected 302 to https://accounts.google.com/" ;;
esac

# 3. Caddy's on-demand certificate question answers, and says no for a host
# that is not a page (this one never reaches the bucket).
got=$(status_of "http://127.0.0.1:8790/_tls-ask?domain=not-a-page.invalid")
[ "${got%% *}" = 404 ] || fail "/_tls-ask for a host that is not a page answers ${got%% *}, expected 404"
ok "/_tls-ask answers, and refuses a host that is not a page"

# 4. The bucket answers with the gateway's key: asking about a page name that
# does not exist reads the bucket, which must say "no such page" (404), not
# fail (502). Skipped with the rehearsal's dummy key, which the bucket refuses.
if grep -q '^AWS_ACCESS_KEY_ID=dummy' /etc/pages/current/gateway.env 2>/dev/null; then
    skip "bucket read: the bucket key is a dummy (AWS_ACCESS_KEY_ID starts with dummy)"
else
    got=$(status_of "http://127.0.0.1:8790/_tls-ask?domain=ontic-server-probe.$apex")
    [ "${got%% *}" = 404 ] || fail "the gateway cannot read the bucket (/_tls-ask answers ${got%% *}, expected 404); check the bucket key"
    ok "the gateway reads the bucket"
fi

# 5. Download CORS, which direct delivery needs. deploy/check-cors.py sends
# unauthenticated preflight requests only, so it needs no bucket key and runs
# with the dummy one too. It runs inside the gateway container (the box may
# have no python3), from this release's unpacked commit.
direct=$(gw_env ONTIC_PAGES_DIRECT_FILES | tr '[:upper:]' '[:lower:]')
case "$direct" in
"" | 1 | true | yes)
    commit=$(sed -n 's/^commit=//p' ../plan.env)
    probe="/opt/$APP/$commit/deploy/check-cors.py"
    [ -f "$probe" ] || fail "cannot find $probe for the CORS check"
    # shellcheck disable=SC2016  # expands inside the container
    podman exec -i pages-gateway sh -c 'exec python - "$ONTIC_PAGES_ENDPOINT" "$ONTIC_PAGES_BUCKET"' <"$probe" ||
        fail "bucket download CORS is not ready (deploy/README.md, \"Direct delivery\"), or set ONTIC_PAGES_DIRECT_FILES=0"
    ;;
*) skip "download CORS: direct delivery is off (ONTIC_PAGES_DIRECT_FILES=$direct)" ;;
esac
