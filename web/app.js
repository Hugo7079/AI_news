import { exportEventsToPdf } from "./report.js";
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js";
import {
  getFirestore,
  collection,
  query,
  where,
  orderBy,
  getDocs,
  doc,
  getDoc,
} from "https://www.gstatic.com/firebasejs/10.12.5/firebase-firestore.js";

const firebaseConfig = {
  apiKey: "AIzaSyBwY4YA-pNbWXum9UkoKYT6pb8vllOLtD8",
  authDomain: "d8ainews.firebaseapp.com",
  projectId: "d8ainews",
  storageBucket: "d8ainews.firebasestorage.app",
  messagingSenderId: "597370655558",
  appId: "1:597370655558:web:8adf51556f54469a644b47",
  measurementId: "G-94G2XF288X",
};

const app = initializeApp(firebaseConfig);
const db = getFirestore(app);

// ─── 分類元資料（與 config.py / ui_assets.py 同步） ───
const CATEGORIES = {
  tech_research:     { label: "技術突破與研究", color: "#4f46e5" },
  industry_business: { label: "產業動態與商業", color: "#059669" },
  hardware_infra:    { label: "硬體與基礎建設", color: "#d97706" },
  products_apps:     { label: "產品與應用",     color: "#0891b2" },
  policy_society:    { label: "政策法規與社會影響", color: "#db2777" },
  uncategorized:     { label: "未分類",         color: "#64748b" },
};

const CATEGORY_ORDER = ["tech_research","industry_business","hardware_infra","products_apps","policy_society","uncategorized"];

// 精選顯示上限（跟 pipeline.py 的 TOP_PICKS_TOTAL 對齊）
const TOP_PICKS_DISPLAY = 6;

const ICONS = {
  tech_research: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><path d="M20.2 20.2c2.04-2.03.02-7.36-4.5-11.9-4.54-4.52-9.87-6.54-11.9-4.5-2.04 2.03-.02 7.36 4.5 11.9 4.54 4.52 9.87 6.54 11.9 4.5Z"/><path d="M15.7 15.7c4.52-4.54 6.54-9.87 4.5-11.9-2.03-2.04-7.36-.02-11.9 4.5-4.52 4.54-6.54 9.87-4.5 11.9 2.03 2.04 7.36.02 11.9-4.5Z"/></svg>`,
  industry_business: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>`,
  hardware_infra: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/></svg>`,
  products_apps: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 4v4"/><path d="M2 8h20"/><path d="M6 4v4"/></svg>`,
  policy_society: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/></svg>`,
  uncategorized: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>`,
};

