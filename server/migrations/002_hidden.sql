-- Books nobody wants to see again. Shared like lists; kept in books.db so a new
-- catalogue upload from X1 never loses them. title/author are a snapshot for the Hidden page.

CREATE TABLE hidden_books (
    book_id   TEXT PRIMARY KEY,           -- ESTER record id
    title     TEXT NOT NULL,
    author    TEXT NOT NULL DEFAULT '',
    cover_url TEXT NOT NULL DEFAULT '',
    hidden_by TEXT NOT NULL,
    hidden_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
