// ─────────────────────────────────────────────────────────────────────────────
// report.js — 產生「雙週電子報」格式的 PDF（瀏覽器列印成 PDF）
//
// 版面完全對齊範例電子報：
//   1) 目錄頁：頁首（客戶 logo｜期別 + 日期｜品牌 logo）→ 主視覺橫幅 + 橘色標題膠囊
//      → 分類標籤 → 每頁 3 張新聞卡（縮圖 + 標題 + 摘要 + 日期/來源/記者）
//      → 右下角換頁按鈕
//   2) 內文頁：滿版橫幅 + 白色圓角卡（標題 / 日期·來源·記者 / 小標 / 內文）
//      內容過長自動續頁，續頁標「(承上頁)」，右下角有上一頁 / 首頁 / 下一頁
//
// 分頁採「實際量測」：在開啟的視窗裡逐段塞進固定高度的內文框，
// 溢出就換頁（段落過長會在句號處切開），因此不會出現半行被切掉的情況。
// ─────────────────────────────────────────────────────────────────────────────

// ── 可調整的電子報設定（也可由 UI 存進 localStorage 覆寫） ──────────────────
const CFG_KEY = "ainews_newsletter_cfg";

export const DEFAULT_CFG = {
  title: "洞悉AI雙週報",       // 橘色膠囊上的刊名
  issue: "",                   // 期別，例：第0014期（留空則不顯示）
  dateLabel: "",               // 頁首日期，留空 = 自動用最新事件日期
  clientLogo: "./assets/logo-client.png",   // 頁首左側 logo（換成自己的即可）
  brandLogo: "./assets/logo-brand.png",     // 頁首右側 logo
  heroBanner: "./assets/hero-banner.jpg",   // 目錄頁主視覺
  detailBanner: "./assets/detail-banner.jpg", // 內文頁主視覺
  perPage: 3,                  // 目錄頁每頁幾則
};

export function getNewsletterConfig() {
  try {
    const raw = localStorage.getItem(CFG_KEY);
    return { ...DEFAULT_CFG, ...(raw ? JSON.parse(raw) : {}) };
  } catch {
    return { ...DEFAULT_CFG };
  }
}

