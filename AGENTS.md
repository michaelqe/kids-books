# Agents — Kids Books

Read the Magpie project AGENTS.md (Childrens Books, BOOKS) first; this file adds repo specifics.

- No third-party dependencies: Python stdlib server, vanilla JS/HTML/CSS. Ask before adding any.
- Users speak English only; all UI text is English. Translate Estonian catalogue fields where shown.
- **Scraping happens on X1, never on the droplet.** Only `crawler/` fetches from ESTER, Open Library
  or Google Books. The droplet server serves the uploaded `catalog.db` and makes no outbound requests.
- Picture books only: filter out chapter books / novels (see `crawler/ester.py`).
- Lists are shared by everyone who logs in; the user name comes from `X-Remote-User` (Caddy forward-auth).
- Commit and push to `origin master` when a ticket is done; deploy per README.
