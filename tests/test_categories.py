"""Outside category signals (crawler/categories.py) and the prefetch step. No network."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crawler import categories, classify, enrich

FIX = Path(__file__).parent / "fixtures" / "loc"

JUVENILE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<record xmlns="http://www.loc.gov/MARC21/slim">
  <leader>01234cam a2200301 a 4500</leader>
  <controlfield tag="008">190312s2019    nyua   j      000 0 eng  </controlfield>
  <datafield tag="050" ind1="0" ind2="0"><subfield code="a">QC981.3</subfield><subfield code="b">.S65 2019</subfield></datafield>
  <datafield tag="082" ind1="0" ind2="0"><subfield code="a">551.6</subfield></datafield>
  <datafield tag="521" ind1="1" ind2=" "><subfield code="a">Ages 4-8.</subfield></datafield>
  <datafield tag="650" ind1=" " ind2="0"><subfield code="a">Weather</subfield><subfield code="v">Juvenile literature.</subfield></datafield>
  <datafield tag="655" ind1=" " ind2="7"><subfield code="a">Picture books.</subfield></datafield>
</record>"""


class Loc(unittest.TestCase):
    def test_adult_field_guide(self):
        loc = categories.parse_loc((FIX / "lccn_2009037681_peterson_birds.xml").read_text())
        self.assertEqual(loc["lcc"], ["QL681"])
        self.assertEqual(loc["ddc"], ["598.097"])
        sigs = categories.loc_signals(loc)
        self.assertTrue(all(s["source"] == "loc" for s in sigs))
        self.assertTrue(any(s.get("nature") for s in sigs))
        self.assertFalse(any(s.get("audience") for s in sigs))
        self.assertIn(["birds"], [s.get("topics") for s in sigs])

    def test_adult_not_nature(self):
        sigs = categories.loc_signals(categories.parse_loc((FIX / "lccn_63021525_adult_social.xml").read_text()))
        self.assertFalse(any(s.get("nature") or s.get("audience") for s in sigs))

    def test_missing_record(self):
        self.assertEqual(categories.parse_loc((FIX / "lccn_missing.xml").read_text()), {})
        self.assertEqual(categories.parse_loc("not xml"), {})

    def test_juvenile_weather_picture_book(self):
        loc = categories.parse_loc(JUVENILE_XML)
        self.assertEqual(loc["audience008"], "j")
        sigs = categories.loc_signals(loc)
        # the specific audiences come first: picture book (655) and ages 4-8 (521), then "children"
        self.assertEqual(sigs[0]["audience"], "picture_book")
        self.assertIn("children", [s.get("audience") for s in sigs])
        self.assertTrue(any(s.get("nature") for s in sigs))  # QC981 is meteorology
        lcsh = [s for s in sigs if s["scheme"] == "lcsh"][0]
        self.assertEqual((lcsh["audience"], lcsh["type"], lcsh["topics"]), ("children", "nonfiction", ["weather"]))

    def test_openlibrary_juvenile_literature_is_nonfiction(self):
        sigs = categories.openlibrary_signals({"ol_subjects": ["Picture books", "Weather, juvenile literature"]})
        sig = [s for s in sigs if s["code"].startswith("Weather")][0]
        self.assertEqual((sig["audience"], sig["type"], sig["nature"]), ("children", "nonfiction", True))

    def test_lcc_and_ddc_ranges(self):
        self.assertTrue(categories._lcc_nature("QC 870"))
        self.assertFalse(categories._lcc_nature("QC 21"))   # physics
        self.assertFalse(categories._lcc_nature("QA76"))    # computing
        self.assertTrue(categories._ddc_nature("598.097"))
        self.assertTrue(categories._ddc_nature("551.6"))
        self.assertFalse(categories._ddc_nature("641.5"))
        self.assertEqual(categories._ages("Ages 3-7."), "picture_book")
        self.assertEqual(categories._ages("Grades 4-7."), "middle_grade")
        self.assertEqual(categories._ages("Ages 12 and up."), "teen")
        self.assertEqual(categories._ages("For adults"), "")

    def test_lccn_path(self):
        self.assertEqual(categories.lccn_path(" 2009037681 "), "https://lccn.loc.gov/2009037681/marcxml")