export function saveNewsletterConfig(patch) {
  const next = { ...getNewsletterConfig(), ...(patch || {}) };
  try { localStorage.setItem(CFG_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  return next;
}

// ── 分類 metadata（與 app.js / config.py 對齊；不含未分類） ──────────────────
const CAT_META = {
  tech_research:     { label: "技術突破與研究",     color: "#4f46e5" },
  industry_business: { label: "產業動態與商業",     color: "#059669" },
  hardware_infra:    { label: "硬體與基礎建設",     color: "#d97706" },
  products_apps:     { label: "產品與應用",         color: "#0891b2" },
  policy_society:    { label: "政策法規與社會影響", color: "#db2777" },
};
const CAT_ORDER = ["tech_research", "industry_business", "hardware_infra", "products_apps", "policy_society"];
const CAT_FALLBACK = { label: "其他 AI 新聞", color: "#64748b" };

const CAT_ICON = {
  tech_research: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><path d="M20.2 20.2c2.04-2.03.02-7.36-4.5-11.9-4.54-4.52-9.87-6.54-11.9-4.5-2.04 2.03-.02 7.36 4.5 11.9 4.54 4.52 9.87 6.54 11.9 4.5Z"/><path d="M15.7 15.7c4.52-4.54 6.54-9.87 4.5-11.9-2.03-2.04-7.36-.02-11.9 4.5-4.52 4.54-6.54 9.87-4.5 11.9 2.03 2.04 7.36.02 11.9-4.5Z"/></svg>',
  industry_business: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>',
  hardware_infra: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/></svg>',
  products_apps: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 4v4"/><path d="M2 8h20"/><path d="M6 4v4"/></svg>',
  policy_society: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/></svg>',
  _default: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16h.01"/></svg>',
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

function catOf(cid) { return CAT_META[cid] || CAT_FALLBACK; }

function ymd(s) {
  if (!s) return "";
  const m = String(s).match(/(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : "";
}
function eventDate(ev) {
  return ymd(ev.date) || ymd((ev.sources || [])[0]?.published) || "";
}
function dateRange(events) {
  const ds = events.map(eventDate).filter(Boolean).sort();
  if (!ds.length) return "";
  return ds[0] === ds[ds.length - 1] ? ds[0] : `${ds[0]} ~ ${ds[ds.length - 1]}`;
}

// 相對路徑 → 絕對網址（開新視窗是 about:blank，用絕對路徑最保險）
function abs(p) {
  if (!p) return "";
  try { return new URL(p, location.href).href; } catch { return p; }
}

function coverUrl(ev) {
  const cover = ev.cover_image || {};
  if ((cover.kind === "remote" || cover.kind === "local") && cover.url) {
    let u = cover.url;
    // file:// 直接開檔案測試時，把 media/ 或 /media/ 改指向真正的 output/
    if (location.protocol === "file:" && !/^https?:/.test(u)) {
      u = u.replace(/^\/?media\//, "../output/");
    } else if (cover.kind === "local" && !/^https?:|^\//.test(u)) {
      u = "../output/" + u;
    }
    return abs(u);
  }
  return "";
}

// ── 內文切成排版區塊：短句無句號視為小標，其餘為段落 ───────────────────────
function contentBlocks(ev) {
  const text = String(ev.full_content || ev.summary || "").trim();
  const lines = text.split(/\n+/).map((s) => s.trim()).filter(Boolean);
  const blocks = [];
  for (const line of lines) {
    const isHead = line.length <= 34 && !/[。！？!?]$/.test(line) && !/^https?:/.test(line);
    blocks.push({ t: isHead ? "h" : "p", text: line });
  }
  if (!blocks.length) blocks.push({ t: "p", text: ev.summary || "" });

  // 結尾補一行資料來源（可點）
  const src = (ev.sources || [])[0];
  if (src?.url) {
    blocks.push({ t: "s", text: `資料來源：${src.source_name || ""} ${src.url}`, url: src.url });
  }
  return blocks;
}

function metaParts(ev) {
  const src = (ev.sources || [])[0] || {};
  const d = eventDate(ev);
  return {
    date: d,
    source: src.source_name || "",
    reporter: src.author || src.reporter || "",
  };
}

// ── 建立資料模型（丟給視窗裡的排版引擎） ────────────────────────────────────
function buildModel(events, cfg) {
  const groups = [];
  const byCat = new Map();
  for (const ev of events) {
    const cid = CAT_META[ev.category] ? ev.category : "_other";
    if (!byCat.has(cid)) byCat.set(cid, []);
    byCat.get(cid).push(ev);
  }
  const order = [...CAT_ORDER.filter((c) => byCat.has(c)), ...(byCat.has("_other") ? ["_other"] : [])];

  let seq = 0;
  const items = [];
  for (const cid of order) {
    const arr = byCat.get(cid).slice().sort(
      (a, b) => (b.importance || 0) - (a.importance || 0)
             || (b.mention_count || 0) - (a.mention_count || 0),
    );
    const meta = catOf(cid);
    const gItems = arr.map((ev) => {
      const m = metaParts(ev);
      const it = {
        id: String(++seq),
        title: ev.title || "(無標題)",
        summary: ev.summary || "",
        date: m.date,
        source: m.source,
        reporter: m.reporter,
        cover: coverUrl(ev),
        color: meta.color,
        icon: CAT_ICON[cid] || CAT_ICON._default,
        blocks: contentBlocks(ev),
      };
      items.push(it);
      return it;
    });
    groups.push({ label: meta.label, color: meta.color, items: gItems });
  }

  const newest = events.map(eventDate).filter(Boolean).sort().slice(-1)[0] || "";
  return {
    title: cfg.title || DEFAULT_CFG.title,
    issue: cfg.issue || "",
    dateLabel: cfg.dateLabel || newest,
    perPage: Number(cfg.perPage) || 3,
    assets: {
      clientLogo: abs(cfg.clientLogo),
      brandLogo: abs(cfg.brandLogo),
      hero: abs(cfg.heroBanner),
      detail: abs(cfg.detailBanner),
    },
    groups,
    items,
  };
}

// ── 版面 CSS（A4 固定頁，列印 1:1） ─────────────────────────────────────────
const STYLE = `
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #fff; }
body {
  font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", "Heiti TC",
               -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #333;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.pg {
  position: relative; width: 210mm; height: 297mm; overflow: hidden;
  background: #fff; page-break-after: always; break-after: page;
}
.pg:last-of-type { page-break-after: auto; break-after: auto; }

/* 頁首 */
.nl-head {
  position: absolute; top: 0; left: 0; right: 0; height: 15mm; z-index: 3;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 9mm; background: #fff;
}
.nl-head img { display: block; }
.nl-head img.c { height: 6.2mm; }
.nl-head img.b { height: 7.2mm; }
.nl-issue { font-size: 9pt; font-weight: 600; color: #8e8e8e; letter-spacing: .18em; white-space: nowrap; }

/* 主視覺 + 橘色刊名膠囊 */
.nl-hero { position: absolute; left: 0; right: 0; height: 64mm; overflow: hidden; background: #2fb2e0; }
.pg-index .nl-hero { top: 15mm; }
.pg-detail .nl-hero { top: 0; }
.nl-hero img { width: 100%; height: 100%; object-fit: cover; display: block; }
.nl-pill {
  position: absolute; left: 50%; top: 52%; transform: translate(-50%, -50%);
  background: #ff8902; color: #fff; font-size: 21pt; font-weight: 800;
  letter-spacing: .04em; padding: 4.6mm 13mm; border-radius: 999px; white-space: nowrap;
  box-shadow: 0 0 0 1.3mm rgba(117,223,234,.95), 0 3mm 8mm rgba(180,80,0,.30);
}

/* 目錄頁 */
.idx-body { position: absolute; top: 79mm; left: 0; right: 0; bottom: 24mm; padding: 0 11mm; overflow: hidden; }
.idx-cat { height: 22mm; display: flex; align-items: center; gap: 3mm; }
.idx-cat .spark { color: #f6a723; display: inline-flex; }
.idx-cat .spark svg { width: 4.2mm; height: 4.2mm; display: block; }
.idx-cat .name {
  border: .35mm solid #b9cfe8; color: #1a3c6d; background: #fff;
  font-weight: 700; font-size: 10.5pt; padding: 1.8mm 5.5mm; border-radius: 999px;
}
.idx-card {
  display: grid; grid-template-columns: 30mm 1fr; gap: 6mm; align-items: center;
  background: #fff; border-radius: 4mm; padding: 5mm; margin-bottom: 6mm;
  min-height: 48mm; text-decoration: none; color: inherit;
  box-shadow: 0 1.2mm 3.6mm rgba(23,63,120,.13);
}
.idx-thumb {
  width: 30mm; height: 30mm; border-radius: 3mm; overflow: hidden;
  display: flex; align-items: center; justify-content: center; color: #fff;
}
.idx-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.idx-thumb svg { width: 12mm; height: 12mm; }
.idx-title {
  font-size: 13pt; font-weight: 800; color: #222; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.idx-sum {
  font-size: 10pt; color: #0099cc; line-height: 1.65; margin-top: 2mm;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.idx-meta { font-size: 8.5pt; color: #888; line-height: 1.75; margin-top: 3mm; }

/* 內文頁 */
.nl-card {
  position: absolute; top: 48mm; left: 12mm; right: 12mm; bottom: 10mm;
  background: #fff; border-radius: 5mm; padding: 12mm 12mm 22mm;
  display: flex; flex-direction: column;
  box-shadow: 0 2mm 9mm rgba(150,110,50,.18);
}
.nl-cont { font-size: 9.5pt; color: #9aa4b2; margin-bottom: 4mm; }
.nl-title { font-size: 19pt; font-weight: 800; color: #1a3c6d; line-height: 1.5; margin: 0 0 4mm; }
.nl-meta { font-size: 9pt; color: #888; margin: 0 0 6mm; }
.nl-flow { flex: 1 1 auto; overflow: hidden; }
.nl-h { font-size: 13pt; font-weight: 800; color: #333; line-height: 1.7; margin: 0 0 4mm; }
.nl-p { font-size: 11pt; color: #333; line-height: 1.95; margin: 0 0 4.5mm; text-align: justify; }
.nl-s { font-size: 8.5pt; color: #9aa4b2; margin: 4mm 0 0; word-break: break-all; }
.nl-s a { color: #0099cc; text-decoration: none; }

/* 換頁按鈕：目錄頁貼版心、內文頁貼白卡內側（不可超出卡片） */
.nl-nav { position: absolute; right: 11mm; bottom: 11mm; display: flex; gap: 3mm; z-index: 4; }
.pg-detail .nl-nav { right: 20mm; bottom: 15mm; }
.nl-nav a {
  display: inline-flex; align-items: center; gap: 1.5mm;
  border: .3mm solid #cfe0f2; border-radius: 999px; background: #fff;
  padding: 1.9mm 5.5mm; font-size: 9pt; font-weight: 600; color: #1a3c6d; text-decoration: none;
}
.nl-nav svg { width: 3.4mm; height: 3.4mm; display: block; }

/* 螢幕預覽 */
@media screen {
  body { background: #e8edf4; padding: 26px 0 60px; }
  .pg { margin: 0 auto 22px; box-shadow: 0 8px 28px rgba(15,45,90,.18); }
  .nl-toolbar {
    position: fixed; top: 14px; right: 18px; z-index: 99; display: flex; gap: 8px;
    background: #fff; border-radius: 999px; padding: 8px 10px;
    box-shadow: 0 6px 18px rgba(15,45,90,.18); font-size: 13px;
  }
  .nl-toolbar button {
    border: 0; border-radius: 999px; padding: 7px 16px; cursor: pointer;
    font-weight: 700; font-size: 13px; background: #ff8902; color: #fff;
  }
  .nl-toolbar span { align-self: center; color: #64748b; padding-left: 6px; }
}
@media print { .nl-toolbar { display: none !important; } }
`;

// ── 視窗內的排版引擎（字串注入，於子視窗執行） ──────────────────────────────
const LAYOUT_JS = String.raw`
(function () {
  var data = JSON.parse(document.getElementById("nl-data").textContent);
  var doc = document.getElementById("doc");
  var pageSeq = 0;
  var ICON_SPARK = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
    '<path d="M12 2.2l2.1 6.1 6.1 2.1-6.1 2.1L12 21.8l-2.1-9.3L3.8 10.4l6.1-2.1z"/></svg>';
  var ICON_HOME = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M3 10.5 12 3l9 7.5"/><path d="M5.5 9.6V21h13V9.6"/></svg>';

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  function newPage(cls) {
    var el = document.createElement("section");
    el.className = "pg " + cls;
    el.id = "pg-" + (++pageSeq);
    doc.appendChild(el);
    return el;
  }

  function headHtml() {
    var a = data.assets, bits = [];
    bits.push('<span></span>');
    var mid = [data.issue, data.dateLabel].filter(Boolean).join("　");
    bits.push('<div class="nl-issue">' + esc(mid) + '</div>');
    bits.push(a.brandLogo ? '<img class="b" src="' + esc(a.brandLogo) + '" alt="" />' : '<span></span>');
    return '<header class="nl-head">' + bits.join("") + '</header>';
  }

  function heroHtml(src) {
    return '<div class="nl-hero"><img src="' + esc(src) + '" alt="" />' +
           (data.title ? '<div class="nl-pill">' + esc(data.title) + '</div>' : '') + '</div>';
  }

  function thumbHtml(it) {
    if (it.cover) {
      return '<div class="idx-thumb"><img src="' + esc(it.cover) + '" alt="" ' +
             'onerror="this.parentNode.style.background=\'linear-gradient(135deg,' + it.color + ',' + it.color + 'aa)\';this.remove()" /></div>';
    }
    return '<div class="idx-thumb" style="background:linear-gradient(135deg,' + it.color + ',' + it.color + 'aa)">' + it.icon + '</div>';
  }

  function cardHtml(it) {
    var meta = [];
    if (it.date) meta.push("日期: " + esc(it.date));
    if (it.source) meta.push("來源: " + esc(it.source));
    if (it.reporter) meta.push("記者: " + esc(it.reporter));
    return '<a class="idx-card" href="#ev-' + it.id + '">' +
      thumbHtml(it) +
      '<div class="idx-text">' +
        '<div class="idx-title">' + esc(it.title) + '</div>' +
        '<div class="idx-sum">' + esc(it.summary) + '</div>' +
        '<div class="idx-meta">' + meta.join("<br />") + '</div>' +
      '</div>' +
    '</a>';
  }

  // ── 目錄頁：逐張放卡片，放不下就換頁（保證不會溢出頁面） ──
  var indexPages = [];

  function newIndexPage(g, withChip) {
    var page = newPage("pg-index");
    page.innerHTML =
      headHtml() + heroHtml(data.assets.hero) +
      '<div class="idx-body">' +
        (withChip
          ? '<div class="idx-cat"><span class="spark">' + ICON_SPARK + '</span><span class="name">' + esc(g.label) + '</span></div>'
          : '<div class="idx-cat"></div>') +
      '</div>' +
      '<nav class="nl-nav"></nav>';
    indexPages.push(page);
    return page;
  }

  data.groups.forEach(function (g) {
    var page = null, body = null, count = 0, firstOfGroup = true;
    g.items.forEach(function (it) {
      if (!page || count >= data.perPage) {
        page = newIndexPage(g, firstOfGroup);
        firstOfGroup = false;
        body = page.querySelector(".idx-body");
        count = 0;
      }
      body.insertAdjacentHTML("beforeend", cardHtml(it));
      count += 1;
      if (body.scrollHeight > body.clientHeight + 1 && count > 1) {
        body.removeChild(body.lastElementChild);
        page = newIndexPage(g, false);
        body = page.querySelector(".idx-body");
        body.insertAdjacentHTML("beforeend", cardHtml(it));
        count = 1;
      }
    });
  });

  // ── 內文頁（量測分頁） ──
  var detailPages = [];

  function detailPage(it, first) {
    var page = newPage("pg-detail");
    var meta = [];
    if (it.date) meta.push("日期: " + esc(it.date));
    if (it.source) meta.push("來源: " + esc(it.source));
    if (it.reporter) meta.push("記者: " + esc(it.reporter));
    page.innerHTML =
      '<div class="nl-hero"><img src="' + esc(data.assets.detail) + '" alt="" /></div>' +
      '<article class="nl-card">' +
        (first
          ? '<h1 class="nl-title">' + esc(it.title) + '</h1>' +
            (meta.length ? '<div class="nl-meta">' + meta.join(" &#124; ") + '</div>' : '')
          : '<div class="nl-cont">(承上頁)</div>') +
        '<div class="nl-flow"></div>' +
      '</article>' +
      '<nav class="nl-nav"></nav>';
    if (first) page.setAttribute("data-ev", it.id);
    detailPages.push(page);
    return page;
  }

  function blockEl(b) {
    var el;
    if (b.t === "h") { el = document.createElement("h2"); el.className = "nl-h"; el.textContent = b.text; }
    else if (b.t === "s") {
      el = document.createElement("div"); el.className = "nl-s";
      el.innerHTML = b.url
        ? esc(b.text.replace(b.url, "")) + '<a href="' + esc(b.url) + '">' + esc(b.url) + '</a>'
        : esc(b.text);
    } else { el = document.createElement("p"); el.className = "nl-p"; el.textContent = b.text; }
    return el;
  }

  function overflowing(flow) { return flow.scrollHeight > flow.clientHeight + 1; }

  // 段落單獨一頁還是塞不下 → 用二分法找可容納的字數，優先切在句末
  function fitPortion(el, text, flow) {
    var lo = 1, hi = text.length, best = 0;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      el.textContent = text.slice(0, mid);
      if (!overflowing(flow)) { best = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    if (best <= 0) best = Math.min(60, text.length);
    if (best < text.length) {
      var head = text.slice(0, best);
      var m = head.match(/[\s\S]*[。！？；!?;]/);
      if (m && m[0].length > best * 0.45) best = m[0].length;
    }
    el.textContent = text.slice(0, best);
    return best;
  }

  data.items.forEach(function (it) {
    var page = detailPage(it, true);
    page.id = "ev-" + it.id;
    var flow = page.querySelector(".nl-flow");
    var queue = it.blocks.slice();
    var guard = 0;
    while (queue.length && guard++ < 400) {
      var b = queue.shift();
      var el = blockEl(b);
      flow.appendChild(el);
      if (!overflowing(flow)) continue;

      if (flow.childElementCount === 1) {
        // 這一塊自己就超過一頁 → 切開，剩下的排到下一頁
        if (b.t === "p") {
          var used = fitPortion(el, b.text, flow);
          if (used < b.text.length) queue.unshift({ t: "p", text: b.text.slice(used) });
          page = detailPage(it, false);
          flow = page.querySelector(".nl-flow");
          continue;
        }
        // 小標 / 來源塊不切，直接留在這頁
        continue;
      }
      flow.removeChild(el);
      queue.unshift(b);
      page = detailPage(it, false);
      flow = page.querySelector(".nl-flow");
    }
  });

  // ── 換頁按鈕 ──
  function btn(href, label) { return '<a href="' + href + '">' + label + '</a>'; }

  indexPages.forEach(function (p, i) {
    var nav = p.querySelector(".nl-nav"), h = "";
    if (i > 0) h += btn("#" + indexPages[i - 1].id, "&#8592; 上一頁");
    if (i < indexPages.length - 1) h += btn("#" + indexPages[i + 1].id, "下一頁 &#8594;");
    nav.innerHTML = h;
  });

  var homeId = indexPages.length ? indexPages[0].id : (detailPages[0] || {}).id;
  detailPages.forEach(function (p, i) {
    var nav = p.querySelector(".nl-nav"), h = "";
    if (i > 0) h += btn("#" + detailPages[i - 1].id, "&#8592; 上一頁");
    if (homeId) h += btn("#" + homeId, ICON_HOME + " 首頁");
    if (i < detailPages.length - 1) h += btn("#" + detailPages[i + 1].id, "下一頁 &#8594;");
    nav.innerHTML = h;
  });

  // ── 螢幕工具列 ──
  var bar = document.createElement("div");
  bar.className = "nl-toolbar";
  bar.innerHTML = '<span>' + (indexPages.length + detailPages.length) + ' 頁</span>' +
                  '<button type="button">列印 / 另存 PDF</button>';
  bar.querySelector("button").addEventListener("click", function () { window.print(); });
  document.body.appendChild(bar);

  window.__NL_PAGES = indexPages.length + detailPages.length;
  window.__NL_READY = true;
  document.dispatchEvent(new Event("nl-ready"));
})();
`;

function reportDocument(events, cfg) {
  const model = buildModel(events, cfg);
  const json = JSON.stringify(model).replace(/</g, "\\u003c");
  const range = dateRange(events);
  const docTitle = [cfg.title || DEFAULT_CFG.title, cfg.issue, range].filter(Boolean).join("_");

  return `<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8" />
<title>${esc(docTitle)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&display=swap" rel="stylesheet" />
<style>${STYLE}</style>
</head>
<body>
<div id="doc"></div>
<script id="nl-data" type="application/json">${json}</script>
<script>${LAYOUT_JS}</script>
</body>
</html>`;
}

// ── 備援：彈出視窗被封鎖時，直接在頁面內開一個全螢幕預覽 ──────────────────
function openInOverlay(html) {
  document.getElementById("nl-overlay")?.remove();

  const ov = document.createElement("div");
  ov.id = "nl-overlay";
  ov.style.cssText = "position:fixed;inset:0;z-index:9999;display:flex;flex-direction:column;background:rgba(15,23,42,.9)";

  const bar = document.createElement("div");
  bar.style.cssText = "display:flex;align-items:center;gap:10px;padding:10px 16px;background:#0f172a;color:#fff;" +
                      "font:600 14px/1.4 system-ui,-apple-system,'PingFang TC',sans-serif";
  const btn = "border:0;border-radius:999px;padding:8px 18px;font:700 13px/1 inherit;cursor:pointer;";
  bar.innerHTML =
    '<span style="margin-right:auto;opacity:.85">電子報預覽 ・ 按「列印 / 另存 PDF」在列印對話框選「另存為 PDF」</span>' +
    '<button id="nl-ov-print" style="' + btn + 'background:#ff8902;color:#fff">列印 / 另存 PDF</button>' +
    '<button id="nl-ov-close" style="' + btn + 'background:#334155;color:#fff">關閉</button>';

  const frame = document.createElement("iframe");
  frame.title = "電子報預覽";
  frame.style.cssText = "flex:1 1 auto;width:100%;border:0;background:#e8edf4";

  ov.append(bar, frame);
  document.body.appendChild(ov);

  const fdoc = frame.contentDocument;
  fdoc.open();
  fdoc.write(html);
  fdoc.close();

  bar.querySelector("#nl-ov-print").addEventListener("click", () => {
    frame.contentWindow.focus();
    frame.contentWindow.print();
  });
  bar.querySelector("#nl-ov-close").addEventListener("click", () => ov.remove());
}

/**
 * 產生電子報的完整 HTML 字串（不開視窗，方便測試 / 預覽）。
 * @param {Array<object>} events 事件物件陣列
 * @param {object} [cfgOverride] 覆寫設定
 * @returns {string} HTML
 */
export function buildReportHtml(events, cfgOverride) {
  return reportDocument(events || [], { ...getNewsletterConfig(), ...(cfgOverride || {}) });
}

/**
 * 把選定的事件匯出成電子報 PDF（開新視窗 → 排版 → 列印對話框）。
 * @param {Array<object>} events 事件物件陣列
 * @param {object} [cfgOverride] 覆寫設定
 */
export function exportEventsToPdf(events, cfgOverride) {
  if (!events || !events.length) {
    alert("尚未勾選任何事件。請先在卡片或清單勾選「加入電子報」。");
    return;
  }
  const html = reportDocument(events, { ...getNewsletterConfig(), ...(cfgOverride || {}) });
  const w = window.open("", "_blank");
  if (!w) {
    // 彈出視窗被封鎖 → 改用頁內全螢幕預覽（一樣可以列印 / 另存 PDF）
    openInOverlay(html);
    return;
  }
  w.document.open();
  w.document.write(html);
  w.document.close();

  // 等排版引擎跑完 + 圖片載入，再叫出列印（避免缺圖或分頁未完成）
  const waitLayout = () => new Promise((res) => {
    if (w.__NL_READY) return res();
    w.document.addEventListener("nl-ready", () => res(), { once: true });
    setTimeout(res, 6000);
  });
  const waitImages = () => {
    const imgs = Array.from(w.document.images || []);
    const pending = imgs.filter((im) => !im.complete);
    if (!pending.length) return Promise.resolve();
    return Promise.all(pending.map((im) => new Promise((res) => {
      im.addEventListener("load", res, { once: true });
      im.addEventListener("error", res, { once: true });
    })));
  };
  const run = async () => {
    await waitLayout();
    await Promise.race([waitImages(), new Promise((r) => setTimeout(r, 8000))]);
    setTimeout(() => { w.focus(); w.print(); }, 300);
  };
  if (w.document.readyState === "complete") run();
  else w.addEventListener("load", run);
}
