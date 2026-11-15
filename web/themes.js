// UI themes: each one is a stylesheet in web/themes/<key>.css loaded on top of style.css.
// Chosen with ?ui=<key> (remembered in localStorage) or the UI button. "classic" is style.css alone.
// A theme may set `brand` (and a `logo` image) to replace the "kids books" title in the header.
// `adv` themes also ask the server for the long filter lists (topics, libraries, years).

export const THEMES = [
  { key: "classic", name: "Classic", blurb: "The original: dark, quiet, covers first.", sw: ["#000000", "#222222", "#1ba1e2"] },
  { key: "catalog", name: "Card catalogue", blurb: "An oak drawer of typed index cards, with call numbers and brass pulls.", sw: ["#6b4423", "#f4ecd3", "#b8332b"] },
  { key: "atlas", name: "Atlas (power filters)", blurb: "A filter sidebar: topics, libraries, year, length, sort, match-all, with removable active filters.", sw: ["#f4f5f7", "#ffffff", "#2563eb"], adv: true },
  { key: "y2013", name: "Circa 2013", blurb: "Blue gradient navbar, glossy buttons, linen, drop shadows, Helvetica.", sw: ["#e9ebee", "#3b5998", "#5cb85c"] },
  { key: "metro", name: "Metro / Lumia", blurb: "Windows Phone: flat live tiles, Segoe Light, a bottom app bar.", sw: ["#000000", "#00aba9", "#e51400"] },
  { key: "shelf", name: "Wooden bookshelf", blurb: "Skeuomorphic: covers stand on lit oak shelves, leather bar, stitched edges.", sw: ["#5a3a22", "#8b5a2b", "#c9a15b"] },
  { key: "coverflow", name: "Cover Flow", blurb: "A 3D carousel of covers on a glossy floor. Swipe or scroll sideways.", sw: ["#0b0b0f", "#2a2a33", "#9aa4b5"] },
  { key: "storybook", name: "Storybook", blurb: "Rounded, bouncy and bright, with sticker badges and wobbly tiles.", sw: ["#fff4d6", "#ff7a59", "#3ec1d3"] },
  { key: "fieldguide", name: "Field guide", blurb: "Cream plates, numbered figures and olive green, like a Peterson guide.", sw: ["#f1ead2", "#4b5b2e", "#8a3b1f"] },
  { key: "brutal", name: "Neo-brutalist", blurb: "Thick black borders, hard shadows, loud flat colour.", sw: ["#fff7e0", "#000000", "#ff5d8f"] },
  { key: "swiss", name: "Swiss", blurb: "International style: a strict grid, big numerals, red and black on white.", sw: ["#ffffff", "#111111", "#e30613"] },
  { key: "rails", name: "Streaming rails", blurb: "Cinematic dark rows of big covers that scroll sideways.", sw: ["#141414", "#2b2b2b", "#e50914"] },
  { key: "pinboard", name: "Cork pinboard", blurb: "Covers pinned to cork, slightly crooked, with paper tags and tape.", sw: ["#c19a6b", "#f7f1e1", "#d33"] },
  { key: "terminal", name: "Green-screen OPAC", blurb: "A 1990s library terminal: phosphor green, monospace, covers as CRT plates.", sw: ["#031403", "#0a3a0a", "#39ff14"] },
  { key: "popart", name: "Pop art", blurb: "Comic halftone dots, thick outlines, speech bubbles.", sw: ["#ffe600", "#e6007e", "#00a3e0"] },
  { key: "nightlight", name: "Night-light", blurb: "Bedtime dark: deep navy, stars, covers glowing like lamps.", sw: ["#0d1330", "#1c2757", "#ffd479"] },
  { key: "dkslate", name: "Slate (rounded)", blurb: "Blue-grey slate, soft blue accent, rounded cards.", sw: ["#1d2330", "#262d3d", "#6ea8fe"], adv: true },
  { key: "dkmoss", name: "Moss (rounded)", blurb: "Deep green-grey with a mint accent and pill controls.", sw: ["#1c2622", "#25322d", "#7be0b0"], adv: true },
  { key: "dkplum", name: "Plum (rounded)", blurb: "Aubergine with violet and pink highlights; big soft radii.", sw: ["#231d2c", "#2d2538", "#d69bff"], adv: true },
  { key: "dkember", name: "Ember (rounded)", blurb: "Warm charcoal-brown with amber accents and a serif heading.", sw: ["#272220", "#322b28", "#ffb454"], adv: true },
  { key: "dkocean", name: "Ocean glass (rounded)", blurb: "Teal-navy with frosted translucent cards and cyan accents.", sw: ["#18272f", "#2a4a56", "#5fd4e8"], adv: true },
  { key: "dkgraphite", name: "Graphite (square)", blurb: "Neutral graphite, orange accent, square cards, mono labels.", sw: ["#222427", "#2b2d31", "#ff9a3c"], adv: true },
  { key: "dkforest", name: "Forest (square)", blurb: "Olive-green dark with cream text, square cards and serif titles.", sw: ["#1f251c", "#283024", "#c9d66a"], adv: true },
  { key: "dkwine", name: "Wine (square)", blurb: "Burgundy-brown with rose-gold hairlines and square tiles.", sw: ["#2a1f24", "#35282e", "#e8b4a0"], adv: true },
  { key: "dkmidnight", name: "Midnight (square)", blurb: "Indigo midnight, yellow accent, hairline grid of square cards.", sw: ["#1b1d33", "#232644", "#ffd75e"], adv: true },
  { key: "dkcopper", name: "Copper (square)", blurb: "Warm grey-brown with copper accents, condensed caps and a left bar on each card.", sw: ["#272523", "#312e2b", "#e2845a"], adv: true },
  { key: "dkwren", name: "Wren Library", brand: "Wren Library", logo: "themes/wren.png", blurb: "Dark green pebbled leather, square cards, stitched edges and a lime-gold accent.", sw: ["#1c2a20", "#263528", "#c9d66a"], adv: true },
  { key: "dknavyleather", name: "Navy leather", blurb: "Square cards on navy leather, brass accent, stitched header.", sw: ["#18223a", "#212d4a", "#e0c079"], adv: true },
  { key: "dkoxblood", name: "Oxblood leather", blurb: "Deep oxblood leather with copper-gold accent and stitching.", sw: ["#2a191c", "#382327", "#dba46b"], adv: true },
  { key: "dkcognac", name: "Cognac leather", blurb: "Warm cognac-brown leather, amber accent, stitched panels.", sw: ["#2d2016", "#3a2b1e", "#e8a655"], adv: true },
  { key: "dkforestgrain", name: "Forest fine grain", blurb: "Forest with a finer, quieter grain, no stitching: the most subtle one.", sw: ["#1f251c", "#283024", "#c9d66a"], adv: true },
];

