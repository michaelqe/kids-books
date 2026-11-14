"""Audience, type and topics for a catalogue record, and the v2 scope rule. Pure functions.

Inputs are a parsed ESTER record (`ester.parse_record`) and optional outside signals
(Library of Congress, Google Books, Open Library; see crawler/enrich.py), each a dict
`{"source", "scheme", "code", "label"}`. Every decision records a short reason, so a
misfiled book can be traced to the signal that put it there.

Precedence: ESTER's own cataloguing (UDC 080/072, form headings 655, 008/33) first, then
where Tallinn shelves its copies (children's departments, call numbers), then LoC, then
Google, then Open Library. Outside sources only fill gaps or break ties; they never
override an explicit ESTER children's/teen marker.
"""
from __future__ import annotations

import re

from . import ester
from .terms import (
    ADULT_NATURE_UDC,
    EXCLUDED_GENRES,
    NATURE_SUBJECTS,
    UDC_TOPICS,
    genre_en,
    subject_en,
)

AUDIENCES = ("baby_toddler", "picture_book", "early_reader", "middle_grade", "teen", "adult")
TYPES = ("fiction", "nonfiction", "poetry", "comics", "activity")

AUDIENCE_LABELS = {
    "baby_toddler": "Baby & toddler",
    "picture_book": "Picture book",
    "early_reader": "Early reader",
    "middle_grade": "Older children",
    "teen": "Teen",
    "adult": "Adult",
}
TYPE_LABELS = {
    "fiction": "Fiction",
    "nonfiction": "Non-fiction",
    "poetry": "Poetry",
    "comics": "Comics",
    "activity": "Activity",
}

# ESTER form headings (655), lower case.
CHILDREN_GENRES = {"lastekirjandus", "pildiraamatud", "lasteluule", "lastelaulud", "liisusalmid", "piltsõnastikud"}
TEEN_GENRES = {"noorsookirjandus", "noortekirjandus"}
BABY_GENRES = {
    "papp-raamatud", "pappraamatud", "papiraamatud", "katsumisraamatud", "vannieraamatud",
    "vanniraamatud", "riidest raamatud", "kaltsuraamatud", "beebiraamatud",
}
EARLY_READER_GENRES = {"suurtähtraamatud", "lugemikud", "aabitsad", "lektüür", "esimesed lugemised"}
PICTURE_GENRES = {"pildiraamatud", "vigurraamatud", "klappraamatud", "voldikraamatud", "ruumilised raamatud", "heliraamatud"}
COMIC_GENRES = {"koomiksid", "graafilised romaanid", "mangad", "pildiromaanid"}
POETRY_GENRES = {"luuletused", "lasteluule", "värssjutud", "lastelaulud", "liisusalmid", "laulud", "luule"}
ACTIVITY_GENRES = {
    "tegevusraamatud", "tegelusraamatud", "nuputamisülesanded", "piltmõistatused", "mõistatused",
    "pusled", "meisterdamisraamatud", "ülesanded", "töövihikud",
}
FICTION_GENRES = {
    "ilukirjandus", "romaanid", "jutud", "jutustused", "muinasjutud", "loomajutud", "lühiromaanid",
    "fantaasiaromaanid", "seiklusromaanid", "põnevusromaanid", "kriminaalromaanid", "ulmeromaanid",
    "armastusromaanid", "õudusromaanid", "õudusjutud", "novellid", "näidendid", "mugandused", "noorsooromaanid",
    "ajaloolised romaanid", "arenguromaanid", "muistendid", "valmid",
}
FIELD_GUIDE_GENRES = {"määrajad", "välimäärajad", "looduse määrajad"}
# 008/33 literary form: 0 non-fiction; everything else (1 fiction, f novels, j short
# stories, d drama, p poetry, h humour, m mixed, ...) is imaginative writing.
FORM_POETRY = {"p"}
FORM_NONFICTION = {"0", "e", "i", "s"}  # non-fiction, essays, letters, speeches

# Call-number prefixes the children's departments use (L = lastekirjandus).
CHILD_CALLNO = re.compile(r"^L(?:\(|-|\s|/|I\b|$)")
PICTURE_CALLNO = re.compile(r"^L\(P\)")


def _genres(rec: dict) -> set[str]:
    return {g.lower() for g in rec.get("genres", [])}


def _udc_children(udc: str) -> str:
    """'-93' (children's literature) or '(0.053.2)'/'-053.2' (for children); '' otherwise."""
    if re.search(r"-93(?:\D|$)", udc):
        return "-93"
    m = re.search(r"\(0\.053\.\d\)|-053\.[2-6]", udc)
    return m.group(0) if m else ""


def _udc_youth(udc: str) -> bool:
    return bool(re.search(r"\(0\.053\.6\)|-053\.6", udc))


