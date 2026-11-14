"""Build data/catalog.db from ESTER. Runs on X1 only.

    python3 -m crawler.run --out data/catalog.db

1. List: walk the browse list for the picture-book genre heading (about 185 pages of
   50) and keep the records a Tallinn library holds.
2. Records: fetch the MARC page (bibliographic data + holdings) for new records, and
   for a rotating slice of the rest so holdings stay fresh (`--refresh-days`).
3. Build: parse every cached record, apply the picture-book rule, write a new
   catalog.db next to the old one and rename it into place.

Fetched pages live in a state DB (`~/.cache/kids-books/state.db`, zlib-compressed)
that survives rebuilds, so a re-run only fetches what is new or due.

Exit status: 0 ok; 75 when ESTER refused or kept failing (the catalogue is still
built from what is cached, and meta.crawl_status says "partial"); 1 on other errors.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import zlib
from pathlib import Path

from . import enrich as enrich_mod
from . import ester
from .terms import LANGUAGES, branch_name, genre_en, status_en, subject_en

SCHEMA_VERSION = "1"
HERE = Path(__file__).resolve().parent
DEFAULT_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kids-books"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def log(msg: str) -> None:
    print(msg, flush=True)


# --- state DB (survives rebuilds) ---------------------------------------------------


def open_state(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS listed (
            id TEXT PRIMARY KEY,
            brief TEXT NOT NULL,          -- JSON from ester.parse_list
            tallinn INTEGER NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY,          -- record id
            body BLOB NOT NULL,           -- zlib(MARC page html)
            fetched_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            started_at TEXT PRIMARY KEY,
            finished_at TEXT,
            status TEXT,
            requests INTEGER
        );
        """
    )
    return db


def crawl_list(client: ester.Client, state: sqlite3.Connection, max_pages: int | None) -> int:
    offset, pages, seen = 1, 0, 0
    total = None
    stamp = now()
    while offset:
        page = ester.parse_list(client.get(ester.genre_page_path(offset, total or 9166)))
        total = page["total"] or total
        for r in page["results"]:
            tallinn = int(ester.held_in_tallinn(r["libraries"]))
            state.execute(
                """INSERT INTO listed (id, brief, tallinn, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET brief = excluded.brief,
                       tallinn = excluded.tallinn, last_seen = excluded.last_seen""",
                (r["id"], json.dumps(r, ensure_ascii=False), tallinn, stamp, stamp),
            )
            seen += 1
        state.commit()
        pages += 1
        if pages % 20 == 0:
            log(f"list: {pages} pages, {seen} records (of {total})")
        if max_pages and pages >= max_pages:
            break
        nxt = page["next_offset"]
        offset = nxt if nxt and nxt > offset else None
    log(f"list: done, {pages} pages, {seen} records")
    return seen