const KEY = "kb-ui";
const known = (k) => THEMES.some((t) => t.key === k);

export function currentUi() {
  let k = "classic";
  try { k = new URLSearchParams(location.search).get("ui") || localStorage.getItem(KEY) || "classic"; } catch { /* storage blocked */ }
  return known(k) ? k : "classic";
}

export const wantsAdv = () => !!THEMES.find((t) => t.key === currentUi())?.adv;

export function applyUi(key) {
  if (!known(key)) key = "classic";
  const link = document.getElementById("theme");
  link.href = key === "classic" ? "" : `themes/${key}.css`;
  if (key === "classic") link.removeAttribute("href");
  document.documentElement.dataset.ui = key;
  const brand = document.querySelector(".brand");  // a theme may rename the app (its `brand`)
  if (brand) {
    const t = THEMES.find((x) => x.key === key);
    brand.replaceChildren();
    if (t?.logo) {
      const img = Object.assign(document.createElement("img"), { src: t.logo, alt: "", className: "brand-logo" });
      brand.append(img);
    }
    brand.append(Object.assign(document.createElement("span"), { textContent: t?.brand || "kids books" }));
  }
  try { localStorage.setItem(KEY, key); } catch { /* ignore */ }
}

export function mountPicker(onChange) {
  const dlg = document.createElement("dialog");
  dlg.className = "ui-pick";
  const fab = document.createElement("button");
  fab.type = "button"; fab.className = "ui-fab"; fab.textContent = "UI";
  fab.setAttribute("aria-label", "Change the look of the app");

  const paint = () => {
    const cur = currentUi();
    dlg.replaceChildren();
    const h2 = Object.assign(document.createElement("h2"), { textContent: "Choose a look" });
    const lede = Object.assign(document.createElement("p"), { className: "lede", textContent: "Same books, same lists; only the interface changes. Saved on this device." });
    const grid = document.createElement("div");
    grid.className = "ui-grid";
    for (const t of THEMES) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "ui-opt"; b.setAttribute("aria-pressed", String(t.key === cur));
      const sw = document.createElement("div");
      sw.className = "ui-swatch";
      for (const c of t.sw) { const i = document.createElement("i"); i.style.background = c; sw.append(i); }
      const n = document.createElement("b"); n.textContent = t.name;
      const d = document.createElement("span"); d.textContent = t.blurb;
      b.append(sw, n, d);
      b.addEventListener("click", () => { applyUi(t.key); dlg.close(); onChange(t.key); paint(); });
      grid.append(b);
    }
    const close = Object.assign(document.createElement("button"), { type: "button", textContent: "Close" });
    close.style.cssText = "margin:0 16px 16px auto;display:block;padding:8px 16px;border-radius:999px;border:0;background:#2e3038;color:#fff;cursor:pointer";
    close.addEventListener("click", () => dlg.close());
    dlg.append(h2, lede, grid, close);
  };
  fab.addEventListener("click", () => { paint(); dlg.showModal(); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  document.body.append(fab, dlg);
}
