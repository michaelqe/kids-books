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
