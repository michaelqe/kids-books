"""ESTER parsers and the catalogue build, against saved pages. No network."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

from crawler import ester, run
from crawler.terms import branch_name, status_en, subject_en

FIX = Path(__file__).parent / "fixtures" / "ester"


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class ListPage(unittest.TestCase):
    def setUp(self):
        self.parsed = ester.parse_list(page("list_pildiraamatud_p1.html"))

    def test_total_and_paging(self):
        self.assertEqual(self.parsed["total"], 9166)
        self.assertEqual(self.parsed["next_offset"], 51)
        self.assertEqual(len(self.parsed["results"]), 50)

    def test_brief_citation(self):
        first = self.parsed["results"][1]
        self.assertEqual(first["id"], "b5260625")
        self.assertTrue(first["title"].startswith("1,2,3 bumblebee"))
        self.assertEqual(first["isbns"], ["9781407191669"])
        self.assertEqual(first["year"], 2019)
        self.assertIn("TlnRK lastekirjandus", first["libraries"])

    def test_tallinn_filter(self):
        self.assertTrue(ester.held_in_tallinn(["Tartu Linnaraamatukogu", "TlnRK lastekirjandus"]))
        self.assertFalse(ester.held_in_tallinn(["Tartu Linnaraamatukogu"]))
        self.assertFalse(ester.held_in_tallinn(["TlnRK e-raamatukogu OverDrive"]))


class Record(unittest.TestCase):
    def test_english_picture_book(self):
        rec = ester.parse_record(page("marc_b5260625_eng.html"), "b5260625")
        self.assertEqual(rec["title"], "1,2,3 bumblebee")
        self.assertEqual(rec["language"], "eng")
        self.assertEqual(rec["year"], 2019)
        self.assertEqual(rec["pages"], 10)
        self.assertEqual(rec["authors"], ["Marshall, Natalie"])
        self.assertEqual(rec["series"], "Find and feel")
        self.assertIn("pildiraamatud", rec["genres"])
        self.assertEqual(rec["holdings"][0]["status"], "KOHAL")
        self.assertEqual(rec["holdings"][0]["call_number"], "L(P) I/MAR")
        self.assertEqual(ester.is_picture_book(rec), (True, ""))

    def test_estonian_edition_with_loans(self):
        rec = ester.parse_record(page("marc_b2699522_est_loans.html"), "b2699522")
        self.assertEqual(rec["language"], "est")
        self.assertEqual(rec["original_language"], "fin")
        self.assertEqual(rec["original_title"], "Kaksitoista lahjaa joulupukille")
        self.assertEqual(rec["authors"], ["Kunnas, Mauri", "Kunnas, Tarja"])  # not the translator
        self.assertTrue(ester.is_picture_book(rec)[0])
        tallinn = ester.tallinn_holdings(rec["holdings"])
        self.assertGreater(len(tallinn), 1)
        self.assertTrue(any(ester.is_available(h["status"]) for h in tallinn))
        self.assertTrue(any(not ester.is_available(h["status"]) for h in tallinn))

    def test_long_book_is_dropped(self):
        rec = ester.parse_record(page("marc_b1447029_long.html"), "b1447029")
        self.assertEqual(rec["pages"], 97)
        ok, why = ester.is_picture_book(rec)
        self.assertFalse(ok)
        self.assertIn("pages", why)

    def test_rule(self):
        base = {"genres": ["pildiraamatud"], "pages": 32}
        self.assertTrue(ester.is_picture_book(base)[0])
        self.assertFalse(ester.is_picture_book({**base, "genres": ["romaanid"]})[0])
        self.assertFalse(ester.is_picture_book({**base, "pages": 120})[0])
        self.assertFalse(ester.is_picture_book({**base, "pages": 56, "genres": ["pildiraamatud", "jutustused"]})[0])
        self.assertFalse(ester.is_picture_book({**base, "genres": ["pildiraamatud", "värvimisraamatud"]})[0])
        self.assertTrue(ester.is_picture_book({**base, "pages": None})[0])


class Helpers(unittest.TestCase):
    def test_pages(self):
        cases = {
            "[10] lk. koos kaanega": 10,
            "96, [1] lk. : ill.": 97,
            "20 nummerdamata lehekülge koos kaanega : illustratsioonid": 20,
            "48 lehekülge : illustratsioonid ; 21 cm": 48,
            "1 volume ; 22 cm": None,
            "": None,
        }
        for extent, want in cases.items():
            self.assertEqual(ester.parse_pages(extent), want, extent)

    def test_terms(self):
        self.assertEqual(status_en("KOHAL"), "Available")
        self.assertEqual(status_en("TÄHTAEG 02.12.26"), "On loan, due 2 Dec 2026")
        self.assertEqual(subject_en("Koerad"), "dogs")
        self.assertEqual(subject_en("jõulud -- lastekirjandus"), "Christmas")
        self.assertEqual(subject_en("tundmatu"), "")
        self.assertEqual(branch_name("TlnRK Kännukuke lastekirjandus"), "Kännukuke")

    def test_isbns(self):
        self.assertEqual(ester.isbns_from("978-9916-14-424-4 (köites) 0123456789"), ["9789916144244", "0123456789"])


def seed(state, records, holdings=None) -> None:
    """Put fixture pages into a state DB as if crawled (v2: English list, Tallinn scope)."""
    holdings = holdings or {}
    for name, rid in records:
        state.execute(
            "INSERT OR REPLACE INTO listed (id, brief, tallinn, first_seen, last_seen, eng) VALUES (?, '{}', 1, 'x', 'x', 1)",
            (rid,),
        )
        hold = holdings.get(rid)
        state.execute(
            "INSERT OR REPLACE INTO pages (id, body, fetched_at, scope, holdings) VALUES (?, ?, '2026-11-14T00:00:00+00:00', 'S8', ?)",
            (rid, zlib.compress(page(name).encode("utf-8")), zlib.compress(page(hold).encode("utf-8")) if hold else None),
        )
    state.commit()


V2_RECORDS = [
    ("marc_b5260625_eng.html", "b5260625"),                  # English board book: kept
    ("marc_b4675367_eng_teen.html", "b4675367"),             # teen novel: kept
    ("marc_b4555593_eng_child_nonfiction.html", "b4555593"), # children's non-fiction: kept
    ("marc_b6062504_eng_adult_nature.html", "b6062504"),     # adult bird book: kept
    ("marc_b5674196_eng_adult_fiction.html", "b5674196"),    # adult novel: dropped
    ("marc_b1253057_library_use_only.html", "b1253057"),     # library use only (and Estonian): dropped
    ("marc_b2699522_est_loans.html", "b2699522"),            # Estonian picture book: dropped
]


class Paths(unittest.TestCase):
    def test_search_and_record_paths(self):
        self.assertEqual(
            ester.search_path("u:(201*)"),
            "/search~S8*est/X?SEARCH=u:(201*)&searchscope=8&l=eng&m=a&b=vv&SORT=D",
        )
        self.assertIn("/51%2C14897%2C14897%2CB/browse", ester.search_path("u:(201*)", "vv", 51, 14897))
        self.assertIn("SUBKEY=u%3A(201*)", ester.search_path("u:(201*)", "vv", 51, 14897))
        self.assertTrue(ester.marc_path("b5260625").startswith("/search~S8*est?/.b5260625/"))
        self.assertIn("holdings~6101819", ester.holdings_path("b6101819"))

    def test_keyword_list_page(self):
        parsed = ester.parse_list(page("list_eng_vlk_2019_p1.html"))
        self.assertEqual(parsed["total"], 350)
        self.assertEqual(len(parsed["results"]), 50)


class V2Record(unittest.TestCase):
    def test_udc_and_form(self):
        rec = ester.parse_record(page("marc_b4555593_eng_child_nonfiction.html"), "b4555593")
        self.assertEqual(rec["udc"], ["591.521(0.053.2)", "821.111-93-32"])
        self.assertEqual(rec["udc_bt"], ["57/59"])
        self.assertEqual(rec["form"], "0")

    def test_full_tallinn_holdings(self):
        marc = page("marc_b6101819_tln_ten.html")
        self.assertEqual(len(ester.parse_holdings(marc)), ester.MAX_MARC_COPIES)
        rec = ester.parse_record(marc, "b6101819", page("holdings_b6101819_tln.html"))
        self.assertEqual(len(ester.tallinn_holdings(rec["holdings"])), 21)

    def test_library_use_only(self):
        rec = ester.parse_record(page("marc_b1253057_library_use_only.html"), "b1253057")
        self.assertEqual(len(ester.tallinn_holdings(rec["holdings"])), 1)
        self.assertEqual(ester.lendable_tallinn_holdings(rec["holdings"]), [])
        self.assertTrue(ester.is_lendable({"location": "TlnRK Kännukuke lastekirjandus", "status": "KOHAL", "note": ""}))
        self.assertFalse(ester.is_lendable({"location": "TlnRK Südalinna lugemissaal", "status": "KOHAL", "note": ""}))
        self.assertFalse(ester.is_lendable({"location": "TlnRK Liivalaia", "status": "KOHAL", "note": "EI LAENUTATA"}))


class Build(unittest.TestCase):
    """The catalogue build from a state DB holding the fixtures."""

    def test_build_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = run.open_state(Path(tmp) / "state.db")
            seed(state, V2_RECORDS)
            out = Path(tmp) / "catalog.db"
            counts = run.build(state, out, "ok", 0)
            self.assertEqual(counts["books"], 4)
            self.assertEqual(counts["english_books"], 4)
            self.assertEqual(counts["dropped"], 3)
            self.assertEqual(counts["dropped_reasons"], {"not English": 2, "adult fiction": 1})
            db = sqlite3.connect(out)
            facets = dict(db.execute("SELECT id, audience || '/' || type FROM books"))
            self.assertEqual(
                facets,
                {
                    "b5260625": "baby_toddler/poetry",
                    "b4675367": "teen/fiction",
                    "b4555593": "picture_book/nonfiction",
                    "b6062504": "adult/nonfiction",
                },
            )
            self.assertEqual(db.execute("SELECT nature FROM books WHERE id='b6062504'").fetchone()[0], 1)
            self.assertIn("birds", json.loads(db.execute("SELECT topics FROM books WHERE id='b6062504'").fetchone()[0]))
            hits = db.execute(
                "SELECT b.id FROM books_fts JOIN books b ON b.rowid = books_fts.rowid WHERE books_fts MATCH ?",
                ("bumblebee",),
            ).fetchall()
            self.assertEqual(hits, [("b5260625",)])
            # topics are searchable: the bird book by its UDC topic
            hits = db.execute("SELECT count(*) FROM books_fts WHERE books_fts MATCH 'subjects:birds'").fetchone()[0]
            self.assertEqual(hits, 1)
            # an author search finds "Marshall, Natalie" as "natalie marshall"
            hits = db.execute(
                "SELECT count(*) FROM books_fts WHERE books_fts MATCH 'authors:natalie'"
            ).fetchone()[0]
            self.assertEqual(hits, 1)
            signals = db.execute(
                "SELECT scheme, code FROM classifications WHERE book_id='b4555593' AND source='ester'"
            ).fetchall()
            self.assertIn(("udc", "591.521(0.053.2)"), signals)
            self.assertIn(("ems_genre", "vigurraamatud"), signals)
            meta = dict(db.execute("SELECT key, value FROM meta"))
            self.assertEqual(meta["books"], "4")
            self.assertEqual(meta["schema_version"], "2")
            self.assertEqual(meta["crawl_status"], "ok")
            links = json.loads(db.execute("SELECT links FROM books WHERE id='b5260625'").fetchone()[0])
            self.assertIn("goodreads.com/search?q=9781407191669", links["goodreads"])
            # verdicts go back to the state DB for the refresh schedule
            kept = dict(state.execute("SELECT id, kept FROM pages"))
            self.assertEqual(kept["b6062504"], 1)
            self.assertEqual(kept["b5674196"], 0)

    def test_due_records_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = run.open_state(Path(tmp) / "state.db")
            seed(state, V2_RECORDS[:2])
            state.execute("UPDATE pages SET kept = 1, fetched_at = '2000-01-01T00:00:00+00:00' WHERE id = 'b5260625'")
            state.execute("UPDATE pages SET kept = 0, fetched_at = datetime('now', '-30 days') WHERE id = 'b4675367'")
            for rid, children in (("b0000001", 0), ("b0000002", 1)):
                state.execute(
                    "INSERT INTO listed (id, brief, tallinn, first_seen, last_seen, eng, children) VALUES (?, '{}', 1, 'x', 'x', 1, ?)",
                    (rid, children),
                )
            # a v1 page (all-libraries scope) must be fetched again
            state.execute("INSERT INTO listed (id, brief, tallinn, first_seen, last_seen, eng) VALUES ('b0000003', '{}', 1, 'x', 'x', 1)")
            state.execute("INSERT INTO pages (id, body, fetched_at) VALUES ('b0000003', x'00', '2026-11-14T00:00:00+00:00')")
            due = run.due_records(state, refresh_days=7, limit=None, recheck_days=60)
            # new and v1 pages first (children's first), then the stale kept book; the
            # out-of-scope page is younger than recheck_days but older than refresh_days
            self.assertEqual(due[0], "b0000002")
            self.assertEqual(set(due[1:3]), {"b0000001", "b0000003"})
            self.assertIn("b5260625", due)
            self.assertNotIn("b4675367", due)
