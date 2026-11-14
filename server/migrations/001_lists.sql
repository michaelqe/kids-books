-- Shared book lists. Every logged-in user sees and edits every list.
-- Items keep a snapshot of the book so a list renders without the catalogue
-- (and survives a book dropping out of it).

CREATE TABLE lists (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE list_items (
    list_id       INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
    book_id       TEXT NOT NULL,          -- ESTER record id
    title         TEXT NOT NULL,
    author        TEXT NOT NULL DEFAULT '',
    year          INTEGER,
    language      TEXT NOT NULL DEFAULT '',
    isbn          TEXT NOT NULL DEFAULT '',
    cover_url     TEXT NOT NULL DEFAULT '',
    ester_url     TEXT NOT NULL DEFAULT '',
    goodreads_url TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    added_by      TEXT NOT NULL,
    added_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (list_id, book_id)
);

CREATE INDEX list_items_book ON list_items(book_id);
