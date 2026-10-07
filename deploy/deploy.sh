#!/bin/sh
# Deploy ontic-pages to the box, from the laptop. One command, every time.
#
#   deploy/deploy.sh ontic-vps            check, then install
#   deploy/deploy.sh ontic-vps check      check only, change nothing
#   deploy/deploy.sh ontic-vps status     what is running
#   deploy/deploy.sh ontic-vps logs       follow both logs
#
# Steps: deploy/secrets.env exists and is mode 600; this branch is pushed; the box
# clones or fast-forwards /opt/ontic-pages; secrets.env is copied over ssh; the box
# runs deploy/pages.sh check, then install; the gateway health is checked.
#
# On a password-only box, ATLAS_SSH_ASKPASS names a program that prints the password
# (as in the old deploy); it is set for this script's ssh calls only.
set -eu

HOST=${1:?usage: deploy.sh <host> [deploy|check|status|logs]}
CMD=${2:-deploy}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$HERE")
BOX_DIR=${PAGES_BOX_DIR:-/opt/ontic-pages}
REPO_URL=${PAGES_REPO_URL:-github-ontic-pages:onticlabs/ontic-pages.git}
BRANCH=$(git -C "$REPO" rev-parse --abbrev-ref HEAD)

if [ -n "${ATLAS_SSH_ASKPASS:-}" ]; then
    SSH_ASKPASS=$ATLAS_SSH_ASKPASS SSH_ASKPASS_REQUIRE=force
    export SSH_ASKPASS SSH_ASKPASS_REQUIRE
fi
CTL="$HOME/.ssh/.ontic-pages-ctl-$HOST.sock"
box() { ssh -o ControlMaster=auto -o "ControlPath=$CTL" -o ControlPersist=60 "$HOST" "$@"; }
step() { printf '\n== %s\n' "$1"; }

case $CMD in
status) box "$BOX_DIR/deploy/pages.sh status"; exit 0 ;;
logs) ssh -t -o "ControlPath=$CTL" "$HOST" "journalctl -u pages-gateway -u pages-oauth2-proxy -f"; exit 0 ;;
check|deploy) ;;
*) echo "unknown command $CMD" >&2; exit 2 ;;
esac

step "1. secrets file"
SECRETS="$HERE/secrets.env"
[ -f "$SECRETS" ] || { echo "no $SECRETS (copy secrets.env.example, chmod 600, fill in)" >&2; exit 1; }
perms=$(stat -f '%Lp' "$SECRETS" 2>/dev/null || stat -c '%a' "$SECRETS")
case "$perms" in *00) echo "ok" ;; *) echo "$SECRETS is mode $perms; chmod 600 it" >&2; exit 1 ;; esac

step "2. $BRANCH is pushed"
git -C "$REPO" fetch --quiet origin "$BRANCH"
[ "$(git -C "$REPO" rev-parse "$BRANCH")" = "$(git -C "$REPO" rev-parse "origin/$BRANCH")" ] \
    || { echo "push $BRANCH first" >&2; exit 1; }
echo "ok"

step "3. code at $HOST:$BOX_DIR"
box "set -e
[ -d $BOX_DIR/.git ] || git clone --quiet $REPO_URL $BOX_DIR
cd $BOX_DIR && git fetch --quiet origin && git checkout --quiet $BRANCH
git merge --quiet --ff-only origin/$BRANCH && git log -1 --format='at %h %s'"

step "4. secrets onto $HOST"
box "umask 077; cat > $BOX_DIR/deploy/secrets.env" < "$SECRETS"
echo "copied, mode 600"

step "5. check"
box "$BOX_DIR/deploy/pages.sh check"
[ "$CMD" = check ] && exit 0

step "6. install"
box "$BOX_DIR/deploy/pages.sh install"

step "7. verify"
# shellcheck disable=SC2016  # expands on the box
box 'for i in $(seq 1 15); do curl -fsS http://127.0.0.1:8790/_health && exit 0; sleep 2; done
journalctl -u pages-gateway -n 30 --no-pager; exit 1'
echo "https://pages.onticlabs.io/ answers: $(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 https://pages.onticlabs.io/ || echo unreachable) (302 to Google sign-in is right)"
