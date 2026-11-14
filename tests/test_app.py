"""The HTTP server: health, static files, search over a fixture catalogue, shared lists."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path

from crawler import run
from server import app as server
from server import db as dbm

FIX = Path(__file__).parent / "fixtures" / "ester"
RECORDS = [
    ("marc_b5260625_eng.html", "b5260625"),                  # board book (baby & toddler, poetry)
    ("marc_b4675367_eng_teen.html", "b4675367"),             # teen novel
    ("marc_b4555593_eng_child_nonfiction.html", "b4555593"), # children's non-fiction about animal homes
    ("marc_b6062504_eng_adult_nature.html", "b6062504"),     # adult bird book
    ("marc_b5674196_eng_adult_fiction.html", "b5674196"),    # adult novel: dropped
    ("marc_b2699522_est_loans.html", "b2699522"),            # Estonian: dropped
]


def build_catalog(out: Path, records=RECORDS) -> None:
    state = run.open_state(out.parent / f"state-{out.stem}.db")
    state.execute("DELETE FROM listed")
    state.execute("DELETE FROM pages")
    for name, rid in records:
        state.execute(
            "INSERT OR REPLACE INTO listed (id, brief, tallinn, first_seen, last_seen, eng) VALUES (?, '{}', 1, 'x', 'x', 1)",
            (rid,),
        )
        state.execute(
            "INSERT OR REPLACE INTO pages (id, body, fetched_at, scope) VALUES (?, ?, '2026-11-14T00:00:00+00:00', 'S8')",
            (rid, zlib.compress((FIX / name).read_text(encoding="utf-8").encode("utf-8"))),
        )
    run.build(state, out, "ok", 0)
    state.close()


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.catalog = cls.tmp / "catalog.db"
        build_catalog(cls.catalog)
        cls.httpd = server.serve("127.0.0.1", 0, cls.tmp / "books.db", cls.catalog, quiet=True)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, user=None, ctype="application/json"):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", ctype)
        if user:
            req.add_header("X-Remote-User", user)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    # --- basics

    def test_health(self):
        status, body = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["catalog"]["books"], 4)
        self.assertEqual(body["catalog"]["schema_version"], 2)
        self.assertEqual(body["catalog"]["status"], "ok")

    def test_me(self):
        self.assertEqual(self.call("GET", "/api/me")[1], {"user": "dev"})
        self.assertEqual(self.call("GET", "/api/me", user="hj")[1], {"user": "hj"})

    def test_static(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body.lower())
        # client-side routes get the shell; missing files 404; no escaping web/
        self.assertEqual(self.call("GET", "/lists/3")[0], 200)
        self.assertEqual(self.call("GET", "/nope.js")[0], 404)
        self.assertEqual(self.call("GET", "/../server/app.py")[0], 404)
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)

    # --- catalogue

    def test_search(self):
        _, body = self.call("GET", "/api/search?q=bumblebee")
        self.assertEqual([r["id"] for r in body["results"]], ["b5260625"])
        self.assertEqual(body["results"][0]["authors"], ["Natalie Marshall"])
        _, body = self.call("GET", "/api/search?q=natalie&field=author")
        self.assertEqual(body["total"], 1)
        _, body = self.call("GET", "/api/search?q=natalie&field=title")
        self.assertEqual(body["total"], 0)
        _, body = self.call("GET", "/api/search?q=bumb")  # prefix match while typing
        self.assertEqual(body["total"], 1)
        _, body = self.call("GET", "/api/search?lang=est")  # ignored: a v2 catalogue is all English
        self.assertEqual(body["total"], 4)
        _, body = self.call("GET", "/api/search?subject=birds")  # topic chips
        self.assertEqual([r["id"] for r in body["results"]], ["b6062504"])
        status, body = self.call("GET", "/api/search?q=%22%20OR%20(")  # junk is not a 500
        self.assertEqual(status, 200)
        _, body = self.call("GET", "/api/search?q=%22%20(%20*")
        self.assertEqual(body["total"], 0)

    def test_facets(self):
        _, body = self.call("GET", "/api/search")
        counts = {f["value"]: f["count"] for f in body["facets"]["audience"]}
        self.assertEqual(counts, {"baby_toddler": 1, "picture_book": 1, "early_reader": 0, "middle_grade": 0, "teen": 1, "adult": 1})
        _, body = self.call("GET", "/api/search?audience=baby_toddler,picture_book")
        self.assertEqual({r["id"] for r in body["results"]}, {"b5260625", "b4555593"})
        # the audience facet still counts the other audiences, the type facet narrows
        self.assertEqual({f["value"]: f["count"] for f in body["facets"]["audience"]}["teen"], 1)
        self.assertEqual({f["value"]: f["count"] for f in body["facets"]["type"]}["fiction"], 0)
        _, body = self.call("GET", "/api/search?nature=1&type=nonfiction")
        self.assertEqual({r["id"] for r in body["results"]}, {"b6062504", "b4555593"})
        _, body = self.call("GET", "/api/search?audience=teen,bogus")
        self.assertEqual([r["id"] for r in body["results"]], ["b4675367"])
        self.assertEqual(body["results"][0]["audience_label"], "Teen")
        _, subjects = self.call("GET", "/api/subjects")
        self.assertIn("birds", [s["subject"] for s in subjects])

    def test_book_detail(self):
        status, book = self.call("GET", "/api/books/b6062504")
        self.assertEqual(status, 200)
        self.assertEqual(book["language_name"], "English")
        self.assertEqual((book["audience"], book["type"], book["nature"]), ("adult", "nonfiction", True))
        self.assertIn("birds", book["topics"])
        self.assertTrue(book["reasons"][0].startswith("audience adult"))
        self.assertTrue(book["holdings"])
        first = book["holdings"][0]
        self.assertIn("branch", first)
        self.assertIn("goodreads", book["links"])
        self.assertEqual(self.call("GET", "/api/books/b0000000")[0], 404)
        self.assertEqual(self.call("GET", "/api/books/b5674196")[0], 404)  # adult fiction is out of scope

    def test_catalog_swap_is_picked_up(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            cat = tmp / "catalog.db"
            httpd = server.serve("127.0.0.1", 0, tmp / "books.db", cat, quiet=True)
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            with urllib.request.urlopen(base + "/api/health") as r:
                self.assertIsNone(json.loads(r.read())["catalog"])
            with urllib.request.urlopen(base + "/api/search?q=bumblebee") as r:
                self.assertEqual(json.loads(r.read())["total"], 0)
            build_catalog(cat, RECORDS[:1])
            with urllib.request.urlopen(base + "/api/search?q=bumblebee") as r:
                self.assertEqual(json.loads(r.read())["total"], 1)
            build_catalog(cat, RECORDS[1:])  # rebuilt without it
            with urllib.request.urlopen(base + "/api/search?q=bumblebee") as r:
                self.assertEqual(json.loads(r.read())["total"], 0)
            httpd.shutdown()
            httpd.server_close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # --- lists

    def test_lists_are_shared(self):
        status, lst = self.call("POST", "/api/lists", {"name": "Bedtime"}, user="mk")
        self.assertEqual(status, 201)
        lid = lst["id"]
        self.assertEqual(lst["created_by"], "mk")
        # another user adds to it and sees it
        status, lst = self.call("POST", f"/api/lists/{lid}/items", {"book_id": "b5260625", "note": "loved it"}, user="hj")
        self.assertEqual(status, 201)
        item = lst["items"][0]
        self.assertEqual((item["title"], item["added_by"], item["note"]), ("1,2,3 bumblebee", "hj", "loved it"))
        self.assertEqual(item["author"], "Natalie Marshall")
        self.assertIn("ester.ee/record=b5260625", item["ester_url"])
        _, all_lists = self.call("GET", "/api/lists", user="mk")
        mine = [l for l in all_lists if l["id"] == lid][0]
        self.assertEqual(mine["count"], 1)
        # the book knows which lists it is on
        self.assertIn(lid, self.call("GET", "/api/books/b5260625")[1]["lists"])
        # adding again keeps one row; note edit; rename
        self.call("POST", f"/api/lists/{lid}/items", {"book_id": "b5260625"}, user="mk")
        _, lst = self.call("PATCH", f"/api/lists/{lid}/items/b5260625", {"note": "borrowed 14 Nov"})
        self.assertEqual((lst["count"], lst["items"][0]["note"]), (1, "borrowed 14 Nov"))
        _, lst = self.call("PATCH", f"/api/lists/{lid}", {"name": "Bedtime favourites"})
        self.assertEqual(lst["name"], "Bedtime favourites")
        # remove, then undo by adding back
        _, lst = self.call("DELETE", f"/api/lists/{lid}/items/b5260625")
        self.assertEqual(lst["count"], 0)
        self.call("POST", f"/api/lists/{lid}/items", {"book_id": "b5260625", "note": "borrowed 14 Nov"})
        self.assertEqual(self.call("GET", f"/api/lists/{lid}")[1]["count"], 1)
        # an item whose book left the catalogue keeps its snapshot and says so
        self.call("POST", f"/api/lists/{lid}/items", {"book_id": "b1111111", "title": "Old Estonian book"})
        items = {i["book_id"]: i for i in self.call("GET", f"/api/lists/{lid}")[1]["items"]}
        self.assertFalse(items["b1111111"]["in_catalogue"])
        self.assertTrue(items["b5260625"]["in_catalogue"])
        # delete the list
        self.assertEqual(self.call("DELETE", f"/api/lists/{lid}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/lists/{lid}")[0], 404)

    def test_list_validation(self):
        self.assertEqual(self.call("POST", "/api/lists", {"name": "  "})[0], 400)
        self.assertEqual(self.call("POST", "/api/lists", {"name": "x"}, ctype="text/plain")[0], 415)
        _, lst = self.call("POST", "/api/lists", {"name": "Tmp"})
        self.assertEqual(self.call("POST", f"/api/lists/{lst['id']}/items", {"book_id": "../etc"})[0], 400)
        self.assertEqual(self.call("POST", f"/api/lists/{lst['id']}/items", {"book_id": "b0000001"})[0], 404)
        self.assertEqual(self.call("POST", "/api/lists/999999/items", {"book_id": "b5260625"})[0], 404)

    def test_migrations_keep_data(self):
        _, lst = self.call("POST", "/api/lists", {"name": "Keep me"})
        self.assertEqual(dbm.migrate(self.tmp / "books.db"), [])
        self.assertEqual(self.call("GET", f"/api/lists/{lst['id']}")[1]["name"], "Keep me")


if __name__ == "__main__":
    unittest.main()
