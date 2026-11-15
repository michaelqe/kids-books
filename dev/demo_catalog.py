"""Build a small demo catalog.db (real titles, Open Library covers by ISBN) for looking at the UI.

    python3 dev/demo_catalog.py data/demo-catalog.db
    python3 server/app.py --port 8512 --db data/demo-books.db --catalog data/demo-catalog.db

Dev only: invented holdings and summaries, no network. The browser fetches the covers.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# title, author ("Surname, Given"), isbn, year, pages, audience, type, topics, nature
BOOKS = [
    ("The Very Hungry Caterpillar", "Carle, Eric", "9780399226908", 1969, 26, "picture_book", "fiction", ["animals", "insects", "food"], 0),
    ("Where the Wild Things Are", "Sendak, Maurice", "9780060254926", 1963, 40, "picture_book", "fiction", ["monsters", "imagination"], 0),
    ("Goodnight Moon", "Brown, Margaret Wise", "9780060775872", 1947, 32, "baby_toddler", "fiction", ["bedtime", "moon"], 0),
    ("Brown Bear, Brown Bear, What Do You See?", "Martin, Bill", "9780805047905", 1967, 28, "baby_toddler", "fiction", ["animals", "colours"], 0),
    ("Chicka Chicka Boom Boom", "Martin, Bill", "9781442450707", 1989, 36, "baby_toddler", "poetry", ["alphabet", "rhyme"], 0),
    ("The Snowy Day", "Keats, Ezra Jack", "9780670867332", 1962, 32, "picture_book", "fiction", ["snow", "weather", "city"], 1),
    ("Owl Babies", "Waddell, Martin", "9780763617080", 1992, 32, "picture_book", "fiction", ["owls", "birds", "animals"], 1),
    ("Stellaluna", "Cannon, Janell", "9780152802172", 1993, 48, "picture_book", "fiction", ["bats", "birds", "animals"], 1),
    ("Make Way for Ducklings", "McCloskey, Robert", "9780140501742", 1941, 64, "picture_book", "fiction", ["ducks", "birds", "city"], 1),
    ("Green Eggs and Ham", "Seuss", "9780394800165", 1960, 62, "early_reader", "poetry", ["rhyme", "food"], 0),
    ("The Cat in the Hat", "Seuss", "9780394800011", 1957, 61, "early_reader", "poetry", ["rhyme", "cats"], 0),
    ("The Lorax", "Seuss", "9780394823379", 1971, 72, "picture_book", "fiction", ["trees", "environment"], 1),
    ("Frog and Toad Are Friends", "Lobel, Arnold", "9780064440202", 1970, 64, "early_reader", "fiction", ["friendship", "frogs", "animals"], 0),
    ("Press Here", "Tullet, Hervé", "9780811879545", 2011, 56, "picture_book", "activity", ["play", "colours"], 0),
    ("Oh, the Places You'll Go!", "Seuss", "9780679805274", 1990, 56, "picture_book", "poetry", ["rhyme", "growing up"], 0),
    ("Corduroy", "Freeman, Don", "9780140501735", 1968, 32, "picture_book", "fiction", ["toys", "bears", "friendship"], 0),
    ("Charlotte's Web", "White, E. B.", "9780064400558", 1952, 184, "middle_grade", "fiction", ["spiders", "farm", "friendship", "animals"], 0),
    ("Matilda", "Dahl, Roald", "9780142410370", 1988, 240, "middle_grade", "fiction", ["school", "magic"], 0),
    ("The Magic Tree House: Dinosaurs Before Dark", "Osborne, Mary Pope", "9780679824114", 1992, 68, "early_reader", "fiction", ["dinosaurs", "time travel"], 0),
    ("Diary of a Wimpy Kid", "Kinney, Jeff", "9780810993136", 2007, 217, "middle_grade", "comics", ["school", "humour"], 0),
    ("Dog Man", "Pilkey, Dav", "9780545581608", 2016, 240, "early_reader", "comics", ["dogs", "humour"], 0),
    ("The Wild Robot", "Brown, Peter", "9780316381994", 2016, 279, "middle_grade", "fiction", ["robots", "island", "animals"], 1),
    ("Wonder", "Palacio, R. J.", "9780375869020", 2012, 315, "middle_grade", "fiction", ["school", "kindness"], 0),
    ("A Wrinkle in Time", "L'Engle, Madeleine", "9780312367541", 1962, 211, "middle_grade", "fiction", ["space", "science fiction"], 0),
    ("Bridge to Terabithia", "Paterson, Katherine", "9780064401845", 1977, 163, "middle_grade", "fiction", ["friendship", "imagination"], 0),
    ("Hatchet", "Paulsen, Gary", "9781416936473", 1987, 195, "teen", "fiction", ["survival", "wilderness"], 1),
    ("The Giver", "Lowry, Lois", "9780544336261", 1993, 240, "teen", "fiction", ["dystopia"], 0),
    ("Percy Jackson and the Lightning Thief", "Riordan, Rick", "9781423113386", 2005, 377, "teen", "fiction", ["myths", "adventure"], 0),
    ("Harry Potter and the Sorcerer's Stone", "Rowling, J. K.", "9780590353427", 1998, 309, "middle_grade", "fiction", ["magic", "school"], 0),
    ("The Hobbit", "Tolkien, J. R. R.", "9780547928227", 1937, 300, "teen", "fiction", ["dragons", "adventure"], 0),
    ("Cloudy with a Chance of Meatballs", "Barrett, Judi", "9780689707490", 1978, 32, "picture_book", "fiction", ["weather", "food"], 1),
    ("National Geographic Kids Weather", "Rattini, Kristin Baird", "9781426309144", 2018, 48, "early_reader", "nonfiction", ["weather", "clouds", "storms"], 1),
    ("Dinosaurs: A Visual Encyclopedia", "Naish, Darren", "9781465414373", 2018, 208, "middle_grade", "nonfiction", ["dinosaurs", "fossils"], 1),
    ("The Magic School Bus Lost in the Solar System", "Cole, Joanna", "9780590414289", 1990, 40, "picture_book", "nonfiction", ["space", "planets"], 1),
    ("What Do You Do with a Tail Like This?", "Jenkins, Steve", "9780547250434", 2003, 32, "picture_book", "nonfiction", ["animals", "bodies"], 1),
    ("A Child's Introduction to the Night Sky", "Driscoll, Michael", "9781579128685", 2004, 96, "middle_grade", "nonfiction", ["space", "stars", "moon"], 1),
    ("Rocks and Minerals", "Symes, R. F.", "9780756645564", 2008, 64, "middle_grade", "nonfiction", ["rocks", "minerals", "geology"], 1),
    ("Peterson Field Guide to Birds of Eastern and Central North America", "Peterson, Roger Tory", "9780547152462", 2010, 560, "adult", "nonfiction", ["birds", "field guide"], 1),
    ("Collins Bird Guide", "Svensson, Lars", "9780007268146", 2009, 400, "adult", "nonfiction", ["birds", "field guide", "Europe"], 1),
    ("The Hidden Life of Trees", "Wohlleben, Peter", "9781771642484", 2016, 288, "adult", "nonfiction", ["trees", "forests"], 1),
    ("The Weather Book", "Burroughs, William", "9780316107433", 1996, 224, "adult", "nonfiction", ["weather", "climate"], 1),
    ("Mushrooms of Northern Europe", "Phillips, Roger", "9780330264419", 2006, 384, "adult", "nonfiction", ["fungi", "field guide"], 1),
    ("Owl Moon", "Yolen, Jane", "9780399214578", 1987, 32, "picture_book", "fiction", ["owls", "winter", "night"], 1),
    ("Guess How Much I Love You", "McBratney, Sam", "9780763642662", 1994, 32, "baby_toddler", "fiction", ["hares", "love"], 0),
    ("Dear Zoo", "Campbell, Rod", "9781416947370", 1982, 18, "baby_toddler", "activity", ["animals", "lift-the-flap"], 0),
    ("We're Going on a Bear Hunt", "Rosen, Michael", "9781406358056", 1989, 36, "picture_book", "fiction", ["bears", "adventure"], 0),
    ("The Gruffalo", "Donaldson, Julia", "9780142501979", 1999, 32, "picture_book", "fiction", ["monsters", "forests", "rhyme"], 1),
    ("The Tiger Who Came to Tea", "Kerr, Judith", "9780007215997", 1968, 32, "picture_book", "fiction", ["tigers", "food"], 0),
    ("Poems to Learn by Heart", "Kennedy, Caroline", "9780786808915", 2013, 128, "middle_grade", "poetry", ["poems"], 0),
    ("Smile", "Telgemeier, Raina", "9780545132060", 2010, 213, "middle_grade", "comics", ["school", "growing up"], 0),
    ("How to Draw Animals", "Ames, Lee J.", "9780823022830", 2004, 48, "middle_grade", "activity", ["drawing", "animals"], 0),
    ("Dinosaur Roar!", "Stickland, Paul", "9780525454144", 1994, 32, "baby_toddler", "picture", ["dinosaurs", "opposites"], 0),
]
BRANCHES = ["Kännukuke lastekirjandus", "Nõmme Raamatukogu", "Kristiine Keskraamatukogu", "Pelgulinna Raamatukogu",
            "Mustamäe Raamatukogu", "Pirita Raamatukogu", "Linnamäe Raamatukogu", "Lasnamäe Keskraamatukogu"]


def main(out: Path) -> None:
    out.unlink(missing_ok=True)
    db = sqlite3.connect(out)
    db.executescript((ROOT / "crawler" / "schema.sql").read_text())
    rnd = random.Random(7)
    for i, (title, author, isbn, year, pages, aud, typ, topics, nature) in enumerate(BOOKS):
        typ = "picture" if typ == "picture" else typ
        typ = "fiction" if typ == "picture" else typ
        bid = f"b{1000000 + i * 37}"
        copies = rnd.choice([0, 1, 1, 2, 3, 4])
        avail = min(copies, rnd.choice([0, 1, 1, 2, 3]))
        cover = f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg?default=false"
        if i % 11 == 10:
            cover = ""   # a few books Open Library lacks: placeholder tiles
        summary = (f"{title} is a well-loved {'non-fiction' if typ == 'nonfiction' else 'story'} for "
                   f"{aud.replace('_', ' ')} readers, about {' and '.join(topics[:2])}. "
                   "This summary is invented for the demo catalogue.")
        db.execute(
            """INSERT INTO books (id,url,title,authors,year,language,isbns,pages,tallinn_copies,available_copies,
               cover_url,summary,summary_source,links,audience,type,topics,nature,reasons,notes,subjects_en,genres_en,holdings_checked_at)
               VALUES (?,?,?,?,?,'eng',?,?,?,?,?,?,?,?,?,?,?,?,?,'',?, '[]', '2026-11-14T03:30:00+00:00')""",
            (bid, f"https://ester.ee/record={bid}", title, json.dumps([author]), year, json.dumps([isbn]), pages, copies, avail,
             cover, summary, "openlibrary", "{}", aud, typ, json.dumps(topics), nature, json.dumps(["demo data"]), json.dumps(topics)))
        for t in topics:
            db.execute("INSERT INTO topics VALUES (?,?)", (bid, t))
        for c in range(copies):
            br = rnd.choice(BRANCHES)
            ok = 1 if c < avail else 0
            db.execute("INSERT INTO holdings VALUES (?,?,?,?,?,?,?)", (
                bid, f"TlnRK {br}", br, f"{'J' if aud != 'adult' else '5'} {author[:3].upper()}",
                "KOHAL" if ok else "TAGASTAMISTÄHT 12-12-26", "Available" if ok else "Due 12 Dec 2026", ok))
        db.execute("INSERT INTO books_fts (rowid, title, authors, subjects, summary) VALUES ((SELECT rowid FROM books WHERE id=?),?,?,?,?)",
                   (bid, title, author, " ".join(topics), summary))
    for k, v in {"schema_version": "2", "crawled_at": "2026-11-14T03:30:00+00:00", "books": str(len(BOOKS)),
                 "english_books": str(len(BOOKS)), "available_books": "0", "nature_books": "0"}.items():
        db.execute("INSERT INTO meta VALUES (?,?)", (k, v))
    db.commit()
    db.close()
    print(f"wrote {out} with {len(BOOKS)} books")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/demo-catalog.db"))