def udc_topics(udcs: list[str]) -> list[str]:
    """English topic tags from UDC numbers, longest prefix first ('598.2' -> birds)."""
    out: list[str] = []
    for u in udcs:
        main = re.split(r"[(\-:\"=+/ ]", u, maxsplit=1)[0]
        for prefix in sorted(UDC_TOPICS, key=len, reverse=True):
            if main.startswith(prefix):
                tag = UDC_TOPICS[prefix]
                if tag not in out:
                    out.append(tag)
                break
    return out


def _udc_main(u: str) -> str:
    return re.split(r"[(\-:\"=+/ ']", u, maxsplit=1)[0]


def is_nature(rec: dict, signals: list[dict] | None = None) -> tuple[bool, str]:
    """Is this book about the natural world (weather, animals, plants, the sky, rocks, ...)?

    The primary UDC number (the first 080) decides when there is one: a secondary number
    or a subject heading doesn't make a cat-care, crafts or travel book a nature book.
    Without a 080, the broad term (072), then subject headings, then outside signals.
    """
    guides = _genres(rec) & FIELD_GUIDE_GENRES
    if guides:
        return True, "genre " + sorted(guides)[0]
    udcs = rec.get("udc", [])
    if udcs:
        primary = udcs[0]
        if _udc_main(primary).startswith(ADULT_NATURE_UDC):
            return True, f"UDC {primary}"
        return False, ""
    for u in rec.get("udc_bt", []):
        if u.startswith("5") and not u.startswith(("51", "53", "54")):
            return True, f"UDC broad term {u}"
    if rec.get("udc_bt"):
        return False, ""
    for s in rec.get("subjects", []):
        base = re.split(r"\s*(?:\(|--)", s.lower())[0].strip()
        if base in NATURE_SUBJECTS:
            return True, f"subject {s}"
    for sig in signals or []:
        if sig.get("nature"):
            return True, f"{sig['source']} {sig['scheme']} {sig.get('label') or sig['code']}"
    return False, ""