const ICON_FIRE = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>`;
const ICON_STAR = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;

// ─── DOM refs ───
const $rangeSelect   = document.getElementById("range-select");
const $rangeHint     = document.getElementById("range-hint");
const $interestChips = document.getElementById("interest-chips");
const $metrics       = document.getElementById("metrics");
const $topPicks      = document.getElementById("top-picks");
const $topPicksTitle = document.getElementById("top-picks-title");
const $osTitle       = document.getElementById("opensource-title");
const $metricsTitle  = document.getElementById("metrics-title");
const $trendingWrap  = document.getElementById("trending-wrap");
const $opensource    = document.getElementById("opensource-grid");
const $tabs          = document.getElementById("category-tabs");
const $eventList     = document.getElementById("event-list");
const $topEntities   = document.getElementById("top-entities");
const $catDist       = document.getElementById("cat-distribution");

let availableDates = [];   // desc 排序：[最新, …, 最舊]
let currentRange = 1;      // 預設今日
let currentDates = [];     // 目前載入的日期集合（desc）
let currentEvents = [];    // 目前區間內所有事件
let activeTab = "all";
let selectedCategories = new Set(CATEGORY_ORDER);  // 預設全選

// ─── 報表匯出：使用者勾選的事件 ───
const exportSelected = new Map();   // event_id → event 物件
let currentById = new Map();        // 目前載入事件的 id → event 查找表

function eventKey(ev) {
  return ev.event_id || `${ev.title || ""}|${(ev.sources || [])[0]?.url || ""}`;
}
function isPicked(ev) {
  return exportSelected.has(eventKey(ev));
}
// 勾選框 HTML（放在卡片/列上）
function pickBoxHtml(ev) {
  const k = eventKey(ev);
  return `
    <label class="pick-check" onclick="event.stopPropagation()">
      <input type="checkbox" class="export-check" data-eid="${escapeHtml(k)}" ${isPicked(ev) ? "checked" : ""} />
      <span>加入報表</span>
    </label>`;
}

function rangeLabel(days) {
  return days === 1 ? "今日" : `近 ${days} 天`;
}
function rangeWord(days) {
  return days === 1 ? "本日" : `近 ${days} 天`;
}

// ─── helpers ───
const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const catColor = (cid) => CATEGORIES[cid]?.color ?? CATEGORIES.uncategorized.color;
const catLabel = (cid) => CATEGORIES[cid]?.label ?? "未分類";

function fmtDate(s) {
  if (!s) return "";
  const [y, m, d] = s.split("-");
  const dt = new Date(Number(y), Number(m) - 1, Number(d));
  const weekday = ["日","一","二","三","四","五","六"][dt.getDay()];
  return `${y}/${m}/${d} (週${weekday})`;
}
function fmtDateShort(s) {
  if (!s) return "";
  const [, m, d] = s.split("-");
  return `${Number(m)}/${Number(d)}`;
}
function fmtRange(dates) {
  if (!dates.length) return "";
  if (dates.length === 1) return fmtDate(dates[0]);
  // dates 是 desc，[新, …, 舊]
  const newest = dates[0];
  const oldest = dates[dates.length - 1];
  return `${fmtDateShort(oldest)} ~ ${fmtDateShort(newest)}`;
}

// 過濾：依目前選的分類
function applyInterestFilter(events) {
  if (selectedCategories.size === 0) return events;  // 空集合 fallback：顯示全部
  return events.filter((ev) => selectedCategories.has(ev.category || "uncategorized"));
}

// ─── Firestore queries ───
async function loadDates() {
  const snap = await getDocs(query(collection(db, "daily_summary"), orderBy("date", "desc")));
  return snap.docs.map((d) => d.id);
}

async function loadEvents(date) {
  const snap = await getDocs(query(collection(db, "events"), where("date", "==", date)));
  return snap.docs.map((d) => d.data());
}

async function loadEventsForDates(dates) {
  if (!dates.length) return [];
  const buckets = await Promise.all(dates.map(loadEvents));
  const events = buckets.flat();
  events.sort((a, b) => {
    const di = (b.importance || 0) - (a.importance || 0);
    if (di !== 0) return di;
    return (b.mention_count || 0) - (a.mention_count || 0);
  });
  return events;
}

async function loadSummary(date) {
  const snap = await getDoc(doc(db, "daily_summary", date));
  return snap.exists() ? snap.data() : null;
}

// ─── Interest filter chips ───
function renderInterestChips() {
  $interestChips.innerHTML = CATEGORY_ORDER.map((cid) => {
    const active = selectedCategories.has(cid);
    const color = catColor(cid);
    return `
      <button type="button" class="chip ${active ? "active" : ""}" data-cid="${cid}"
              style="${active ? `background:${color};` : `color:${color};`}">
        ${ICONS[cid]}<span>${catLabel(cid)}</span>
      </button>
    `;
  }).join("");
  $interestChips.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const cid = btn.dataset.cid;
      if (selectedCategories.has(cid)) selectedCategories.delete(cid);
      else selectedCategories.add(cid);
      renderInterestChips();
      renderAll();   // 重畫所有區塊
    });
  });
}

// ─── Top picks ───
function coverHtml(ev) {
  const cover = ev.cover_image || {};
  const tagColor = catColor(ev.category);
  const tag = `
    <div class="cover-tag" style="background:${tagColor}cc">
      ${ICONS[ev.category] || ICONS.uncategorized}
      <span>${escapeHtml(catLabel(ev.category))}</span>
    </div>
  `;
  const isImage = (cover.kind === "remote" || cover.kind === "local") && cover.url;
  if (isImage) {
    let imgUrl = cover.url;
    if (cover.kind === "local" && !imgUrl.startsWith("http") && !imgUrl.startsWith("/")) {
      imgUrl = "../output/" + imgUrl;
    }
    return `<div class="cover" style="background-image:url('${escapeHtml(imgUrl)}')">${tag}</div>`;
  }
  return `
    <div class="cover-fallback" style="background:linear-gradient(135deg, ${tagColor}, ${tagColor}cc)">
      <div class="fallback-icon">${ICONS[ev.category] || ICONS.uncategorized}</div>
      ${tag}
    </div>
  `;
}

function cardHtml(ev) {
  const importance = Number(ev.importance || 0);
  const mention = Number(ev.mention_count || 1);
  const primarySrc = (ev.sources || [])[0] || {};
  const titleLink = primarySrc.url
    ? `<a href="${escapeHtml(primarySrc.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(ev.title)}</a>`
    : escapeHtml(ev.title);
  const sourceChips = (ev.sources || []).slice(0, 5).map((s) => `
    <a class="source-chip" href="${escapeHtml(s.url || "#")}" target="_blank" rel="noopener noreferrer">
      ${escapeHtml(s.source_name || "?")}
    </a>
  `).join("");
  return `
    <article class="card">
      ${coverHtml(ev)}
      <div class="card-body">
        <h3 class="card-title">${titleLink}</h3>
        <p class="card-summary">${escapeHtml(ev.summary || "")}</p>
        <div class="card-meta">
          <span class="pill pill-importance">${ICON_STAR} 重要度 ${importance}</span>
          ${mention > 1 ? `<span class="pill pill-mention">${ICON_FIRE} ${mention} 報導</span>` : ""}
          ${pickBoxHtml(ev)}
        </div>
        ${sourceChips ? `<div class="sources">${sourceChips}</div>` : ""}
      </div>
    </article>
  `;
}

