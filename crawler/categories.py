"""Outside category signals for the classifier. Runs on X1 only, inside crawler.run.

Sources, in the order classify.py trusts them after ESTER:

1. Library of Congress: the full MARC record by LCCN (`https://lccn.loc.gov/{lccn}/marcxml`).
   The LCCN comes from the Open Library edition (enrich.py). LoC's SRU ISBN index returns
   nothing (probed 14 Nov 2026), so there is no direct ISBN lookup. Used fields: 050 LC
   class (PZ = juvenile belles lettres; QB/QC851-999/QE/QH-QL = the natural world), 082
   Dewey ("[E]" easy/picture book, "[Fic]" juvenile fiction, 5xx sciences), 650/655
   subjects and genres with their "Juvenile fiction" / "Juvenile literature" subdivisions,
   008/22 target audience, 008/33 literary form, 521 audience notes ("Ages 3-7").
2. Google Books categories (BISAC-style "Juvenile Nonfiction / Science & Nature / Weather"),
   only when GOOGLE_BOOKS_API_KEY is set; enrich.py stores them with its lookup.
3. Open Library work subjects and edition Dewey / LC classes (noisy; lowest weight).

Each signal is a dict {source, scheme, code, label} plus whatever it implies:
`audience` (one of classify.AUDIENCES, or "children" when only "juvenile" is known),
`type`, `nature` (bool) and `topics` (English tags).

LoC lookups are cached in ~/.cache/kids-books/enrich.db (table `loc`), hits for 90 days,
misses for 30.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

LOC = "https://lccn.loc.gov"
NS = {"m": "http://www.loc.gov/MARC21/slim"}
HIT_DAYS, MISS_DAYS = 90, 30

# Main headings (LCSH, Google category parts, Open Library subjects), lower case, to
# English topic tags. A heading in NATURE_TOPICS marks the book as about the natural world.
HEADING_TOPICS = {
    "animals": "animals", "birds": "birds", "bird watching": "birdwatching", "insects": "insects",
    "butterflies": "butterflies", "bees": "bees", "fishes": "fish", "fish": "fish", "mammals": "mammals",
    "reptiles": "reptiles", "amphibians": "amphibians", "frogs": "frogs", "dinosaurs": "dinosaurs",
    "marine animals": "sea creatures", "whales": "whales", "sharks": "sharks", "pets": "pets",
    "dogs": "dogs", "cats": "cats", "horses": "horses", "bears": "bears", "wolves": "wolves",
    "foxes": "foxes", "owls": "owls", "rabbits": "rabbits", "mice": "mice", "plants": "plants",
    "trees": "trees", "flowers": "flowers", "wild flowers": "flowers", "mushrooms": "fungi", "fungi": "fungi",
    "weather": "weather", "meteorology": "weather", "climatic changes": "climate change",
    "climate change": "climate change", "clouds": "clouds", "rain and rainfall": "rain", "snow": "snow",
    "storms": "storms", "seasons": "seasons", "natural history": "nature", "nature": "nature",
    "ecology": "ecology", "environmental protection": "the environment", "environment": "the environment",
    "nature conservation": "nature conservation", "astronomy": "space", "outer space": "space",
    "space": "space", "planets": "planets", "solar system": "the solar system", "stars": "stars",
    "moon": "the moon", "geology": "geology", "rocks": "rocks", "minerals": "minerals",
    "volcanoes": "volcanoes", "earthquakes": "earthquakes", "oceans": "oceans", "ocean": "oceans",
    "seashore": "the beach", "forests and forestry": "forests", "forests": "forests", "rivers": "rivers",
    "mountains": "mountains", "fossils": "fossils", "evolution": "evolution", "human body": "the human body",
    "science": "science", "family": "family", "friendship": "friendship", "bedtime": "bedtime",
    "christmas": "Christmas", "emotions": "feelings", "feelings": "feelings", "trucks": "trucks",
    "trains": "trains", "vehicles": "vehicles", "transportation": "vehicles", "counting": "counting",
    "alphabet": "alphabet", "colors": "colours", "shapes": "shapes", "school": "school",
    "fairy tales": "fairy tales", "humorous stories": "humour", "humor": "humour",
}
NATURE_TOPICS = {
    "animals", "birds", "birdwatching", "insects", "butterflies", "bees", "fish", "mammals", "reptiles",
    "amphibians", "frogs", "dinosaurs", "sea creatures", "whales", "sharks", "plants", "trees", "flowers",
    "fungi", "weather", "climate change", "clouds", "rain", "snow", "storms", "seasons", "nature",
    "ecology", "the environment", "nature conservation", "space", "planets", "the solar system", "stars",
    "the moon", "geology", "rocks", "minerals", "volcanoes", "earthquakes", "oceans", "forests",
    "rivers", "mountains", "fossils", "evolution", "bears", "wolves", "foxes", "owls",
}

AUDIENCE_008 = {"a": "picture_book", "b": "early_reader", "c": "middle_grade", "d": "teen", "j": "children",
                "e": "adult", "f": "adult", "g": ""}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# --- Library of Congress -------------------------------------------------------------------


def lccn_path(lccn: str) -> str:
    return f"{LOC}/{re.sub(r'[^0-9a-z]', '', lccn.lower())}/marcxml"


def parse_loc(xml_text: str) -> dict:
    """The fields we use from one MARCXML record. Empty dict when it isn't a record."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    rec = root if root.tag.endswith("record") else root.find(".//m:record", NS)
    if rec is None:
        return {}
    out: dict = {"lcc": [], "ddc": [], "subjects": [], "genres": [], "audience008": "", "form008": "", "notes521": []}
    for cf in rec.findall("m:controlfield", NS):
        if cf.get("tag") == "008" and cf.text and len(cf.text) >= 34:
            out["audience008"] = cf.text[22].strip("| ")
            out["form008"] = cf.text[33].strip("| ")
    for df in rec.findall("m:datafield", NS):
        tag = df.get("tag")
        sub = [(s.get("code"), (s.text or "").strip()) for s in df.findall("m:subfield", NS)]
        a = next((v for c, v in sub if c == "a"), "")
        if tag == "050" and a:
            out["lcc"].append(a)
        elif tag == "082" and a:
            out["ddc"].append(a)
        elif tag in ("650", "651") and a:
            subdiv = [v.rstrip(". ") for c, v in sub if c in "vx"]
            out["subjects"].append({"heading": a.rstrip(". "), "subdivisions": subdiv})
        elif tag == "655" and a:
            out["genres"].append(a.rstrip(". "))
        elif tag == "521" and a:
            out["notes521"].append(a)
    return out