def classify(rec: dict, signals: list[dict] | None = None) -> dict:
    """{"audience", "type", "topics", "nature", "reasons"} for a parsed record."""
    signals = signals or []
    genres = _genres(rec)
    udcs = rec.get("udc", []) + rec.get("udc_bt", [])
    copies = ester.lendable_tallinn_holdings(rec.get("holdings", [])) or ester.tallinn_holdings(rec.get("holdings", []))
    reasons: list[str] = []
    pages = rec.get("pages")

    # --- children's or adult -------------------------------------------------------
    child_why = ""
    for u in udcs:
        mark = _udc_children(u)
        if mark:
            child_why = f"UDC {u}"
            break
    if not child_why and genres & (CHILDREN_GENRES | TEEN_GENRES):
        child_why = "genre " + sorted(genres & (CHILDREN_GENRES | TEEN_GENRES))[0]
    if not child_why and copies and all(_child_location(h) for h in copies):
        child_why = "shelved in children's departments"
    if not child_why:
        for sig in signals:
            if sig.get("audience") in AUDIENCES + ("children",) and sig["audience"] != "adult":
                child_why = f"{sig['source']} {sig['scheme']} {sig.get('label') or sig['code']}"
                break

    # --- type ------------------------------------------------------------------------
    form = rec.get("form", "")
    primary = (rec.get("udc") or [""])[0]
    if genres & COMIC_GENRES or any(re.match(r"741\.5", u) for u in udcs):
        typ, why = "comics", "genre " + (sorted(genres & COMIC_GENRES) or ["UDC 741.5"])[0]
    elif genres & ACTIVITY_GENRES or any(re.match(r"79[34]", u) for u in rec.get("udc", [])):
        typ, why = "activity", "genre " + (sorted(genres & ACTIVITY_GENRES) or ["UDC 793/794"])[0]
    elif genres & POETRY_GENRES or form in FORM_POETRY or any(re.search(r"-93?-1(?:\D|$)|^821[^-]*-1$", u) for u in udcs):
        typ, why = "poetry", "genre " + (sorted(genres & POETRY_GENRES) or [f"008/33 {form}" if form else "UDC -1"])[0]
    elif primary.startswith("82"):
        # literature; ESTER sometimes leaves 008/33 at 0 even for stories
        typ, why = "fiction", f"UDC {primary}"
    elif primary and (form in FORM_NONFICTION or not form):
        typ, why = "nonfiction", f"UDC {primary}" + (f", 008/33 {form}" if form else "")
    elif form in FORM_NONFICTION and not genres & FICTION_GENRES:
        typ, why = "nonfiction", f"008/33 {form}"
    elif form or genres & FICTION_GENRES:
        typ, why = "fiction", (f"008/33 {form}" if form else "genre " + sorted(genres & FICTION_GENRES)[0])
    else:
        typ, why = _type_from_signals(signals) or ("nonfiction", "default")
    reasons.append(f"type {typ}: {why}")

    # --- audience ----------------------------------------------------------------------
    if not child_why:
        audience, why = "adult", "no children's marker"
    elif genres & TEEN_GENRES or any(_udc_youth(u) for u in udcs) or _sig_audience(signals) == "teen":
        if genres & PICTURE_GENRES:
            audience, why = "picture_book", "genre pildiraamatud"
        else:
            audience, why = "teen", ("genre " + sorted(genres & TEEN_GENRES)[0]) if genres & TEEN_GENRES else "UDC youth"
    elif genres & BABY_GENRES:
        audience, why = "baby_toddler", "genre " + sorted(genres & BABY_GENRES)[0]
    elif genres & EARLY_READER_GENRES:
        audience, why = "early_reader", "genre " + sorted(genres & EARLY_READER_GENRES)[0]
    elif ester.is_picture_book({**rec, "genres": list(genres)})[0]:
        audience, why = "picture_book", "genre pildiraamatud, ≤ 64 pages"
        if pages and pages <= 14 and genres & {"vigurraamatud", "katsumisraamatud"}:
            audience, why = "baby_toddler", f"novelty book, {pages} pages"
    elif genres & PICTURE_GENRES and (not pages or pages <= 64):
        audience, why = "picture_book", "genre " + sorted(genres & PICTURE_GENRES)[0]
    elif any(PICTURE_CALLNO.match(h.get("call_number", "")) for h in copies):
        audience, why = "picture_book", "call number L(P)"
    elif pages and pages <= 48:
        audience, why = "picture_book", f"{pages}-page children's book"
    else:
        sig = _sig_audience(signals)
        if sig in ("early_reader", "picture_book", "baby_toddler"):
            audience, why = sig, "outside source"
        else:
            audience, why = "middle_grade", f"children's book{f', {pages} pages' if pages else ''}"
    reasons.insert(0, f"audience {audience}: {why}" + (f" (children's: {child_why})" if child_why and why != child_why else ""))

    # --- topics ------------------------------------------------------------------------
    topics: list[str] = []
    for s in rec.get("subjects", []):
        en = subject_en(s)
        if en and en not in topics:
            topics.append(en)
    for t in udc_topics(rec.get("udc", [])):
        if t not in topics:
            topics.append(t)
    for sig in signals:
        for t in sig.get("topics", []):
            if t not in topics:
                topics.append(t)
    nature, nature_why = is_nature(rec, signals)
    if nature:
        reasons.append(f"nature: {nature_why}")
    return {"audience": audience, "type": typ, "topics": topics[:12], "nature": nature, "reasons": reasons}


def _child_location(h: dict) -> bool:
    loc = h.get("location", "").lower()
    return "laste" in loc or bool(CHILD_CALLNO.match(h.get("call_number", "")))


def _sig_audience(signals: list[dict]) -> str:
    for sig in signals:
        if sig.get("audience") in AUDIENCES:
            return sig["audience"]
    return ""


def _type_from_signals(signals: list[dict]) -> tuple[str, str] | None:
    for sig in signals:
        if sig.get("type") in TYPES:
            return sig["type"], f"{sig['source']} {sig['scheme']}"
    return None


def in_scope(rec: dict, facets: dict) -> tuple[bool, str]:
    """Keep a book when it's English, can be borrowed in Tallinn, and is a children's book
    or adult non-fiction about the natural world. The reason names why a book is dropped."""
    if rec.get("language") != "eng":
        return False, "not English"
    tallinn = ester.tallinn_holdings(rec.get("holdings", []))
    if not tallinn:
        return False, "no Tallinn copy"
    if not ester.lendable_tallinn_holdings(rec.get("holdings", [])):
        return False, "library use only"
    excluded = _genres(rec) & EXCLUDED_GENRES
    if excluded:
        return False, f"genre {sorted(excluded)[0]}"
    if facets["audience"] != "adult":
        return True, ""
    if facets["type"] == "fiction" or facets["type"] == "poetry":
        return False, "adult fiction"
    if facets["type"] == "comics":
        return False, "adult comics"
    if not facets["nature"]:
        return False, "adult non-fiction, not nature"
    return True, ""


def labels(facets: dict) -> dict:
    return {
        "audience_label": AUDIENCE_LABELS.get(facets["audience"], facets["audience"]),
        "type_label": TYPE_LABELS.get(facets["type"], facets["type"]),
    }


def genre_tags(rec: dict) -> list[str]:
    return [e for e in dict.fromkeys(genre_en(g) for g in rec.get("genres", [])) if e]
