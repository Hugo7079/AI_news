// ─────────────────────────────────────────────────────────────────────────────
// report.js — 產生「晨誌」電子報 PDF（瀏覽器列印成 PDF）
//
// 視覺與網站同一套：印刷藍 #283B69、低彩度欄目墨色、Noto Serif TC 報頭、
// 分隔靠細線與留白，不用陰影與圓角。
//
//   1) 目錄頁：第一頁是完整報頭（刊名 + 期別 + 日期），後續頁改小報眉；
//      欄目名當分節標題，每則是一條有細線分隔的索引列
//      （編號 + 縮圖 + 欄目 + 標題 + 摘要 + 日期/來源/記者）
//   2) 內文頁：小報眉 + 該則自己的封面圖 + 欄目 + 大標 + meta + 內文；
//      內容過長自動續頁，續頁標「(承上頁)」，右下角有上一頁 / 首頁 / 下一頁
//
// 分頁採「實際量測」：在開啟的視窗裡逐段塞進固定高度的內文框，
// 溢出就換頁（段落過長會在句號處切開），因此不會出現半行被切掉的情況。
// ─────────────────────────────────────────────────────────────────────────────

// ── 可調整的電子報設定（也可由 UI 存進 localStorage 覆寫） ──────────────────
const CFG_KEY = "ainews_newsletter_cfg";

export const DEFAULT_CFG = {
  title: "晨誌",               // 報頭刊名
  latin: "MORNING LEDGER",     // 報頭下方的拉丁副名
  issue: "",                   // 期別，例：第0134期（留空則不顯示）
  dateLabel: "",               // 報頭日期，留空 = 自動用最新事件日期
  perPage: 6,                  // 目錄頁每頁幾則（索引列比舊卡片矮，A4 放得下 6 則）
                               // 排版引擎會實際量測，塞不下會自動往下一頁擠，不會溢出
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
// 色值與 web/style.css 的 :root 淺色版一致（PDF 是獨立文件，不能用 CSS 變數）
const CAT_META = {
  tech_research:     { label: "技術突破與研究",     color: "#1F3D7A" },
  industry_business: { label: "產業動態與商業",     color: "#1E5F4B" },
  hardware_infra:    { label: "硬體與基礎建設",     color: "#8A5A1B" },
  products_apps:     { label: "產品與應用",         color: "#2A6E86" },
  policy_society:    { label: "政策法規與社會影響", color: "#7A2340" },
};
const CAT_ORDER = ["tech_research", "industry_business", "hardware_infra", "products_apps", "policy_society"];
const CAT_FALLBACK = { label: "其他 AI 新聞", color: "#5E626C" };

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
        catLabel: meta.label,
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
    latin: cfg.latin === undefined ? DEFAULT_CFG.latin : cfg.latin,
    issue: cfg.issue || "",
    dateLabel: cfg.dateLabel || newest,
    perPage: Number(cfg.perPage) || DEFAULT_CFG.perPage,
    groups,
    items,
  };
}

