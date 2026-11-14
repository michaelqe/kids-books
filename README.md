# Kids Books

A simple English UI for finding **picture books** in Tallinn's libraries (from the Estonian
ESTER catalogue), with covers and summaries from Open Library, and shared reading lists.

- Live: https://books.app.kennedy.ee (droplet, behind Caddy `import protected`)
- Dev: X1 (`~/src/personal/kids-books`), http://127.0.0.1:8512 via `kids-books-dev`
- Magpie project: Childrens Books (BOOKS)

## How it fits together

```text
X1 (nightly 03:30, kids-books-crawl.timer)            droplet
  crawler/  ESTER MARC pages ─┐                        server/app.py :8512  <- Caddy books.app.kennedy.ee
            Open Library    ──┴─> data/catalog.db ──scp──> data/catalog.db (read-only)
                                                          data/books.db  (shared lists, backed up nightly)
```

- `crawler/` (**X1 only**, Python 3 stdlib): walks ESTER's picture-book genre list, keeps books a
  Tallinn library holds, reads each book's MARC view (data + holdings), applies the picture-book
  rule, adds covers and English summaries, and writes `data/catalog.db` (SQLite + FTS5, schema in
  `crawler/schema.sql`). Fetched pages are cached in `~/.cache/kids-books/`, so nightly runs only
  fetch new books and a rotating seventh of the holdings.
- `server/` (droplet; X1 for dev, Python 3 stdlib): serves `web/` and the JSON API. Search reads
  `catalog.db`; lists live in `books.db`. **It never calls ESTER or any other site.**
- `web/`: plain HTML, CSS and an ES module. No build step, no npm.

## Run locally

```sh
python3 -m crawler.run --out data/catalog.db              # X1 only; first run takes hours
python3 -m crawler.run --out data/catalog.db --build-only # rebuild from the cache, no network
python3 server/app.py --port 8512 --db data/books.db --catalog data/catalog.db
# open http://127.0.0.1:8512
```

Useful crawl flags: `--max-list-pages N`, `--max-records N`, `--skip-list`, `--no-enrich`,
`--enrich-max N`, `--refresh-days N`. Set `GOOGLE_BOOKS_API_KEY` to add Google Books summaries
(the keyless quota is shared and usually exhausted).

## Tests

```sh
python3 -m unittest discover -s tests
```

No network: ESTER pages are fixtures in `tests/fixtures/ester/`; Open Library answers are canned.

## Deploy

Droplet, once (needs sudo; installs the unit, a sudoers line so deploys can restart it, the Caddy
block and the nightly lists backup):

```sh
ssh michael@142.93.133.110
git clone https://github.com/michaelqe/kids-books.git ~/kids-books   # or let deploy.sh clone it
sudo ~/kids-books/deploy/droplet/install.sh
```

Then every deploy (the X1 poller runs this after a merge; see `.magpie.toml`):

```sh
deploy/droplet/deploy.sh     # pull on the droplet, restart, check /api/health reports this commit
```

X1, once: `deploy/x1/install.sh` (user units: the nightly crawl + upload, and the dev server).
Crawl and upload by hand: `deploy/x1/crawl-and-upload.sh` (or `--upload-only`).
