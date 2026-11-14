#!/usr/bin/env bash
# Nightly on X1 (kids-books-crawl.timer): crawl ESTER, rebuild data/catalog.db, upload it
# to the droplet. Only X1 scrapes; the droplet only serves what is uploaded here.
#
#   deploy/x1/crawl-and-upload.sh              # crawl + upload
#   deploy/x1/crawl-and-upload.sh --upload-only
#
# Exit status: the crawl's (75 = ESTER refused or kept failing; the catalogue was still
# rebuilt from the cache and uploaded), else the upload's. Posts the outcome to Magpie
# notifications (project childrens-books) when ~/.config/magpie/poller.env has a token.
set -uo pipefail

HOST="${KIDS_BOOKS_HOST:-michael@running.app.kennedy.ee}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
CATALOG="$REPO/data/catalog.db"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/kids-books-crawl.lock"
cd "$REPO"

notify() {  # level title body
    local env="$HOME/.config/magpie/poller.env"
    [[ -f "$env" ]] || return 0
    python3 - "$env" "$1" "$2" "$3" <<'PY' || true
import json, sys, urllib.request
env_path, level, title, body = sys.argv[1:]
env = {}
for line in open(env_path):
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
base, token = env.get("MAGPIE_API_BASE"), env.get("MAGPIE_API_TOKEN")
if base and token:
    req = urllib.request.Request(
        base.rstrip("/") + "/api/notifications",
        data=json.dumps({"project": "childrens-books", "title": title, "body": body,
                         "level": level, "source": "kids-books-crawl"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    urllib.request.urlopen(req, timeout=15)
PY
}

exec 9>"$LOCK"
flock -n 9 || { echo "another crawl is running"; exit 75; }

# No git pull here: this is the poller's checkout too; the poller keeps it current.

crawl_rc=0
summary=""
if [[ "${1:-}" != "--upload-only" ]]; then
    runlog="$(mktemp)"
    python3 -m crawler.run --out "$CATALOG" 2>&1 | tee "$runlog"
    crawl_rc=${PIPESTATUS[0]}
    out="$(cat "$runlog")"
    rm -f "$runlog"
    summary="$(grep '^catalog:' <<<"$out" | tail -1)"
    if [[ ! -f "$CATALOG" ]] || [[ $crawl_rc -ne 0 && $crawl_rc -ne 75 ]]; then
        notify failure "Kids Books crawl failed (exit $crawl_rc)" "$(tail -20 <<<"$out")"
        exit "$crawl_rc"
    fi
fi

# Upload: copy next to the live file, then rename (atomic; the server reopens per request).
up_rc=0
up_out="$(
    ssh -o BatchMode=yes "$HOST" 'mkdir -p ~/kids-books/data' 2>&1 &&
    scp -q -o BatchMode=yes "$CATALOG" "$HOST:kids-books/data/catalog.db.upload" 2>&1 &&
    ssh -o BatchMode=yes "$HOST" 'mv -f ~/kids-books/data/catalog.db.upload ~/kids-books/data/catalog.db &&
        curl -sf --max-time 10 http://127.0.0.1:8512/api/health || echo "(server not answering yet)"' 2>&1
)" || up_rc=$?
echo "upload: $up_out"

if [[ $up_rc -ne 0 ]]; then
    notify failure "Kids Books upload to the droplet failed" "$up_out"
    exit "$up_rc"
fi
if [[ $crawl_rc -eq 75 ]]; then
    notify info "Kids Books crawl partial (ESTER stopped it); uploaded what was cached" "$summary"
else
    notify success "Kids Books catalogue updated" "$summary"
fi
exit "$crawl_rc"
