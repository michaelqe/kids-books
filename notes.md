# Notes

- 2026-11-14: Repo scaffolded. ESTER (www.ester.ee) is still Sierra WebPAC (`search~S1*est`);
  no public JSON API found yet, so expect HTML scraping. See ticket BOOKS-3 (parent BOOKS-1).
- Droplet port reserved: 8512 (8500-8511 in use).
- 2026-11-14: The user decided scraping runs on X1, not the droplet. X1 builds `catalog.db` and uploads it
  (same pattern as fantasy: crawl on an X1 user timer, then upload). The droplet only serves.

## ESTER (BOOKS-3, 14 Nov 2026)

- Sierra WebPAC, HTML only. No SRU/JSON found; the **MARC view** (`/search~S1*est?/.b{id}/.b{id}/1%2C1%2C1%2CB/marc~b{id}`)
  is the structured source: raw MARC in a `<pre>` (fixed columns: `245 10 data`, continuation lines indented 7)
  **plus the holdings table** (`tr.bibItemsEntry`: ASUKOHT, KOHAVIIT, STAATUS, MÄRKUSED). One request per book.
- Seed: the browse list for the form heading `pildiraamatud (vormimärksõna)` (EMS014937): 9166 records across
  all of ESTER, 50 per page (`&51,9166` offsets). Brief citations carry id, title, imprint, extent, ISBN and the
  holding libraries (`div.briefcitStatus`), so we keep Tallinn records (`TlnRK …`, not OverDrive) before fetching
  MARC. About 3/4 of the first page is held in Tallinn.
- Fields used: 008/35-37 language, 008/07-10 year, 020 ISBN, 041$h original language, 100/700 names
  (700$e roles for illustrators), 245, 300 extent, 490 series, 520 notes, 650/651 subjects, 655 genres.
- Statuses seen: `KOHAL` (on the shelf), `TÄHTAEG dd.mm.yy` (on loan, due).
- Picture-book rule (`crawler/ester.is_picture_book`): genre pildiraamatud; not colouring/sticker books;
  ≤ 64 pages; > 48 pages with a novel/story genre is dropped. Page count sums the extent ("96, [1] lk." = 97).
  English picture books without the pildiraamatud heading are missed; add more seed headings if that shows.
- First full crawl: ~185 list pages + one MARC page per Tallinn record at 1 req/s. Later runs refetch the list and
  new records, and holdings older than `--refresh-days` (7), so about a seventh of the books each night.
- State (`~/.cache/kids-books/state.db`, zlib pages) survives rebuilds; `--build-only` rebuilds offline.

## ESTER v2 probe (BOOKS-10, 14 Nov 2026)

Measured on X1 at about 1 req/s, roughly 450 requests in total.

- **Query.** Use keyword search with limits. Two URL shapes:
  - First page: `/search~S8*est/X?SEARCH=u:(201*)&searchscope=8&l=eng&m=a&b=vv&SORT=D`
  - Page N: `/search~S8*est?/X{q}/X{q}&SUBKEY={quote(term)}/{offset}%2C{total}%2C{total}%2CB/browse`
  - `q` is the whole `u:(…)&searchscope=…&SORT=D` string.
  - Limits: `l=eng` language, `m=a` books, `b=vv` all TlnRK, `b=vlk` TlnRK children's literature,
    `b=vve` OverDrive. Scopes: 8 TlnRK, 20 TlnRK lastekirjandus.
  - `u:` is the publisher/place/year index, and it takes `*` truncation.
  - An empty `SEARCH`, or a bare `*`, returns nothing.
  - Results are brief citations in the same markup as the genre list, so `ester.parse_list` reads them.
    The next-page link has a different shape, so page by offset up to the total.
- **Size.**

  | Slice | Records |
  |---|---|
  | `u:(19*)` | 3,675 |
  | `u:(200*)` | 7,163 |
  | `u:(201*)` | 14,897 |
  | `u:(202*)` | 8,738 |

  About 34.5k distinct records. Per-year counts for 1960–2026 sum to 35,050 for `vv` and 4,956 for `vlk`;
  a reprint's imprint can carry two years, which explains the overlap. Peak years are 2018–2019
  (about 2,000 a year for `vv`, 350 for `vlk`).
