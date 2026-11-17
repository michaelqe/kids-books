// Kids Books: search English children's books (and adult nature books) you can borrow in
// Tallinn's libraries, save them to shared lists.
// Plain ES module, no build step. Routes live in the hash: #/?q=..., #/book/b123, #/lists, #/lists/4.

import { appName, applyUi, currentUi, mountPicker, wantsAdv } from "./themes.js";

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
  freshNav = true;
  scrollAt.set(pageKey, window.scrollY);
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
  const who = Array.isArray(book.authors) && book.authors.length ? book.authors[0].split(",").reverse().join(" ").trim() : "";
  const ph = h("div", { class: "cover placeholder", style: `background:${tint(book.title || "")}` },
    h("span", { class: "ph-title" }, book.title || ""),
    who ? h("span", { class: "ph-author" }, who) : null);
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

const AUD_CODE = { baby_toddler: "B", picture_book: "E", early_reader: "ER", middle_grade: "J", teen: "YA", adult: "590" };
/** A shelf-mark look-alike for themes that show one (not the real ESTER call number): J CAR 1969. */
function callNo(book) {
  const first = (book.authors || [])[0] || book.title || "";
  const last = first.trim().split(/\s+/).pop().replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase();
  return [AUD_CODE[book.audience] || "", last, book.year].filter(Boolean).join(" ");
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

const LANGS = [["eng", "English"], ["est", "Estonian"], ["any", "Any language"]];  // v1 catalogues only
const FIELDS = [["any", "Anything"], ["title", "Title"], ["author", "Author"], ["subject", "Subject"]];
const PICTURE = ["baby_toddler", "picture_book"];
// Shortcuts: a set of filters. The first one is the default view.
const SHORTCUTS = [
  { key: "picture", label: "Picture books", set: { audience: PICTURE, type: [], nature: false } },
  { key: "nature", label: "Nature & weather", set: { audience: [], type: ["nonfiction"], nature: true } },
  { key: "all", label: "All books", set: { audience: [], type: [], nature: false } },
];

function listParam(params, name, fallback) {
  if (!params.has(name)) return fallback;
  return (params.get(name) || "").split(",").filter(Boolean);
}

function searchParams(params) {
  const fresh = ![...params.keys()].length;  // the landing page: picture books
  return {
    q: params.get("q") || "",
    field: params.get("field") || "any",
    lang: params.get("lang") || "eng",
    available: params.get("available") === "1",
    subject: params.get("subject") || "",
    audience: listParam(params, "audience", fresh ? PICTURE : []),
    type: listParam(params, "type", []),
    nature: params.get("nature") === "1",
    sort: params.get("sort") || "",
    yfrom: params.get("year_from") || "",
    yto: params.get("year_to") || "",
    pmin: params.get("pages_min") || "",
    pmax: params.get("pages_max") || "",
    topics: listParam(params, "topics", []),
    topicsAll: params.get("topics_all") === "1",
    branch: listParam(params, "branch", []),
    page: Math.max(1, parseInt(params.get("page") || "1", 10) || 1),
  };
}

function searchHash(p) {
  const q = new URLSearchParams();
  if (p.q) q.set("q", p.q);
  if (p.field !== "any") q.set("field", p.field);
  if (p.lang && p.lang !== "eng") q.set("lang", p.lang);
  if (p.available) q.set("available", "1");
  if (p.subject) q.set("subject", p.subject);
  // audience is always written, even empty, so "All books" isn't read back as the default
  q.set("audience", (p.audience || []).join(","));
  if ((p.type || []).length) q.set("type", p.type.join(","));
  if (p.nature) q.set("nature", "1");
  if (p.sort) q.set("sort", p.sort);
  if (p.yfrom) q.set("year_from", p.yfrom);
  if (p.yto) q.set("year_to", p.yto);
  if (p.pmin) q.set("pages_min", p.pmin);
  if (p.pmax) q.set("pages_max", p.pmax);
  if ((p.topics || []).length) q.set("topics", p.topics.join(","));
  if (p.topicsAll) q.set("topics_all", "1");
  if ((p.branch || []).length) q.set("branch", p.branch.join(","));
  if (p.page > 1) q.set("page", String(p.page));
  return "#/?" + q.toString().replace(/%2C/g, ",");
}

const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

function activeShortcut(p) {
  const s = SHORTCUTS.find((sc) => sameSet(p.audience, sc.set.audience) && sameSet(p.type, sc.set.type) && p.nature === sc.set.nature);
  return s ? s.key : "";
}

let searchSeq = 0;

async function renderSearch(params) {
  setNav("search");
  const p = searchParams(params);
  const input = h("input", {
    type: "search", value: p.q, placeholder: matchMedia("(max-width: 860px)").matches ? "Search books" : "Search books: title, author, subject",
    "aria-label": "Search", autocomplete: "off", enterkeyhint: "search",
  });
  const field = h("select", { "aria-label": "Search in" },
    FIELDS.map(([v, label]) => h("option", { value: v, selected: v === p.field }, label)));
  const results = h("div", {});
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Topics" });
  const shortcuts = h("div", { class: "seg", role: "group", "aria-label": "Shortcuts" });
  const facetBox = h("div", { class: "facets" });
  const advBox = h("div", { class: "adv" });
  const topicFilter = h("input", { type: "search", placeholder: "Find a topic", "aria-label": "Find a topic", autocomplete: "off" });
  let lastFacets = null;
  // Phones: the filters live in a bottom sheet (see style.css); on desktop .filter-body is transparent.
  const form = h("form", { class: "search", role: "search", onsubmit: (e) => e.preventDefault() });
  const setSheet = (open) => { form.classList.toggle("open", open); document.documentElement.classList.toggle("sheet-lock", open); };
  const filterBadge = h("span", { class: "badge-count" });
  const filtersBtn = h("button", { class: "filters-btn", type: "button", onclick: () => setSheet(true) }, "Filters", filterBadge);
  const activeStrip = h("div", { class: "active-strip" });
  const doneBtn = h("button", { class: "btn primary", type: "button", onclick: () => setSheet(false) }, "Show books");
  const sheetHead = h("div", { class: "sheet-head" }, h("strong", {}, "Filters"), h("button", { class: "linkbtn", type: "button", onclick: () => setSheet(false) }, "Close"));
  const sheetFoot = h("div", { class: "sheet-foot" }, doneBtn);

  const update = (patch) => {
    const next = { ...p, ...patch };
    if (!("page" in patch)) next.page = 1;
    history.replaceState(null, "", searchHash(next));
    pageKey = location.hash;
    Object.assign(p, next);
    paintControls();
    runSearch(p, results, paintFacets);
  };

  let typing = null;
  input.addEventListener("input", () => {
    clearTimeout(typing);
    typing = setTimeout(() => update({ q: input.value.trim() }), 250);
  });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(typing); update({ q: input.value.trim() }); input.blur(); } });
  field.addEventListener("change", () => update({ field: field.value }));

  const langSeg = h("div", { class: "seg", role: "group", "aria-label": "Language", hidden: true });
  const availBtn = h("button", { class: "toggle", type: "button", onclick: () => update({ available: !p.available }) },
    h("span", { class: "dot" }), "On the shelf now");

  const toggleIn = (list, value) => (list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);

  const ANY_ADV = { sort: "", yfrom: "", yto: "", pmin: "", pmax: "", topics: [], topicsAll: false, branch: [], subject: "", available: false };
  const LENGTHS = [["Any", "", ""], ["Under 32 pages", "", "31"], ["32 to 64", "32", "64"], ["65 to 200", "65", "200"], ["Over 200", "201", ""]];
  const SORTS = [["", "Best match"], ["newest", "Newest first"], ["oldest", "Oldest first"], ["title", "Title A to Z"], ["shortest", "Shortest first"], ["longest", "Longest first"], ["shelf", "Most on the shelf"]];

  function activeChips(facets) {
    const active = [];
    const chip = (label, patch) => active.push(h("button", { class: "chip", type: "button", "aria-pressed": "true", onclick: () => update(patch) }, label));
    if (p.subject) chip(p.subject, { subject: "" });
    for (const t of p.topics) chip(t, { topics: p.topics.filter((x) => x !== t) });
    for (const b of p.branch) chip(b, { branch: p.branch.filter((x) => x !== b) });
    if (p.yfrom || p.yto) chip(`${p.yfrom || "…"} to ${p.yto || "…"}`, { yfrom: "", yto: "" });
    if (p.pmin || p.pmax) chip((LENGTHS.find(([, a, b]) => a === p.pmin && b === p.pmax) || ["Pages " + (p.pmin || "0") + " to " + (p.pmax || "…")])[0], { pmin: "", pmax: "" });
    if (p.available) chip("On the shelf now", { available: false });
    if (p.audience.length) for (const a of p.audience) chip((facets.audience.find((o) => o.value === a) || { label: a }).label, { audience: p.audience.filter((x) => x !== a) });
    if (p.type.length) for (const t of p.type) chip((facets.type.find((o) => o.value === t) || { label: t }).label, { type: p.type.filter((x) => x !== t) });
    if (p.nature) chip("Nature", { nature: false });
    return active;
  }

  function paintAdv(facets) {
    if (!wantsAdv() || !facets || !facets.topics) { advBox.replaceChildren(); activeStrip.replaceChildren(); filterBadge.textContent = ""; return; }
    lastFacets = facets;
    const years = facets.years || {};
    const numInput = (name, value, placeholder) => h("input", {
      type: "number", inputmode: "numeric", value, placeholder: String(placeholder || ""), "aria-label": name,
      onchange: (e) => update({ [name === "From year" ? "yfrom" : "yto"]: e.target.value.trim() }),
    });
    const pick = (field, o) => h("label", {},
      h("input", { type: "checkbox", checked: p[field].includes(o.value), onchange: () => update({ [field]: toggleIn(p[field], o.value) }) }),
      o.label, h("span", { class: "count" }, o.count.toLocaleString("en-GB")));
    const topicList = h("div", { class: "picks", role: "group", "aria-label": "Topics" });
    const paintTopics = () => {
      const needle = topicFilter.value.trim().toLowerCase();
      topicList.replaceChildren(...facets.topics.filter((o) => !needle || o.label.toLowerCase().includes(needle)).map((o) => pick("topics", o)));
    };
    topicFilter.oninput = paintTopics;
    paintTopics();

    const active = activeChips(facets);

    advBox.replaceChildren(
      h("div", { class: "adv-sec" },
        h("div", { class: "label" }, "Filters in use", active.length ? h("button", { class: "linkbtn", type: "button", onclick: () => update({ ...ANY_ADV, audience: [], type: [], nature: false }) }, "Clear all") : null),
        h("div", { class: "active" }, active),
        active.length ? null : h("div", { class: "muted small" }, "None yet: showing everything.")),
      h("div", { class: "adv-sec" }, h("div", { class: "label" }, "Sort"),
        h("select", { "aria-label": "Sort", onchange: (e) => update({ sort: e.target.value }) },
          SORTS.map(([v, l]) => h("option", { value: v, selected: v === p.sort }, l)))),
      h("div", { class: "adv-sec" }, h("div", { class: "label" }, "Year published"),
        h("div", { class: "range" }, numInput("From year", p.yfrom, years.min), h("span", { class: "muted" }, "to"), numInput("To year", p.yto, years.max))),
      h("div", { class: "adv-sec" }, h("div", { class: "label" }, "Length"),
        h("div", { class: "chips facet", role: "group", style: "flex-wrap:wrap" }, LENGTHS.map(([l, a, b]) =>
          h("button", { class: "chip", type: "button", "aria-pressed": String(p.pmin === a && p.pmax === b), onclick: () => update({ pmin: a, pmax: b }) }, l)))),
      h("div", { class: "adv-sec" },
        h("div", { class: "label" }, "Topics",
          h("label", { class: "small", style: "text-transform:none;letter-spacing:0;display:flex;gap:6px;align-items:center" },
            h("input", { type: "checkbox", checked: p.topicsAll, onchange: (e) => update({ topicsAll: e.target.checked }) }), "match all")),
        topicFilter, topicList),
      h("div", { class: "adv-sec" }, h("div", { class: "label" }, "Libraries with a copy"),
        h("div", { class: "picks", role: "group", "aria-label": "Libraries" }, facets.branches.map((o) => pick("branch", o)))),
    );
    activeStrip.replaceChildren(...activeChips(facets));
    filterBadge.textContent = active.length ? String(active.length) : "";
  }

  function paintFacets(facets, total) {
    paintAdv(facets);
    if (total !== undefined) doneBtn.textContent = `Show ${total.toLocaleString("en-GB")} ${total === 1 ? "book" : "books"}`;
    if (!facets || !facets.audience) {  // a v1 catalogue: no facets, the language filter instead
      facetBox.replaceChildren();
      langSeg.hidden = false;
      shortcuts.hidden = true;
      return;
    }
    langSeg.hidden = true;
    shortcuts.hidden = false;
    const group = (name, label, options, selected) =>
      h("div", { class: "chips facet", role: "group", "aria-label": label },
        options.filter((o) => o.count || selected.includes(o.value)).map((o) =>
          h("button", {
            class: "chip", type: "button", "aria-pressed": String(selected.includes(o.value)),
            onclick: () => update({ [name]: toggleIn(p[name], o.value) }),
          }, o.label, h("span", { class: "count" }, o.count.toLocaleString("en-GB")))));
    facetBox.replaceChildren(
      group("audience", "Who it's for", facets.audience, p.audience),
      group("type", "Kind of book", facets.type, p.type));
  }

  function paintControls() {
    langSeg.replaceChildren(...LANGS.map(([v, label]) =>
      h("button", { type: "button", "aria-pressed": String(p.lang === v), onclick: () => update({ lang: v }) }, label)));
    const active = activeShortcut(p);
    shortcuts.replaceChildren(...SHORTCUTS.map((sc) =>
      h("button", { type: "button", "aria-pressed": String(active === sc.key), onclick: () => update({ ...sc.set }) }, sc.label)));
    availBtn.setAttribute("aria-pressed", String(p.available));
    for (const c of chips.children) c.setAttribute("aria-pressed", String(c.dataset.subject === p.subject));
  }

  form.append(
    h("div", { class: "search-row" }, input, field),
    filtersBtn,
    activeStrip,
    h("div", { class: "filter-body" },
      sheetHead,
      h("div", { class: "filters" }, shortcuts, langSeg, availBtn),
      facetBox,
      chips,
      advBox,
      sheetFoot));
  view.replaceChildren(form, results);
  setSheet(false);
  paintControls();
  if (!p.q && matchMedia("(pointer: fine)").matches) input.focus({ preventScroll: true });  // not on phones: it would pop the keyboard

  loadSubjects().then((subjects) => {
    chips.replaceChildren(...subjects.slice(0, 24).map((s) =>
      h("button", {
        class: "chip", type: "button", dataset: { subject: s.subject },
        "aria-pressed": String(s.subject === p.subject),
        onclick: () => update({ subject: p.subject === s.subject ? "" : s.subject }),
      }, s.subject)));
  }).catch(() => {});

  runSearch(p, results, paintFacets);
}

