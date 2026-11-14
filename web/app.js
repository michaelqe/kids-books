// Kids Books: search Tallinn's picture books, save them to shared lists.
// Plain ES module, no build step. Routes live in the hash: #/?q=..., #/book/b123, #/lists, #/lists/4.

const view = document.getElementById("view");
const foot = document.getElementById("foot");
const toastEl = document.getElementById("toast");

// --- helpers -----------------------------------------------------------------------------

/** h("div", {class: "x", onclick: fn}, child, "text") -> Element. Strings are text, never HTML. */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch("/api" + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  let data = null;
  try { data = await res.json(); } catch { /* login redirect or empty */ }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  return { parts: path.split("/").filter(Boolean), params: new URLSearchParams(query) };
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

let toastTimer = null;
function toast(message, action) {
  toastEl.replaceChildren(h("span", {}, message));
  if (action) {
    toastEl.append(h("button", { class: "linkbtn", type: "button", onclick: () => { hideToast(); action.run(); } }, action.label));
  }
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, action ? 7000 : 3500);
}
function hideToast() { toastEl.hidden = true; }

const PALETTE = ["#2b4c7e", "#6b3d7a", "#2f6d5a", "#8a4b2a", "#7a2f45", "#3d5f2a", "#5a4a8a", "#2a6a7a"];
function tint(text) {
  let n = 0;
  for (const ch of text) n = (n * 31 + ch.codePointAt(0)) >>> 0;
  return PALETTE[n % PALETTE.length];
}

function cover(book, { size = "card" } = {}) {
  const ph = h("div", { class: "cover placeholder", style: `background:${tint(book.title || "")}` }, book.title || "");
  if (!book.cover_url) return ph;
  const box = h("div", { class: "cover" });
  const img = h("img", {
    src: book.cover_url, alt: "", loading: size === "card" ? "lazy" : "eager",
    referrerpolicy: "no-referrer", decoding: "async",
  });
  img.addEventListener("error", () => box.replaceWith(ph));
  // Open Library sometimes answers with a 1x1 image instead of a 404.
  img.addEventListener("load", () => { if (img.naturalWidth < 10) box.replaceWith(ph); });
  box.append(img);
  return box;
}

function availability(book) {
  if (!book.tallinn_copies) return h("span", { class: "badge" }, "Not in Tallinn");
  if (book.available_copies > 0) {
    return h("span", { class: "badge in" }, book.available_copies === 1 ? "1 on the shelf" : `${book.available_copies} on the shelf`);
  }
  return h("span", { class: "badge out" }, "All on loan");
}

