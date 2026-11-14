"""Kids Books server: static web/ plus a JSON API. Python 3 standard library only.

    python3 server/app.py --port 8512 --db data/books.db --catalog data/catalog.db

It makes no outbound requests. Search reads catalog.db (built and uploaded by the
X1 crawler); lists live in books.db. Behind Caddy, the user comes from
X-Remote-User (forward-auth); locally it falls back to --dev-user.
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


def book_card(row: sqlite3.Row) -> dict:
    authors = [display_name(a) for a in dbm.loads(row["authors"], [])]
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
    }


def search(cat: sqlite3.Connection, params: dict) -> dict:
    q = params.get("q", "").strip()
    field = params.get("field", "any")
    lang = params.get("lang", "any")
    subject = params.get("subject", "").strip()
    available = params.get("available") in ("1", "true", "yes")
    try:
        page = max(1, int(params.get("page", "1")))
    except ValueError:
        page = 1
    where, args = [], []
    join = ""
    order = "b.year DESC, b.title"
    if q:
        match = fts_query(q, field)
        if not match:
            return {"total": 0, "page": page, "per_page": PER_PAGE, "results": []}
        join = "JOIN books_fts f ON f.rowid = b.rowid"
        where.append("books_fts MATCH ?")
        args.append(match)
        order = "f.rank"
    if lang in ("eng", "est", "rus"):
        where.append("b.language = ?")
        args.append(lang)
    elif lang == "other":
        where.append("b.language NOT IN ('eng', 'est')")
    if available:
        where.append("b.available_copies > 0")
    if subject:
        where.append("b.id IN (SELECT book_id FROM subjects WHERE subject_en = ? OR subject = ?)")
        args += [subject, subject]
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        total = cat.execute(f"SELECT count(*) FROM books b {join} {sql_where}", args).fetchone()[0]
        rows = cat.execute(
            f"SELECT b.* FROM books b {join} {sql_where} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [PER_PAGE, (page - 1) * PER_PAGE],
        ).fetchall()
    except sqlite3.OperationalError as e:  # a query FTS5 can't parse
        raise ApiError(400, f"bad search: {e}") from e
    return {"total": total, "page": page, "per_page": PER_PAGE, "results": [book_card(r) for r in rows]}


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
    def __init__(self, db_path: Path, catalog_path: Path, dev_user: str, quiet: bool = False):
        self.quiet = quiet
        self.db_path = db_path
        self.catalog_path = catalog_path
        self.dev_user = dev_user
        self.sha = git_sha()
        dbm.migrate(db_path)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "kids-books"
        sys_version = ""

        def log_message(self, fmt, *args):  # one line per request to stderr (journald)
            if not app.quiet:
                sys.stderr.write("%s %s\n" % (self.command, fmt % args))

        # --- plumbing

        @property
        def user(self) -> str:
            return (self.headers.get("X-Remote-User") or "").strip() or app.dev_user

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
                return self.send_json(200, {"ok": True, "git_sha": app.sha, "version": app.sha[:7], "catalog": meta})
            if parts == ["me"] and method == "GET":
                return self.send_json(200, {"user": self.user})
            if parts and parts[0] in ("search", "books", "subjects"):
                return self.catalog_api(method, parts, params)
            if parts and parts[0] == "lists":
                return self.lists_api(method, parts[1:])
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
                    return self.send_json(200, search(cat, params))
                if parts == ["subjects"]:
                    return self.send_json(200, subjects(cat))
                if len(parts) == 2 and parts[0] == "books":
                    book = book_detail(cat, parts[1])
                    if book is None:
                        raise ApiError(404, "book not found")
                    lists = dbm.connect_lists(app.db_path)
                    try:
                        book["lists"] = [
                            r[0] for r in lists.execute("SELECT list_id FROM list_items WHERE book_id = ?", (parts[1],))
                        ]
                    finally:
                        lists.close()
                    return self.send_json(200, book)
            finally:
                cat.close()
            raise ApiError(404, "not found")

        def lists_api(self, method: str, parts: list[str]) -> None:
            lists = dbm.connect_lists(app.db_path)
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
    host: str, port: int, db_path: Path, catalog_path: Path, dev_user: str = "dev", quiet: bool = False
) -> ThreadingHTTPServer:
    app = App(db_path, catalog_path, dev_user, quiet)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    return httpd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kids Books server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8512)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "books.db")
    ap.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog.db")
    ap.add_argument("--dev-user", default="dev", help="user when there is no X-Remote-User header")
    args = ap.parse_args(argv)
    httpd = serve(args.host, args.port, args.db, args.catalog, args.dev_user)
    print(f"kids-books on http://{args.host}:{args.port} (catalog {args.catalog}, lists {args.db})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