def _lcc_nature(lcc: str) -> bool:
    m = re.match(r"([A-Z]{1,3})\s*(\d+)?", lcc.upper())
    if not m:
        return False
    cls, num = m.group(1), int(m.group(2) or 0)
    if cls in ("QB", "QE", "QH", "QK", "QL"):
        return True
    return cls == "QC" and 851 <= num <= 999


def _ddc_nature(ddc: str) -> bool:
    m = re.match(r"\[?([JE]\s*)?(\d{3})", ddc.upper())
    if not m:
        return False
    n = int(m.group(2))
    return n == 508 or 520 <= n <= 529 or 550 <= n <= 599


def _ages(note: str) -> str:
    """'Ages 3-7.' -> picture_book; 'Grades 4-7' -> middle_grade; '' when unknown."""
    text = note.lower()
    m = re.search(r"ages?\s*(\d{1,2})\s*(?:-|to|–)?\s*(\d{1,2})?", text)
    if m:
        low = int(m.group(1))
        return "baby_toddler" if low <= 2 else "picture_book" if low <= 5 else "early_reader" if low <= 7 else "middle_grade" if low <= 11 else "teen"
    m = re.search(r"grades?\s*(k|p|\d{1,2})", text)
    if m:
        g = m.group(1)
        low = 0 if g in ("k", "p") else int(g)
        return "picture_book" if low == 0 else "early_reader" if low <= 2 else "middle_grade" if low <= 6 else "teen"
    return ""