def due_records(state: sqlite3.Connection, refresh_days: int, limit: int | None) -> list[str]:
    """New Tallinn records first, then the oldest fetches past `refresh_days`."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=refresh_days)).isoformat()
    rows = state.execute(
        """SELECT l.id FROM listed l LEFT JOIN pages p ON p.id = l.id
           WHERE l.tallinn = 1 AND (p.id IS NULL OR p.fetched_at < ?)
           ORDER BY p.fetched_at IS NOT NULL, p.fetched_at, l.id""",
        (cutoff,),
    ).fetchall()
    ids = [r[0] for r in rows]
    return ids[:limit] if limit is not None else ids


def crawl_records(client: ester.Client, state: sqlite3.Connection, ids: list[str]) -> int:
    done = 0
    for rid in ids:
        body = client.get(ester.marc_path(rid))
        state.execute(
            "INSERT OR REPLACE INTO pages (id, body, fetched_at) VALUES (?, ?, ?)",
            (rid, zlib.compress(body.encode("utf-8")), now()),
        )
        done += 1
        if done % 25 == 0:
            state.commit()
        if done % 250 == 0:
            log(f"records: {done}/{len(ids)}")
    state.commit()
    log(f"records: fetched {done}")
    return done


# --- build catalog.db ----------------------------------------------------------------


def book_row(rec: dict, fetched_at: str) -> tuple[dict, list[dict]]:
    holdings = []
    for h in ester.tallinn_holdings(rec["holdings"]):
        holdings.append(
            {
                "location": h["location"],
                "branch": branch_name(h["location"]),
                "call_number": h["call_number"],
                "status": h["status"],
                "status_en": status_en(h["status"]),
                "available": int(ester.is_available(h["status"])),
            }
        )
    subjects_en = [e for e in (subject_en(s) for s in rec["subjects"]) if e]
    genres_en = [e for e in (genre_en(g) for g in rec["genres"]) if e]
    isbn = rec["isbns"][0] if rec["isbns"] else ""
    who = " ".join(a.split(",")[0] for a in rec["authors"][:1])
    q = isbn or f"{rec['title']} {who}".strip()
    links = {"goodreads": "https://www.goodreads.com/search?q=" + ester.urllib.parse.quote_plus(q)}
    book = {
        "id": rec["id"],
        "url": rec["url"],
        "title": rec["title"],
        "subtitle": rec["subtitle"],
        "responsibility": rec["responsibility"],
        "authors": json.dumps(rec["authors"], ensure_ascii=False),
        "illustrators": json.dumps(rec["illustrators"], ensure_ascii=False),
        "year": rec["year"],
        "language": rec["language"],
        "original_language": rec["original_language"],
        "original_title": rec["original_title"],
        "isbns": json.dumps(rec["isbns"]),
        "pages": rec["pages"],
        "extent": rec["extent"],
        "series": rec["series"],
        "notes": rec["summary"],
        "subjects": json.dumps(rec["subjects"], ensure_ascii=False),
        "subjects_en": json.dumps(list(dict.fromkeys(subjects_en)), ensure_ascii=False),
        "genres": json.dumps(rec["genres"], ensure_ascii=False),
        "genres_en": json.dumps(list(dict.fromkeys(genres_en)), ensure_ascii=False),
        "tallinn_copies": len(holdings),
        "available_copies": sum(h["available"] for h in holdings),
        "holdings_checked_at": fetched_at,
        "links": json.dumps(links),
    }
    return book, holdings


def build(state: sqlite3.Connection, out: Path, status: str, requests: int, enrich=None) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    kept = dropped = 0
    reasons: dict[str, int] = {}
    rows = state.execute(
        "SELECT p.id, p.body, p.fetched_at FROM pages p JOIN listed l ON l.id = p.id WHERE l.tallinn = 1"
    )
    for rid, body, fetched_at in rows:
        rec = ester.parse_record(zlib.decompress(body).decode("utf-8"), rid)
        ok, why = ester.is_picture_book(rec)
        if ok and not ester.tallinn_holdings(rec["holdings"]):
            ok, why = False, "no Tallinn copy"
        if not ok:
            dropped += 1
            key = "too long" if why[0].isdigit() else why
            reasons[key] = reasons.get(key, 0) + 1
            continue
        book, holdings = book_row(rec, fetched_at)
        cols = ", ".join(book)
        db.execute(f"INSERT INTO books ({cols}) VALUES ({', '.join('?' * len(book))})", list(book.values()))
        for h in holdings:
            db.execute(
                """INSERT INTO holdings (book_id, location, branch, call_number, status, status_en, available)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (rid, h["location"], h["branch"], h["call_number"], h["status"], h["status_en"], h["available"]),
            )
        for s in rec["subjects"]:
            db.execute("INSERT INTO subjects (book_id, subject, subject_en) VALUES (?, ?, ?)", (rid, s, subject_en(s)))
        kept += 1
    if enrich:
        enrich(db)
    index_fts(db)
    counts = {
        "books": kept,
        "english_books": db.execute("SELECT count(*) FROM books WHERE language = 'eng'").fetchone()[0],
        "available_books": db.execute("SELECT count(*) FROM books WHERE available_copies > 0").fetchone()[0],
        "covers": db.execute("SELECT count(*) FROM books WHERE cover_url != ''").fetchone()[0],
        "summaries": db.execute("SELECT count(*) FROM books WHERE summary != ''").fetchone()[0],
        "dropped": dropped,
        "dropped_reasons": reasons,
    }
    meta = {
        "schema_version": SCHEMA_VERSION,
        "crawled_at": now(),
        "crawl_status": status,
        "requests": str(requests),
        **{k: (json.dumps(v) if isinstance(v, dict) else str(v)) for k, v in counts.items()},
    }
    db.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", list(meta.items()))
    db.commit()
    db.execute("VACUUM")
    db.close()
    os.replace(tmp, out)
    return counts