function renderTopPicks(events) {
  // 跨日合併：每天的 is_top 都納入候選，再以 importance / mention_count 排序取總上限。
  const sortedTops = [...events.filter((e) => e.is_top)].sort((a, b) => {
    const di = (b.importance || 0) - (a.importance || 0);
    if (di !== 0) return di;
    return (b.mention_count || 0) - (a.mention_count || 0);
  });
  const tops = applyInterestFilter(sortedTops).slice(0, TOP_PICKS_DISPLAY);
  if (!tops.length) {
    $topPicks.innerHTML = `<div class="empty">您關注的領域中${escapeHtml(rangeWord(currentRange))}暫無精選事件。</div>`;
    return;
  }
  $topPicks.innerHTML = tops.map(cardHtml).join("");
}

// ─── Trending list ───
// 改版：按「主體跨事件出現次數」計算。同一個 who 出現在 N 個事件 → N 個事件熱度。
// 取出現次數 >= 2 的 entity，按次數排序顯示 Top 5，挑那個 entity 旗下最重要的事件當代表。
function _entityKey(s) {
  return String(s || "").trim().toLowerCase()
    .replace(/[\s"'()（）\-_、,，。.]/g, "");
}

function trendingTitleText() {
  return `${rangeWord(currentRange)}最受關注主體（跨事件出現次數）`;
}

function renderTrending(events) {
  const filtered = applyInterestFilter(events);

  // 1) 為每個 entity（原始字串）統計出現過的事件
  //    用 normalized key 做合併（"南山人壽" / "南山人壽保險" 算同一個）
  const byKey = new Map();   // key → { display, events: [] }
  for (const ev of filtered) {
    const seenInThisEvent = new Set();   // 同事件不重覆計
    for (const w of (ev.who || [])) {
      const k = _entityKey(w);
      if (!k || k.length < 2 || seenInThisEvent.has(k)) continue;
      seenInThisEvent.add(k);
      if (!byKey.has(k)) byKey.set(k, { display: String(w).trim(), events: [] });
      byKey.get(k).events.push(ev);
    }
  }

  // 2) 篩出 count >= 2 的 entity，按 count desc 排序
  const ranked = [...byKey.entries()]
    .map(([k, v]) => ({ key: k, display: v.display, events: v.events }))
    .filter((e) => e.events.length >= 2)
    .sort((a, b) => {
      if (b.events.length !== a.events.length) return b.events.length - a.events.length;
      // 平手用代表事件的 importance 當 tiebreaker
      const ai = Math.max(...a.events.map((x) => x.importance || 0));
      const bi = Math.max(...b.events.map((x) => x.importance || 0));
      return bi - ai;
    })
    .slice(0, 5);

  if (!ranked.length) {
    $trendingWrap.innerHTML = "";
    return;
  }

  const rows = ranked.map((entry, i) => {
    // 代表事件：該 entity 旗下 importance 最高、mention_count 最高的一筆
    const repEvent = [...entry.events].sort((a, b) => {
      const di = (b.importance || 0) - (a.importance || 0);
      if (di !== 0) return di;
      return (b.mention_count || 0) - (a.mention_count || 0);
    })[0];
    const rank = String(i + 1).padStart(2, "0");
    const color = catColor(repEvent.category);
    const primarySrc = (repEvent.sources || [])[0] || {};
    const titleNode = primarySrc.url
      ? `<a href="${escapeHtml(primarySrc.url)}" target="_blank" rel="noopener noreferrer"><span class="title-text">${escapeHtml(repEvent.title)}</span></a>`
      : `<span class="title-text">${escapeHtml(repEvent.title)}</span>`;
    return `
      <div class="trending-item">
        <div class="trending-rank">${rank}</div>
        <div class="trending-text">
          <span class="cat-badge" style="background:${color}">${ICONS[repEvent.category] || ICONS.uncategorized}${escapeHtml(entry.display)}</span>
          ${titleNode}
        </div>
        <div class="trending-count">${entry.events.length} 個事件</div>
      </div>
    `;
  }).join("");

  $trendingWrap.innerHTML = `
    <div class="trending">
      <div class="trending-title">${ICON_FIRE}${escapeHtml(trendingTitleText())}</div>
      <div class="trending-list">${rows}</div>
    </div>
  `;
}

// ─── Open Source Radar ───
const ICON_CODE = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`;
const ICON_STAR_OS = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
const ICON_DL = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;
const ICON_UP = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>`;
const ICON_CTX = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/></svg>`;
const ICON_TAG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>`;

function _fmtNum(n) {
  n = Number(n) || 0;
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}

function osCardHtml(ev) {
  const osSources = (ev.sources || []).filter((s) => s.is_opensource);
  if (!osSources.length) return "";

  // 彙整指標
  let stars = "", pulls = "", downloads = 0, likes = 0, upvotes = 0, ctx = 0, task = "";
  const sourceNames = [];
  for (const s of osSources) {
    if (s.source_name && !sourceNames.includes(s.source_name)) sourceNames.push(s.source_name);
    if (!stars && s.stars) stars = String(s.stars);
    if (!pulls && s.pulls) pulls = String(s.pulls);
    if (s.downloads) downloads = Math.max(downloads, Number(s.downloads) || 0);
    if (s.likes) likes = Math.max(likes, Number(s.likes) || 0);
    if (s.upvotes) upvotes = Math.max(upvotes, Number(s.upvotes) || 0);
    if (s.context_length) ctx = Math.max(ctx, Number(s.context_length) || 0);
    if (!task && s.task) task = String(s.task);
  }

  const badges = [];
  if (stars) badges.push(`<span class="os-badge">${ICON_STAR_OS}${stars} stars</span>`);
  if (pulls) badges.push(`<span class="os-badge">${ICON_DL}${pulls} pulls</span>`);
  if (downloads > 0) badges.push(`<span class="os-badge">${ICON_DL}${_fmtNum(downloads)} dl</span>`);
  if (likes > 0) badges.push(`<span class="os-badge os-badge-alt">${ICON_UP}${_fmtNum(likes)} likes</span>`);
  if (upvotes > 0) badges.push(`<span class="os-badge os-badge-alt">${ICON_UP}${upvotes} upvotes</span>`);
  if (ctx > 0) {
    const ctxStr = ctx >= 1024 ? `${Math.floor(ctx / 1024)}k` : String(ctx);
    badges.push(`<span class="os-badge">${ICON_CTX}Ctx ${ctxStr}</span>`);
  }
  if (task) badges.push(`<span class="os-badge os-badge-alt">${ICON_TAG}${escapeHtml(task)}</span>`);

  const url = (ev.sources || [])[0]?.url || "#";
  return `
    <article class="os-card">
      <div class="os-card-source">${ICON_CODE}<span>${escapeHtml(sourceNames.join(" / "))}</span></div>
      <div class="os-card-name"><a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(ev.title || "(無標題)")}</a></div>
      <div class="os-card-desc">${escapeHtml(ev.summary || "")}</div>
      ${badges.length ? `<div class="os-badges">${badges.join("")}</div>` : ""}
    </article>
  `;
}

function renderOpenSource(events) {
  const filtered = applyInterestFilter(events);
  const osEvents = filtered.filter((ev) =>
    (ev.sources || []).some((s) => s.is_opensource),
  );
  if (!osEvents.length) {
    $opensource.innerHTML = `<div class="empty" style="grid-column:1/-1">${escapeHtml(rangeWord(currentRange))}無開源生態事件。</div>`;
    return;
  }
  // 依 importance 排序，顯示前 8 筆
  osEvents.sort((a, b) => (b.importance || 0) - (a.importance || 0));
  $opensource.innerHTML = osEvents.slice(0, 8).map(osCardHtml).join("");
}

// ─── Database (tabs + list) ───
function rowHtml(ev) {
  const tagColor = catColor(ev.category);
  const primarySrc = (ev.sources || [])[0] || {};
  const titleLink = primarySrc.url
    ? `<a href="${escapeHtml(primarySrc.url)}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:none">${escapeHtml(ev.title)}</a>`
    : escapeHtml(ev.title);
  const mention = Number(ev.mention_count || 1);
  return `
    <article class="event-row">
      <div class="row-head">
        <span class="cat-badge" style="background:${tagColor}">${ICONS[ev.category] || ICONS.uncategorized}${escapeHtml(catLabel(ev.category))}</span>
        <span class="pill pill-importance">★ ${ev.importance || 0}</span>
        ${mention > 1 ? `<span class="pill pill-mention">${mention} 報導</span>` : ""}
        ${pickBoxHtml(ev)}
      </div>
      <div class="row-title">${titleLink}</div>
      <div class="row-summary">${escapeHtml(ev.summary || "")}</div>
    </article>
  `;
}

function renderTabsAndList(events) {
  const filtered = applyInterestFilter(events);
  const counts = { all: filtered.length };
  for (const ev of filtered) {
    const cid = ev.category || "uncategorized";
    counts[cid] = (counts[cid] || 0) + 1;
  }
  // 只顯示「使用者選的、且當天有事件」的分類 tab
  const visibleCats = CATEGORY_ORDER.filter((cid) => selectedCategories.has(cid) && counts[cid]);
  // 如果 activeTab 不在可見裡，重置成 all
  if (activeTab !== "all" && !visibleCats.includes(activeTab)) activeTab = "all";

  const entries = [["all", "全部"], ...visibleCats.map((cid) => [cid, catLabel(cid)])];
  $tabs.innerHTML = entries.map(([cid, label]) => `
    <button class="tab ${cid === activeTab ? "active" : ""}" data-cat="${cid}">
      ${label}
      <span class="tab-count">${counts[cid] || 0}</span>
    </button>
  `).join("");
  $tabs.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.cat;
      renderTabsAndList(events);
    });
  });

  const listSrc = activeTab === "all"
    ? filtered
    : filtered.filter((e) => (e.category || "uncategorized") === activeTab);

  if (!listSrc.length) {
    $eventList.innerHTML = `<div class="empty">沒有符合您關注領域的事件。</div>`;
    return;
  }
  $eventList.innerHTML = listSrc.map(rowHtml).join("");
}