async function loadSubjects() {
  if (!state.subjects) state.subjects = await api("/subjects");
  return state.subjects;
}

async function runSearch(p, results, paintFacets) {
  const seq = ++searchSeq;
  const q = new URLSearchParams({ q: p.q, field: p.field, lang: p.lang, page: String(p.page) });
  if (p.available) q.set("available", "1");
  if (p.subject) q.set("subject", p.subject);
  if (p.audience.length) q.set("audience", p.audience.join(","));
  if (p.type.length) q.set("type", p.type.join(","));
  if (p.nature) q.set("nature", "1");
  if (p.sort) q.set("sort", p.sort);
  if (p.yfrom) q.set("year_from", p.yfrom);
  if (p.yto) q.set("year_to", p.yto);
  if (p.pmin) q.set("pages_min", p.pmin);
  if (p.pmax) q.set("pages_max", p.pmax);
  if (p.topics.length) q.set("topics", p.topics.join(","));
  if (p.topicsAll) q.set("topics_all", "1");
  if (p.branch.length) q.set("branch", p.branch.join(","));
  if (wantsAdv()) q.set("adv", "1");
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
  if (paintFacets) paintFacets(data.facets, data.total);
  const v2 = !!(data.facets && data.facets.audience);
  const what = [p.q && `"${p.q}"`, p.subject, p.nature && "nature"].filter(Boolean).join(" · ");
  const lang = LANGS.find(([v]) => v === p.lang)[1].replace(" language", "");
  const filtered = p.audience.length || p.type.length || p.nature || p.subject || p.available
    || p.topics.length || p.branch.length || p.yfrom || p.yto || p.pmin || p.pmax;
  results.replaceChildren(
    h("div", { class: "summary-line" },
      h("div", { class: "label" },
        `${data.total.toLocaleString("en-GB")} ${data.total === 1 ? "book" : "books"}`,
        what ? ` for ${what}` : "", !v2 && p.lang !== "any" ? ` · ${lang}` : "", p.available ? " · on the shelf" : ""),
    ),
    data.results.length
      ? h("div", { class: "grid" }, data.results.map(card))
      : h("div", { class: "empty" },
          "No books found.",
          v2 && filtered
            ? h("div", {}, h("button", { class: "linkbtn", type: "button", onclick: () => go(searchHash({ ...p, audience: [], type: [], nature: false, subject: "", available: false, topics: [], branch: [], yfrom: "", yto: "", pmin: "", pmax: "", sort: "", page: 1 })) }, "Clear the filters"))
            : !v2 && p.lang !== "any"
              ? h("div", {}, h("button", { class: "linkbtn", type: "button", onclick: () => go(searchHash({ ...p, lang: "any", page: 1 })) }, "Try any language"))
              : null),
    pager(p, data) || [],
  );
  if (restoreY) { const y = restoreY; restoreY = 0; requestAnimationFrame(() => window.scrollTo(0, y)); }
}

