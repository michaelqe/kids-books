#!/usr/bin/env bash
# One-time (idempotent) droplet setup for Kids Books. Run on the droplet with sudo:
#
#   sudo ~/kids-books/deploy/droplet/install.sh
#
# 1. Installs and starts the kids-books systemd unit (127.0.0.1:8512).
# 2. Lets michael restart it without a password (/etc/sudoers.d/kids-books), so
#    deploy.sh and the X1 poller can deploy non-interactively.
# 3. Appends or refreshes the books.app.kennedy.ee block in /etc/caddy/Caddyfile
#    (backup first, caddy validate, reload; restores the backup if validation fails).
# 4. Adds a nightly backup of the lists DB to michael's crontab.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
USER_NAME=michael
CADDYFILE=/etc/caddy/Caddyfile
BEGIN="# --- kids-books (deploy/droplet/Caddyfile.books) ---"
END="# --- end kids-books ---"

install -d -o "$USER_NAME" -g "$USER_NAME" "$REPO/data"

# 1. unit
install -m 0644 "$HERE/kids-books.service" /etc/systemd/system/kids-books.service
systemctl daemon-reload
systemctl enable --now kids-books.service
systemctl restart kids-books.service
echo "unit: kids-books enabled and restarted"

# 2. sudoers
SUDOERS=/etc/sudoers.d/kids-books
TMP="$(mktemp)"
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl restart kids-books.service" > "$TMP"
if visudo -cf "$TMP" >/dev/null; then
    install -m 0440 "$TMP" "$SUDOERS"
    echo "sudoers: $SUDOERS"
else
    echo "sudoers: validation failed, not installed" >&2
fi
rm -f "$TMP"

# 3. Caddy
cp -a "$CADDYFILE" "$CADDYFILE.bak-pre-books-$(date +%Y%m%d-%H%M%S)"
python3 - "$CADDYFILE" "$HERE/Caddyfile.books" "$BEGIN" "$END" <<'PY'
import sys
path, block_path, begin, end = sys.argv[1:]
text = open(path, encoding="utf-8").read()
block = open(block_path, encoding="utf-8").read().strip() + "\n"
if begin in text and end in text:
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    text = head.rstrip("\n") + "\n\n" + block + tail.lstrip("\n")
else:
    text = text.rstrip("\n") + "\n\n" + block
open(path, "w", encoding="utf-8").write(text)
PY
if caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1; then
    systemctl reload caddy
    echo "caddy: books.app.kennedy.ee block installed, caddy reloaded"
else
    latest="$(ls -t "$CADDYFILE".bak-pre-books-* | head -1)"
    cp -a "$latest" "$CADDYFILE"
    echo "caddy: validation failed; restored $latest" >&2
    caddy validate --config "$CADDYFILE" --adapter caddyfile || true
    exit 1
fi

# 4. nightly backup of the lists
LINE="15 4 * * * $REPO/deploy/droplet/backup.sh >> \$HOME/backups/kids-books/backup.log 2>&1"
install -d -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/backups/kids-books"
current="$(crontab -u "$USER_NAME" -l 2>/dev/null || true)"
if ! grep -qF "deploy/droplet/backup.sh" <<<"$current"; then
    printf '%s\n%s\n' "$current" "$LINE" | sed '/^$/N;/^\n$/D' | crontab -u "$USER_NAME" -
    echo "cron: nightly lists backup added"
fi

sleep 1
curl -sf --max-time 10 http://127.0.0.1:8512/api/health && echo