// ─── Analytics ───
function renderMetrics(events) {
  const filtered = applyInterestFilter(events);
  const totalDb = filtered.length;
  const topCount = filtered.filter((e) => e.is_top).length;
  const catCount = new Set(filtered.map((e) => e.category || "uncategorized")).size;
  const topLabel = currentRange === 1 ? "今日精選" : `${rangeLabel(currentRange)}精選`;
  const cards = [
    { label: "事件總數",   value: totalDb },
    { label: topLabel,     value: topCount },
    { label: "覆蓋分類",   value: catCount },
    { label: "資料區間",   value: fmtRange(currentDates) },
  ];
  $metrics.innerHTML = cards.map((c) => `
    <div class="metric">
      <div class="metric-label">${escapeHtml(c.label)}</div>
      <div class="metric-value">${escapeHtml(c.value)}</div>
    </div>
  `).join("");
}

function hbarRow(label, count, max, color) {
  const w = max ? (count / max) * 100 : 0;
  return `
    <div class="hbar-row">
      <div class="hbar-label">${escapeHtml(label)}</div>
      <div class="hbar-track"><div class="hbar-fill" style="width:${w}%;background:${color}"></div></div>
      <div class="hbar-count">${count}</div>
    </div>
  `;
}

function renderTopEntities(events) {
  const filtered = applyInterestFilter(events);
  const counts = new Map();
  for (const ev of filtered) {
    for (const w of (ev.who || [])) {
      const k = String(w).trim();
      if (!k) continue;
      counts.set(k, (counts.get(k) || 0) + 1);
    }
  }
  const sorted = [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);
  if (!sorted.length) {
    $topEntities.innerHTML = `<div class="empty" style="padding:8px">無資料</div>`;
    return;
  }
  const max = sorted[0][1];
  $topEntities.innerHTML = sorted.map(([k, v]) => hbarRow(k, v, max, "#4f46e5")).join("");
}