function authorsLine(book) {
  return (book.authors || []).slice(0, 2).join(", ");
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function setNav(name) {
  for (const a of document.querySelectorAll("[data-nav]")) a.classList.toggle("active", a.dataset.nav === name);
}

// --- state shared across views ------------------------------------------------------------

const state = {
  health: null,
  subjects: null,
  lists: null,          // [{id, name, count, ...}]
  savedIds: new Set(),  // book ids on any list (for the dot on cards)
};

async function loadLists(force = false) {
  if (state.lists && !force) return state.lists;
  state.lists = await api("/lists");
  return state.lists;
}

async function refreshSaved() {
  // A cheap way to mark saved books on result cards: fetch each list once.
  const lists = await loadLists(true);
  const ids = new Set();
  await Promise.all(lists.map(async (l) => {
    const full = await api(`/lists/${l.id}`);
    for (const it of full.items) ids.add(it.book_id);
  }));
  state.savedIds = ids;
}

// --- search view ----------------------------------------------------------------------------

const LANGS = [["eng", "English"], ["est", "Estonian"], ["any", "Any language"]];
const FIELDS = [["any", "Anything"], ["title", "Title"], ["author", "Author"], ["subject", "Subject"]];

function searchParams(params) {
  return {
    q: params.get("q") || "",
    field: params.get("field") || "any",
    lang: params.get("lang") || "eng",
    available: params.get("available") === "1",
    subject: params.get("subject") || "",
    page: Math.max(1, parseInt(params.get("page") || "1", 10) || 1),
  };
}

function searchHash(p) {
  const q = new URLSearchParams();
  if (p.q) q.set("q", p.q);
  if (p.field !== "any") q.set("field", p.field);
  if (p.lang !== "eng") q.set("lang", p.lang);
  if (p.available) q.set("available", "1");
  if (p.subject) q.set("subject", p.subject);
  if (p.page > 1) q.set("page", String(p.page));
  const s = q.toString();
  return "#/" + (s ? "?" + s : "");
}

let searchSeq = 0;

async function renderSearch(params) {
  setNav("search");
  const p = searchParams(params);
  const input = h("input", {
    type: "search", value: p.q, placeholder: "Search picture books: title, author, subject",
    "aria-label": "Search", autocomplete: "off", enterkeyhint: "search",
  });
  const field = h("select", { "aria-label": "Search in" },
    FIELDS.map(([v, label]) => h("option", { value: v, selected: v === p.field }, label)));
  const results = h("div", {});
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Subjects" });

  const update = (patch) => {
    const next = { ...p, ...patch };
    if (!("page" in patch)) next.page = 1;
    history.replaceState(null, "", searchHash(next));
    Object.assign(p, next);
    paintControls();
    runSearch(p, results);
  };

  let typing = null;
  input.addEventListener("input", () => {
    clearTimeout(typing);
    typing = setTimeout(() => update({ q: input.value.trim() }), 250);
  });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(typing); update({ q: input.value.trim() }); input.blur(); } });
  field.addEventListener("change", () => update({ field: field.value }));

  const langSeg = h("div", { class: "seg", role: "group", "aria-label": "Language" });
  const availBtn = h("button", { class: "toggle", type: "button", onclick: () => update({ available: !p.available }) },
    h("span", { class: "dot" }), "On the shelf now");

  function paintControls() {
    langSeg.replaceChildren(...LANGS.map(([v, label]) =>
      h("button", { type: "button", "aria-pressed": String(p.lang === v), onclick: () => update({ lang: v }) }, label)));
    availBtn.setAttribute("aria-pressed", String(p.available));
    for (const c of chips.children) c.setAttribute("aria-pressed", String(c.dataset.subject === p.subject));
  }

  view.replaceChildren(
    h("form", { class: "search", role: "search", onsubmit: (e) => e.preventDefault() },
      h("div", { class: "search-row" }, input, field),
      h("div", { class: "filters" }, langSeg, availBtn),
      chips),
    results,
  );
  paintControls();
  if (!p.q) input.focus({ preventScroll: true });

  loadSubjects().then((subjects) => {
    chips.replaceChildren(...subjects.slice(0, 24).map((s) =>
      h("button", {
        class: "chip", type: "button", dataset: { subject: s.subject },
        "aria-pressed": String(s.subject === p.subject),
        onclick: () => update({ subject: p.subject === s.subject ? "" : s.subject }),
      }, s.subject)));
  }).catch(() => {});

  runSearch(p, results);
}

async function loadSubjects() {
  if (!state.subjects) state.subjects = await api("/subjects");
  return state.subjects;
}

async function runSearch(p, results) {
  const seq = ++searchSeq;
  const q = new URLSearchParams({ q: p.q, field: p.field, lang: p.lang, page: String(p.page) });
  if (p.available) q.set("available", "1");
  if (p.subject) q.set("subject", p.subject);
  results.replaceChildren(h("div", { class: "grid" }, Array.from({ length: 8 }, () => h("div", { class: "skeleton" }))));
  let data;
  try {
    data = await api("/search?" + q.toString());
  } catch (e) {
    if (seq === searchSeq) results.replaceChildren(h("p", { class: "error" }, "Search failed: " + e.message));
    return;
  }
  if (seq !== searchSeq) return;  // a newer search is on its way

  if (data.catalog === null) {
    results.replaceChildren(h("div", { class: "empty" }, "The catalogue hasn't been loaded yet. It's updated every night from ESTER."));
    return;
  }
  const what = [p.q && `"${p.q}"`, p.subject].filter(Boolean).join(" · ");
  const lang = LANGS.find(([v]) => v === p.lang)[1].replace(" language", "");
  results.replaceChildren(
    h("div", { class: "summary-line" },
      h("div", { class: "label" },
        `${data.total.toLocaleString("en-GB")} ${data.total === 1 ? "book" : "books"}`,
        what ? ` for ${what}` : "", p.lang !== "any" ? ` · ${lang}` : "", p.available ? " · on the shelf" : ""),
    ),
    data.results.length
      ? h("div", { class: "grid" }, data.results.map(card))
      : h("div", { class: "empty" },
          "No picture books found.",
          p.lang !== "any" ? h("div", {}, h("button", { class: "linkbtn", type: "button", onclick: () => go(searchHash({ ...p, lang: "any", page: 1 })) }, "Try any language")) : null),
    pager(p, data),
  );
}