async function hideBook(book, el) {
  try {
    await api("/hidden", { method: "POST", body: { book_id: book.id } });
  } catch (e) { toast(e.message); return false; }
  if (el) el.remove();
  toast(`Hidden "${book.title}"`, {
    label: "Undo",
    run: async () => {
      try { await api(`/hidden/${book.id}`, { method: "DELETE" }); route(); } catch (e) { toast(e.message); }
    },
  });
  return true;
}

function card(book) {
  const el = h("a", { class: "card", href: `#/book/${book.id}`, dataset: { aud: book.audience || "", type: book.type || "" } },
    h("div", { class: "cover-wrap", style: "position:relative" },
      cover(book),
      h("button", {
        class: "hide-btn", type: "button", title: "Never show this book again", "aria-label": `Never show "${book.title}" again`,
        onclick: (e) => { e.preventDefault(); e.stopPropagation(); hideBook(book, el); },
      }, "\u00d7"),
      h("button", {
        class: "add-btn", type: "button", title: "Add to a list", "aria-label": `Add "${book.title}" to a list`,
        onclick: (e) => { e.preventDefault(); e.stopPropagation(); quickAdd(book, el); },
      }, "+"),
      book.language && book.language !== "eng" ? h("span", { class: "lang-tag" }, book.language) : null,
      state.savedIds.has(book.id) ? h("span", { class: "save-mark", title: "On a list" }) : null),
    h("div", { class: "card-title" }, book.title),
    h("div", { class: "card-meta" }, [authorsLine(book), book.year].filter(Boolean).join(" · ")),
    book.audience_label ? h("div", { class: "card-meta" }, [book.audience_label, book.type_label].filter(Boolean).join(" · ")) : null,
    h("div", { class: "card-pages" }, book.pages ? `${book.pages} pages` : ""),
    availability(book),
    h("div", { class: "spine", style: `--spine:${tint(book.title || "")}` }, h("span", {}, book.title)));
  el.prepend(h("div", { class: "cn" }, callNo(book)));
  return el;
}