function renderCatDist(events) {
  const filtered = applyInterestFilter(events);
  const counts = {};
  for (const ev of filtered) {
    const cid = ev.category || "uncategorized";
    counts[cid] = (counts[cid] || 0) + 1;
  }
  const rows = CATEGORY_ORDER
    .filter((cid) => counts[cid])
    .sort((a, b) => counts[b] - counts[a]);
  if (!rows.length) {
    $catDist.innerHTML = `<div class="empty" style="padding:8px">無資料</div>`;
    return;
  }
  const max = Math.max(...rows.map((cid) => counts[cid]));
  $catDist.innerHTML = rows.map((cid) => hbarRow(catLabel(cid), counts[cid], max, catColor(cid))).join("");
}

// ─── 報表匯出列（浮動工具列） ───
function ensureExportBar() {
  if (document.getElementById("export-bar")) return;
  const bar = document.createElement("div");
  bar.id = "export-bar";
  bar.className = "export-bar hidden";
  bar.innerHTML = `
    <span class="export-count">已選 <b id="export-n">0</b> 則</span>
    <button id="export-clear" class="export-btn export-btn-ghost" type="button">清空</button>
    <button id="export-go" class="export-btn export-btn-primary" type="button">匯出 PDF</button>
  `;
  document.body.appendChild(bar);
  document.getElementById("export-clear").addEventListener("click", () => {
    exportSelected.clear();
    // 取消畫面上所有勾選
    document.querySelectorAll(".export-check").forEach((cb) => { cb.checked = false; });
    updateExportBar();
  });
  document.getElementById("export-go").addEventListener("click", () => {
    exportEventsToPdf([...exportSelected.values()]);
  });

  // 勾選 / 取消勾選（事件委派，撐過重繪）
  document.addEventListener("change", (e) => {
    const cb = e.target.closest?.(".export-check");
    if (!cb) return;
    const id = cb.dataset.eid;
    if (cb.checked) {
      const ev = currentById.get(id);
      if (ev) exportSelected.set(id, ev);
    } else {
      exportSelected.delete(id);
    }
    updateExportBar();
  });
}