class GoogleAndOpenLibrary(unittest.TestCase):
    def test_google(self):
        sigs = categories.google_signals(["Juvenile Nonfiction / Science & Nature / Weather"])
        self.assertEqual(sigs[0]["audience"], "children")
        self.assertEqual(sigs[0]["type"], "nonfiction")
        self.assertTrue(sigs[0]["nature"])
        self.assertEqual(sigs[0]["topics"], ["weather"])
        sigs = categories.google_signals(["Nature / Birdwatching Guides"])
        self.assertTrue(sigs[0]["nature"])
        self.assertNotIn("audience", sigs[0])
        self.assertEqual(categories.google_signals(["Young Adult Fiction / Fantasy"])[0]["audience"], "teen")
        self.assertFalse(categories.google_signals(["Cooking / General"])[0].get("nature"))

    def test_openlibrary(self):
        sigs = categories.openlibrary_signals(
            {"ol_lcc": ["PZ7.C21476"], "ol_ddc": ["[E]"], "ol_subjects": ["Picture books", "Caterpillars", "Butterflies"]}
        )
        self.assertEqual(sigs[0]["audience"], "picture_book")
        self.assertIn("children", [s.get("audience") for s in sigs])
        self.assertIn(["butterflies"], [s.get("topics") for s in sigs])


class Classify(unittest.TestCase):
    def rec(self, **kw):
        base = {
            "id": "b1", "language": "eng", "genres": [], "subjects": [], "udc": [], "udc_bt": [], "form": "0",
            "pages": 300, "holdings": [{"location": "TlnRK Liivalaia kojulaenutus", "call_number": "", "status": "KOHAL", "note": ""}],
        }
        return {**base, **kw}

    def test_loc_rescues_undescribed_field_guide(self):
        r = self.rec()
        facets = classify.classify(r)
        self.assertEqual(classify.in_scope(r, facets), (False, "adult non-fiction, not nature"))
        sigs = categories.loc_signals(categories.parse_loc((FIX / "lccn_2009037681_peterson_birds.xml").read_text()))
        facets = classify.classify(r, sigs)
        self.assertEqual(classify.in_scope(r, facets), (True, ""))
        self.assertIn("birds", facets["topics"])
        self.assertTrue(any(x.startswith("nature: loc") for x in facets["reasons"]))

    def test_loc_audience_for_undescribed_childrens_book(self):
        r = self.rec(pages=None)
        facets = classify.classify(r, categories.loc_signals(categories.parse_loc(JUVENILE_XML)))
        self.assertEqual(facets["audience"], "picture_book")
        self.assertTrue(classify.in_scope(r, facets)[0])


class FakeFetcher:
    """Answers enrich/categories requests from a dict; counts requests."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.requests = 0

    def json(self, url):
        self.requests += 1
        return self.answers.get(url)

    def text(self, url):
        self.requests += 1
        return self.answers.get(url)


class Prefetch(unittest.TestCase):
    def test_prefetch_fills_both_caches(self):
        book = {"id": "b9", "title": "Peterson field guide to birds", "original_title": "", "language": "eng",
                "original_language": "", "isbns": ["9780547152462"], "authors": json.dumps(["Peterson, Roger Tory"])}
        answers = {
            "https://openlibrary.org/isbn/9780547152462.json": {
                "key": "/books/OL1M", "works": [{"key": "/works/OL1W"}], "covers": [123],
                "lccn": ["2009037681"], "lc_classifications": ["QL681 .P45 2009"], "dewey_decimal_class": ["598.097"],
            },
            "https://openlibrary.org/works/OL1W.json": {"description": "Birds.", "subjects": ["Birds", "Identification"]},
            "https://lccn.loc.gov/2009037681/marcxml": (FIX / "lccn_2009037681_peterson_birds.xml").read_text(),
        }
        with tempfile.TemporaryDirectory() as tmp:
            f = FakeFetcher(answers)
            stats = enrich.prefetch([book], Path(tmp), log=lambda m: None, fetcher=f)
            self.assertEqual((stats["looked_up"], stats["loc"]), (1, 1))
            self.assertEqual(f.requests, 3)
            sig = categories.Signals(Path(tmp))
            sigs = sig.for_record({"id": "b9"})
            self.assertEqual({s["source"] for s in sigs}, {"loc", "openlibrary"})
            sig.close()
            # second run: everything cached, no requests
            f2 = FakeFetcher(answers)
            enrich.prefetch([book], Path(tmp), log=lambda m: None, fetcher=f2)
            self.assertEqual(f2.requests, 0)


if __name__ == "__main__":
    unittest.main()
