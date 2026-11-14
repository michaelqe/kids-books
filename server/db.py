"""SQLite helpers: the read-only catalogue (uploaded from X1) and the lists DB (ours)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def connect_catalog(path: Path) -> sqlite3.Connection | None:
    """Open catalog.db read-only, or None when there is none yet.

    Opened per request, so a catalogue swapped in by the X1 upload (atomic rename)
    is picked up on the next request without a restart.
    """
    if not path.is_file():
        return None
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def connect_lists(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 10000")
    return db


def migrate(path: Path) -> list[str]:
    """Apply server/migrations/NNN_*.sql in order, once each. Never drops data."""
    db = connect_lists(path)
    try:
        db.execute("PRAGMA journal_mode = WAL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        done = {r[0] for r in db.execute("SELECT name FROM schema_migrations")}
        applied = []
        for f in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
            if f.name in done:
                continue
            with db:
                db.executescript(f.read_text(encoding="utf-8"))
                db.execute("INSERT INTO schema_migrations (name) VALUES (?)", (f.name,))
            applied.append(f.name)
        return applied
    finally:
        db.close()


def catalog_meta(db: sqlite3.Connection | None) -> dict | None:
    if db is None:
        return None
    meta = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM meta")}
    out: dict = {"crawled_at": meta.get("crawled_at"), "status": meta.get("crawl_status")}
    for key in ("books", "english_books", "available_books", "nature_books", "schema_version"):
        if key in meta:
            out[key] = int(meta[key])
    if "audiences" in meta:
        out["audiences"] = loads(meta["audiences"], {})
    return out


def loads(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default