function updateExportBar() {
  const bar = document.getElementById("export-bar");
  if (!bar) return;
  const n = exportSelected.size;
  document.getElementById("export-n").textContent = String(n);
  bar.classList.toggle("hidden", n === 0);
}

// ─── Orchestration ───
function updateSectionTitles() {
  const rl = rangeLabel(currentRange);
  if ($topPicksTitle) $topPicksTitle.innerHTML = `<span class="accent"></span>${escapeHtml(rl)}精選`;
  if ($osTitle)       $osTitle.innerHTML       = `<span class="accent"></span>開源生態與模型觀測站（${escapeHtml(rl)}）`;
  if ($metricsTitle)  $metricsTitle.innerHTML  = `<span class="accent"></span>${escapeHtml(rl)} AI 局勢數據看板`;
}

function updateRangeHint() {
  if (!$rangeHint) return;
  if (!currentDates.length) { $rangeHint.textContent = ""; return; }
  $rangeHint.textContent = currentDates.length === 1
    ? fmtDate(currentDates[0])
    : `${fmtRange(currentDates)}（共 ${currentDates.length} 天）`;
}

function renderAll() {
  updateSectionTitles();
  updateRangeHint();
  renderTopPicks(currentEvents);
  renderTrending(currentEvents);
  renderOpenSource(currentEvents);
  renderTabsAndList(currentEvents);
  renderMetrics(currentEvents);
  renderTopEntities(currentEvents);
  renderCatDist(currentEvents);
}

