# Kids Books

A simple English UI for finding **picture books** in the Estonian library catalogue (ESTER),
with covers and summaries from English sources, and shared reading lists.

- Live: https://books.app.kennedy.ee (droplet, behind Caddy `import protected`)
- Dev: X1 (`~/src/personal/kids-books`)
- Magpie project: Childrens Books (BOOKS)

## Stack

- `web/`: plain HTML, CSS and ES modules. No build step, no npm.
- `crawler/` (runs on **X1 only**): Python 3 stdlib. Crawls ESTER for picture books, adds
  covers and summaries (Open Library, Google Books), and writes `data/catalog.db` (SQLite + FTS5).
  A nightly `systemd --user` timer on X1 runs it, then uploads `catalog.db` to the droplet.
- `server/` (droplet; also X1 for dev): Python 3 **standard library only** (`http.server`, `sqlite3`).
  Serves `web/` and a JSON API. Search reads `catalog.db` read-only; lists live in `data/books.db`.
  **The server never calls ESTER or any other outside site.**
- `data/`: `catalog.db` (rebuilt by the crawler, replaceable) and `books.db` (shared lists,
  back this one up). Not in git.

## Run locally

```sh
python3 -m crawler.run --out data/catalog.db     # X1 only
python3 server/app.py --port 8512 --db data/books.db --catalog data/catalog.db
# open http://127.0.0.1:8512
```

## Tests

```sh
python3 -m unittest discover -s tests
```

## Deploy (droplet)

See `deploy/` (systemd unit `kids-books` on 127.0.0.1:8512, Caddy block for
`books.app.kennedy.ee`).