def index_fts(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM books_fts")
    for rowid, title, subtitle, series, original_title, authors, illustrators, subjects, subjects_en, genres_en, notes, summary in db.execute(
        """SELECT rowid, title, subtitle, series, original_title, authors, illustrators, subjects, subjects_en,
                  genres_en, notes, summary FROM books"""
    ).fetchall():
        names = json.loads(authors) + json.loads(illustrators)
        # "Marshall, Natalie" also as "Natalie Marshall"
        names += [" ".join(reversed(n.split(", ", 1))) for n in names if ", " in n]
        db.execute(
            "INSERT INTO books_fts (rowid, title, authors, subjects, summary) VALUES (?, ?, ?, ?, ?)",
            (
                rowid,
                " ".join(x for x in (title, subtitle, series, original_title) if x),
                " ".join(names),
                " ".join(json.loads(subjects) + json.loads(subjects_en) + json.loads(genres_en)),
                " ".join(x for x in (summary, notes) if x),
            ),
        )


# --- main ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=Path("data/catalog.db"))
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between ESTER requests")
    ap.add_argument("--refresh-days", type=int, default=7, help="re-fetch holdings older than this")
    ap.add_argument("--max-records", type=int, default=None, help="cap record fetches this run")
    ap.add_argument("--max-list-pages", type=int, default=None)
    ap.add_argument("--skip-list", action="store_true", help="reuse the last list")
    ap.add_argument("--build-only", action="store_true", help="no network; rebuild from the cache")
    ap.add_argument("--no-enrich", action="store_true", help="skip covers and summaries")
    ap.add_argument("--enrich-max", type=int, default=enrich_mod.DEFAULT_MAX, help="cover/summary lookups this run")
    args = ap.parse_args(argv)

    state = open_state(args.cache / "state.db")
    started = now()
    state.execute("INSERT INTO runs (started_at) VALUES (?)", (started,))
    state.commit()
    client = ester.Client(delay=args.delay)
    status, code = "ok", 0
    t0 = time.monotonic()
    if not args.build_only:
        try:
            if not args.skip_list:
                crawl_list(client, state, args.max_list_pages)
            crawl_records(client, state, due_records(state, args.refresh_days, args.max_records))
        except ester.EsterError as e:
            status, code = f"partial: {e}", 75
            log(f"stopped: {e}")
    enrich = None
    if not args.no_enrich:
        enrich = lambda db: enrich_mod.run(  # noqa: E731
            db, cache_dir=args.cache, log=log, network=not args.build_only, max_lookups=args.enrich_max
        )
    counts = build(state, args.out, status, client.requests, enrich)
    state.execute(
        "UPDATE runs SET finished_at = ?, status = ?, requests = ? WHERE started_at = ?",
        (now(), status, client.requests, started),
    )
    state.commit()
    langs = ", ".join(f"{LANGUAGES.get(k, k)} {v}" for k, v in _languages(args.out))
    log(
        f"catalog: {counts['books']} picture books ({langs}); {counts['available_books']} on a shelf now; "
        f"{counts['covers']} covers, {counts['summaries']} English summaries; "
        f"dropped {counts['dropped']} {counts['dropped_reasons']}; {client.requests} requests in "
        f"{time.monotonic() - t0:.0f}s; status {status}"
    )
    return code


def _languages(path: Path) -> list[tuple[str, int]]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return db.execute(
            "SELECT language, count(*) FROM books GROUP BY language ORDER BY count(*) DESC LIMIT 4"
        ).fetchall()
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
