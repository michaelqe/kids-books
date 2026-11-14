"""Covers, English summaries and links for catalog.db. Runs on X1 only, inside crawler.run.

Per book (results cached in ~/.cache/kids-books/enrich.db, which outlives the catalogue):

1. Open Library edition by ISBN (`/isbn/{isbn}.json`): cover ids and the work.
2. No edition? Open Library search by the original title (translated editions) or the
   title, plus the first author's surname. Only a close title match is accepted.
3. The work (`/works/{key}.json`): the English description, and covers if the edition had none.
4. Google Books, only when GOOGLE_BOOKS_API_KEY is set (the keyless quota is shared
   and usually exhausted): description and thumbnail for books Open Library missed.

Cover URLs use Open Library cover ids (`/b/id/{id}-M.jpg`), which are not rate limited
per IP the way ISBN cover URLs are; the viewer's browser loads them directly.
Goodreads has no API: we link to its search. Amazon is not used.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "kids-books/0.1 (personal picture-book finder)"
OL = "https://openlibrary.org"
HIT_DAYS = 30
MISS_DAYS = 7
DEFAULT_MAX = 1500  # books looked up per run; the rest wait for the next night


class Stop(Exception):
    """The service refused (429/403): stop looking things up this run."""


class Fetcher:
    def __init__(self, delay: float = 1.0, timeout: float = 20.0):
        self.delay = delay
        self.timeout = timeout
        self._last = 0.0
        self.requests = 0

    def json(self, url: str):
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429):
                raise Stop(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}") from e
            return None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None


# --- text helpers ----------------------------------------------------------------------


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def titles_match(want: str, got: str) -> bool:
    a, b = norm(want), norm(got)
    if not a or not b:
        return False
    a = re.sub(r"^(the|a|an) ", "", a)
    b = re.sub(r"^(the|a|an) ", "", b)
    return a == b or b.startswith(a) or a.startswith(b)


def clean_description(value) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    text = str(value or "")
    text = text.split("----------")[0]
    text = re.sub(r"\[([^\]]+)\]\[\d+\]", r"\1", text)      # [text][1]
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)     # [text](url)
    text = re.sub(r"^\s*\[\d+\]:\s*\S+\s*$", "", text, flags=re.M)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:2000]


def cover_url(cover_id) -> str:
    try:
        cid = int(cover_id)
    except (TypeError, ValueError):
        return ""
    return f"https://covers.openlibrary.org/b/id/{cid}-M.jpg" if cid > 0 else ""


def surname(authors_json: str) -> str:
    try:
        authors = json.loads(authors_json or "[]")
    except ValueError:
        return ""
    return authors[0].split(",")[0].strip() if authors else ""


# --- lookups ---------------------------------------------------------------------------


def lookup(book: dict, f: Fetcher, google_key: str = "") -> dict:
    """Everything we can find for one book. Empty fields when nothing matched."""
    out = {"cover_url": "", "summary": "", "summary_source": "", "openlibrary": "", "google_books": ""}
    work_key = ""
    covers: list = []
    for isbn in book["isbns"][:3]:
        edition = f.json(f"{OL}/isbn/{isbn}.json")
        if edition:
            covers = [c for c in edition.get("covers") or [] if isinstance(c, int) and c > 0]
            works = edition.get("works") or []
            work_key = works[0].get("key", "") if works else ""
            out["openlibrary"] = f"{OL}{edition.get('key', '')}" if edition.get("key") else ""
            if work_key or covers:
                break
    if not work_key:
        title = book["original_title"] or (book["title"] if book["language"] == "eng" else "")
        if title:
            params = {"title": title, "limit": "3", "fields": "key,title,cover_i,author_name"}
            who = surname(book["authors"])
            if who:
                params["author"] = who
            found = f.json(f"{OL}/search.json?{urllib.parse.urlencode(params)}") or {}
            for doc in found.get("docs") or []:
                if titles_match(title, doc.get("title", "")):
                    work_key = doc.get("key", "")
                    if doc.get("cover_i") and not covers:
                        covers = [doc["cover_i"]]
                    break
    if work_key:
        work = f.json(f"{OL}{work_key}.json") or {}
        out["summary"] = clean_description(work.get("description"))
        if out["summary"]:
            out["summary_source"] = "openlibrary"
        if not covers:
            covers = [c for c in work.get("covers") or [] if isinstance(c, int) and c > 0]
        out["openlibrary"] = out["openlibrary"] or f"{OL}{work_key}"
    if covers:
        out["cover_url"] = cover_url(covers[0])
    if google_key and (not out["summary"] or not out["cover_url"]) and book["isbns"]:
        q = urllib.parse.urlencode({"q": f"isbn:{book['isbns'][0]}", "maxResults": "1", "key": google_key})
        data = f.json(f"https://www.googleapis.com/books/v1/volumes?{q}") or {}
        items = data.get("items") or []
        if items:
            info = items[0].get("volumeInfo", {})
            if not out["summary"] and info.get("description"):
                out["summary"] = clean_description(info["description"])
                out["summary_source"] = "google_books"
            thumb = (info.get("imageLinks") or {}).get("thumbnail", "")
            if not out["cover_url"] and thumb:
                out["cover_url"] = thumb.replace("http://", "https://").replace("&edge=curl", "")
            out["google_books"] = info.get("infoLink", "").replace("http://", "https://")
    return out


# --- cache + apply -------------------------------------------------------------------------


def open_cache(cache_dir: Path) -> sqlite3.Connection:
    cache_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(cache_dir / "enrich.db")
    db.execute(
        """CREATE TABLE IF NOT EXISTS lookups (
               book_id TEXT PRIMARY KEY,
               key TEXT NOT NULL,          -- what was looked up (ISBNs + title); a change refetches
               result TEXT NOT NULL,       -- JSON from lookup()
               hit INTEGER NOT NULL,
               fetched_at TEXT NOT NULL)"""
    )
    return db


def lookup_key(book: dict) -> str:
    return json.dumps([book["isbns"][:3], book["original_title"], book["title"], book["language"]], ensure_ascii=False)


def is_fresh(row, key: str) -> bool:
    if row is None or row[0] != key:
        return False
    age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(row[3])
    return age < dt.timedelta(days=HIT_DAYS if row[2] else MISS_DAYS)


def run(
    db: sqlite3.Connection,
    cache_dir: Path,
    log=print,
    network: bool = True,
    max_lookups: int = DEFAULT_MAX,
    fetcher: Fetcher | None = None,
) -> dict:
    """Fill cover_url, summary, summary_source and links in catalog.db's books table."""
    cache = open_cache(cache_dir)
    google_key = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
    f = fetcher or Fetcher()
    rows = db.execute(
        """SELECT id, title, original_title, language, original_language, isbns, authors, links
           FROM books
           ORDER BY language = 'eng' DESC, original_language = 'eng' DESC, year DESC"""
    ).fetchall()
    looked = hits = 0
    stopped = ""
    for rid, title, original_title, language, original_language, isbns, authors, links in rows:
        book = {
            "id": rid, "title": title, "original_title": original_title, "language": language,
            "original_language": original_language, "isbns": json.loads(isbns or "[]"), "authors": authors,
        }
        key = lookup_key(book)
        row = cache.execute("SELECT key, result, hit, fetched_at FROM lookups WHERE book_id = ?", (rid,)).fetchone()
        result = json.loads(row[1]) if row else None
        if network and not stopped and looked < max_lookups and not is_fresh(row, key):
            try:
                result = lookup(book, f, google_key)
            except Stop as e:
                stopped = str(e)
                log(f"enrich: stopped ({stopped}); the rest wait for the next run")
            else:
                looked += 1
                hit = int(bool(result["cover_url"] or result["summary"]))
                cache.execute(
                    "INSERT OR REPLACE INTO lookups VALUES (?, ?, ?, ?, ?)",
                    (rid, key, json.dumps(result, ensure_ascii=False), hit,
                     dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()),
                )
                if looked % 25 == 0:
                    cache.commit()
                if looked % 250 == 0:
                    log(f"enrich: {looked} looked up")
        if not result:
            continue
        merged = json.loads(links or "{}")
        for name in ("openlibrary", "google_books"):
            if result.get(name):
                merged[name] = result[name]
        db.execute(
            "UPDATE books SET cover_url = ?, summary = ?, summary_source = ?, links = ? WHERE id = ?",
            (result.get("cover_url", ""), result.get("summary", ""), result.get("summary_source", ""),
             json.dumps(merged), rid),
        )
        if result.get("cover_url") or result.get("summary"):
            hits += 1
    cache.commit()
    cache.close()
    covers = db.execute("SELECT count(*) FROM books WHERE cover_url != ''").fetchone()[0]
    summaries = db.execute("SELECT count(*) FROM books WHERE summary != ''").fetchone()[0]
    stats = {"looked_up": looked, "requests": f.requests, "covers": covers, "summaries": summaries, "stopped": stopped}
    log(f"enrich: {looked} looked up ({f.requests} requests); {covers} covers, {summaries} summaries of {len(rows)}"
        + (f"; stopped: {stopped}" if stopped else ""))
    return stats
