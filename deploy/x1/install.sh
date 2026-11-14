#!/usr/bin/env bash
# Install the X1 user units (no sudo): the nightly crawl timer and the dev server.
#
#   deploy/x1/install.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.config/systemd/user"
mkdir -p "$DEST"
for unit in kids-books-crawl.service kids-books-crawl.timer kids-books-dev.service; do
    install -m 0644 "$HERE/$unit" "$DEST/$unit"
done
chmod +x "$HERE/crawl-and-upload.sh"
systemctl --user daemon-reload
systemctl --user enable --now kids-books-crawl.timer
systemctl --user enable --now kids-books-dev.service
systemctl --user restart kids-books-dev.service
systemctl --user list-timers kids-books-crawl.timer --no-pager
