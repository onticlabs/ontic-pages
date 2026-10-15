#!/bin/sh
# pages' own checks. Runs on the box as root after ontic-server's general
# checks passed: units ready, image IDs, /_health on loopback and through
# Caddy, "/", /_api/me and /_api/pages turning away requests that are not
# signed in, and /_tls-ask refusing names that are not pages. Exit nonzero
# to fail the deploy. Gets APP, RELEASE, PREVIOUS_RELEASE, PHASE, ACTION,
# SOURCE_DIR (the release's unpacked commit) and PUBLIC_HOST (the apex) in
# its environment. Never prints a secret: the output goes to the deploy log.
set -eu

fail() { echo "  FAIL     $*"; exit 1; }
ok() { echo "  ok       $*"; }
skip() { echo "  skip     $*"; }

status_of() { curl -sS -o /dev/null --max-time 10 -w '%{http_code} %{redirect_url}' "$@" 2>/dev/null || true; }

apex=${PUBLIC_HOST:?}

# 1. The sign-in link works: through Caddy, /oauth2/* reaches this app's
# oauth2-proxy, which sends the browser on to Google. (The general checks of
# the "app" recipe accept a redirect to /oauth2/start but never follow it.)
# Before Caddy has a certificate for the apex (no DNS yet) there is no TLS
# answer, and this is skipped like the general HTTPS checks.
got=$(status_of --resolve "$apex:443:127.0.0.1" "https://$apex/oauth2/start?rd=https%3A%2F%2F$apex%2F")
case "$got" in
"302 https://accounts.google.com/"*) ok "/oauth2/start on $apex redirects to Google sign-in" ;;
000*) skip "/oauth2/start: no TLS answer for $apex yet (no certificate before DNS points here)" ;;
*) fail "/oauth2/start on $apex answers ${got%%\?*}, expected 302 to https://accounts.google.com/" ;;
esac

# 2. Download CORS, which direct delivery needs. deploy/check-cors.py sends
# unauthenticated preflight requests only, so it needs no bucket key. It runs
# inside the gateway container (the box may have no python3), which also
# holds the bucket's endpoint and name.
direct=$(podman exec pages-gateway printenv ONTIC_PAGES_DIRECT_FILES 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)
case "$direct" in
"" | 1 | true | yes)
    probe="${SOURCE_DIR:?}/deploy/check-cors.py"
    [ -f "$probe" ] || fail "cannot find $probe for the CORS check"
    # shellcheck disable=SC2016  # expands inside the container
    podman exec -i pages-gateway sh -c 'exec python - "$ONTIC_PAGES_ENDPOINT" "$ONTIC_PAGES_BUCKET"' <"$probe" ||
        fail "bucket download CORS is not ready (deploy/README.md, \"Direct delivery\"), or set ONTIC_PAGES_DIRECT_FILES=0"
    ;;
*) skip "download CORS: direct delivery is off (ONTIC_PAGES_DIRECT_FILES=$direct)" ;;
esac
