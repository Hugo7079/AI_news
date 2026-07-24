// ─────────────────────────────────────────────────────────────────────────────
// report.js — 將使用者勾選的事件組成一份 PDF 報表（瀏覽器列印成 PDF）
//
// 版面（對齊範例「雙週電子報」）：
//   1) 封面：報表標題 + 日期區間 + 產生時間 + 事件數
//   2) 大綱摘要：依分類分組，每筆 = 標題 + 一句摘要 + 來源/日期 meta
//   3) 細節說明：每個事件獨立一段（分頁），含完整摘要 + 5W + 重要度 + 來源連結
//
// 設計成靜態前端可用：開新視窗、寫入自帶樣式的 HTML、載入後自動叫出列印對話框。
// 使用者在列印對話框選「另存為 PDF」即可。
// ─────────────────────────────────────────────────────────────────────────────

const CAT_META = {
  tech_research:     { label: "技術突破與研究",     color: "#4f46e5" },
  industry_business: { label: "產業動態與商業",     color: "#059669" },
  hardware_infra:    { label: "硬體與基礎建設",     color: "#d97706" },
  products_apps:     { label: "產品與應用",         color: "#0891b2" },
  policy_society:    { label: "政策法規與社會影響", color: "#db2777" },
  uncategorized:     { label: "未分類",             color: "#64748b" },
};
const CAT_ORDER = ["tech_research","industry_business","hardware_infra","products_apps","policy_society","uncategorized"];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

function catLabel(cid) { return (CAT_META[cid] || CAT_META.uncategorized).label; }
function catColor(cid) { return (CAT_META[cid] || CAT_META.uncategorized).color; }

