"""ESTER (Sierra WebPAC) client and parsers. Runs on X1 only.

ESTER has no JSON API. Two pages are enough:

- The browse list for the genre heading "pildiraamatud (vormimärksõna)": 50 brief
  citations per page with record id, title, publisher, extent, ISBN and the libraries
  that hold a copy. We use it to discover records and keep only those Tallinn holds.
- The MARC view of a record (`.../marc~b1234567`): the raw MARC fields in a <pre>
  block plus the holdings table (location, call number, status). One request per book.
"""
from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .terms import EXCLUDED_GENRES

BASE = "https://www.ester.ee"
USER_AGENT = "kids-books/0.1 (personal picture-book finder)"

# The genre heading every picture book carries. Its browse list is the crawl seed.
GENRE_KEY = "dpildiraamatud+vormimw~brksw~ana+https+ems+elnet+ee+id+ems014937"
GENRE_PREFIX = "/search~S1*est?/dpildiraamatud/dpildiraamatud/1%2C4%2C9244%2CB/exact&FF="

TALLINN_PREFIX = "TlnRK"  # Tallinna Keskraamatukogu and its branches
ONLINE_MARKERS = ("e-raamatukogu", "OverDrive")


class EsterError(Exception):
    """ESTER refused or failed repeatedly; the crawl should stop (exit 75)."""


# --- fetching -----------------------------------------------------------------


