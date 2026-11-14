"""The v2 facets and scope rule (crawler/classify.py). No network."""
from __future__ import annotations

import unittest

from crawler import classify

LENDABLE_CHILD = {"location": "TlnRK Kännukuke lastekirjandus", "call_number": "L(P) I/MAR", "status": "KOHAL", "note": ""}
CHILD_SHELF = {"location": "TlnRK Pääsküla lastekirjandus", "call_number": "L-I/SMI", "status": "KOHAL", "note": ""}
LENDABLE_ADULT = {"location": "TlnRK Liivalaia kojulaenutus", "call_number": "59 PET", "status": "KOHAL", "note": ""}
READING_ROOM = {"location": "TlnRK Südalinna lugemissaal", "call_number": "59 PET", "status": "KOHAL", "note": "KOHALKASUTUS"}


def rec(**kw) -> dict:
    base = {
        "language": "eng", "genres": [], "subjects": [], "udc": [], "udc_bt": [], "form": "",
        "pages": None, "holdings": [LENDABLE_ADULT],
    }
    return {**base, **kw}


CASES = [
    # (name, record, signals, want audience, want type, want kept, want reason)
    ("English picture book",
     rec(genres=["lastekirjandus", "pildiraamatud"], udc=["821.111-93-32"], form="1", pages=32, holdings=[LENDABLE_CHILD]),
     [], "picture_book", "fiction", True, ""),
    ("teen novel on adult shelves",
     rec(genres=["noorsookirjandus", "fantaasiaromaanid"], udc=["821.111(73)-312.9"], form="1", pages=340),
     [], "teen", "fiction", True, ""),
    ("middle-grade novel",
     rec(genres=["lastekirjandus", "jutustused"], udc=["821.111-93-31"], form="1", pages=180, holdings=[CHILD_SHELF]),
     [], "middle_grade", "fiction", True, ""),
    ("early reader",
     rec(genres=["lastekirjandus", "suurtähtraamatud"], udc=["821.111-93-32"], form="1", pages=48, holdings=[LENDABLE_CHILD]),
     [], "early_reader", "fiction", True, ""),
    ("board book",
     rec(genres=["lastekirjandus", "pappraamatud"], udc=["821.111-93"], form="1", pages=12, holdings=[LENDABLE_CHILD]),
     [], "baby_toddler", "fiction", True, ""),
    ("children's comic",
     rec(genres=["koomiksid", "lastekirjandus"], udc=["741.5(0.053.2)"], form="0", pages=48, holdings=[LENDABLE_CHILD]),
     [], "picture_book", "comics", True, ""),
    ("children's non-fiction about space",
     rec(genres=["lastekirjandus"], udc=["523(0.053.2)"], form="0", pages=96, holdings=[CHILD_SHELF]),
     [], "middle_grade", "nonfiction", True, ""),
    ("adult bird field guide",
     rec(genres=["määrajad"], udc=["598.2(4)(083.71)"], form="0", pages=448, subjects=["linnud"]),
     [], "adult", "nonfiction", True, ""),
    ("adult weather book (subject only)",
     rec(udc=[], subjects=["ilm", "pilved"], form="0", pages=224),
     [], "adult", "nonfiction", True, ""),
    ("adult novel",
     rec(genres=["ilukirjandus", "romaanid"], udc=["821.111(73)-31"], form="1", pages=320),
     [], "adult", "fiction", False, "adult fiction"),
    ("adult cookbook",
     rec(genres=["kokaraamatud"], udc=["641.5(083.12)"], form="0", pages=256),
     [], "adult", "nonfiction", False, "adult non-fiction, not nature"),
    ("adult travel guide (geography is not nature)",
     rec(genres=["reisijuhid"], udc=["913(591)(036)"], form="0", pages=300),
     [], "adult", "nonfiction", False, "adult non-fiction, not nature"),
    ("cat care with an animal-behaviour secondary UDC",
     rec(genres=["käsiraamatud"], udc=["636.8(035)", "591.5(035)"], subjects=["kass", "loomad"], form="0"),
     [], "adult", "nonfiction", False, "adult non-fiction, not nature"),
    ("felt crafts with a subject 'loomad'",
     rec(genres=["käsiraamatud"], udc=["745.52(035)"], udc_bt=["745/746"], subjects=["loomad"], form="0"),
     [], "adult", "nonfiction", False, "adult non-fiction, not nature"),
    ("travel guide with broad term 91 only",
     rec(genres=["reisijuhid"], udc=[], udc_bt=["91"], subjects=["loodus"], form="0"),
     [], "adult", "nonfiction", False, "adult non-fiction, not nature"),
    ("houseplants",
     rec(genres=["käsiraamatud"], udc=["635.91(035)"], form="0"),
     [], "adult", "nonfiction", False, "adult non-fiction, not nature"),
    ("library use only",
     rec(udc=["598.2"], form="0", holdings=[READING_ROOM]),
     [], "adult", "nonfiction", False, "library use only"),
    ("no Tallinn copy",
     rec(udc=["598.2"], form="0", holdings=[{"location": "TLÜAR hoidla", "call_number": "", "status": "KOHAL", "note": ""}]),
     [], "adult", "nonfiction", False, "no Tallinn copy"),
    ("Estonian picture book",
     rec(language="est", genres=["lastekirjandus", "pildiraamatud"], udc=["821.511.113-93-32"], form="1", pages=32, holdings=[LENDABLE_CHILD]),
     [], "picture_book", "fiction", False, "not English"),
    ("colouring book",
     rec(genres=["värvimisraamatud", "lastekirjandus"], udc=["793.7(0.053.2)"], form="0", pages=32, holdings=[LENDABLE_CHILD]),
     [], "picture_book", "activity", False, "genre värvimisraamatud"),
    ("no UDC, outside source says juvenile nature",
     rec(udc=[], form="0", pages=32),
     [{"source": "loc", "scheme": "lcsh", "code": "Weather -- Juvenile literature", "audience": "picture_book", "nature": True}],
     "picture_book", "nonfiction", True, ""),
    ("no UDC, outside source says adult nature",
     rec(udc=[], form="0", pages=300),
     [{"source": "loc", "scheme": "lcc", "code": "QL676", "nature": True, "audience": "adult"}],
     "adult", "nonfiction", True, ""),
]


