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


class Build(unittest.TestCase):
    """The catalogue build from a state DB holding the fixtures."""

    def test_build_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = run.open_state(Path(tmp) / "state.db")
            for name, rid in [
                ("marc_b5260625_eng.html", "b5260625"),
                ("marc_b2699522_est_loans.html", "b2699522"),
                ("marc_b1447029_long.html", "b1447029"),
            ]:
                state.execute(
                    "INSERT INTO listed VALUES (?, '{}', 1, 'x', 'x')", (rid,)
                )
                state.execute(
                    "INSERT INTO pages VALUES (?, ?, '2026-11-14T00:00:00+00:00')",
                    (rid, zlib.compress(page(name).encode("utf-8"))),
                )
            out = Path(tmp) / "catalog.db"
            counts = run.build(state, out, "ok", 0)
            self.assertEqual(counts["books"], 2)
            self.assertEqual(counts["english_books"], 1)
            self.assertEqual(counts["dropped"], 1)
            db = sqlite3.connect(out)
            hits = db.execute(
                "SELECT b.id FROM books_fts JOIN books b ON b.rowid = books_fts.rowid WHERE books_fts MATCH ?",
                ("bumblebee",),
            ).fetchall()
            self.assertEqual(hits, [("b5260625",)])
            # an author search finds "Marshall, Natalie" as "natalie marshall"
            hits = db.execute(
                "SELECT count(*) FROM books_fts WHERE books_fts MATCH 'authors:natalie'"
            ).fetchone()[0]
            self.assertEqual(hits, 1)
            meta = dict(db.execute("SELECT key, value FROM meta"))
            self.assertEqual(meta["books"], "2")
            self.assertEqual(meta["crawl_status"], "ok")
            links = json.loads(db.execute("SELECT links FROM books WHERE id='b5260625'").fetchone()[0])
            self.assertIn("goodreads.com/search?q=9781407191669", links["goodreads"])
            self.assertFalse(out.with_suffix(".db.tmp").exists())


if __name__ == "__main__":
    unittest.main()