async function quickAdd(book, el) {
  let full;
  try { full = await api(`/books/${encodeURIComponent(book.id)}`); } catch (e) { toast(e.message); return; }
  dialog.addEventListener("close", () => {
    const wrap = el.querySelector(".cover-wrap");
    const mark = wrap.querySelector(".save-mark");
    if (state.savedIds.has(book.id) && !mark) wrap.append(h("span", { class: "save-mark", title: "On a list" }));
  }, { once: true });
  openListDialog(full, null);
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
  document.title = `${book.title} · ${appName()}`;
  const links = book.links || {};
  const facts = [
    ["For", book.audience_label || ""],
    ["Kind", book.type_label || ""],
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
  const hideLabel = (b) => (b.hidden ? "Show in search again" : "Never show again");
  const hideBtn = h("button", { class: "btn", type: "button", onclick: async () => {
    try {
      if (book.hidden) {
        await api(`/hidden/${book.id}`, { method: "DELETE" });
        book.hidden = false; toast("This book will show up in search again");
      } else {
        await api("/hidden", { method: "POST", body: { book_id: book.id } });
        book.hidden = true; toast("Hidden from search. You can undo this on the Hidden page.");
      }
      hideBtn.textContent = hideLabel(book);
    } catch (e) { toast(e.message); }
  } }, hideLabel(book));
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
          hideBtn,
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
        (book.topics || []).length || (book.subjects_en || []).length || (book.genres_en || []).length
          ? h("div", { class: "tags" },
              [...new Set([...(book.topics || []), ...(book.subjects_en || []), ...(book.genres_en || []).filter((g) => g !== "picture books" && g !== "children's books")])]
                .map((s) => h("a", { class: "chip", href: searchHash({ q: "", field: "any", lang: "any", available: false, subject: s, audience: [], type: [], nature: false, topics: [], branch: [], page: 1 }) }, s)))
          : null,
        (book.reasons || []).length
          ? h("details", { class: "why" },
              h("summary", { class: "muted small" }, "Why this category"),
              h("ul", { class: "muted small" }, book.reasons.map((r) => h("li", {}, r))))
          : null,
        h("div", { class: "section libraries" },
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
document.addEventListener("keydown", (e) => {
  // Enter finishes the dialog (the new-list box keeps its own Enter = create). Listening on the
  // document because repainting the list drops focus to <body>, outside the dialog element.
  if (e.key === "Enter" && dialog.open && e.target !== newListName && e.target.tagName !== "BUTTON") { e.preventDefault(); dialog.close(); }
});
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
    const first = dialogLists.querySelector("input");
    if (first) first.focus();
  } catch (e) {
    dialogLists.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

function paintDialog() {
  const hadFocus = dialogLists.contains(document.activeElement);
  const idx = hadFocus ? [...dialogLists.querySelectorAll("input")].indexOf(document.activeElement) : -1;
  paintDialogInner();
  if (idx >= 0) dialogLists.querySelectorAll("input")[idx]?.focus();
}

function paintDialogInner() {
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
  document.title = `Lists · ${appName()}`;
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
  document.title = `${list.name} · ${appName()}`;

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
    it.in_catalogue === false ? h("div", { class: "card-meta gone" }, "No longer in the catalogue") : null,
    h("div", { class: "card-meta" }, `Added by ${it.added_by}`),
    h("div", { class: "item-actions" },
      h("a", { href: it.ester_url, target: "_blank", rel: "noopener", class: "linkbtn" }, "ESTER"),
      it.goodreads_url ? h("a", { href: it.goodreads_url, target: "_blank", rel: "noopener noreferrer", class: "linkbtn" }, "Goodreads") : null,
      h("button", { class: "linkbtn", type: "button", onclick: editNote }, "Note"),
      h("button", { class: "linkbtn", type: "button", onclick: removeItem }, "Remove")));
}

// --- hidden view ------------------------------------------------------------------------------

async function renderHidden() {
  setNav("hidden");
  document.title = `Hidden · ${appName()}`;
  view.replaceChildren(h("h1", { class: "page" }, "hidden"), h("p", { class: "muted" }, "Loading..."));
  let items = await api("/hidden");
  const paint = () => view.replaceChildren(
    h("h1", { class: "page" }, "hidden"),
    h("p", { class: "muted" }, "Books nobody wants to see in search again. Everyone who signs in shares this."),
    items.length
      ? h("div", { class: "grid" }, items.map((it) => {
          const restore = async () => {
            try { items = await api(`/hidden/${it.book_id}`, { method: "DELETE" }); paint(); toast(`"${it.title}" will show up in search again`); }
            catch (e) { toast(e.message); }
          };
          return h("div", { class: "card" },
            h("a", { href: `#/book/${it.book_id}`, style: "text-decoration:none" }, cover({ cover_url: it.cover_url, title: it.title })),
            h("a", { class: "card-title", href: `#/book/${it.book_id}`, style: "text-decoration:none" }, it.title),
            h("div", { class: "card-meta" }, it.author),
            h("div", { class: "card-meta" }, `Hidden by ${it.hidden_by}`),
            h("div", { class: "item-actions" }, h("button", { class: "linkbtn", type: "button", onclick: restore }, "Show again")));
        }))
      : h("div", { class: "empty" }, "Nothing hidden."),
  );
  paint();
}

// --- router -------------------------------------------------------------------------------------

// Scroll position per page (keyed by hash), so Back from a book lands where you were in the results.
// Only Back/Forward restores it; following a link or the nav starts at the top.
history.scrollRestoration = "manual";
const scrollAt = new Map();
let pageKey = location.hash || "#/";  // the page on screen; scroll events can arrive after the hash has already changed
let freshNav = false;  // set when the user clicked an in-app link
let restoreY = 0;      // consumed by runSearch once the results are on screen
window.addEventListener("scroll", () => { scrollAt.set(pageKey, window.scrollY); }, { passive: true });

// Phones: the header slides away while scrolling down and returns on any scroll up (CSS: html.top-tucked).
const phone = matchMedia("(max-width: 860px)");
const topBar = document.querySelector(".top");
let lastY = window.scrollY;
function tuckHeader(on) {
  if (on) document.documentElement.style.setProperty("--top-h", topBar.offsetHeight + "px");
  document.documentElement.classList.toggle("top-tucked", on);
}
window.addEventListener("scroll", () => {
  const y = window.scrollY, dy = y - lastY;
  if (!phone.matches || y <= topBar.offsetHeight) { tuckHeader(false); lastY = y; return; }
  if (Math.abs(dy) < 8) return;  // ignore jitter (and iOS bounce) until the move is clear
  tuckHeader(dy > 0);
  lastY = y;
}, { passive: true });
phone.addEventListener("change", () => tuckHeader(false));
document.addEventListener("click", (e) => {
  if (e.target.closest && e.target.closest('a[href^="#"]')) { freshNav = true; scrollAt.set(pageKey, window.scrollY); }
}, true);

async function route() {
  hideToast();
  if (dialog.open) dialog.close();
  const { parts, params } = parseHash();
  const wantY = freshNav ? 0 : scrollAt.get(location.hash || "#/") || 0;
  freshNav = false;
  pageKey = location.hash || "#/";
  restoreY = 0;
  window.scrollTo(0, 0);
  document.title = appName();
  try {
    if (parts[0] === "book" && parts[1]) return await renderBook(parts[1]);
    if (parts[0] === "hidden") return await renderHidden();
    if (parts[0] === "lists" && parts[1]) return await renderList(parts[1]);
    if (parts[0] === "lists") return await renderLists();
    restoreY = wantY;
    return await renderSearch(params);
  } catch (e) {
    view.replaceChildren(h("p", { class: "error" }, "Something went wrong: " + e.message));
  }
}

async function renderFoot() {
  try {
    state.health = await api("/health");
    const c = state.health.catalog;
    const n = (x) => (x || 0).toLocaleString("en-GB");
    foot.replaceChildren(
      !c ? "The catalogue hasn't been loaded yet."
        : (c.schema_version || 1) >= 2
          ? `${n(c.books)} English books you can borrow in Tallinn libraries, ${n(c.nature_books)} of them about nature. Catalogue updated ${fmtDate(c.crawled_at)} from ESTER.`
          : `${n(c.books)} picture books in Tallinn libraries, ${n(c.english_books)} in English. Catalogue updated ${fmtDate(c.crawled_at)} from ESTER.`,
      c && (c.schema_version || 1) >= 2
        ? " Covers and summaries from Open Library; categories from ESTER, the Library of Congress and Open Library."
        : " Covers and summaries from Open Library.");
  } catch { /* the footer is optional */ }
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.documentElement.classList.remove("sheet-lock"); document.querySelector("form.search.open")?.classList.remove("open"); });
applyUi(currentUi());
mountPicker(() => route());  // atlas wants extra facets, so repaint the current view
window.addEventListener("hashchange", route);
route();
renderFoot();
refreshSaved().catch(() => {});