- **Brief citations aren't proof of a copy.** Every TlnRK record lists "TlnRK Tallinna Raamatukogud", even when
  the only copies are elsewhere or on OverDrive. Only the MARC/holdings page tells.
- **No result cap.** The last page of a 14,897-record slice loads fine. Decade slices are enough.
- **Narrowing.** No usable UDC limit: the `g:` keyword index and UDC browse don't honour `l=`/`b=`.
  So fetch MARC for every English TlnRK record once. That's about 34.5k requests, roughly 10 h, run once.
  After that, nightly runs fetch only new records plus the holdings rotation for kept books.
- **Holdings bug (also in v1).** A MARC page shows at most 10 copies.
  - 2,140 of the 5,330 cached v1 pages show exactly 10, so Tallinn copies can be hidden behind other libraries'.
  - Fix: fetch the MARC view through scope 8 (`/search~S8*est?/.b{id}/…/marc~b{id}`), which lists Tallinn
    copies first.
  - When that view shows 10 rows, also fetch the Tallinn holdings page:
    `/search~S8*est?/.b{id}/.b{id}/1%2C1%2C1%2CB/holdings~{id}&FF=&1%2C0%2C`. It lists every Tallinn copy
    (19–26 copies seen where the MARC view showed 10).
- **Language.** `l=eng` also matches bilingual and parallel-text records (Russian Alice, a Turkish/English
  picture book). Keep only 008/35-37 = `eng`.