function card(book) {
  return h("a", { class: "card", href: `#/book/${book.id}` },
    h("div", { style: "position:relative" },
      cover(book),
      book.language && book.language !== "eng" ? h("span", { class: "lang-tag" }, book.language) : null,
      state.savedIds.has(book.id) ? h("span", { class: "save-mark", title: "On a list" }) : null),
    h("div", { class: "card-title" }, book.title),
    h("div", { class: "card-meta" }, [authorsLine(book), book.year].filter(Boolean).join(" · ")),
    availability(book));
}

function pager(p, data) {
  const pages = Math.ceil(data.total / data.per_page);
  if (pages <= 1) return null;
  return h("div", { class: "pager" },
    p.page > 1 ? h("a", { class: "btn", href: searchHash({ ...p, page: p.page - 1 }) }, "Previous") : null,
    h("span", { class: "muted", style: "align-self:center" }, `Page ${p.page} of ${pages}`),
    p.page < pages ? h("a", { class: "btn", href: searchHash({ ...p, page: p.page + 1 }) }, "Next") : null);
}

// --- book view ------------------------------------------------------------------------------

async function renderBook(id) {
  setNav("search");
  view.replaceChildren(h("p", { class: "muted" }, "Loading..."));
  let book;
  try {
    book = await api(`/books/${encodeURIComponent(id)}`);
  } catch (e) {
    view.replaceChildren(h("p", { class: "error" }, e.message === "book not found" ? "This book isn't in the catalogue any more." : e.message));
    return;
  }
  document.title = `${book.title} · Kids Books`;
  const links = book.links || {};
  const facts = [
    ["Illustrated by", (book.illustrators || []).join(", ")],
    ["Language", book.language_name + (book.original_language && book.original_language !== book.language ? `, translated from ${book.original_language_name}` : "")],
    ["Original title", book.original_title || ""],
    ["Published", book.year || ""],
    ["Pages", book.pages || ""],
    ["Series", book.series || ""],
    ["ISBN", (book.isbns || []).join(", ")],
  ].filter(([, v]) => v);

  const saveBtn = h("button", { class: "btn primary", type: "button", onclick: () => openListDialog(book, saveBtn) },
    saveLabel(book));
  const back = history.length > 1
    ? h("button", { class: "linkbtn", type: "button", onclick: () => history.back() }, "Back")
    : h("a", { class: "linkbtn", href: "#/" }, "Search");

  view.replaceChildren(
    h("div", { style: "margin-bottom:12px" }, back),
    h("div", { class: "detail" },
      cover(book, { size: "detail" }),
      h("div", {},
        h("h1", {}, book.title),
        book.subtitle ? h("div", { class: "muted" }, book.subtitle) : null,
        h("div", { class: "by" }, (book.authors || []).join(", ") || book.responsibility),
        availability(book),
        h("div", { class: "actions" },
          saveBtn,
          h("a", { class: "btn", href: book.url, target: "_blank", rel: "noopener" }, "Open in ESTER"),
          links.goodreads ? h("a", { class: "btn", href: links.goodreads, target: "_blank", rel: "noopener noreferrer" }, "Goodreads") : null,
          links.openlibrary ? h("a", { class: "btn", href: links.openlibrary, target: "_blank", rel: "noopener noreferrer" }, "Open Library") : null),
        book.summary
          ? h("div", { class: "section" }, h("div", { class: "label" }, "About this book"),
              h("p", { class: "prose" }, book.summary),
              h("div", { class: "muted small" }, book.summary_source === "google_books" ? "Summary from Google Books" : "Summary from Open Library"))
          : null,
        book.notes && !book.summary
          ? h("div", { class: "section" }, h("div", { class: "label" }, "Library note (Estonian)"), h("p", { class: "prose muted" }, book.notes))
          : null,
        h("dl", { class: "facts" }, facts.map(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))])),
        (book.subjects_en || []).length || (book.genres_en || []).length
          ? h("div", { class: "tags" },
              [...new Set([...(book.subjects_en || []), ...(book.genres_en || []).filter((g) => g !== "picture books" && g !== "children's books")])]
                .map((s) => h("a", { class: "chip", href: searchHash({ q: "", field: "any", lang: "any", available: false, subject: s, page: 1 }) }, s)))
          : null,
        h("div", { class: "section" },
          h("div", { class: "label" }, "Tallinn libraries"),
          book.holdings.length
            ? h("div", { class: "branches" }, book.holdings.map(branchCard))
            : h("p", { class: "muted" }, "No copies in Tallinn."),
          h("p", { class: "muted small" },
            `Status as of ${fmtDate(book.holdings_checked_at)}. `,
            h("a", { href: book.url, target: "_blank", rel: "noopener" }, "Check ESTER"), " for the live status or to reserve a copy.")),
      )),
  );
}

