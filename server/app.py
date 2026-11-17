"""Kids Books server: static web/ plus a JSON API. Python 3 standard library only.

    python3 server/app.py --port 8512 --db data/books.db --catalog data/catalog.db

It makes no outbound requests. Search reads catalog.db (built and uploaded by the
X1 crawler); lists live in books.db. Behind Caddy, the user comes from
X-Remote-User (forward-auth); locally it falls back to --dev-user.

/demo/ is the same app without a login (Caddy skips forward-auth there). Its API
(/demo/api/...) reads the same catalogue but keeps lists and hidden books in a
separate demo.db, so nothing done in the demo touches the real lists.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sqlite3
import subprocess
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import db as dbm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
LANGUAGES = {
    "eng": "English", "est": "Estonian", "rus": "Russian", "fin": "Finnish",
    "ger": "German", "swe": "Swedish", "fre": "French", "ukr": "Ukrainian",
    "spa": "Spanish", "ita": "Italian", "lav": "Latvian", "lit": "Lithuanian",
    "mul": "Multiple languages",
}
FIELDS = {"title": "title", "author": "authors", "subject": "subjects"}
PER_PAGE = 48
DEMO_PREFIX = "/demo"
DEMO_USER = "demo"
# The demo is public, so cap what anyone can write into demo.db.
DEMO_MAX_LISTS = 50
DEMO_MAX_ITEMS = 1000
DEMO_MAX_HIDDEN = 500
# v2 facets (crawler/classify.py). Order is display order.
AUDIENCES = {
    "baby_toddler": "Baby & toddler",
    "picture_book": "Picture books",
    "early_reader": "Early readers",
    "middle_grade": "Older children",
    "teen": "Teen",
    "adult": "Adult nature",
}
TYPES = {"fiction": "Fiction", "nonfiction": "Non-fiction", "poetry": "Poetry", "comics": "Comics", "activity": "Activity"}
# `sort=` values; anything else (or none) means relevance when searching, newest first when browsing.
SORTS = {
    "newest": "b.year IS NULL, b.year DESC, b.title COLLATE NOCASE",
    "oldest": "b.year IS NULL, b.year ASC, b.title COLLATE NOCASE",
    "title": "b.title COLLATE NOCASE",
    "shortest": "b.pages IS NULL, b.pages ASC, b.title COLLATE NOCASE",
    "longest": "b.pages IS NULL, b.pages DESC, b.title COLLATE NOCASE",
    "shelf": "b.available_copies DESC, b.title COLLATE NOCASE",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# --- catalogue -----------------------------------------------------------------------


def display_name(name: str) -> str:
    """'Marshall, Natalie' -> 'Natalie Marshall'."""
    if ", " in name:
        last, first = name.split(", ", 1)
        return f"{first} {last}"
    return name


def fts_query(q: str, field: str) -> str:
    words = re.findall(r"[\w'’-]+", q, flags=re.UNICODE)
    col = FIELDS.get(field)
    terms = []
    for w in words:
        w = w.replace('"', "")
        if not w:
            continue
        term = f'"{w}"*'
        terms.append(f"{col}:{term}" if col else term)
    return " AND ".join(terms)


def has_facets(cat: sqlite3.Connection) -> bool:
    """A v2 catalogue (audience/type columns). v1 catalogues still work, without facets."""
    return any(r[1] == "audience" for r in cat.execute("PRAGMA table_info(books)"))


def _multi(params: dict, name: str, allowed: dict) -> list[str]:
    return [v for v in params.get(name, "").split(",") if v in allowed]


def _int(params: dict, name: str) -> int | None:
    try:
        return int(params[name])
    except (KeyError, ValueError):
        return None


def _csv(params: dict, name: str, limit: int = 40) -> list[str]:
    return [v.strip() for v in params.get(name, "").split(",") if v.strip()][:limit]


def book_card(row: sqlite3.Row) -> dict:
    authors = [display_name(a) for a in dbm.loads(row["authors"], [])]
    keys = row.keys()
    audience = row["audience"] if "audience" in keys else ""
    typ = row["type"] if "type" in keys else ""
    return {
        "id": row["id"],
        "title": row["title"],
        "subtitle": row["subtitle"],
        "authors": authors,
        "year": row["year"],
        "language": row["language"],
        "language_name": LANGUAGES.get(row["language"], row["language"]),
        "pages": row["pages"],
        "cover_url": row["cover_url"],
        "tallinn_copies": row["tallinn_copies"],
        "available_copies": row["available_copies"],
        "url": row["url"],
        "audience": audience,
        "audience_label": AUDIENCES.get(audience, "").replace("Adult nature", "Adult"),
        "type": typ,
        "type_label": TYPES.get(typ, ""),
        "nature": bool(row["nature"]) if "nature" in keys else False,
    }


def search(cat: sqlite3.Connection, params: dict, hidden: list[str] | None = None) -> dict:
    """Full-text search plus filters. v2 filters: audience and type (comma-separated, any of),
    topic, and nature=1. Also: year_from/year_to, pages_min/pages_max, branch (comma-separated),
    topics (comma-separated; topics_all=1 wants every one), sort (see SORTS), and adv=1 for the
    topic, branch and year facets. `lang` is accepted and ignored on a v2 catalogue (all English)."""
    q = params.get("q", "").strip()
    field = params.get("field", "any")
    lang = params.get("lang", "any")
    subject = params.get("subject", "").strip()
    topic = params.get("topic", "").strip()
    available = params.get("available") in ("1", "true", "yes")
    nature = params.get("nature") in ("1", "true", "yes")
    facets_on = has_facets(cat)
    audiences = _multi(params, "audience", AUDIENCES) if facets_on else []
    types = _multi(params, "type", TYPES) if facets_on else []
    try:
        page = max(1, int(params.get("page", "1")))
    except ValueError:
        page = 1
    join = ""
    order = "b.year DESC, b.title"
    base: list[tuple[str, list]] = []  # (condition, args) shared by the results and the facet counts
    if q:
        match = fts_query(q, field)
        if not match:
            return {"total": 0, "page": page, "per_page": PER_PAGE, "results": [], "facets": empty_facets(facets_on)}
        join = "JOIN books_fts f ON f.rowid = b.rowid"
        base.append(("books_fts MATCH ?", [match]))
        order = "f.rank"
    if hidden:  # "never show again": one JSON parameter, however many are hidden
        base.append(("b.id NOT IN (SELECT value FROM json_each(?))", [json.dumps(hidden)]))
    if not facets_on:
        if lang in ("eng", "est", "rus"):
            base.append(("b.language = ?", [lang]))
        elif lang == "other":
            base.append(("b.language NOT IN ('eng', 'est')", []))
    if available:
        base.append(("b.available_copies > 0", []))
    if subject and facets_on:  # the chips are v2 topics; Estonian headings still match
        base.append((
            "(b.id IN (SELECT book_id FROM topics WHERE topic = ?) OR b.id IN (SELECT book_id FROM subjects WHERE subject = ?))",
            [subject, subject],
        ))
    elif subject:
        base.append(("b.id IN (SELECT book_id FROM subjects WHERE subject_en = ? OR subject = ?)", [subject, subject]))
    if topic and facets_on:
        base.append(("b.id IN (SELECT book_id FROM topics WHERE topic = ?)", [topic]))
    if nature and facets_on:
        base.append(("b.nature = 1", []))
    year_from, year_to = _int(params, "year_from"), _int(params, "year_to")
    pages_min, pages_max = _int(params, "pages_min"), _int(params, "pages_max")
    if year_from is not None:
        base.append(("b.year >= ?", [year_from]))
    if year_to is not None:
        base.append(("b.year <= ?", [year_to]))
    if pages_min is not None:
        base.append(("b.pages >= ?", [pages_min]))
    if pages_max is not None:
        base.append(("b.pages <= ?", [pages_max]))
    topic_list = _csv(params, "topics") if facets_on else []
    branch_list = _csv(params, "branch")
    topic_cond = branch_cond = None
    if topic_list:
        marks = ",".join("?" * len(topic_list))
        if params.get("topics_all") in ("1", "true", "yes"):  # every chosen topic, not just one of them
            topic_cond = (
                f"b.id IN (SELECT book_id FROM topics WHERE topic IN ({marks}) GROUP BY book_id HAVING count(DISTINCT topic) = ?)",
                topic_list + [len(topic_list)],
            )
        else:
            topic_cond = (f"b.id IN (SELECT book_id FROM topics WHERE topic IN ({marks}))", topic_list)
    if branch_list:
        branch_cond = (
            f"b.id IN (SELECT book_id FROM holdings WHERE branch IN ({','.join('?' * len(branch_list))}))", branch_list)
    aud_cond = (f"b.audience IN ({','.join('?' * len(audiences))})", audiences) if audiences else None
    type_cond = (f"b.type IN ({','.join('?' * len(types))})", types) if types else None

    def where(*conds) -> tuple[str, list]:
        parts = [c for c in conds if c]
        sql = " AND ".join(c[0] for c in parts)
        return ("WHERE " + sql) if sql else "", [a for c in parts for a in c[1]]

    sql_where, args = where(*base, aud_cond, type_cond, topic_cond, branch_cond)
    if params.get("sort") in SORTS:
        order = SORTS[params["sort"]]
    try:
        total = cat.execute(f"SELECT count(*) FROM books b {join} {sql_where}", args).fetchone()[0]
        rows = cat.execute(
            f"SELECT b.* FROM books b {join} {sql_where} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [PER_PAGE, (page - 1) * PER_PAGE],
        ).fetchall()
        facets = empty_facets(facets_on)
        if facets_on:
            # Each facet counts with every other filter applied, so its options stay pickable.
            w, a = where(*base, type_cond, topic_cond, branch_cond)
            counts = dict(cat.execute(f"SELECT b.audience, count(*) FROM books b {join} {w} GROUP BY b.audience", a).fetchall())
            facets["audience"] = [{"value": k, "label": v, "count": counts.get(k, 0)} for k, v in AUDIENCES.items()]
            w, a = where(*base, aud_cond, topic_cond, branch_cond)
            counts = dict(cat.execute(f"SELECT b.type, count(*) FROM books b {join} {w} GROUP BY b.type", a).fetchall())
            facets["type"] = [{"value": k, "label": v, "count": counts.get(k, 0)} for k, v in TYPES.items()]
        if facets_on and params.get("adv") in ("1", "true", "yes"):
            # The long facets: each counts with every other filter applied, like audience and type.
            w, a = where(*base, aud_cond, type_cond, branch_cond)
            rows_t = cat.execute(
                f"""SELECT topic, count(DISTINCT book_id) AS n FROM topics
                    WHERE book_id IN (SELECT b.id FROM books b {join} {w}) GROUP BY topic ORDER BY n DESC, topic LIMIT 40""", a).fetchall()
            seen = {r[0]: r[1] for r in rows_t}
            facets["topics"] = [{"value": k, "label": k, "count": n} for k, n in seen.items()] + [
                {"value": t, "label": t, "count": 0} for t in topic_list if t not in seen]
            w, a = where(*base, aud_cond, type_cond, topic_cond)
            rows_b = cat.execute(
                f"""SELECT branch, count(DISTINCT book_id) AS n FROM holdings
                    WHERE book_id IN (SELECT b.id FROM books b {join} {w}) GROUP BY branch ORDER BY n DESC, branch LIMIT 60""", a).fetchall()
            seen = {r[0]: r[1] for r in rows_b}
            facets["branches"] = [{"value": k, "label": k, "count": n} for k, n in seen.items()] + [
                {"value": t, "label": t, "count": 0} for t in branch_list if t not in seen]
            lo, hi = cat.execute("SELECT min(year), max(year) FROM books WHERE year > 0").fetchone()
            facets["years"] = {"min": lo, "max": hi}
    except sqlite3.OperationalError as e:  # a query FTS5 can't parse
        raise ApiError(400, f"bad search: {e}") from e
    return {
        "total": total, "page": page, "per_page": PER_PAGE,
        "results": [book_card(r) for r in rows], "facets": facets,
    }


def empty_facets(facets_on: bool) -> dict:
    if not facets_on:
        return {}
    return {
        "audience": [{"value": k, "label": v, "count": 0} for k, v in AUDIENCES.items()],
        "type": [{"value": k, "label": v, "count": 0} for k, v in TYPES.items()],
    }


def book_detail(cat: sqlite3.Connection, book_id: str) -> dict | None:
    row = cat.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        return None
    out = book_card(row)
    out.update(
        {
            "responsibility": row["responsibility"],
            "illustrators": [display_name(a) for a in dbm.loads(row["illustrators"], [])],
            "original_language": row["original_language"],
            "original_title": row["original_title"] if "original_title" in row.keys() else "",
            "original_language_name": LANGUAGES.get(row["original_language"], row["original_language"]),
            "isbns": dbm.loads(row["isbns"], []),
            "extent": row["extent"],
            "series": row["series"],
            "notes": row["notes"],
            "summary": row["summary"],
            "summary_source": row["summary_source"],
            "subjects": dbm.loads(row["subjects"], []),
            "subjects_en": dbm.loads(row["subjects_en"], []),
            "genres_en": dbm.loads(row["genres_en"], []),
            "links": dbm.loads(row["links"], {}),
            "holdings_checked_at": row["holdings_checked_at"],
            "topics": dbm.loads(row["topics"], []) if "topics" in row.keys() else [],
            "reasons": dbm.loads(row["reasons"], []) if "reasons" in row.keys() else [],
        }
    )
    branches: dict[str, dict] = {}
    for h in cat.execute(
        "SELECT * FROM holdings WHERE book_id = ? ORDER BY available DESC, branch", (book_id,)
    ):
        b = branches.setdefault(h["branch"], {"branch": h["branch"], "available": 0, "copies": []})
        b["available"] += h["available"]
        b["copies"].append(
            {
                "location": h["location"],
                "call_number": h["call_number"],
                "status": h["status_en"] or h["status"],
                "available": bool(h["available"]),
            }
        )
    out["holdings"] = sorted(branches.values(), key=lambda b: (-b["available"], b["branch"]))
    return out


def subjects(cat: sqlite3.Connection) -> list[dict]:
    """Topic chips: v2 topics (from every source), else v1 subject headings."""
    if has_facets(cat):
        rows = cat.execute(
            """SELECT topic AS subject_en, count(DISTINCT book_id) AS n FROM topics
               GROUP BY topic ORDER BY n DESC LIMIT 60"""
        ).fetchall()
    else:
        rows = cat.execute(
            """SELECT subject_en, count(DISTINCT book_id) AS n FROM subjects
               WHERE subject_en != '' GROUP BY subject_en ORDER BY n DESC LIMIT 60"""
        ).fetchall()
    return [{"subject": r["subject_en"], "books": r["n"]} for r in rows]


# --- lists ---------------------------------------------------------------------------


def list_summary(lists: sqlite3.Connection) -> list[dict]:
    out = []
    for r in lists.execute(
        """SELECT l.*, count(i.book_id) AS n FROM lists l LEFT JOIN list_items i ON i.list_id = l.id
           GROUP BY l.id ORDER BY l.updated_at DESC, l.id DESC"""
    ):
        covers = [
            c[0]
            for c in lists.execute(
                "SELECT cover_url FROM list_items WHERE list_id = ? AND cover_url != '' ORDER BY added_at DESC LIMIT 4",
                (r["id"],),
            )
        ]
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "created_by": r["created_by"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "count": r["n"],
                "covers": covers,
            }
        )
    return out


def list_detail(lists: sqlite3.Connection, list_id: int) -> dict | None:
    r = lists.execute("SELECT * FROM lists WHERE id = ?", (list_id,)).fetchone()
    if r is None:
        return None
    items = [dict(i) for i in lists.execute(
        "SELECT * FROM list_items WHERE list_id = ? ORDER BY added_at DESC, title", (list_id,)
    )]
    return {**dict(r), "items": items, "count": len(items)}


def hidden_ids(lists: sqlite3.Connection) -> list[str]:
    return [r[0] for r in lists.execute("SELECT book_id FROM hidden_books")]


def hidden_list(lists: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in lists.execute("SELECT * FROM hidden_books ORDER BY hidden_at DESC, title")]


def touch(lists: sqlite3.Connection, list_id: int) -> None:
    lists.execute(
        "UPDATE lists SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?", (list_id,)
    )


def item_snapshot(cat: sqlite3.Connection | None, book_id: str, body: dict) -> dict:
    """What a list item stores: from the catalogue when it has the book, else from the request."""
    if cat is not None:
        row = cat.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if row is not None:
            authors = [display_name(a) for a in dbm.loads(row["authors"], [])]
            isbns = dbm.loads(row["isbns"], [])
            return {
                "title": row["title"],
                "author": ", ".join(authors[:2]),
                "year": row["year"],
                "language": row["language"],
                "isbn": isbns[0] if isbns else "",
                "cover_url": row["cover_url"],
                "ester_url": row["url"],
                "goodreads_url": dbm.loads(row["links"], {}).get("goodreads", ""),
            }
    title = str(body.get("title") or "").strip()
    if not title:
        raise ApiError(404, "book not in the catalogue")
    return {
        "title": title[:300],
        "author": str(body.get("author") or "")[:300],
        "year": body.get("year") if isinstance(body.get("year"), int) else None,
        "language": str(body.get("language") or "")[:3],
        "isbn": str(body.get("isbn") or "")[:13],
        "cover_url": _safe_url(body.get("cover_url")),
        "ester_url": f"https://www.ester.ee/record={book_id}~S1*est",
        "goodreads_url": _safe_url(body.get("goodreads_url")),
    }


def _safe_url(value) -> str:
    value = str(value or "")
    return value if value.startswith("https://") else ""


# --- HTTP ----------------------------------------------------------------------------


class App:
    def __init__(
        self, db_path: Path, catalog_path: Path, dev_user: str, quiet: bool = False, demo_db_path: Path | None = None
    ):
        self.quiet = quiet
        self.db_path = db_path
        self.demo_db_path = demo_db_path or db_path.with_name("demo.db")
        self.catalog_path = catalog_path
        self.dev_user = dev_user
        self.sha = git_sha()
        dbm.migrate(db_path)
        dbm.migrate(self.demo_db_path)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "kids-books"
        sys_version = ""

        def log_message(self, fmt, *args):  # one line per request to stderr (journald)
            if not app.quiet:
                sys.stderr.write("%s %s\n" % (self.command, fmt % args))

        # --- plumbing

        demo = False  # set per request by dispatch() for /demo/ paths

        @property
        def user(self) -> str:
            if self.demo:  # no login in the demo; never trust a client-sent X-Remote-User there
                return DEMO_USER
            return (self.headers.get("X-Remote-User") or "").strip() or app.dev_user

        @property
        def lists_path(self) -> Path:
            return app.demo_db_path if self.demo else app.db_path

        def demo_cap(self, db: sqlite3.Connection, sql: str, limit: int, what: str) -> None:
            if self.demo and db.execute(sql).fetchone()[0] >= limit:
                raise ApiError(409, f"the demo holds at most {limit} {what}")

        _deferred: list | None = None

        def send_json(self, status: int, payload) -> None:
            if self._deferred is not None:  # inside a lists transaction: send after commit
                self._deferred.append((status, payload))
                return
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def read_json(self) -> dict:
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("application/json"):
                raise ApiError(415, "send application/json")
            length = int(self.headers.get("Content-Length") or 0)
            if length > 64 * 1024:
                raise ApiError(413, "too large")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except ValueError as e:
                raise ApiError(400, "invalid JSON") from e
            if not isinstance(data, dict):
                raise ApiError(400, "expected a JSON object")
            return data

        def dispatch(self, method: str) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            params = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            self.demo = False
            if path == DEMO_PREFIX and method in ("GET", "HEAD"):
                self.send_response(301)
                self.send_header("Location", DEMO_PREFIX + "/" + ("?" + parsed.query if parsed.query else ""))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path.startswith(DEMO_PREFIX + "/"):
                self.demo = True
                path = path[len(DEMO_PREFIX):]
            try:
                if path.startswith("/api/"):
                    self.api(method, path, params)
                elif method in ("GET", "HEAD"):
                    self.static(path, head=method == "HEAD")
                else:
                    raise ApiError(405, "method not allowed")
            except ApiError as e:
                self.send_json(e.status, {"error": e.message})
            except sqlite3.Error as e:
                self.send_json(500, {"error": f"database error: {e}"})

        def do_GET(self):
            self.dispatch("GET")

        def do_HEAD(self):
            self.dispatch("HEAD")

        def do_POST(self):
            self.dispatch("POST")

        def do_PATCH(self):
            self.dispatch("PATCH")

        def do_DELETE(self):
            self.dispatch("DELETE")

        # --- static files

        def static(self, path: str, head: bool = False) -> None:
            rel = urllib.parse.unquote(path).lstrip("/") or "index.html"
            target = (WEB / rel).resolve()
            if WEB.resolve() not in target.parents and target != WEB.resolve():
                raise ApiError(404, "not found")
            if target.is_dir() or not target.is_file():
                # client-side routes fall back to the app shell
                if "." in Path(rel).name:
                    raise ApiError(404, "not found")
                target = WEB / "index.html"
            body = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if not head:
                self.wfile.write(body)

        # --- API

        def api(self, method: str, path: str, params: dict) -> None:
            parts = [p for p in path.split("/")[2:] if p]
            if parts == ["health"] and method == "GET":
                cat = dbm.connect_catalog(app.catalog_path)
                try:
                    meta = dbm.catalog_meta(cat)
                finally:
                    if cat:
                        cat.close()
                return self.send_json(
                    200, {"ok": True, "git_sha": app.sha, "version": app.sha[:7], "catalog": meta, "demo": self.demo}
                )
            if parts == ["me"] and method == "GET":
                return self.send_json(200, {"user": self.user, "demo": self.demo})
            if parts and parts[0] in ("search", "books", "subjects"):
                return self.catalog_api(method, parts, params)
            if parts and parts[0] == "lists":
                return self.lists_api(method, parts[1:])
            if parts and parts[0] == "hidden":
                return self.hidden_api(method, parts[1:])
            raise ApiError(404, "not found")

        def catalog_api(self, method: str, parts: list[str], params: dict) -> None:
            if method != "GET":
                raise ApiError(405, "method not allowed")
            cat = dbm.connect_catalog(app.catalog_path)
            if cat is None:
                if parts == ["search"]:
                    return self.send_json(200, {"total": 0, "page": 1, "per_page": PER_PAGE, "results": [], "catalog": None})
                if parts == ["subjects"]:
                    return self.send_json(200, [])
                raise ApiError(404, "no catalogue yet")
            try:
                if parts == ["search"]:
                    lists = dbm.connect_lists(self.lists_path)
                    try:
                        hidden = hidden_ids(lists)
                    finally:
                        lists.close()
                    return self.send_json(200, search(cat, params, hidden))
                if parts == ["subjects"]:
                    return self.send_json(200, subjects(cat))
                if len(parts) == 2 and parts[0] == "books":
                    book = book_detail(cat, parts[1])
                    if book is None:
                        raise ApiError(404, "book not found")
                    lists = dbm.connect_lists(self.lists_path)
                    try:
                        book["lists"] = [
                            r[0] for r in lists.execute("SELECT list_id FROM list_items WHERE book_id = ?", (parts[1],))
                        ]
                        book["hidden"] = lists.execute(
                            "SELECT 1 FROM hidden_books WHERE book_id = ?", (parts[1],)
                        ).fetchone() is not None
                    finally:
                        lists.close()
                    return self.send_json(200, book)
            finally:
                cat.close()
            raise ApiError(404, "not found")

        def hidden_api(self, method: str, parts: list[str]) -> None:
            """GET /hidden; POST /hidden {book_id}; DELETE /hidden/<book_id> (idempotent)."""
            lists = dbm.connect_lists(self.lists_path)
            try:
                with lists:
                    if not parts and method == "GET":
                        out = hidden_list(lists)
                    elif not parts and method == "POST":
                        body = self.read_json()
                        book_id = str(body.get("book_id") or "").strip()
                        if not re.fullmatch(r"b\d{5,9}", book_id):
                            raise ApiError(400, "book_id must be an ESTER record id like b5260625")
                        self.demo_cap(lists, "SELECT count(*) FROM hidden_books", DEMO_MAX_HIDDEN, "hidden books")
                        cat = dbm.connect_catalog(app.catalog_path)
                        try:
                            snap = item_snapshot(cat, book_id, body)
                        finally:
                            if cat:
                                cat.close()
                        lists.execute(
                            "INSERT OR IGNORE INTO hidden_books (book_id, title, author, cover_url, hidden_by) VALUES (?, ?, ?, ?, ?)",
                            (book_id, snap["title"], snap["author"], snap["cover_url"], self.user),
                        )
                        out = hidden_list(lists)
                    elif len(parts) == 1 and method == "DELETE":
                        lists.execute("DELETE FROM hidden_books WHERE book_id = ?", (parts[0],))
                        out = hidden_list(lists)
                    else:
                        raise ApiError(405 if method not in ("GET", "POST", "DELETE") else 404, "not found")
            finally:
                lists.close()
            self.send_json(200 if method != "POST" else 201, out)

        def lists_api(self, method: str, parts: list[str]) -> None:
            lists = dbm.connect_lists(self.lists_path)
            self._deferred = []
            try:
                with lists:  # commits on success, rolls back on ApiError
                    self._lists(lists, method, parts)
                responses = self._deferred
            finally:
                self._deferred = None
                lists.close()
            for status, payload in responses:
                self.send_json(status, payload)

        def _lists(self, lists: sqlite3.Connection, method: str, parts: list[str]) -> None:
            if not parts:
                if method == "GET":
                    return self.send_json(200, list_summary(lists))
                if method == "POST":
                    name = str(self.read_json().get("name") or "").strip()[:120]
                    if not name:
                        raise ApiError(400, "name is required")
                    self.demo_cap(lists, "SELECT count(*) FROM lists", DEMO_MAX_LISTS, "lists")
                    cur = lists.execute("INSERT INTO lists (name, created_by) VALUES (?, ?)", (name, self.user))
                    return self.send_json(201, list_detail(lists, cur.lastrowid))
                raise ApiError(405, "method not allowed")
            try:
                list_id = int(parts[0])
            except ValueError as e:
                raise ApiError(404, "not found") from e
            current = list_detail(lists, list_id)
            if current is None:
                raise ApiError(404, "list not found")
            if len(parts) == 1:
                if method == "GET":
                    cat = dbm.connect_catalog(app.catalog_path)
                    try:
                        for item in current["items"]:
                            item["in_catalogue"] = cat is None or cat.execute(
                                "SELECT 1 FROM books WHERE id = ?", (item["book_id"],)
                            ).fetchone() is not None
                    finally:
                        if cat:
                            cat.close()
                    return self.send_json(200, current)
                if method == "PATCH":
                    name = str(self.read_json().get("name") or "").strip()[:120]
                    if not name:
                        raise ApiError(400, "name is required")
                    lists.execute("UPDATE lists SET name = ? WHERE id = ?", (name, list_id))
                    touch(lists, list_id)
                    return self.send_json(200, list_detail(lists, list_id))
                if method == "DELETE":
                    lists.execute("DELETE FROM lists WHERE id = ?", (list_id,))
                    return self.send_json(200, {"deleted": list_id})
                raise ApiError(405, "method not allowed")
            if parts[1] != "items":
                raise ApiError(404, "not found")
            if len(parts) == 2 and method == "POST":
                body = self.read_json()
                book_id = str(body.get("book_id") or "").strip()
                if not re.fullmatch(r"b\d{5,9}", book_id):
                    raise ApiError(400, "book_id must be an ESTER record id like b5260625")
                self.demo_cap(lists, "SELECT count(*) FROM list_items", DEMO_MAX_ITEMS, "saved books")
                cat = dbm.connect_catalog(app.catalog_path)
                try:
                    snap = item_snapshot(cat, book_id, body)
                finally:
                    if cat:
                        cat.close()
                note = str(body.get("note") or "")[:500]
                lists.execute(
                    """INSERT INTO list_items (list_id, book_id, title, author, year, language, isbn, cover_url,
                           ester_url, goodreads_url, note, added_by)
                       VALUES (:list_id, :book_id, :title, :author, :year, :language, :isbn, :cover_url,
                           :ester_url, :goodreads_url, :note, :added_by)
                       ON CONFLICT(list_id, book_id) DO UPDATE SET note = CASE WHEN excluded.note != ''
                           THEN excluded.note ELSE list_items.note END""",
                    {**snap, "list_id": list_id, "book_id": book_id, "note": note, "added_by": self.user},
                )
                touch(lists, list_id)
                return self.send_json(201, list_detail(lists, list_id))
            if len(parts) == 3:
                book_id = parts[2]
                exists = lists.execute(
                    "SELECT 1 FROM list_items WHERE list_id = ? AND book_id = ?", (list_id, book_id)
                ).fetchone()
                if not exists:
                    raise ApiError(404, "book not on this list")
                if method == "PATCH":
                    note = str(self.read_json().get("note") or "")[:500]
                    lists.execute(
                        "UPDATE list_items SET note = ? WHERE list_id = ? AND book_id = ?", (note, list_id, book_id)
                    )
                    touch(lists, list_id)
                    return self.send_json(200, list_detail(lists, list_id))
                if method == "DELETE":
                    lists.execute("DELETE FROM list_items WHERE list_id = ? AND book_id = ?", (list_id, book_id))
                    touch(lists, list_id)
                    return self.send_json(200, list_detail(lists, list_id))
            raise ApiError(405, "method not allowed")

    return Handler


def serve(
    host: str, port: int, db_path: Path, catalog_path: Path, dev_user: str = "dev", quiet: bool = False,
    demo_db_path: Path | None = None,
) -> ThreadingHTTPServer:
    app = App(db_path, catalog_path, dev_user, quiet, demo_db_path)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    return httpd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kids Books server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8512)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "books.db")
    ap.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog.db")
    ap.add_argument("--demo-db", type=Path, default=None, help="lists DB for /demo/ (default: demo.db next to --db)")
    ap.add_argument("--dev-user", default="dev", help="user when there is no X-Remote-User header")
    args = ap.parse_args(argv)
    httpd = serve(args.host, args.port, args.db, args.catalog, args.dev_user, demo_db_path=args.demo_db)
    print(f"kids-books on http://{args.host}:{args.port} (catalog {args.catalog}, lists {args.db})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
