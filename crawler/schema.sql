-- catalog.db: built on X1 by `python3 -m crawler.run`, uploaded to the droplet and
-- opened read-only by server/app.py. The crawler rebuilds the whole file each run,
-- so there are no migrations: bump `meta.schema_version` when this changes and keep
-- the server reading both for one release if needed.
--
-- JSON columns hold arrays of strings.

CREATE TABLE books (
    id              TEXT PRIMARY KEY,      -- ESTER record id, e.g. b5260625
    url             TEXT NOT NULL,         -- ESTER permalink
    title           TEXT NOT NULL,
    subtitle        TEXT NOT NULL DEFAULT '',
    responsibility  TEXT NOT NULL DEFAULT '', -- 245 $c as printed ("Natalie Marshall")
    authors         TEXT NOT NULL DEFAULT '[]', -- JSON, "Surname, Given"
    illustrators    TEXT NOT NULL DEFAULT '[]', -- JSON
    year            INTEGER,
    language        TEXT NOT NULL DEFAULT '',   -- MARC code: eng, est, rus, ...
    original_language TEXT NOT NULL DEFAULT '',
    original_title  TEXT NOT NULL DEFAULT '',   -- 240 / 246 x9, for translated editions
    isbns           TEXT NOT NULL DEFAULT '[]', -- JSON, digits only
    pages           INTEGER,
    extent          TEXT NOT NULL DEFAULT '',
    series          TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',   -- ESTER 520 summary, usually Estonian
    subjects        TEXT NOT NULL DEFAULT '[]', -- JSON, Estonian headings
    subjects_en     TEXT NOT NULL DEFAULT '[]', -- JSON, English where we have a translation
    genres          TEXT NOT NULL DEFAULT '[]', -- JSON, Estonian form headings
    genres_en       TEXT NOT NULL DEFAULT '[]', -- JSON
    tallinn_copies  INTEGER NOT NULL DEFAULT 0,
    available_copies INTEGER NOT NULL DEFAULT 0, -- status KOHAL at a Tallinn branch
    holdings_checked_at TEXT,                   -- ISO time of the MARC page fetch
    -- Filled by crawler/enrich.py (BOOKS-5); empty until then.
    cover_url       TEXT NOT NULL DEFAULT '',
    summary         TEXT NOT NULL DEFAULT '',   -- English summary
    summary_source  TEXT NOT NULL DEFAULT '',   -- openlibrary | google_books | ''
    links           TEXT NOT NULL DEFAULT '{}', -- JSON object: goodreads, openlibrary, google_books
    -- v2 facets (crawler/classify.py, BOOKS-11)
    audience        TEXT NOT NULL DEFAULT '',   -- baby_toddler | picture_book | early_reader | middle_grade | teen | adult
    type            TEXT NOT NULL DEFAULT '',   -- fiction | nonfiction | poetry | comics | activity
    topics          TEXT NOT NULL DEFAULT '[]', -- JSON, English topic tags
    nature          INTEGER NOT NULL DEFAULT 0, -- about the natural world (weather, animals, plants, space, ...)
    reasons         TEXT NOT NULL DEFAULT '[]'  -- JSON, why each facet was chosen
);

CREATE INDEX books_language ON books(language);
CREATE INDEX books_year ON books(year);
CREATE INDEX books_audience ON books(audience);
CREATE INDEX books_type ON books(type);

CREATE TABLE holdings (
    book_id     TEXT NOT NULL REFERENCES books(id),
    location    TEXT NOT NULL,   -- "TlnRK Kännukuke lastekirjandus"
    branch      TEXT NOT NULL,   -- location without the TlnRK prefix and department
    call_number TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT '',   -- raw ESTER status: KOHAL, TAGASTAMISTÄHT 12-12-26, ...
    status_en   TEXT NOT NULL DEFAULT '',   -- "Available", "Due 12 Dec 2026", ...
    available   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX holdings_book ON holdings(book_id);
-- Only lendable Tallinn copies are stored: library-use-only, reading-room and archive
-- copies are left out (v2), and tallinn_copies / available_copies count lendable ones.

CREATE TABLE subjects (
    book_id    TEXT NOT NULL REFERENCES books(id),
    subject    TEXT NOT NULL,   -- Estonian heading
    subject_en TEXT NOT NULL DEFAULT ''
);

CREATE INDEX subjects_subject_en ON subjects(subject_en);

CREATE TABLE topics (
    book_id TEXT NOT NULL REFERENCES books(id),
    topic   TEXT NOT NULL      -- English tag, same as books.topics
);

CREATE INDEX topics_topic ON topics(topic);

-- Every classification signal, per source, so facets can be traced and re-derived.
-- source: ester | loc | google | openlibrary
-- scheme: udc, udc_bt, ems_genre, ems_subject, marc008, location, callno (ester);
--         lcc, ddc, lcsh, marc008, audience_note (loc); bisac (google); subject, ddc, lcc (openlibrary)
CREATE TABLE classifications (
    book_id TEXT NOT NULL REFERENCES books(id),
    source  TEXT NOT NULL,
    scheme  TEXT NOT NULL,
    code    TEXT NOT NULL,
    label   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX classifications_book ON classifications(book_id);

-- Full-text search. rowid = books.rowid. Columns hold both Estonian and English text
-- so either language finds a book.
CREATE VIRTUAL TABLE books_fts USING fts5(
    title, authors, subjects, summary,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- keys: schema_version, crawled_at (ISO UTC), books, english_books, available_books,
--       requests, crawl_status (ok | partial: <reason>), dropped, dropped_reasons (JSON),
--       audiences (JSON counts), types (JSON counts), nature_books