// ── 版面 CSS（A4 固定頁，列印 1:1）─────────────────────────────────────────
//
// 色值對齊 web/style.css 的淺色版；差別只在紙底改成純白 —— 螢幕上的 #EDEEF0
// 印出來會整頁鋪滿灰墨，紙本用白底、灰只留給細線與底紋。
const STYLE = `
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #fff; }
body {
  font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", "Heiti TC",
               -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #16181D;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.pg {
  position: relative; width: 210mm; height: 297mm; overflow: hidden;
  background: #fff; page-break-after: always; break-after: page;
}
.pg:last-of-type { page-break-after: auto; break-after: auto; }

/* ── 報頭（只有第一頁）── */
.nl-masthead {
  position: absolute; top: 14mm; left: 14mm; right: 14mm; height: 30mm;
  display: flex; align-items: flex-end; justify-content: space-between; gap: 10mm;
  border-bottom: 1.1mm solid #16181D; padding-bottom: 3mm;
}
.nl-name {
  font-family: "Noto Serif TC", serif; font-weight: 900;
  font-size: 34pt; letter-spacing: .1em; line-height: 1; margin: 0;
}
.nl-latin {
  font-family: "Newsreader", Georgia, serif; font-size: 8pt;
  letter-spacing: .26em; color: #5E626C; margin: 2.6mm 0 0;
}
.nl-edition {
  text-align: right; font-family: "Newsreader", Georgia, serif;
  font-variant-numeric: tabular-nums; line-height: 1.6; white-space: nowrap;
}
.nl-edition .no { font-size: 10pt; font-weight: 600; letter-spacing: .12em; }
.nl-edition .dt { font-size: 8.5pt; color: #5E626C; letter-spacing: .08em; margin-top: .8mm; }

/* ── 報眉（後續每一頁）── */
.nl-runhead {
  position: absolute; top: 14mm; left: 14mm; right: 14mm; height: 8mm;
  display: flex; align-items: center; justify-content: space-between; gap: 6mm;
  border-bottom: .3mm solid #C9CCD3; padding-bottom: 2mm;
  font-family: "Newsreader", Georgia, serif; font-size: 8pt;
  letter-spacing: .2em; text-transform: uppercase; color: #5E626C;
}
.nl-runhead .rh-name {
  font-family: "Noto Serif TC", serif; font-weight: 900;
  font-size: 10pt; letter-spacing: .12em; text-transform: none; color: #16181D;
}
.nl-runhead .rh-edition { font-variant-numeric: tabular-nums; text-align: right; min-width: 40mm; }

/* ── 目錄頁 ── */
.idx-body { position: absolute; left: 14mm; right: 14mm; bottom: 18mm; overflow: hidden; }
.pg-index .idx-body { top: 28mm; }
.pg-index.first .idx-body { top: 50mm; }

.idx-cat {
  display: flex; align-items: baseline; gap: 4mm;
  padding-bottom: 2mm; margin-bottom: 1mm;
  border-bottom: .8mm solid #16181D;
}
.idx-cat .name {
  font-family: "Noto Serif TC", serif; font-weight: 900;
  font-size: 12pt; letter-spacing: .08em;
}
.idx-cat .en {
  font-family: "Newsreader", Georgia, serif; font-size: 7.5pt;
  letter-spacing: .2em; text-transform: uppercase; color: #5E626C; margin-left: auto;
}
.idx-cat:empty { border-bottom: 0; padding: 0; margin: 0; height: 0; }

.idx-card {
  display: grid; grid-template-columns: 9mm 32mm 1fr; gap: 5mm; align-items: start;
  padding: 4.5mm 0; border-top: .25mm solid #DEE0E5;
  text-decoration: none; color: inherit;
}
.idx-card:first-of-type { border-top: 0; }
.idx-no {
  font-family: "Newsreader", Georgia, serif; font-size: 13pt;
  font-variant-numeric: tabular-nums; line-height: 1.2; color: #283B69;
}
.idx-thumb {
  width: 32mm; height: 24mm; overflow: hidden; border: .25mm solid #C9CCD3;
  display: flex; align-items: center; justify-content: center; color: rgba(255,255,255,.8);
}
.idx-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.idx-thumb svg { width: 9mm; height: 9mm; }
.idx-dept {
  font-family: "Newsreader", Georgia, serif; font-size: 7.5pt;
  letter-spacing: .2em; text-transform: uppercase; font-weight: 600; margin-bottom: 1.2mm;
}
.idx-title {
  font-family: "Noto Serif TC", serif; font-size: 12.5pt; font-weight: 600;
  color: #16181D; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.idx-sum {
  font-size: 9pt; color: #2C3038; line-height: 1.75; margin-top: 1.6mm;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.idx-meta {
  font-family: "Newsreader", Georgia, serif; font-size: 8pt; color: #5E626C;
  line-height: 1.6; margin-top: 2mm; font-variant-numeric: tabular-nums;
}

/* ── 內文頁 ── */
.nl-card {
  position: absolute; top: 28mm; left: 14mm; right: 14mm; bottom: 18mm;
  display: flex; flex-direction: column;
}
.nl-cover {
  width: 100%; height: 52mm; overflow: hidden; border: .25mm solid #C9CCD3;
  margin-bottom: 4mm; flex: none;
  display: flex; align-items: center; justify-content: center; color: rgba(255,255,255,.8);
}
.nl-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.nl-cover svg { width: 16mm; height: 16mm; }
.nl-dept {
  font-family: "Newsreader", Georgia, serif; font-size: 8pt; font-weight: 600;
  letter-spacing: .22em; text-transform: uppercase; margin-bottom: 1.5mm; flex: none;
}
.nl-title {
  font-family: "Noto Serif TC", serif; font-size: 21pt; font-weight: 900;
  color: #16181D; line-height: 1.36; letter-spacing: -.01em; margin: 0 0 3mm; flex: none;
}
.nl-meta {
  font-family: "Newsreader", Georgia, serif; font-size: 8.5pt; color: #5E626C;
  margin: 0 0 4mm; padding-bottom: 3mm; border-bottom: .8mm solid #16181D;
  font-variant-numeric: tabular-nums; flex: none;
}
/* 續頁那行含文章標題（可能中英混排）→ 不做 uppercase，字距也放小 */
.nl-cont {
  font-family: "Noto Sans TC", sans-serif; font-size: 8.5pt; color: #5E626C;
  letter-spacing: .04em;
  margin-bottom: 4mm; padding-bottom: 2.5mm; border-bottom: .3mm solid #C9CCD3; flex: none;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.nl-flow { flex: 1 1 auto; overflow: hidden; }
.nl-h {
  font-family: "Noto Serif TC", serif; font-size: 12pt; font-weight: 900;
  color: #16181D; line-height: 1.65; margin: 0 0 3mm;
}
.nl-p { font-size: 10.5pt; color: #2C3038; line-height: 2.0; margin: 0 0 4mm; text-align: justify; }
.nl-s {
  font-family: "Newsreader", Georgia, serif; font-size: 8pt; color: #5E626C;
  margin: 4mm 0 0; padding-top: 2.5mm; border-top: .25mm solid #DEE0E5; word-break: break-all;
}
.nl-s a { color: #283B69; text-decoration: none; }

/* ── 換頁按鈕 ── */
.nl-nav { position: absolute; right: 14mm; bottom: 9mm; display: flex; gap: 2mm; z-index: 4; }
.nl-nav a {
  display: inline-flex; align-items: center; gap: 1.4mm;
  border: .25mm solid #C9CCD3; background: #fff;
  padding: 1.6mm 4.5mm; font-family: "Newsreader", Georgia, serif;
  font-size: 8.5pt; letter-spacing: .05em; color: #283B69; text-decoration: none;
}
.nl-nav svg { width: 3.2mm; height: 3.2mm; display: block; }

/* ── 螢幕預覽 ── */
@media screen {
  body { background: #EDEEF0; padding: 26px 0 60px; }
  .pg { margin: 0 auto 22px; box-shadow: 0 8px 28px rgba(22,24,29,.18); }
  .nl-toolbar {
    position: fixed; top: 14px; right: 18px; z-index: 99; display: flex; gap: 8px;
    background: #fff; border: 1px solid #C9CCD3; padding: 8px 10px;
    box-shadow: 0 6px 18px rgba(22,24,29,.16); font-size: 13px;
  }
  .nl-toolbar button {
    border: 0; padding: 7px 16px; cursor: pointer;
    font-weight: 600; font-size: 13px; background: #283B69; color: #fff;
  }
  .nl-toolbar span { align-self: center; color: #5E626C; padding-left: 6px; }
}
@media print { .nl-toolbar { display: none !important; } }
`;