**Signal coverage** (random sample of 198 MARC pages: 72 children's-location, 126 all-TlnRK):

| Signal | Children's (72) | All TlnRK (126) | Notes |
|---|---|---|---|
| 080 UDC | 100% | 87% | `-93` = children's fiction (58% / 11%); `(0.053.2)`/`-053.2` = for children (most of the rest of the children's set); `(03)`/`(038)` reference 6% |
| 072 | 100% | 88% | broad UDC, `821-93` etc. |
| 655 genre | 100% | 89% | lastekirjandus 81% of children's; noorsookirjandus (YA) 12% of all; ilukirjandus 42% of all; e-raamatud flags OverDrive |
| 008/33 form | 100% | 99% | `0` non-fiction, `1`/`f` fiction: reliable |
| 008/22 audience | 1% | 5% | mostly `|` fill: useless |
| 520 summary | rare | 17% | |
| holdings dept | | | `lastekirjandus`, `laste koomiksikogu` (children's); `kojulaenutus` (adult lending); `koomiksikogu`; `lugemissaal` (reading room, library use); `muusika- ja filmisaal`; `miniraamatukogu` |
| call no. | | | `L`, `L(P)` (picture book), `L-I`, `L-Luul`, `LI-74` children's; `I`, `I-74` fiction; `N`; UDC numbers for adult non-fiction (`59`, `913(E)`) |
| holdings notes | | | mostly empty; `Kingitud raamat` (gift); `KAASAS LISA(D)` (comes with CD etc.); `KOHALKASUTUS` (library use only) |
| status | | | `KOHAL`, `TÄHTAEG dd.mm.yy`, `VARUKOGUS` (in the reserve stock, can be ordered), `TÖÖTLUSES` (processing), `TEEL` (in transit) |

- **Adult nature non-fiction is rare.** About 3% of the adult sample (UDC 57x/58x/59x/91x), so roughly 1k books.
  Expect about 5k children's-shelf books, about 3k YA shelved for adults (noorsookirjandus), and about 1k adult
  nature, so roughly 9k kept.
- **Fixtures** (Tallinn-scoped MARC views) in `tests/fixtures/ester/`:
  - `marc_b6062504_eng_adult_nature`, `marc_b2101439_eng_adult_nature2`: kept
  - `marc_b4675367_eng_teen`: kept
  - `marc_b4555593_eng_child_nonfiction`: kept
  - `marc_b5674196_eng_adult_fiction`: dropped
  - `marc_b1253057_library_use_only`: dropped
  - `marc_b6101819_tln_ten` + `holdings_b6101819_tln`: 10 rows → 21 Tallinn copies
  - `list_eng_vlk_2019_p1`: keyword list page
- **Estimates at 1 req/s:**
  - First crawl: about 700 list pages plus about 34.5k MARC pages plus about 1.5k holdings pages, roughly 10–11 h.
  - Nightly: list (about 12 min), new records (a few), a seventh of kept books' holdings (about 1.3k, about 25 min).
  - Enrichment: Open Library about 2–3 requests and LoC 1 request per kept book, about 30k requests,
    so about 9 h the first time, then only new books.

## Outside categories (BOOKS-12, 14 Nov 2026)

- **LoC SRU ISBN index doesn't work.** `http://lx2.loc.gov:210/LCDB?...query=bath.isbn=…` returns 0 records,
  even for ISBNs LoC holds (The Very Hungry Caterpillar). `bath.standardIdentifier` is unsupported. Title search
  works but is too fuzzy to use.
- **What works:** the LCCN permalink `https://lccn.loc.gov/{lccn}/marcxml` (full MARCXML; a miss returns
  `<error>Record not found…`).
  - The LCCN comes from the Open Library edition (`lccn`). So the chain is OL edition → LCCN → LoC record.
  - Open Library editions also carry `lc_classifications` and `dewey_decimal_class`. The Very Hungry Caterpillar
    has `PZ7…` and `[E]` but no LCCN.
- **Signals and precedence:** see `crawler/categories.py`. ESTER first, then LoC, Google, Open Library.
  Outside sources never override an ESTER children's/teen marker. They decide only when ESTER has no topic
  (no UDC, no subjects), or refine topics and the audience band.
- **Ordering:** `crawler/run.build` classifies with ESTER alone, prefetches lookups for candidates (kept books first,
  then undecided adult books), then classifies again with the cached outside signals. Coverage per source is in
  `meta.signal_coverage`.
- **Google:** X1 has no `GOOGLE_BOOKS_API_KEY`, so there are no Google categories for now.

## v2 rollout (BOOKS-9, 14–15 Nov 2026)

- **First full ESTER fetch** runs as the X1 unit `kids-books-v2fetch`. It holds the crawl lock, so the nightly run
  skips while it runs.
  - Measured about 37 records a minute (the MARC page plus a holdings page for about 1% of records), slower than
    the 1 req/s estimate, so about 15 h for 33.9k records.
- **`kids-books-v2populate`** loops: offline build + prefetch of 1,200 Open Library/LoC lookups + `--upload-only`.
  - About 16 lookups a minute. Each pass takes about 1.5 h and uploads, so the site fills as it goes.
  - It stops once the fetch is done and a pass looks up nothing.
- **LoC coverage is low.** About 3% of looked-up books have an LCCN on Open Library (UK editions mostly don't).
- **Fix after the first upload:** "nature" is decided by the primary UDC number only. A broad term of 91, a
  secondary 591.5 or a subject heading was letting in travel guides, cat care, crafts and houseplants.
  Adult picks went from 284 to 139 on the same cache.

## Demo (BOOKS-15, 17 Nov 2026)

- `/demo/` is the app without a login. Caddy skips `import protected` for `/demo` and `/demo/*` and strips
  any client-sent `X-Remote-User`. The server maps `/demo/api/...` onto the normal API, but uses `demo.db`
  (next to `books.db`, or `--demo-db`) for lists and hidden books, and the user is always `demo`.
- The demo is public, so writes are capped (`DEMO_MAX_LISTS`, `DEMO_MAX_ITEMS`, `DEMO_MAX_HIDDEN` in
  `server/app.py`; 409 when full). To reset it, stop the service and delete `data/demo.db`.
- The Caddy block only goes live after `sudo ~/kids-books/deploy/droplet/install.sh` on the droplet. Run it only
  after the deploy: install.sh installs whatever `Caddyfile.books` the droplet checkout has. The first try ran
  it before the merge, so it reinstalled the old block, and `/demo/` (served by old code) 404ed its `app.js`
  and showed a blank page behind the login. `deploy.sh` now warns when the live block differs from the repo.