async function showRange(days) {
  currentRange = days;
  currentDates = availableDates.slice(0, days);   // desc, 取前 N 天
  $topPicks.innerHTML = `<div class="loading"><div class="spinner"></div><div>讀取中…</div></div>`;
  $trendingWrap.innerHTML = "";
  $opensource.innerHTML = "";
  $eventList.innerHTML = "";
  $metrics.innerHTML = "";
  $topEntities.innerHTML = "";
  $catDist.innerHTML = "";
  updateSectionTitles();
  updateRangeHint();

  try {
    currentEvents = await loadEventsForDates(currentDates);
    // 重建 id → event 查找表，並把已勾選事件同步成新載入的物件
    currentById = new Map(currentEvents.map((ev) => [eventKey(ev), ev]));
    for (const id of [...exportSelected.keys()]) {
      if (currentById.has(id)) exportSelected.set(id, currentById.get(id));
    }
    activeTab = "all";
    renderAll();
    updateExportBar();
  } catch (err) {
    console.error(err);
    $topPicks.innerHTML = `<div class="empty">讀取失敗：${escapeHtml(err.message || err)}</div>`;
  }
}

async function main() {
  try {
    ensureExportBar();
    renderInterestChips();
    availableDates = await loadDates();
    if (!availableDates.length) {
      $topPicks.innerHTML = `<div class="empty">Firestore 還沒有資料。先跑 <code>scripts/migrate_legacy.py</code> 或等今日 cron 跑完。</div>`;
      return;
    }
    $rangeSelect.addEventListener("change", (e) => showRange(Number(e.target.value) || 1));
    await showRange(Number($rangeSelect.value) || 1);
  } catch (err) {
    console.error(err);
    $topPicks.innerHTML = `<div class="empty">初始化失敗：${escapeHtml(err.message || err)}<br>請確認 Firestore Rules 是否允許 public read。</div>`;
  }
}

main();