def loc_signals(loc: dict) -> list[dict]:
    out: list[dict] = []
    for lcc in loc.get("lcc", []):
        sig = {"source": "loc", "scheme": "lcc", "code": lcc, "label": ""}
        if lcc.upper().startswith("PZ"):
            sig["audience"] = "children"
            sig["type"] = "poetry" if lcc.upper().startswith("PZ8.3") else "fiction"
        if _lcc_nature(lcc):
            sig["nature"] = True
        out.append(sig)
    for ddc in loc.get("ddc", []):
        sig = {"source": "loc", "scheme": "ddc", "code": ddc, "label": ""}
        up = ddc.upper().replace(" ", "")
        if up.startswith("[E]") or up == "E":
            sig["audience"] = "picture_book"
        elif up.startswith("[FIC]") or up == "FIC":
            sig["audience"], sig["type"] = "children", "fiction"
        if _ddc_nature(ddc):
            sig["nature"] = True
        out.append(sig)
    for s in loc.get("subjects", []):
        heading, subdiv = s["heading"], s["subdivisions"]
        label = " -- ".join([heading, *subdiv])
        sig = {"source": "loc", "scheme": "lcsh", "code": label, "label": ""}
        low = [d.lower() for d in subdiv]
        if any(d.startswith("juvenile fiction") for d in low):
            sig["audience"], sig["type"] = "children", "fiction"
        elif any(d.startswith("juvenile literature") for d in low):
            sig["audience"], sig["type"] = "children", "nonfiction"
        elif any(d.startswith("juvenile poetry") for d in low):
            sig["audience"], sig["type"] = "children", "poetry"
        elif any(d.startswith("young adult fiction") for d in low):
            sig["audience"], sig["type"] = "teen", "fiction"
        topic = HEADING_TOPICS.get(heading.lower())
        if topic:
            sig["topics"] = [topic]
            if topic in NATURE_TOPICS:
                sig["nature"] = True
        if any(d.lower() == "identification" for d in subdiv) and topic in NATURE_TOPICS:
            sig["nature"] = True
        out.append(sig)
    for g in loc.get("genres", []):
        sig = {"source": "loc", "scheme": "lcgft", "code": g, "label": ""}
        gl = g.lower()
        if gl.startswith("board books"):
            sig["audience"] = "baby_toddler"
        elif gl.startswith("picture books"):
            sig["audience"] = "picture_book"
        elif gl.startswith("young adult"):
            sig["audience"] = "teen"
        elif gl.startswith(("juvenile", "children's")):
            sig["audience"] = "children"
        elif gl.startswith("field guides"):
            sig["nature"] = True
        out.append(sig)
    if loc.get("audience008"):
        aud = AUDIENCE_008.get(loc["audience008"], "")
        sig = {"source": "loc", "scheme": "marc008", "code": f"audience={loc['audience008']}", "label": ""}
        if aud:
            sig["audience"] = aud
        out.append(sig)
    for note in loc.get("notes521", []):
        sig = {"source": "loc", "scheme": "audience_note", "code": note, "label": ""}
        aud = _ages(note)
        if aud:
            sig["audience"] = aud
        out.append(sig)
    return _order(out)


def _order(signals: list[dict]) -> list[dict]:
    """Specific audiences before the generic 'children', so classify picks the most specific."""
    rank = {"baby_toddler": 0, "picture_book": 0, "early_reader": 0, "middle_grade": 0, "teen": 0, "adult": 2}
    return sorted(signals, key=lambda s: rank.get(s.get("audience", ""), 1))


# --- Google Books + Open Library (stored by enrich.py) ------------------------------------------


def google_signals(categories: list[str]) -> list[dict]:
    out = []
    for cat in categories or []:
        parts = [p.strip() for p in cat.split("/") if p.strip()]
        if not parts:
            continue
        top = parts[0].lower()
        sig = {"source": "google", "scheme": "bisac", "code": cat, "label": ""}
        if top.startswith("juvenile fiction"):
            sig["audience"], sig["type"] = "children", "fiction"
        elif top.startswith("juvenile nonfiction"):
            sig["audience"], sig["type"] = "children", "nonfiction"
        elif top.startswith("young adult fiction"):
            sig["audience"], sig["type"] = "teen", "fiction"
        elif top.startswith("young adult nonfiction"):
            sig["audience"], sig["type"] = "teen", "nonfiction"
        elif top in ("nature", "science") and not top.startswith("juvenile"):
            sig["type"] = "nonfiction"
        elif top == "fiction":
            sig["type"] = "fiction"
        topics = [HEADING_TOPICS[p.lower()] for p in parts[1:] if p.lower() in HEADING_TOPICS]
        if top == "nature" or any(t in NATURE_TOPICS for t in topics) or "earth sciences" in cat.lower() \
                or "science & nature" in cat.lower():
            sig["nature"] = True
        if topics:
            sig["topics"] = topics
        out.append(sig)
    return _order(out)


