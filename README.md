# Kids Books

A simple English UI for finding **picture books** in the Estonian library catalogue (ESTER),
with covers and summaries from English sources, and shared reading lists.

- Live: https://books.app.kennedy.ee (droplet, behind Caddy `import protected`)
- Dev: X1 (`~/src/personal/kids-books`)
- Magpie project: Childrens Books (BOOKS)

## Stack

- `web/`: plain HTML, CSS and ES modules. No build step, no npm.
- `server/`: Python 3 **standard library only** (`http.server`, `sqlite3`, `urllib`).
  Serves `web/`, a JSON API, the ESTER search adapter and the cover/summary lookup.
- `data/books.db`: SQLite (lists, cache). Not in git.

## Run locally

```sh
python3 server/app.py --port 8512 --db data/books.db
# open http://127.0.0.1:8512
```

## Tests

```sh
python3 -m unittest discover -s tests
```

## Deploy (droplet)

See `deploy/` (systemd unit `kids-books` on 127.0.0.1:8512, Caddy block for
`books.app.kennedy.ee`).