class Rules(unittest.TestCase):
    def test_cases(self):
        for name, r, signals, audience, typ, kept, reason in CASES:
            with self.subTest(name):
                facets = classify.classify(r, signals)
                self.assertEqual(facets["audience"], audience, facets["reasons"])
                self.assertEqual(facets["type"], typ, facets["reasons"])
                self.assertEqual(classify.in_scope(r, facets), (kept, reason), facets["reasons"])
                self.assertTrue(facets["reasons"][0].startswith(f"audience {audience}:"))

    def test_outside_source_never_overrides_ester_children(self):
        r = rec(genres=["lastekirjandus", "pildiraamatud"], udc=["821.111-93-32"], form="1", pages=32)
        facets = classify.classify(r, [{"source": "openlibrary", "scheme": "subject", "code": "Fiction", "audience": "adult"}])
        self.assertEqual(facets["audience"], "picture_book")

    def test_udc_topics(self):
        self.assertEqual(classify.udc_topics(["598.2(4)", "551.5(0.053.2)", "523.4"]), ["birds", "weather", "the solar system"])
        self.assertEqual(classify.udc_topics(["821.111-93"]), [])

    def test_nature(self):
        self.assertTrue(classify.is_nature(rec(udc=["551.583"]))[0])
        self.assertTrue(classify.is_nature(rec(udc_bt=["57/59"]))[0])
        self.assertFalse(classify.is_nature(rec(udc=["641.5"]))[0])
        self.assertFalse(classify.is_nature(rec(udc=["512(075.8)"], udc_bt=["51"]))[0])


if __name__ == "__main__":
    unittest.main()