def openlibrary_signals(result: dict) -> list[dict]:
    out = []
    for lcc in result.get("ol_lcc", [])[:3]:
        sig = {"source": "openlibrary", "scheme": "lcc", "code": lcc, "label": ""}
        if lcc.upper().startswith("PZ"):
            sig["audience"] = "children"
        if _lcc_nature(lcc):
            sig["nature"] = True
        out.append(sig)
    for ddc in result.get("ol_ddc", [])[:3]:
        sig = {"source": "openlibrary", "scheme": "ddc", "code": ddc, "label": ""}
        if _ddc_nature(ddc):
            sig["nature"] = True
        out.append(sig)
    for subject in result.get("ol_subjects", [])[:25]:
        s = subject.lower().strip()
        sig = {"source": "openlibrary", "scheme": "subject", "code": subject, "label": ""}
        if s in ("juvenile fiction", "children's fiction", "children's stories"):
            sig["audience"] = "children"
        elif s in ("picture books", "picture books for children", "stories in rhyme"):
            sig["audience"] = "picture_book"
        elif s in ("board books",):
            sig["audience"] = "baby_toddler"
        elif s in ("young adult fiction",):
            sig["audience"] = "teen"
        topic = HEADING_TOPICS.get(re.split(r"\s*,\s*|\s+--\s+", s)[0])
        if topic:
            sig["topics"] = [topic]
            if topic in NATURE_TOPICS:
                sig["nature"] = True
        if len(sig) > 4:  # only subjects that say something
            out.append(sig)
    return _order(out)


# --- cache ------------------------------------------------------------------------------------


class Signals:
    """Reads (and, with a fetcher, fills) the outside-signal caches in enrich.db."""

    def __init__(self, cache_dir: Path, db: sqlite3.Connection | None = None):
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.own = db is None  # share enrich.py's connection when it has writes pending
        self.db = db or sqlite3.connect(cache_dir / "enrich.db", timeout=60)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS loc (
                   lccn TEXT PRIMARY KEY,
                   result TEXT NOT NULL,      -- JSON from parse_loc ({} on a miss)
                   hit INTEGER NOT NULL,
                   fetched_at TEXT NOT NULL)"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS lookups (
                   book_id TEXT PRIMARY KEY, key TEXT NOT NULL, result TEXT NOT NULL,
                   hit INTEGER NOT NULL, fetched_at TEXT NOT NULL)"""
        )
        self.db.commit()

    def close(self) -> None:
        self.db.commit()
        if self.own:
            self.db.close()

    def enrich_result(self, rid: str) -> dict:
        row = self.db.execute("SELECT result FROM lookups WHERE book_id = ?", (rid,)).fetchone()
        return json.loads(row[0]) if row else {}

    def loc(self, lccn: str) -> dict | None:
        row = self.db.execute("SELECT result FROM loc WHERE lccn = ?", (lccn,)).fetchone()
        return json.loads(row[0]) if row else None

    def loc_due(self, lccn: str) -> bool:
        row = self.db.execute("SELECT hit, fetched_at FROM loc WHERE lccn = ?", (lccn,)).fetchone()
        if row is None:
            return True
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(row[1])
        return age > dt.timedelta(days=HIT_DAYS if row[0] else MISS_DAYS)

    def fetch_loc(self, lccn: str, fetcher) -> dict:
        text = fetcher.text(lccn_path(lccn)) or ""
        parsed = parse_loc(text)
        self.db.execute(
            "INSERT OR REPLACE INTO loc VALUES (?, ?, ?, ?)",
            (lccn, json.dumps(parsed, ensure_ascii=False), int(bool(parsed)), _now()),
        )
        return parsed

    def for_record(self, rec: dict) -> list[dict]:
        """Every cached outside signal for a parsed ESTER record: LoC, then Google, then Open Library."""
        result = self.enrich_result(rec["id"])
        if not result:
            return []
        out: list[dict] = []
        lccn = result.get("ol_lccn", "")
        loc = self.loc(lccn) if lccn else None
        if loc:
            out += loc_signals(loc)
        if result.get("google_categories"):
            out += google_signals(result["google_categories"])
        return out + openlibrary_signals(result)
