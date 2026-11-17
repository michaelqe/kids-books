# Kids Books

A simple English UI for finding **English children's books** (and adult nature non-fiction such
as field guides) that can be borrowed from Tallinn's libraries, from the Estonian ESTER catalogue,
with covers and summaries from Open Library, categories from several sources, and shared reading
lists.

- Live: https://books.app.kennedy.ee (droplet, behind Caddy `import protected`)
- Demo (no login): https://books.app.kennedy.ee/demo/ — same catalogue, its own lists in `data/demo.db`
- Dev: X1 (`~/src/personal/kids-books`), http://127.0.0.1:8512 via `kids-books-dev`
- Magpie project: Childrens Books (BOOKS)

## How it fits together

```text
X1 (nightly 03:30, kids-books-crawl.timer)            droplet
  crawler/  ESTER MARC pages ─┐                        server/app.py :8512  <- Caddy books.app.kennedy.ee
            Open Library    ──┴─> data/catalog.db ──scp──> data/catalog.db (read-only)
                                                          data/books.db  (shared lists, backed up nightly)
```

- `crawler/` (**X1 only**, Python 3 stdlib): searches ESTER for every English book in Tallinn's
  libraries (by imprint decade, about 34.5k records), reads each record's Tallinn-scoped MARC view
  (data + Tallinn copies, plus the full holdings page when it stops at 10), classifies it
  (`crawler/classify.py`: audience, type, topics, nature, each with a reason), keeps children's
  books and adult nature non-fiction with a lendable copy, adds covers, summaries and outside
  categories, and writes `data/catalog.db` (SQLite + FTS5, schema in `crawler/schema.sql`).
  Fetched pages are cached in `~/.cache/kids-books/`. The first crawl takes about 10 hours at
  1 request a second. After that, nightly runs fetch new records, a seventh of the kept books'
  holdings, and re-check out-of-scope records every 60 days.
- `server/` (droplet; X1 for dev, Python 3 stdlib): serves `web/` and the JSON API. Search reads
  `catalog.db`; lists and the hidden-books override list live in `books.db`. **It never calls ESTER or any other site.**
- `web/`: plain HTML, CSS and an ES module. No build step, no npm.

## Run locally

```sh
python3 -m crawler.run --out data/catalog.db              # X1 only; first run takes hours
python3 -m crawler.run --out data/catalog.db --build-only # rebuild from the cache, no network
python3 server/app.py --port 8512 --db data/books.db --catalog data/catalog.db
# open http://127.0.0.1:8512
```

Useful crawl flags: `--max-list-pages N`, `--max-records N`, `--skip-list`, `--no-enrich`,
`--enrich-max N`, `--refresh-days N`, `--recheck-days N`, `--no-build` (fetch only).
Set `GOOGLE_BOOKS_API_KEY` to add Google Books summaries and categories (the keyless quota is
shared and usually exhausted; X1 has no key today). Outside categories come from the Library of
Congress (by the LCCN Open Library knows) and Open Library; see `crawler/categories.py`.

## UIs (skins)

`web/themes/<key>.css` loads on top of `style.css`. The default is **Wren Library** (`dkwren`); `classic` is still in the picker. Pick one with the **UI** button (remembered per
device) or `?ui=<key>`. The list and blurbs are in `web/themes.js`: classic, catalog, atlas (robust
filters: topics, libraries, year, length, sort), y2013, metro, shelf, coverflow, storybook,
fieldguide, brutal, swiss, rails, pinboard, terminal, popart, nightlight, plus ten dark sidebar-filter
skins (`dk*`, shared layout in `style.css`): dkslate, dkmoss, dkplum, dkember, dkocean (rounded cards),
dkgraphite, dkforest, dkwine, dkmidnight, dkcopper (square cards), and textured Forest variants
(dkwren, dknavyleather, dkoxblood, dkcognac, dkforestgrain; the texture is a tiled inline SVG). `python3 dev/demo_catalog.py`
builds a small demo catalogue to look at them without the real one.

## Tests

```sh
python3 -m unittest discover -s tests
```

No network: ESTER pages are fixtures in `tests/fixtures/ester/`; Open Library answers are canned.

## Deploy

Droplet, once (needs sudo; installs the unit, a sudoers line so deploys can restart it, the Caddy
block and the nightly lists backup):

```sh
ssh michael@running.app.kennedy.ee
git clone https://github.com/michaelqe/kids-books.git ~/kids-books   # or let deploy.sh clone it
sudo ~/kids-books/deploy/droplet/install.sh
```

Re-run `install.sh` whenever `Caddyfile.books` changes; `deploy.sh` doesn't touch Caddy.

Then every deploy (the X1 poller runs this after a merge; see `.magpie.toml`):

```sh
deploy/droplet/deploy.sh     # pull on the droplet, restart, check /api/health reports this commit
```

X1, once: `deploy/x1/install.sh` (user units: the nightly crawl + upload, and the dev server).
Crawl and upload by hand: `deploy/x1/crawl-and-upload.sh` (or `--upload-only`).
