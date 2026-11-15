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

v2 (BOOKS-12): each lookup also keeps the category fields (edition LCCN, LC and Dewey
classes, work subjects, Google categories), and `prefetch()` runs the lookups (plus the
Library of Congress record, crawler/categories.py) for candidate books *before* the build
decides their scope, so outside categories can change what is kept.
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
DEFAULT_MAX = 3000  # Open Library lookups per run (each may add one LoC request); the rest wait for the next night


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

    def bytes(self, url: str) -> bytes | None:
        """A binary body (a cover image), or None on a 404 or a network error."""
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Stop(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}") from e
            return None
        except (urllib.error.URLError, TimeoutError, OSError):
            return None

    def text(self, url: str) -> str | None:
        """A text body (the LoC MARCXML), or None on a 404 or a network error."""
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 503):
                raise Stop(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}") from e
            return None
        except (urllib.error.URLError, TimeoutError, OSError):
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


GOOGLE_COVER = "https://books.google.com/books/content?vid=ISBN{isbn}&printsec=frontcover&img=1&zoom=1"
GOOGLE_NO_COVER = {10794}  # byte size of Google's grey "image not available" JPEG
COVER_ISBNS = 5            # ISBNs tried per book (ESTER lists every edition's ISBN)
COVER_MAX = 3000           # Google cover top-ups per run


def real_cover(data: bytes | None) -> bool:
    """A JPEG that is not Google's placeholder (which also comes as a tiny PNG)."""
    return bool(data) and data[:3] == b"\xff\xd8\xff" and len(data) not in GOOGLE_NO_COVER and len(data) > 3000


def google_cover(isbns: list, f: Fetcher) -> str:
    """Google Books cover URL for the first ISBN that has a real cover, else ''.

    The keyless image endpoint always answers with an image, so the bytes are checked here
    (on X1); the browser later loads the stored URL directly.
    """
    for isbn in isbns[:COVER_ISBNS]:
        url = GOOGLE_COVER.format(isbn=isbn)
        if real_cover(f.bytes(url)):
            return url
    return ""


# --- lookups ---------------------------------------------------------------------------


def lookup(book: dict, f: Fetcher, google_key: str = "") -> dict:
    """Everything we can find for one book. Empty fields when nothing matched."""
    out = {
        "cover_url": "", "summary": "", "summary_source": "", "openlibrary": "", "google_books": "",
        # category signals (crawler/categories.py)
        "ol_lccn": "", "ol_lcc": [], "ol_ddc": [], "ol_subjects": [], "google_categories": [],
    }
    work_key = ""
    covers: list = []
    for isbn in book["isbns"][:COVER_ISBNS]:
        edition = f.json(f"{OL}/isbn/{isbn}.json")
        if edition:
            covers = [c for c in edition.get("covers") or [] if isinstance(c, int) and c > 0]
            works = edition.get("works") or []
            work_key = works[0].get("key", "") if works else ""
            out["openlibrary"] = f"{OL}{edition.get('key', '')}" if edition.get("key") else ""
            out["ol_lccn"] = ((edition.get("lccn") or [""])[0] or "").strip()
            out["ol_lcc"] = [str(x) for x in edition.get("lc_classifications") or []][:3]
            out["ol_ddc"] = [str(x) for x in edition.get("dewey_decimal_class") or []][:3]
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
        out["ol_subjects"] = [str(x) for x in work.get("subjects") or [] if isinstance(x, str)][:25]
        out["summary"] = clean_description(work.get("description"))
        if out["summary"]:
            out["summary_source"] = "openlibrary"
        if not covers:
            covers = [c for c in work.get("covers") or [] if isinstance(c, int) and c > 0]
        out["openlibrary"] = out["openlibrary"] or f"{OL}{work_key}"
    if covers:
        out["cover_url"] = cover_url(covers[0])
    if google_key and (not out["summary"] or not out["cover_url"] or not out["ol_lccn"]) and book["isbns"]:
        q = urllib.parse.urlencode({"q": f"isbn:{book['isbns'][0]}", "maxResults": "1", "key": google_key})
        data = f.json(f"https://www.googleapis.com/books/v1/volumes?{q}") or {}
        items = data.get("items") or []
        if items:
            info = items[0].get("volumeInfo", {})
            out["google_categories"] = [str(c) for c in info.get("categories") or []][:5]
            if not out["summary"] and info.get("description"):
                out["summary"] = clean_description(info["description"])
                out["summary_source"] = "google_books"
            thumb = (info.get("imageLinks") or {}).get("thumbnail", "")
            if not out["cover_url"] and thumb:
                out["cover_url"] = thumb.replace("http://", "https://").replace("&edge=curl", "")
            out["google_books"] = info.get("infoLink", "").replace("http://", "https://")
    if not out["cover_url"] and book["isbns"]:
        out["cover_url"] = google_cover(book["isbns"], f)
        out["gcover"] = 1
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


