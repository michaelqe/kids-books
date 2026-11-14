#!/usr/bin/env bash
# Nightly copy of the lists DB (books.db) on the droplet; keeps 30 days.
# catalog.db is not backed up: X1 rebuilds it every night.
set -euo pipefail
SRC="$HOME/kids-books/data/books.db"
DEST="$HOME/backups/kids-books"
mkdir -p "$DEST"
[[ -f "$SRC" ]] || { echo "$(date -Is) no $SRC yet"; exit 0; }
OUT="$DEST/books-$(date +%Y%m%d).db"
python3 - "$SRC" "$OUT" <<'PY'
import sqlite3, sys
src, out = sys.argv[1:]
with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(out) as d:
    s.backup(d)
PY
find "$DEST" -name 'books-*.db' -mtime +30 -delete
echo "$(date -Is) backed up to $OUT"
