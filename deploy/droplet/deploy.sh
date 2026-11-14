#!/usr/bin/env bash
# Deploy origin/master to the droplet (run from X1 or the Mac; the poller runs it after a merge).
# The commit must be pushed: the droplet pulls it from GitHub.
#
#   deploy/droplet/deploy.sh
#
# First time only: clone on the droplet and run `sudo ~/kids-books/deploy/droplet/install.sh`.
set -euo pipefail

# TODO(DNS): back to michael@running.app.kennedy.ee once it resolves again (14 Nov 2026).
HOST="${KIDS_BOOKS_HOST:-michael@142.93.133.110}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "working tree not clean" >&2; exit 1; }
git fetch -q origin
SHA="$(git rev-parse origin/master)"
[[ "$(git rev-parse HEAD)" == "$SHA" ]] || { echo "HEAD is not origin/master; push first" >&2; exit 1; }

ssh -o BatchMode=yes "$HOST" bash -s -- "$SHA" <<'REMOTE'
set -euo pipefail
SHA="$1"
if [[ ! -d ~/kids-books/.git ]]; then
    git clone -q https://github.com/michaelqe/kids-books.git ~/kids-books
fi
cd ~/kids-books
git fetch -q origin
git checkout -q master
git merge -q --ff-only origin/master
[[ "$(git rev-parse HEAD)" == "$SHA" ]] || { echo "deploy: droplet is not on $SHA" >&2; exit 1; }
mkdir -p data
if ! systemctl cat kids-books.service >/dev/null 2>&1; then
    echo "deploy: NOT INSTALLED. Run once on the droplet: sudo ~/kids-books/deploy/droplet/install.sh" >&2
    exit 1
fi
sudo -n /usr/bin/systemctl restart kids-books.service
for _ in $(seq 1 20); do
    body="$(curl -sf --max-time 5 http://127.0.0.1:8512/api/health || true)"
    if [[ "$body" == *"\"git_sha\": \"$SHA\""* ]]; then
        echo "health: ok ($SHA) $body"
        exit 0
    fi
    sleep 1
done
echo "health: FAIL (expected $SHA, got: ${body:-no answer})" >&2
exit 1
REMOTE