LOOKUP_VERSION = 2  # 2: also category fields (LCCN, LC/Dewey classes, subjects, Google categories)


def lookup_key(book: dict) -> str:
    return json.dumps(
        [LOOKUP_VERSION, book["isbns"][:3], book["original_title"], book["title"], book["language"]], ensure_ascii=False
    )


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


def book_from_record(rec: dict) -> dict:
    """The lookup input for a parsed ESTER record (same shape as a catalogue row)."""
    return {
        "id": rec["id"], "title": rec["title"], "original_title": rec.get("original_title", ""),
        "language": rec.get("language", ""), "original_language": rec.get("original_language", ""),
        "isbns": rec.get("isbns", []), "authors": json.dumps(rec.get("authors", []), ensure_ascii=False),
    }


def top_up_cover(cache: sqlite3.Connection, book: dict, result: dict, f: Fetcher) -> bool:
    """Google cover for a cached miss that predates the fallback. True if a request was made."""
    if result.get("cover_url") or result.get("gcover") or not book["isbns"]:
        return False
    result["cover_url"] = google_cover(book["isbns"], f)
    result["gcover"] = 1
    cache.execute(
        "UPDATE lookups SET result = ?, hit = ? WHERE book_id = ?",
        (json.dumps(result, ensure_ascii=False), int(bool(result["cover_url"] or result.get("summary"))), book["id"]),
    )
    return True


def prefetch(
    books: list[dict],
    cache_dir: Path,
    log=print,
    max_lookups: int = DEFAULT_MAX,
    fetcher: Fetcher | None = None,
) -> dict:
    """Look up candidate books before the build decides their scope (BOOKS-12).

    Fills the Open Library / Google cache (`lookups`) and, for editions with an LCCN, the
    Library of Congress cache (`loc`, crawler/categories.py). `books` are in priority order;
    at most `max_lookups` Open Library lookups run, and LoC follows each one that found an LCCN.
    Cached answers are reused, so later runs only look up what is new or stale.
    """
    from .categories import Signals  # local: categories imports nothing from here

    cache = open_cache(cache_dir)
    signals = Signals(cache_dir, db=cache)
    google_key = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
    f = fetcher or Fetcher()
    looked = loc_looked = topped = 0
    stopped = ""
    for book in books:
        if stopped or (looked >= max_lookups and topped >= COVER_MAX):
            break
        key = lookup_key(book)
        row = cache.execute("SELECT key, result, hit, fetched_at FROM lookups WHERE book_id = ?", (book["id"],)).fetchone()
        result = json.loads(row[1]) if row else {}
        try:
            if is_fresh(row, key) and result and topped < COVER_MAX:
                topped += top_up_cover(cache, book, result, f)
            elif not is_fresh(row, key) and looked < max_lookups:
                result = lookup(book, f, google_key)
                looked += 1
                hit = int(bool(result["cover_url"] or result["summary"]))
                cache.execute(
                    "INSERT OR REPLACE INTO lookups VALUES (?, ?, ?, ?, ?)",
                    (book["id"], key, json.dumps(result, ensure_ascii=False), hit,
                     dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()),
                )
            lccn = result.get("ol_lccn", "")
            if lccn and signals.loc_due(lccn):
                signals.fetch_loc(lccn, f)
                loc_looked += 1
        except Stop as e:
            stopped = str(e)
            log(f"prefetch: stopped ({stopped}); the rest wait for the next run")
        if (looked + loc_looked) % 25 == 0:
            cache.commit()
        if looked and looked % 250 == 0:
            log(f"prefetch: {looked} looked up, {loc_looked} Library of Congress records")
    signals.close()
    cache.close()
    stats = {"looked_up": looked, "google_covers": topped, "loc": loc_looked, "requests": f.requests, "stopped": stopped}
    log(f"prefetch: {looked} looked up, {topped} cover top-ups, {loc_looked} Library of Congress records ({f.requests} requests)"
        + (f"; stopped: {stopped}" if stopped else ""))
    return stats