// ── 視窗內的排版引擎（字串注入，於子視窗執行） ──────────────────────────────
const LAYOUT_JS = String.raw`
(function () {
  var data = JSON.parse(document.getElementById("nl-data").textContent);
  var doc = document.getElementById("doc");
  var pageSeq = 0;
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

  // 第一頁：完整報頭
  function mastheadHtml() {
    return '<header class="nl-masthead">' +
        '<div>' +
          '<h1 class="nl-name">' + esc(data.title) + '</h1>' +
          (data.latin ? '<p class="nl-latin">' + esc(data.latin) + '</p>' : '') +
        '</div>' +
        '<div class="nl-edition">' +
          (data.issue ? '<div class="no">' + esc(data.issue) + '</div>' : '') +
          (data.dateLabel ? '<div class="dt">' + esc(data.dateLabel) + '</div>' : '') +
        '</div>' +
      '</header>';
  }

  // 後續每一頁：小報眉（刊名 · 欄目／目錄 · 期別日期）
  function runheadHtml(mid) {
    var edition = [data.issue, data.dateLabel].filter(Boolean).join(" \u00B7 ");
    return '<header class="nl-runhead">' +
        '<span class="rh-name">' + esc(data.title) + '</span>' +
        '<span>' + esc(mid || "") + '</span>' +
        '<span class="rh-edition">' + esc(edition) + '</span>' +
      '</header>';
  }

  function thumbHtml(it) {
    if (it.cover) {
      return '<div class="idx-thumb"><img src="' + esc(it.cover) + '" alt="" ' +
             'onerror="this.parentNode.style.background=\'' + it.color + '\';this.remove()" /></div>';
    }
    return '<div class="idx-thumb" style="background:' + it.color + '">' + it.icon + '</div>';
  }

  function cardHtml(it) {
    var meta = [];
    if (it.date) meta.push(esc(it.date));
    if (it.source) meta.push(esc(it.source));
    if (it.reporter) meta.push("記者 " + esc(it.reporter));
    var no = String(it.id).length < 2 ? "0" + it.id : it.id;
    return '<a class="idx-card" href="#ev-' + it.id + '">' +
      '<div class="idx-no">' + no + '</div>' +
      thumbHtml(it) +
      '<div class="idx-text">' +
        '<div class="idx-dept" style="color:' + it.color + '">' + esc(it.catLabel || "") + '</div>' +
        '<div class="idx-title">' + esc(it.title) + '</div>' +
        '<div class="idx-sum">' + esc(it.summary) + '</div>' +
        '<div class="idx-meta">' + meta.join(" \u00B7 ") + '</div>' +
      '</div>' +
    '</a>';
  }

  // ── 目錄頁：逐張放卡片，放不下就換頁（保證不會溢出頁面） ──
  var indexPages = [];

  function newIndexPage(g, withChip) {
    var isFirst = indexPages.length === 0;
    var page = newPage("pg-index" + (isFirst ? " first" : ""));
    page.innerHTML =
      (isFirst ? mastheadHtml() : runheadHtml("本期目錄")) +
      '<div class="idx-body">' +
        (withChip
          ? '<div class="idx-cat">' +
              '<span class="name" style="color:' + g.color + '">' + esc(g.label) + '</span>' +
              '<span class="en">' + g.items.length + ' 則</span>' +
            '</div>'
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
    if (it.date) meta.push(esc(it.date));
    if (it.source) meta.push(esc(it.source));
    if (it.reporter) meta.push("記者 " + esc(it.reporter));
    var coverBlock = it.cover
      ? '<div class="nl-cover"><img src="' + esc(it.cover) + '" alt="" ' +
        'onerror="this.parentNode.style.background=\'' + it.color + '\';this.remove()" /></div>'
      : '<div class="nl-cover" style="background:' + it.color + '">' + it.icon + '</div>';

    page.innerHTML =
      runheadHtml(it.catLabel || "") +
      '<article class="nl-card">' +
        (first
          ? coverBlock +
            '<div class="nl-dept" style="color:' + it.color + '">' + esc(it.catLabel || "") + '</div>' +
            '<h1 class="nl-title">' + esc(it.title) + '</h1>' +
            (meta.length ? '<div class="nl-meta">' + meta.join(" \u00B7 ") + '</div>' : '')
          : '<div class="nl-cont">承上頁 &#183; ' + esc(it.title) + '</div>') +
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
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,600&family=Noto+Sans+TC:wght@400;500;700&family=Noto+Serif+TC:wght@400;600;900&display=swap" rel="stylesheet" />
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