function branchCard(b) {
  const statuses = {};
  for (const c of b.copies) statuses[c.status] = (statuses[c.status] || 0) + 1;
  const callNumbers = [...new Set(b.copies.map((c) => c.call_number).filter(Boolean))];
  return h("div", { class: "branch" },
    h("div", { class: "name" }, b.branch),
    h("span", { class: b.available ? "badge in" : "badge out" }, b.available ? `${b.available} on the shelf` : "On loan"),
    h("div", { class: "copies" },
      Object.entries(statuses).map(([s, n]) => (n > 1 ? `${n} × ${s}` : s)).join(" · "),
      callNumbers.length ? ` · shelf mark ${callNumbers.join(", ")}` : ""));
}

function saveLabel(book) {
  const n = (book.lists || []).length;
  return n ? (n === 1 ? "Saved to 1 list" : `Saved to ${n} lists`) : "Save to a list";
}

// --- list dialog ------------------------------------------------------------------------------

const dialog = document.getElementById("listDialog");
const dialogLists = document.getElementById("listDialogLists");
const newListName = document.getElementById("newListName");
document.getElementById("newListBtn").addEventListener("click", createFromDialog);
newListName.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); createFromDialog(); } });
let dialogBook = null;
let dialogButton = null;

async function openListDialog(book, button) {
  dialogBook = book;
  dialogButton = button;
  document.getElementById("listDialogTitle").textContent = book.title;
  newListName.value = "";
  dialogLists.replaceChildren(h("p", { class: "muted" }, "Loading lists..."));
  dialog.showModal();
  try {
    await loadLists(true);
    paintDialog();
  } catch (e) {
    dialogLists.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

function paintDialog() {
  const on = new Set(dialogBook.lists || []);
  if (!state.lists.length) {
    dialogLists.replaceChildren(h("p", { class: "muted" }, "No lists yet. Create one below."));
    return;
  }
  dialogLists.replaceChildren(...state.lists.map((l) => {
    const box = h("input", { type: "checkbox", checked: on.has(l.id) });
    box.addEventListener("change", () => toggleMembership(l, box));
    return h("label", {}, box, h("span", {}, l.name), h("span", { class: "muted small", style: "margin-left:auto" }, String(l.count)));
  }));
}

async function toggleMembership(list, box) {
  box.disabled = true;
  try {
    if (box.checked) {
      await api(`/lists/${list.id}/items`, { method: "POST", body: { book_id: dialogBook.id } });
      dialogBook.lists = [...new Set([...(dialogBook.lists || []), list.id])];
      state.savedIds.add(dialogBook.id);
    } else {
      await api(`/lists/${list.id}/items/${dialogBook.id}`, { method: "DELETE" });
      dialogBook.lists = (dialogBook.lists || []).filter((x) => x !== list.id);
    }
    await loadLists(true);
    paintDialog();
    if (dialogButton) dialogButton.textContent = saveLabel(dialogBook);
  } catch (e) {
    box.checked = !box.checked;
    toast("Couldn't update the list: " + e.message);
  } finally {
    box.disabled = false;
  }
}

async function createFromDialog() {
  const name = newListName.value.trim();
  if (!name) { newListName.focus(); return; }
  try {
    const list = await api("/lists", { method: "POST", body: { name } });
    await api(`/lists/${list.id}/items`, { method: "POST", body: { book_id: dialogBook.id } });
    dialogBook.lists = [...new Set([...(dialogBook.lists || []), list.id])];
    state.savedIds.add(dialogBook.id);
    newListName.value = "";
    await loadLists(true);
    paintDialog();
    if (dialogButton) dialogButton.textContent = saveLabel(dialogBook);
  } catch (e) {
    toast("Couldn't create the list: " + e.message);
  }
}

// --- lists views ------------------------------------------------------------------------------

async function renderLists() {
  setNav("lists");
  document.title = "Lists · Kids Books";
  view.replaceChildren(h("h1", { class: "page" }, "lists"), h("p", { class: "muted" }, "Loading..."));
  let lists;
  try { lists = await loadLists(true); } catch (e) { view.replaceChildren(h("p", { class: "error" }, e.message)); return; }
  const name = h("input", { type: "text", placeholder: "New list, e.g. Bedtime favourites", maxlength: "120", "aria-label": "New list name" });
  const create = async () => {
    const value = name.value.trim();
    if (!value) { name.focus(); return; }
    try {
      const list = await api("/lists", { method: "POST", body: { name: value } });
      go(`#/lists/${list.id}`);
    } catch (e) { toast(e.message); }
  };
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") create(); });
  view.replaceChildren(
    h("h1", { class: "page" }, "lists"),
    h("p", { class: "muted" }, "Everyone who signs in shares these lists."),
    h("div", { class: "new-list" }, name, h("button", { class: "btn primary", type: "button", onclick: create }, "Create list")),
    lists.length
      ? h("div", { class: "lists" }, lists.map((l) =>
          h("a", { class: "list-card", href: `#/lists/${l.id}` },
            h("div", { class: "list-covers" },
              Array.from({ length: 4 }, (_, i) => l.covers[i]
                ? cover({ cover_url: l.covers[i], title: l.name })
                : h("div", { class: "cover", style: "opacity:.4" }))),
            h("div", { class: "list-name" }, l.name),
            h("div", { class: "muted small" }, `${l.count} ${l.count === 1 ? "book" : "books"} · started by ${l.created_by}`))))
      : h("div", { class: "empty" }, "No lists yet."),
  );
}

async function renderList(id) {
  setNav("lists");
  view.replaceChildren(h("p", { class: "muted" }, "Loading..."));
  let list;
  try { list = await api(`/lists/${encodeURIComponent(id)}`); } catch (e) {
    view.replaceChildren(h("p", { class: "error" }, e.message === "list not found" ? "This list was deleted." : e.message), h("a", { href: "#/lists" }, "All lists"));
    return;
  }
  document.title = `${list.name} · Kids Books`;

  const title = h("h1", { class: "page", style: "text-transform:none;margin:0" }, list.name);
  const rename = async () => {
    const value = prompt("Rename list", list.name);
    if (!value || !value.trim() || value.trim() === list.name) return;
    try { list = await api(`/lists/${list.id}`, { method: "PATCH", body: { name: value.trim() } }); title.textContent = list.name; }
    catch (e) { toast(e.message); }
  };
  const remove = async () => {
    if (!confirm(`Delete the list "${list.name}" for everyone? The books stay in the catalogue.`)) return;
    try { await api(`/lists/${list.id}`, { method: "DELETE" }); toast("List deleted"); go("#/lists"); }
    catch (e) { toast(e.message); }
  };

  const grid = h("div", { class: "grid" });
  const paint = () => {
    grid.replaceChildren(...list.items.map((it) => listItem(list, it, paint)));
    count.textContent = `${list.items.length} ${list.items.length === 1 ? "book" : "books"}`;
  };
  const count = h("span", { class: "label" });

  view.replaceChildren(
    h("div", { style: "margin-bottom:12px" }, h("a", { class: "linkbtn", href: "#/lists" }, "All lists")),
    h("div", { class: "list-head" },
      title,
      h("div", { style: "display:flex;gap:8px" },
        h("button", { class: "btn", type: "button", onclick: rename }, "Rename"),
        h("button", { class: "btn danger", type: "button", onclick: remove }, "Delete"))),
    h("div", { class: "summary-line" }, count, h("span", { class: "muted small" }, `Started by ${list.created_by}`)),
    list.items.length ? grid : h("div", { class: "empty" }, "No books yet. ", h("a", { href: "#/" }, "Search"), " and save some."),
  );
  paint();
}

function listItem(list, it, repaint) {
  const book = { id: it.book_id, title: it.title, cover_url: it.cover_url };
  const editNote = async (e) => {
    e.preventDefault();
    const value = prompt("Note (e.g. borrowed 14 Nov, loved it)", it.note);
    if (value === null) return;
    try {
      const updated = await api(`/lists/${list.id}/items/${it.book_id}`, { method: "PATCH", body: { note: value.trim() } });
      list.items = updated.items; repaint();
    } catch (err) { toast(err.message); }
  };
  const removeItem = async (e) => {
    e.preventDefault();
    try {
      const updated = await api(`/lists/${list.id}/items/${it.book_id}`, { method: "DELETE" });
      list.items = updated.items; repaint();
      toast(`Removed "${it.title}"`, {
        label: "Undo",
        run: async () => {
          const back = await api(`/lists/${list.id}/items`, { method: "POST", body: { book_id: it.book_id, note: it.note, title: it.title, author: it.author, cover_url: it.cover_url } });
          list.items = back.items; repaint();
        },
      });
    } catch (err) { toast(err.message); }
  };
  return h("div", { class: "card" },
    h("a", { href: `#/book/${it.book_id}`, style: "text-decoration:none" }, cover(book)),
    h("a", { class: "card-title", href: `#/book/${it.book_id}`, style: "text-decoration:none" }, it.title),
    h("div", { class: "card-meta" }, [it.author, it.year].filter(Boolean).join(" · ")),
    it.note ? h("div", { class: "item-note" }, it.note) : null,
    h("div", { class: "card-meta" }, `Added by ${it.added_by}`),
    h("div", { class: "item-actions" },
      h("a", { href: it.ester_url, target: "_blank", rel: "noopener", class: "linkbtn" }, "ESTER"),
      it.goodreads_url ? h("a", { href: it.goodreads_url, target: "_blank", rel: "noopener noreferrer", class: "linkbtn" }, "Goodreads") : null,
      h("button", { class: "linkbtn", type: "button", onclick: editNote }, "Note"),
      h("button", { class: "linkbtn", type: "button", onclick: removeItem }, "Remove")));
}

// --- router -------------------------------------------------------------------------------------

async function route() {
  hideToast();
  if (dialog.open) dialog.close();
  const { parts, params } = parseHash();
  window.scrollTo(0, 0);
  document.title = "Kids Books";
  try {
    if (parts[0] === "book" && parts[1]) return await renderBook(parts[1]);
    if (parts[0] === "lists" && parts[1]) return await renderList(parts[1]);
    if (parts[0] === "lists") return await renderLists();
    return await renderSearch(params);
  } catch (e) {
    view.replaceChildren(h("p", { class: "error" }, "Something went wrong: " + e.message));
  }
}

async function renderFoot() {
  try {
    state.health = await api("/health");
    const c = state.health.catalog;
    foot.replaceChildren(
      c ? `${(c.books || 0).toLocaleString("en-GB")} picture books in Tallinn libraries, ${(c.english_books || 0).toLocaleString("en-GB")} in English. Catalogue updated ${fmtDate(c.crawled_at)} from ESTER.`
        : "The catalogue hasn't been loaded yet.",
      " Covers and summaries from Open Library.");
  } catch { /* the footer is optional */ }
}

window.addEventListener("hashchange", route);
route();
renderFoot();
refreshSaved().catch(() => {});