class Client:
    """One request at a time, with a delay and a few retries."""

    def __init__(self, delay: float = 1.0, retries: int = 3, timeout: float = 30.0):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0
        self.requests = 0

    def get(self, path: str) -> str:
        url = path if path.startswith("http") else BASE + path
        error = ""
        for attempt in range(self.retries):
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                error = f"HTTP {e.code}"
                if e.code in (403, 429):
                    raise EsterError(f"ESTER refused the request ({error}): {url}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                error = str(e)
            time.sleep(self.delay * 5 * (attempt + 1))
        raise EsterError(f"ESTER failed {self.retries} times ({error}): {url}")


def genre_page_path(offset: int, total: int = 9166) -> str:
    """Browse-list page starting at `offset` (1-based, steps of 50)."""
    return f"{GENRE_PREFIX}{GENRE_KEY}&{offset}%2C{total}%2C"


def marc_path(record_id: str) -> str:
    rid = record_id.lstrip("b")
    return f"/search~S1*est?/.b{rid}/.b{rid}/1%2C1%2C1%2CB/marc~b{rid}"


def permalink(record_id: str) -> str:
    return f"{BASE}/record=b{record_id.lstrip('b')}~S1*est"


# --- small helpers ----------------------------------------------------------------


def _text(fragment: str) -> str:
    fragment = re.sub(r"<!--.*?-->", "", fragment, flags=re.S)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = html.unescape(fragment).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", fragment).strip()


def parse_pages(extent: str) -> int | None:
    """Page count from a MARC 300 / brief extent.

    '[10] lk.' -> 10, '96, [1] lk.' -> 97, '20 nummerdamata lehekülge' -> 20,
    '1 volume' -> None.
    """
    if not extent:
        return None
    m = re.match(r"^\s*((?:\[?\d+\]?\s*,\s*)*\[?\d+\]?)\s*(?:nummerdamata\s+)?(?:lk|lehek|pages?\b|p\.|unnumbered)", extent)
    if not m:
        return None
    return sum(int(n) for n in re.findall(r"\d+", m.group(1))) or None


# --- browse list ----------------------------------------------------------------


def parse_list(page: str) -> dict:
    """Brief citations on one browse-list page, plus the total and the next offset."""
    total = None
    m = re.search(r"\(\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*\)", page)
    if m:
        total = int(m.group(3))
    results = []
    for block in re.split(r'<div class="result-item box"', page)[1:]:
        rid = re.search(r'name="save" value="(b\d+)"', block)
        if not rid:
            continue
        title = re.search(r'<h2 class="title">\s*<a[^>]*>(.*?)</a>', block, re.S)
        spans = [_text(s) for s in re.findall(r'<span class="remove-if-empty">(.*?)</span>', block, re.S)]
        spans = [s for s in spans if s]
        isbn = re.search(r'<span class="isbn-issn">(.*?)</span>', block, re.S)
        status = re.search(r'<div class="briefcitStatus[^"]*">(.*?)</div>', block, re.S)
        year = re.search(r'itemprop="datePublished">\s*(\d{4})', block)
        libraries = [s.strip() for s in _text(status.group(1)).split(",")] if status else []
        results.append(
            {
                "id": rid.group(1),
                "title": _text(title.group(1)) if title else "",
                "imprint": spans[0] if spans else "",
                "extent": spans[1] if len(spans) > 1 else "",
                "isbns": isbns_from(_text(isbn.group(1)) if isbn else ""),
                "libraries": [lib for lib in libraries if lib],
                "year": int(year.group(1)) if year else None,
            }
        )
    next_offset = None
    offsets = sorted({int(o) for o in re.findall(r"exact&FF=[^\"&]+&(\d+),\d+\"", page)})
    current = _current_offset(page)
    later = [o for o in offsets if current is None or o > current]
    if later:
        next_offset = later[0]
    return {"total": total, "results": results, "next_offset": next_offset}


def _current_offset(page: str) -> int | None:
    m = re.search(r"\(\s*(\d+)\s*-\s*\d+\s*-\s*\d+\s*\)", page)
    return int(m.group(1)) if m else None


def isbns_from(text: str) -> list[str]:
    out = []
    for raw in re.findall(r"[0-9Xx][0-9Xx\-]{8,16}", text):
        digits = raw.replace("-", "").upper()
        if len(digits) in (10, 13) and digits not in out:
            out.append(digits)
    return out


def held_in_tallinn(libraries: list[str]) -> bool:
    return any(
        lib.startswith(TALLINN_PREFIX) and not any(m in lib for m in ONLINE_MARKERS)
        for lib in libraries
    )


# --- MARC view ----------------------------------------------------------------------


def parse_marc_fields(page: str) -> list[tuple[str, str, str]]:
    """(tag, indicators, data) for each MARC field in the <pre> block."""
    m = re.search(r"<pre[^>]*>(.*?)</pre>", page, re.S)
    if not m:
        return []
    # Keep the whitespace: MARC lines are fixed columns. "245 10 data", "008    data",
    # continuation lines are indented by 7 spaces.
    raw = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).replace("\xa0", " ")
    fields: list[list[str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("LEADER"):
            fields.append(["LEADER", "", line[6:].strip()])
        elif re.match(r"^\d{3} ", line):
            tag = line[:3]
            if tag < "010":
                fields.append([tag, "", line[7:]])
            else:
                fields.append([tag, line[4:6], line[7:].strip()])
        elif fields:  # continuation line
            prev = fields[-1][2]
            piece = line.strip()
            fields[-1][2] = prev + piece if prev.endswith("/") else prev + " " + piece
    return [(t, i, d) for t, i, d in fields]


def subfields(data: str) -> dict[str, list[str]]:
    """'a text|bmore|cauthor' -> {'a': [...], 'b': [...]}; leading text without a code is 'a'."""
    parts = data.split("|")
    out: dict[str, list[str]] = {}
    first = parts[0].strip()
    if first:
        out.setdefault("a", []).append(first)
    for p in parts[1:]:
        if p:
            out.setdefault(p[0], []).append(p[1:].strip())
    return out


def _clean(value: str) -> str:
    return re.sub(r"\s*[/:;,.=]\s*$", "", value.strip()).strip()


def _heading(value: str) -> str:
    return re.sub(r"\s*\((vormimärksõna)\)\s*$", "", _clean(value))


def parse_holdings(page: str) -> list[dict]:
    rows = []
    for row in re.findall(r'<tr\s+class="bibItemsEntry">(.*?)</tr>', page, re.S):
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 3:
            rows.append(
                {
                    "location": cells[0],
                    "call_number": cells[1],
                    "status": cells[2],
                    "note": cells[3] if len(cells) > 3 else "",
                }
            )
    return rows


def parse_record(page: str, record_id: str) -> dict:
    """Bibliographic data and holdings from a MARC-view page."""
    fields = parse_marc_fields(page)
    rec: dict = {
        "id": record_id,
        "url": permalink(record_id),
        "title": "",
        "subtitle": "",
        "responsibility": "",
        "authors": [],
        "illustrators": [],
        "year": None,
        "language": "",
        "original_language": "",
        "isbns": [],
        "extent": "",
        "pages": None,
        "series": "",
        "summary": "",
        "subjects": [],
        "genres": [],
        "audience": "",
        "holdings": parse_holdings(page),
    }
    for tag, _ind, data in fields:
        sf = subfields(data)
        if tag == "008" and len(data) >= 38:
            rec["language"] = data[35:38].strip("| ")
            year = data[7:11]
            if year.isdigit():
                rec["year"] = int(year)
            rec["audience"] = data[22].strip("| ")
        elif tag == "020":
            rec["isbns"] += [i for i in isbns_from(" ".join(sf.get("a", []))) if i not in rec["isbns"]]
        elif tag == "041":
            orig = sf.get("h", [])
            if orig:
                rec["original_language"] = orig[0][:3]
        elif tag == "100":
            rec["authors"].append(_clean(sf.get("a", [""])[0]))
        elif tag == "700":
            name = _clean(sf.get("a", [""])[0])
            roles = " ".join(sf.get("e", []) + sf.get("4", []))
            if re.search(r"illustr|kunstnik|joonista|ill\b", roles):
                rec["illustrators"].append(name)
            elif re.search(r"autor|author|aut\b", roles) or not roles:
                rec["authors"].append(name)
        elif tag == "245":
            rec["title"] = _clean(sf.get("a", [""])[0])
            rec["subtitle"] = _clean(" ".join(sf.get("b", [])))
            rec["responsibility"] = _clean(" ".join(sf.get("c", [])))
        elif tag in ("260", "264") and rec["year"] is None:
            m = re.search(r"(\d{4})", " ".join(sf.get("c", [])))
            if m:
                rec["year"] = int(m.group(1))
        elif tag == "300":
            rec["extent"] = _clean(" ".join(v for k in "ab" for v in sf.get(k, [])))
            rec["pages"] = parse_pages(rec["extent"])
        elif tag == "490" and not rec["series"]:
            rec["series"] = _clean(sf.get("a", [""])[0])
        elif tag == "520":
            rec["summary"] = (rec["summary"] + "\n" + _clean(sf.get("a", [""])[0])).strip()
        elif tag in ("650", "651"):
            value = _heading(sf.get("a", [""])[0])
            if value and value not in rec["subjects"]:
                rec["subjects"].append(value)
        elif tag == "655":
            value = _heading(sf.get("a", [""])[0])
            if value and value not in rec["genres"]:
                rec["genres"].append(value)
    if not rec["year"]:
        rec["year"] = None
    rec["authors"] = [a for a in dict.fromkeys(rec["authors"]) if a]
    rec["illustrators"] = [a for a in dict.fromkeys(rec["illustrators"]) if a]
    return rec


# --- the picture-book rule -----------------------------------------------------------

MAX_PAGES = 64
NOVEL_GENRES = {"romaanid", "jutustused", "lühiromaanid", "noorsooromaanid"}


def is_picture_book(rec: dict) -> tuple[bool, str]:
    """Keep a record when it is a picture book a toddler could read.

    1. It carries the genre heading "pildiraamatud" (form heading).
    2. Its page count, when known, is at most 64 (picture books run 12-48).
    3. A novel/story genre on a book longer than 48 pages means it's an
       illustrated chapter book, not a picture book.
    """
    genres = {g.lower() for g in rec.get("genres", [])}
    if "pildiraamatud" not in genres:
        return False, "no picture-book genre"
    excluded = genres & EXCLUDED_GENRES
    if excluded:
        return False, f"genre {sorted(excluded)[0]}"
    pages = rec.get("pages")
    if pages and pages > MAX_PAGES:
        return False, f"{pages} pages"
    if pages and pages > 48 and genres & NOVEL_GENRES:
        return False, f"{pages} pages and genre {sorted(genres & NOVEL_GENRES)[0]}"
    return True, ""


def tallinn_holdings(holdings: list[dict]) -> list[dict]:
    return [
        h
        for h in holdings
        if h["location"].startswith(TALLINN_PREFIX)
        and not any(m in h["location"] for m in ONLINE_MARKERS)
    ]


def is_available(status: str) -> bool:
    return status.strip().upper() == "KOHAL"
