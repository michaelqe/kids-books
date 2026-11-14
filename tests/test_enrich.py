"""Covers and summaries, with canned Open Library answers. No network."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from crawler import enrich

SCHEMA = (Path(__file__).resolve().parent.parent / "crawler" / "schema.sql").read_text(encoding="utf-8")

CANNED = {
    "https://openlibrary.org/isbn/9780399226908.json": {
        "key": "/books/OL1M", "covers": [7835968], "works": [{"key": "/works/OL52987W"}],
    },
    "https://openlibrary.org/works/OL52987W.json": {
        "description": {"type": "/type/text", "value": "One sunny day, a caterpillar pops out of an egg.\n\n----------\nSee also [this][1]\n[1]: https://x"},
    },
    "https://openlibrary.org/works/OL1938178W.json": {"description": "A mouse took a stroll through the deep dark wood.", "covers": [8561698]},
}


class FakeFetcher(enrich.Fetcher):
    def __init__(self, refuse=False):
        super().__init__(delay=0)
        self.urls = []
        self.refuse = refuse

    def json(self, url):
        self.urls.append(url)
        self.requests += 1
        if self.refuse:
            raise enrich.Stop("HTTP 429 from openlibrary.org")
        if url.startswith("https://openlibrary.org/search.json"):
            if "Gruffalo" in url:
                return {"docs": [{"key": "/works/OL1938178W", "title": "The Gruffalo", "cover_i": 8561698}]}
            return {"docs": [{"key": "/works/OL9W", "title": "Something else entirely"}]}
        return CANNED.get(url)


def catalog(books):
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    for b in books:
        db.execute(
            """INSERT INTO books (id, url, title, original_title, language, isbns, authors, links)
               VALUES (?, '', ?, ?, ?, ?, ?, '{"goodreads": "g"}')""",
            (b["id"], b["title"], b.get("original_title", ""), b.get("language", "eng"),
             json.dumps(b.get("isbns", [])), json.dumps(b.get("authors", []))),
        )
    return db


BOOKS = [
    {"id": "b1", "title": "The very hungry caterpillar", "isbns": ["9780399226908"], "authors": ["Carle, Eric"]},
    {"id": "b2", "title": "Grühvel", "original_title": "The Gruffalo", "language": "est",
     "isbns": ["9789985000000"], "authors": ["Donaldson, Julia"]},
    {"id": "b3", "title": "Väike karu", "language": "est", "isbns": []},  # Estonian original: nothing to find
    {"id": "b4", "title": "Unknown book", "isbns": ["9781111111111"], "authors": ["Nobody, A"]},
]


class Enrich(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def row(self, db, rid):
        return db.execute("SELECT cover_url, summary, summary_source, links FROM books WHERE id = ?", (rid,)).fetchone()

    def test_isbn_edition_and_work(self):
        db = catalog(BOOKS)
        stats = enrich.run(db, self.cache, log=lambda m: None, fetcher=FakeFetcher())
        cover, summary, source, links = self.row(db, "b1")
        self.assertEqual(cover, "https://covers.openlibrary.org/b/id/7835968-M.jpg")
        self.assertEqual(summary, "One sunny day, a caterpillar pops out of an egg.")
        self.assertEqual(source, "openlibrary")
        links = json.loads(links)
        self.assertEqual(links["openlibrary"], "https://openlibrary.org/books/OL1M")
        self.assertEqual(links["goodreads"], "g")  # kept
        self.assertEqual(stats["covers"], 2)

    def test_translation_found_by_original_title(self):
        db = catalog(BOOKS)
        enrich.run(db, self.cache, log=lambda m: None, fetcher=FakeFetcher())
        cover, summary, _, _ = self.row(db, "b2")
        self.assertIn("8561698", cover)
        self.assertTrue(summary.startswith("A mouse"))

    def test_wrong_title_is_rejected(self):
        db = catalog(BOOKS)
        enrich.run(db, self.cache, log=lambda m: None, fetcher=FakeFetcher())
        self.assertEqual(self.row(db, "b4")[:2], ("", ""))
        self.assertEqual(self.row(db, "b3")[:2], ("", ""))

    def test_cache_and_offline_build(self):
        enrich.run(catalog(BOOKS), self.cache, log=lambda m: None, fetcher=FakeFetcher())
        again = FakeFetcher()
        db = catalog(BOOKS)
        enrich.run(db, self.cache, log=lambda m: None, fetcher=again)
        self.assertEqual(again.urls, [])  # all fresh
        db = catalog(BOOKS)
        enrich.run(db, self.cache, log=lambda m: None, network=False, fetcher=FakeFetcher())
        self.assertIn("7835968", self.row(db, "b1")[0])

    def test_refusal_stops_cleanly(self):
        db = catalog(BOOKS)
        f = FakeFetcher(refuse=True)
        stats = enrich.run(db, self.cache, log=lambda m: None, fetcher=f)
        self.assertEqual(len(f.urls), 1)
        self.assertIn("429", stats["stopped"])

    def test_cap(self):
        f = FakeFetcher()
        stats = enrich.run(catalog(BOOKS), self.cache, log=lambda m: None, fetcher=f, max_lookups=1)
        self.assertEqual(stats["looked_up"], 1)

    def test_helpers(self):
        self.assertTrue(enrich.titles_match("The Gruffalo", "Gruffalo"))
        self.assertTrue(enrich.titles_match("Grühvel", "Gruhvel"))
        self.assertFalse(enrich.titles_match("The Gruffalo", "Room on the Broom"))
        self.assertEqual(enrich.cover_url(-1), "")
        self.assertEqual(enrich.clean_description("<p>Hi</p> [x](http://y)"), "Hi x")


if __name__ == "__main__":
    unittest.main()