// 從 ISO 字串取 YYYY-MM-DD
function ymd(s) {
  if (!s) return "";
  const m = String(s).match(/(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : "";
}
function ymdSlash(s) {
  const v = ymd(s);
  return v ? v.replaceAll("-", "/") : "";
}

// 取事件代表日期：優先 event.date（Firestore），否則第一個來源的 published
function eventDate(ev) {
  return ymd(ev.date) || ymd((ev.sources || [])[0]?.published) || "";
}

// 計算日期區間字串
function dateRange(events) {
  const ds = events.map(eventDate).filter(Boolean).sort();
  if (!ds.length) return "";
  const a = ds[0].replaceAll("-", "/");
  const b = ds[ds.length - 1].replaceAll("-", "/");
  return a === b ? a : `${a} – ${b}`;
}

// 依分類分組（保持 CAT_ORDER 順序），組內依 importance / mention_count 排序
function groupByCategory(events) {
  const buckets = new Map();
  for (const ev of events) {
    const cid = CAT_META[ev.category] ? ev.category : "uncategorized";
    if (!buckets.has(cid)) buckets.set(cid, []);
    buckets.get(cid).push(ev);
  }
  for (const arr of buckets.values()) {
    arr.sort((a, b) => (b.importance || 0) - (a.importance || 0)
                    || (b.mention_count || 0) - (a.mention_count || 0));
  }
  return CAT_ORDER.filter((c) => buckets.has(c)).map((c) => [c, buckets.get(c)]);
}

// ── 大綱摘要列（標題可點，跳到該則細節） ──
function outlineItemHtml(ev) {
  const idx = ev.__rid;
  const primary = (ev.sources || [])[0] || {};
  const meta = [
    eventDate(ev) ? `日期：${ymdSlash(ev.date) || ymdSlash(primary.published)}` : "",
    primary.source_name ? `來源：${esc(primary.source_name)}` : "",
    (ev.mention_count || 1) > 1 ? `${ev.mention_count} 篇報導` : "",
  ].filter(Boolean).join("　");
  return `
    <div class="ol-item">
      <div class="ol-num">${String(idx).padStart(2, "0")}</div>
      <div class="ol-body">
        <a class="ol-title" href="#ev-${idx}">${esc(ev.title || "(無標題)")}</a>
        <div class="ol-sum">${esc(ev.summary || "")}</div>
        <div class="ol-meta">${meta}</div>
      </div>
      <div class="ol-imp" style="--c:${catColor(ev.category)}">${ev.importance || 0}</div>
    </div>`;
}

function outlineHtml(grouped) {
  const sections = grouped.map(([cid, evs]) => {
    const rows = evs.map((ev) => outlineItemHtml(ev)).join("");
    return `
      <section class="ol-section">
        <h3 class="ol-cat" style="--c:${catColor(cid)}">
          <span class="ol-cat-dot"></span>${esc(catLabel(cid))}
          <span class="ol-cat-count">${evs.length}</span>
        </h3>
        ${rows}
      </section>`;
  }).join("");
  return `
    <section class="outline">
      <h2 class="part-title">大綱摘要</h2>
      ${sections}
    </section>`;
}

// 把 full_content 切成段落 <p>；沒有就退回 summary。
function bodyParagraphs(ev) {
  const text = (ev.full_content || ev.summary || "").trim();
  const paras = text.split(/\n+/).map((s) => s.trim()).filter(Boolean);
  if (!paras.length) return "";
  return paras.map((p) => `<p class="detail-p">${esc(p)}</p>`).join("");
}

// ── 封面圖（文生圖）：remote/local → <img>；其餘 → 分類漸層底圖 ──
function coverImgHtml(ev) {
  const cover = ev.cover_image || {};
  const color = catColor(ev.category);
  const isImage = (cover.kind === "remote" || cover.kind === "local") && cover.url;
  if (isImage) {
    let imgUrl = cover.url;
    if (cover.kind === "local" && !imgUrl.startsWith("http") && !imgUrl.startsWith("/")) {
      imgUrl = "../output/" + imgUrl;
    }
    return `<div class="detail-cover">
      <img src="${esc(imgUrl)}" alt="" loading="eager"
           onerror="this.parentNode.classList.add('cover-broken')" />
    </div>`;
  }
  // fallback：分類色漸層（無外部圖）
  return `<div class="detail-cover detail-cover-fallback"
               style="background:linear-gradient(135deg, ${color}, ${color}99)"></div>`;
}

// ── 細節說明（每事件一段） ──
function detailHtml(ev) {
  const idx = ev.__rid;
  const cid = CAT_META[ev.category] ? ev.category : "uncategorized";
  const five = [
    ["主體", (ev.who || []).join("、")],
    ["動作", ev.what || ""],
    ["時間", ev.when || ""],
    ["地點", ev.where || ""],
  ].filter(([, v]) => v).map(([k, v]) => `
    <div class="w-row"><div class="w-key">${k}</div><div class="w-val">${esc(v)}</div></div>`).join("");

  const sources = (ev.sources || []).map((s) => {
    const name = esc(s.source_name || "來源");
    const date = ymdSlash(s.published);
    const url = s.url || "";
    const title = esc(s.title || ev.title || "");
    return `
      <li class="src">
        <div class="src-head"><span class="src-name">${name}</span>${date ? `<span class="src-date">${date}</span>` : ""}</div>
        <div class="src-title">${title}</div>
        ${url ? `<a class="src-url" href="${esc(url)}">${esc(url)}</a>` : ""}
      </li>`;
  }).join("");

  return `
    <article class="detail" id="ev-${idx}">
      <div class="detail-head" style="--c:${catColor(cid)}">
        <span class="detail-cat">${esc(catLabel(cid))}</span>
        <span class="detail-pills">
          <span class="pill">★ 重要度 ${ev.importance || 0}</span>
          ${(ev.mention_count || 1) > 1 ? `<span class="pill">🔥 ${ev.mention_count} 篇報導</span>` : ""}
        </span>
      </div>
      <h3 class="detail-title"><span class="detail-idx">${String(idx).padStart(2, "0")}</span>${esc(ev.title || "(無標題)")}</h3>
      ${coverImgHtml(ev)}
      <div class="detail-body">${bodyParagraphs(ev)}</div>
      ${five ? `<div class="w-table">${five}</div>` : ""}
      ${sources ? `<div class="src-wrap"><div class="src-label">資料來源</div><ul class="src-list">${sources}</ul></div>` : ""}
    </article>`;
}

function detailsHtml(events) {
  const items = events.map((ev) => detailHtml(ev)).join("");
  return `
    <section class="details">
      <h2 class="part-title part-title-break">細節說明</h2>
      ${items}
    </section>`;
}

// ── 整份文件 ──
function reportDocument(events) {
  const grouped = groupByCategory(events);
  // 細節順序與大綱一致（分類 → 重要度）
  const ordered = grouped.flatMap(([, evs]) => evs);
  // 指派穩定編號：大綱、細節、錨點都用同一個 __rid，確保點擊可正確跳轉
  ordered.forEach((ev, i) => { ev.__rid = i + 1; });
  const range = dateRange(events);
  const generated = new Date().toLocaleString("zh-TW", { hour12: false });

  return `<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8" />
<title>AI新聞報告${range ? `（${range}）` : ""}</title>
<style>
  @page { size: A4; margin: 18mm 16mm; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei",
                 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #0f172a; line-height: 1.7; font-size: 11.5pt;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }
  a { color: #4f46e5; text-decoration: none; word-break: break-all; }

  /* ── 封面 ── */
  .cover {
    height: 100vh; display: flex; flex-direction: column; justify-content: center;
    page-break-after: always; text-align: center;
    background: linear-gradient(135deg, #eef2ff 0%, #ecfeff 100%);
    margin: -18mm -16mm; padding: 18mm 16mm;
  }
  .cover-kicker { letter-spacing: .35em; color: #6366f1; font-weight: 700; font-size: 12pt; }
  .cover-title { font-size: 34pt; font-weight: 800; margin: 14px 0 8px; letter-spacing: .02em; }
  .cover-range { font-size: 16pt; color: #334155; font-weight: 600; }
  .cover-meta { margin-top: 26px; color: #64748b; font-size: 11pt; }
  .cover-line { width: 64px; height: 4px; border-radius: 4px; margin: 22px auto;
                background: linear-gradient(90deg, #4f46e5, #0891b2); }

  .part-title {
    font-size: 18pt; font-weight: 800; margin: 4px 0 16px;
    padding-bottom: 8px; border-bottom: 3px solid #4f46e5; color: #1e293b;
  }
  .part-title-break { page-break-before: always; }

  /* ── 大綱 ── */
  .ol-section { margin-bottom: 14px; break-inside: avoid; }
  .ol-cat {
    display: flex; align-items: center; gap: 8px; font-size: 13pt; font-weight: 700;
    color: var(--c); margin: 14px 0 8px;
  }
  .ol-cat-dot { width: 10px; height: 10px; border-radius: 3px; background: var(--c); }
  .ol-cat-count {
    margin-left: auto; font-size: 9.5pt; font-weight: 600; color: #fff;
    background: var(--c); border-radius: 20px; padding: 1px 9px;
  }
  .ol-item {
    display: grid; grid-template-columns: 26px 1fr 30px; gap: 10px; align-items: start;
    padding: 8px 0; border-bottom: 1px solid #e2e8f0; break-inside: avoid;
  }
  .ol-num { color: #94a3b8; font-weight: 700; font-size: 11pt; font-variant-numeric: tabular-nums; }
  .ol-title { display: block; font-weight: 700; font-size: 11.5pt; color: #1e293b;
              text-decoration: none; }
  .ol-title:hover { color: #4f46e5; text-decoration: underline; }
  .ol-sum { color: #475569; font-size: 10.5pt; margin-top: 2px; }
  .ol-meta { color: #94a3b8; font-size: 9pt; margin-top: 4px; }
  .ol-imp {
    color: var(--c); font-weight: 800; font-size: 13pt; text-align: center;
    font-variant-numeric: tabular-nums;
  }

  /* ── 細節 ── */
  .detail { break-inside: avoid; page-break-inside: avoid; margin: 0 0 22px;
            padding-bottom: 16px; border-bottom: 1px solid #e2e8f0; }
  .detail-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  .detail-cat {
    font-size: 9.5pt; font-weight: 700; color: #fff; background: var(--c);
    border-radius: 6px; padding: 2px 10px;
  }
  .detail-pills { margin-left: auto; display: flex; gap: 6px; }
  .pill { font-size: 9pt; font-weight: 600; color: #475569; background: #f1f5f9;
          border-radius: 20px; padding: 2px 10px; }
  .detail-title { font-size: 15pt; font-weight: 800; margin: 4px 0 8px; line-height: 1.4; }
  .detail-idx { color: #cbd5e1; margin-right: 8px; font-variant-numeric: tabular-nums; }

  /* ── 文生圖封面 ── */
  .detail-cover { width: 100%; aspect-ratio: 16 / 9; margin: 2px 0 12px;
                  border-radius: 12px; overflow: hidden; background: #e2e8f0; }
  .detail-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .detail-cover.cover-broken { background: linear-gradient(135deg, #cbd5e1, #94a3b8); }
  .detail-cover.cover-broken img { display: none; }
  .detail-cover-fallback { aspect-ratio: 16 / 5; }
  .detail-body { margin: 0 0 12px; }
  .detail-p { margin: 0 0 9px; color: #1e293b; text-align: justify; }
  .detail-p:last-child { margin-bottom: 0; }

  .w-table { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px;
             background: #f8fafc; border-radius: 10px; padding: 10px 14px; margin-bottom: 12px; }
  .w-row { display: flex; gap: 8px; font-size: 10.5pt; }
  .w-key { color: #64748b; font-weight: 700; flex: 0 0 36px; }
  .w-val { color: #1e293b; }

  .src-wrap { margin-top: 6px; }
  .src-label { font-size: 9.5pt; font-weight: 700; color: #64748b; margin-bottom: 4px; }
  .src-list { list-style: none; margin: 0; padding: 0; }
  .src { padding: 6px 0 6px 12px; border-left: 3px solid #e2e8f0; margin-bottom: 6px; }
  .src-head { display: flex; align-items: baseline; gap: 8px; }
  .src-name { font-weight: 700; font-size: 10pt; color: #334155; }
  .src-date { font-size: 9pt; color: #94a3b8; }
  .src-title { font-size: 10pt; color: #475569; margin: 1px 0; }
  .src-url { font-size: 8.5pt; color: #6366f1; }

  @media screen {
    body { background: #f1f5f9; }
    .cover, .outline, .details {
      max-width: 794px; margin-left: auto; margin-right: auto; background: #fff;
    }
    .outline, .details { padding: 24px 32px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  }
</style>
</head>
<body>
  <section class="cover">
    <div class="cover-kicker">AI新聞報告</div>
    <div class="cover-line"></div>
    <h1 class="cover-title">AI 新聞精選報表</h1>
    <div class="cover-range">${range ? esc(range) : "彙整報告"}</div>
    <div class="cover-meta">
      共 ${events.length} 則事件 ・ 涵蓋 ${grouped.length} 個分類<br/>
      產生時間：${esc(generated)}
    </div>
  </section>
  ${outlineHtml(grouped)}
  ${detailsHtml(ordered)}
</body>
</html>`;
}

/**
 * 產生報表的完整 HTML 字串（不開視窗，方便測試/預覽）。
 * @param {Array<object>} events 事件物件陣列
 * @returns {string} HTML
 */
export function buildReportHtml(events) {
  return reportDocument(events || []);
}

/**
 * 把選定的事件匯出成 PDF 報表（開新視窗並叫出列印對話框）。
 * @param {Array<object>} events 事件物件陣列
 */
export function exportEventsToPdf(events) {
  if (!events || !events.length) {
    alert("尚未勾選任何事件。請先在卡片或清單勾選「加入報表」。");
    return;
  }
  const html = reportDocument(events);
  const w = window.open("", "_blank");
  if (!w) {
    alert("瀏覽器封鎖了彈出視窗，請允許本站開啟新視窗後再試。");
    return;
  }
  w.document.open();
  w.document.write(html);
  w.document.close();

  // 等字型 + 所有封面圖載入後再叫出列印（避免 PDF 缺圖）。
  // 任一圖載不到不阻塞，最多等 8 秒當保險。
  const waitImages = () => {
    const imgs = Array.from(w.document.images || []);
    const pending = imgs.filter((im) => !im.complete);
    if (!pending.length) return Promise.resolve();
    return Promise.all(pending.map((im) => new Promise((res) => {
      im.addEventListener("load", res, { once: true });
      im.addEventListener("error", res, { once: true });
    })));
  };
  const triggerPrint = () => { w.focus(); w.print(); };
  const ready = () => {
    const cap = new Promise((res) => setTimeout(res, 8000));
    Promise.race([waitImages(), cap]).then(() => setTimeout(triggerPrint, 250));
  };
  if (w.document.readyState === "complete") ready();
  else w.addEventListener("load", ready);
}
