# Agents — Kids Books

Read the Magpie project AGENTS.md (Childrens Books, BOOKS) first; this file adds repo specifics.

- No third-party dependencies: Python stdlib server, vanilla JS/HTML/CSS. Ask before adding any.
- Users speak English only; all UI text is English. Translate Estonian catalogue fields where shown.
- **Scraping happens on X1, never on the droplet.** Only `crawler/` fetches from ESTER, Open Library
  or Google Books. The droplet server serves the uploaded `catalog.db` and makes no outbound requests.
- Scope (v2, BOOKS-9): **English books only** with at least one **lendable** Tallinn copy (no
  library-use-only, reading-room or archive copies), that are either **children's books** (baby to
  teen, fiction and non-fiction) or **adult non-fiction about the natural world** (weather, animals,
  plants, space, rocks, field guides). No adult fiction. The rule is `crawler/classify.in_scope`; the
  adult nature classes are `ADULT_NATURE_UDC` / `NATURE_SUBJECTS` in `crawler/terms.py`.
- Every facet (audience, type, topics, nature) records its reason in `books.reasons`; raw signals per
  source are in the `classifications` table. Fix misfilings in the rules, not by hand.
- Lists are shared by everyone who logs in; the user name comes from `X-Remote-User` (Caddy forward-auth).
- Commit and push to `origin master` when a ticket is done; deploy per README.
