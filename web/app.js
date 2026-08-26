import { exportEventsToPdf, getNewsletterConfig, saveNewsletterConfig } from "./report.js";

// ─── 資料來源 ───────────────────────────────────────────────────────────────
// 由 ./config.json 的 mode 決定：
//   local     → 打自架伺服器的 /api/*（src/server.py），完全不碰 Firebase
//   firestore → 動態載入 Firebase SDK 讀 Firestore（Firebase Hosting 版）
// 本地模式不會 import 任何 gstatic 上的東西，內網 / 離線環境也能跑。
const FIREBASE_CONFIG = {
  apiKey: "AIzaSyBwY4YA-pNbWXum9UkoKYT6pb8vllOLtD8",
  authDomain: "d8ainews.firebaseapp.com",
  projectId: "d8ainews",
  storageBucket: "d8ainews.firebasestorage.app",
  messagingSenderId: "597370655558",
  appId: "1:597370655558:web:8adf51556f54469a644b47",
  measurementId: "G-94G2XF288X",
};

let dataSource = null;

async function detectMode() {
  try {
    const r = await fetch("./config.json", { cache: "no-store" });
    if (!r.ok) return "firestore";
    const cfg = await r.json();
    return cfg.mode === "local" ? "local" : "firestore";
  } catch {
    return "firestore";
  }
}

function localSource() {
  const get = async (path) => {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) throw new Error(`${path} 回應 HTTP ${r.status}`);
    return r.json();
  };
  return {
    mode: "local",
    async loadDates() {
      return (await get("./api/dates")).dates || [];
    },
    async loadEvents(start, end) {
      const d = await get(`./api/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
      return d.events || [];
    },
  };
}

async function firestoreSource() {
  const [{ initializeApp }, fs] = await Promise.all([
    import("https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js"),
    import("https://www.gstatic.com/firebasejs/10.12.5/firebase-firestore.js"),
  ]);
  const db = fs.getFirestore(initializeApp(FIREBASE_CONFIG));
  return {
    mode: "firestore",
    async loadDates() {
      const snap = await fs.getDocs(fs.query(
        fs.collection(db, "daily_summary"), fs.orderBy("date", "desc"),
      ));
      return snap.docs.map((d) => d.id);
    },
    async loadEvents(start, end) {
      const snap = await fs.getDocs(fs.query(
        fs.collection(db, "events"),
        fs.where("date", ">=", start),
        fs.where("date", "<=", end),
      ));
      return snap.docs.map((d) => d.data());
    },
  };
}

async function createDataSource() {
  const mode = await detectMode();
  return mode === "local" ? localSource() : firestoreSource();
}

// ─── 分類元資料（與 config.py 同步；「未分類」不再出現在 UI） ───
const CATEGORIES = {
  tech_research:     { label: "技術突破與研究", color: "#4f46e5" },
  industry_business: { label: "產業動態與商業", color: "#059669" },
  hardware_infra:    { label: "硬體與基礎建設", color: "#d97706" },
  products_apps:     { label: "產品與應用",     color: "#0891b2" },
  policy_society:    { label: "政策法規與社會影響", color: "#db2777" },
};
const CATEGORY_ORDER = ["tech_research","industry_business","hardware_infra","products_apps","policy_society"];
const FALLBACK_CAT = { label: "其他", color: "#64748b" };

const ICONS = {
  tech_research: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><path d="M20.2 20.2c2.04-2.03.02-7.36-4.5-11.9-4.54-4.52-9.87-6.54-11.9-4.5-2.04 2.03-.02 7.36 4.5 11.9 4.54 4.52 9.87 6.54 11.9 4.5Z"/><path d="M15.7 15.7c4.52-4.54 6.54-9.87 4.5-11.9-2.03-2.04-7.36-.02-11.9 4.5-4.52 4.54-6.54 9.87-4.5 11.9 2.03 2.04 7.36.02 11.9-4.5Z"/></svg>`,
  industry_business: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>`,
  hardware_infra: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/></svg>`,
  products_apps: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 4v4"/><path d="M2 8h20"/><path d="M6 4v4"/></svg>`,
  policy_society: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/></svg>`,
  _default: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>`,
};

const ICON_FIRE = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>`;
const ICON_STAR = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
const ICON_GAUGE = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"/><path d="M13.4 10.6 19 5"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>`;

// ─── DOM refs ───
const $rangeSelect   = document.getElementById("range-select");
const $rangeHint     = document.getElementById("range-hint");
const $interestChips = document.getElementById("interest-chips");
const $metrics       = document.getElementById("metrics");
const $topPicks      = document.getElementById("top-picks");
const $topPicksTitle = document.getElementById("top-picks-title");
const $osTitle       = document.getElementById("opensource-title");
const $osToggle      = document.getElementById("os-toggle");
const $metricsTitle  = document.getElementById("metrics-title");
const $metricList    = document.getElementById("metric-list");
const $picksCount    = document.getElementById("picks-count");
const $metricReset   = document.getElementById("metric-reset");
const $metricAddAll  = document.getElementById("metric-add-all");
const $pickToggle    = document.getElementById("pick-panel-toggle");
const $pickToggleLbl = document.getElementById("pick-toggle-label");
const $picksLayout   = document.getElementById("picks-layout");
const $opensource    = document.getElementById("opensource-grid");
const $dbToolbar     = document.getElementById("db-toolbar");
const $tabs          = document.getElementById("category-tabs");
const $eventList     = document.getElementById("event-list");
const $dbPager       = document.getElementById("db-pager");
const $topEntities   = document.getElementById("top-entities");
const $catDist       = document.getElementById("cat-distribution");

let availableDates = [];   // desc 排序：[最新, …, 最舊]
let currentRange = 1;      // 預設今日
let rangeStart = "";       // 目前查詢的起訖日（實際日曆日期）
let rangeEnd = "";
let currentDates = [];     // 目前區間內「真的有資料」的日期（desc）
let currentEvents = [];    // 目前區間內所有事件
let activeTab = "all";
let selectedCategories = new Set(CATEGORY_ORDER);  // 預設全選

// 事件資料庫分頁
let dbPage = 1;
let dbPageSize = 20;

// ─── localStorage 小工具 ───
const LS = {
  get(k, fallback) {
    try { const v = localStorage.getItem(k); return v === null ? fallback : v; }
    catch { return fallback; }
  },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
};

// ─── 精選指標 ───
const METRICS = [
  { id: "importance", label: "重要度",     hint: "LLM 對事件影響力的評分（0–10）" },
  { id: "mention",    label: "報導熱度",   hint: "同一件事被多少篇報導提到" },
  { id: "diversity",  label: "來源多樣性", hint: "跨越幾家媒體、幾種來源類型" },
  { id: "recency",    label: "時效性",     hint: "越接近區間最新一天分數越高" },
  { id: "entity",     label: "主體聲量",   hint: "事件主角在這段期間跨幾個事件出現" },
  { id: "taiwan",     label: "台灣相關",   hint: "台灣媒體報導，或內容提到台灣" },
  { id: "opensource", label: "開源熱度",   hint: "GitHub / HuggingFace 星數、下載、按讚" },
  { id: "depth",      label: "深度內容",   hint: "有完整內文可讀，適合放進電子報" },
];
const METRIC_IDS = METRICS.map((m) => m.id);
const DEFAULT_METRICS = ["importance", "mention"];

let selectedMetrics = new Set(
  (LS.get("ainews_metrics", DEFAULT_METRICS.join(","))
    .split(",")
    .map((s) => s.trim())
    .filter((s) => METRIC_IDS.includes(s))),
);
if (!selectedMetrics.size) selectedMetrics = new Set(DEFAULT_METRICS);

let picksCount = Number(LS.get("ainews_picks_count", "6")) || 6;
let osCollapsed = LS.get("ainews_os_collapsed", "0") === "1";
let picksPanelCollapsed = LS.get("ainews_picks_panel_collapsed", "0") === "1";

// ─── 報表匯出：使用者勾選的事件 ───
const exportSelected = new Map();   // event_id → event 物件
let currentById = new Map();        // 目前載入事件的 id → event 查找表
let scoreById = new Map();          // event key → { total, parts }

function eventKey(ev) {
  return ev.event_id || `${ev.title || ""}|${(ev.sources || [])[0]?.url || ""}`;
}
function isPicked(ev) {
  return exportSelected.has(eventKey(ev));
}
function pickBoxHtml(ev) {
  const k = eventKey(ev);
  return `
    <label class="pick-check" onclick="event.stopPropagation()">
      <input type="checkbox" class="export-check" data-eid="${escapeHtml(k)}" ${isPicked(ev) ? "checked" : ""} />
      <span>加入電子報</span>
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
const catMeta  = (cid) => CATEGORIES[cid] || FALLBACK_CAT;
const catColor = (cid) => catMeta(cid).color;
const catLabel = (cid) => catMeta(cid).label;
const catIcon  = (cid) => ICONS[cid] || ICONS._default;

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
  const newest = dates[0];
  const oldest = dates[dates.length - 1];
  return `${fmtDateShort(oldest)} ~ ${fmtDateShort(newest)}`;
}
// YYYY-MM-DD ± n 天
function shiftDate(ymd, days) {
  const [y, m, d] = String(ymd).split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}
function dayDiff(a, b) {   // a - b，單位：天
  const t = (s) => { const [y, m, d] = String(s).split("-").map(Number); return Date.UTC(y, m - 1, d); };
  return Math.round((t(a) - t(b)) / 86400000);
}

// 過濾：依目前選的分類（未知分類一律保留，避免資料憑空消失）
function applyInterestFilter(events) {
  if (selectedCategories.size === 0) return events;
  return events.filter((ev) => {
    const cid = ev.category || "";
    if (!CATEGORIES[cid]) return true;
    return selectedCategories.has(cid);
  });
}

// ─── 資料查詢 ───
async function loadDates() {
  return dataSource.loadDates();
}

// 直接用日期區間查（不再只抓「有資料的 N 天」），
// 這樣指定範圍內的每一天、每一則事件都會被列出來。
async function loadEventsInRange(start, end) {
  const events = await dataSource.loadEvents(start, end);
  events.sort((a, b) => {
    const dd = String(b.date || "").localeCompare(String(a.date || ""));
    if (dd !== 0) return dd;
    const di = (b.importance || 0) - (a.importance || 0);
    if (di !== 0) return di;
    return (b.mention_count || 0) - (a.mention_count || 0);
  });
  return events;
}

// ─── Interest filter chips ───
function renderInterestChips() {
  $interestChips.innerHTML = CATEGORY_ORDER.map((cid) => {
    const active = selectedCategories.has(cid);
    const color = catColor(cid);
    return `
      <button type="button" class="chip ${active ? "active" : ""}" data-cid="${cid}"
              style="${active ? `background:${color};` : `color:${color};`}">
        ${catIcon(cid)}<span>${catLabel(cid)}</span>
      </button>
    `;
  }).join("");
  $interestChips.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const cid = btn.dataset.cid;
      if (selectedCategories.has(cid)) selectedCategories.delete(cid);
      else selectedCategories.add(cid);
      dbPage = 1;
      renderInterestChips();
      renderAll();
    });
  });
}

// ─── 精選：多指標評分 ───
function _entityKey(s) {
  return String(s || "").trim().toLowerCase().replace(/[\s"'()（）\-_、,，。.]/g, "");
}
function parseCount(v) {
  if (typeof v === "number") return v;
  const s = String(v || "").trim().toLowerCase().replace(/,/g, "");
  if (!s) return 0;
  const m = s.match(/^([\d.]+)\s*([km])?/);
  if (!m) return 0;
  const n = parseFloat(m[1]) || 0;
  return m[2] === "k" ? n * 1e3 : m[2] === "m" ? n * 1e6 : n;
}
function osRaw(ev) {
  let v = 0;
  for (const s of ev.sources || []) {
    if (!s.is_opensource) continue;
    v = Math.max(v, parseCount(s.stars), parseCount(s.pulls), parseCount(s.downloads),
                    parseCount(s.likes), parseCount(s.upvotes), 1);
  }
  return v > 0 ? Math.log10(1 + v) : 0;
}

// 針對目前這批事件，算出每個指標的原始值 → 正規化 0~1 → 依勾選的指標平均
function computeScores(events) {
  const entityCount = new Map();
  for (const ev of events) {
    const seen = new Set();
    for (const w of ev.who || []) {
      const k = _entityKey(w);
      if (!k || k.length < 2 || seen.has(k)) continue;
      seen.add(k);
      entityCount.set(k, (entityCount.get(k) || 0) + 1);
    }
  }
  const dates = [...new Set(events.map((e) => e.date).filter(Boolean))].sort();
  const newest = dates[dates.length - 1] || "";
  const oldest = dates[0] || "";
  const span = Math.max(1, newest && oldest ? dayDiff(newest, oldest) : 1);

  const raws = events.map((ev) => {
    const srcs = ev.sources || [];
    const names = new Set(srcs.map((s) => s.source_name).filter(Boolean));
    const kinds = new Set(srcs.map((s) => s.source_kind).filter(Boolean));
    const text = `${ev.title || ""}${ev.summary || ""}`;
    const entities = (ev.who || []).map((w) => entityCount.get(_entityKey(w)) || 0);
    return {
      importance: Number(ev.importance || 0),
      mention: Math.log2(1 + Number(ev.mention_count || 1)),
      diversity: names.size + kinds.size * 0.5,
      recency: ev.date && newest ? Math.max(0, 1 - dayDiff(newest, ev.date) / span) : 0,
      entity: entities.length ? Math.max(...entities) : 0,
      taiwan: srcs.some((s) => s.source_region === "TW") ? 1 : (/台灣|臺灣/.test(text) ? 0.6 : 0),
      opensource: osRaw(ev),
      depth: Math.min(1, String(ev.full_content || "").length / 1200),
    };
  });

  const max = {};
  for (const id of METRIC_IDS) max[id] = Math.max(0, ...raws.map((r) => r[id]));

  const map = new Map();
  events.forEach((ev, i) => {
    const parts = {};
    for (const id of METRIC_IDS) parts[id] = max[id] > 0 ? raws[i][id] / max[id] : 0;
    const use = selectedMetrics.size ? [...selectedMetrics] : DEFAULT_METRICS;
    const total = use.reduce((sum, id) => sum + (parts[id] || 0), 0) / use.length;
    map.set(eventKey(ev), { total, parts });
  });
  return map;
}

function renderMetricList() {
  $metricList.innerHTML = METRICS.map((m) => {
    const on = selectedMetrics.has(m.id);
    return `
      <button type="button" class="metric-chip ${on ? "on" : ""}" data-mid="${m.id}" title="${escapeHtml(m.hint)}">
        <span class="metric-box" aria-hidden="true"></span>
        <span class="metric-text">
          <span class="metric-name">${escapeHtml(m.label)}</span>
          <span class="metric-hint">${escapeHtml(m.hint)}</span>
        </span>
      </button>`;
  }).join("");
  $metricList.querySelectorAll(".metric-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.mid;
      if (selectedMetrics.has(id)) selectedMetrics.delete(id);
      else selectedMetrics.add(id);
      LS.set("ainews_metrics", [...selectedMetrics].join(","));
      renderMetricList();
      renderTopPicks(currentEvents);
    });
  });
}

// 依目前指標排序後的精選清單
function rankedPicks(events) {
  const pool = applyInterestFilter(events);
  scoreById = computeScores(pool);
  const sorted = [...pool].sort((a, b) => {
    const sa = scoreById.get(eventKey(a))?.total || 0;
    const sb = scoreById.get(eventKey(b))?.total || 0;
    if (sb !== sa) return sb - sa;
    const di = (b.importance || 0) - (a.importance || 0);
    if (di !== 0) return di;
    return (b.mention_count || 0) - (a.mention_count || 0);
  });
  // 只留下真的符合所選指標的事件；若一則都沒有就退回完整排序，避免精選開天窗
  const hit = sorted.filter((ev) => (scoreById.get(eventKey(ev))?.total || 0) > 0);
  return (hit.length ? hit : sorted).slice(0, picksCount);
}

// ─── Top picks ───
function coverHtml(ev) {
  const cover = ev.cover_image || {};
  const tagColor = catColor(ev.category);
  const tag = `
    <div class="cover-tag" style="background:${tagColor}cc">
      ${catIcon(ev.category)}
      <span>${escapeHtml(catLabel(ev.category))}</span>
    </div>
  `;
  const isImage = (cover.kind === "remote" || cover.kind === "local") && cover.url;
  if (isImage) {
    let imgUrl = cover.url;
    // file:// 直接開檔案測試時，把 media/ 或 /media/ 改指向真正的 output/
    if (location.protocol === "file:" && !imgUrl.startsWith("http")) {
      imgUrl = imgUrl.replace(/^\/?media\//, "../output/");
    }
    return `<div class="cover" style="background-image:url('${escapeHtml(imgUrl)}')">${tag}</div>`;
  }
  return `
    <div class="cover-fallback" style="background:linear-gradient(135deg, ${tagColor}, ${tagColor}cc)">
      <div class="fallback-icon">${catIcon(ev.category)}</div>
      ${tag}
    </div>
  `;
}

function scorePillHtml(ev) {
  const s = scoreById.get(eventKey(ev));
  if (!s) return "";
  const use = selectedMetrics.size ? [...selectedMetrics] : DEFAULT_METRICS;
  const tip = use
    .map((id) => `${METRICS.find((m) => m.id === id)?.label || id} ${Math.round((s.parts[id] || 0) * 100)}`)
    .join("　");
  return `<span class="pill pill-score" title="${escapeHtml(tip)}">${ICON_GAUGE} 精選分 ${Math.round(s.total * 100)}</span>`;
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
          ${scorePillHtml(ev)}
          <span class="pill pill-importance">${ICON_STAR} 重要度 ${importance}</span>
          ${mention > 1 ? `<span class="pill pill-mention">${ICON_FIRE} ${mention} 報導</span>` : ""}
          ${pickBoxHtml(ev)}
        </div>
        ${sourceChips ? `<div class="sources">${sourceChips}</div>` : ""}
      </div>
    </article>
  `;
}

let currentPicks = [];

function renderTopPicks(events) {
  currentPicks = rankedPicks(events);
  if (!currentPicks.length) {
    $topPicks.innerHTML = `<div class="empty">您關注的領域中${escapeHtml(rangeWord(currentRange))}暫無事件。</div>`;
    return;
  }
  $topPicks.innerHTML = currentPicks.map(cardHtml).join("");
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

function applyPicksPanelCollapse() {
  if (!$picksLayout || !$pickToggle) return;
  // 收合時整塊面板不佔版面，卡片直接補滿寬度
  $picksLayout.classList.toggle("collapsed", picksPanelCollapsed);
  $pickToggle.setAttribute("aria-expanded", picksPanelCollapsed ? "false" : "true");
  $pickToggle.classList.toggle("is-collapsed", picksPanelCollapsed);
  if ($pickToggleLbl) $pickToggleLbl.textContent = picksPanelCollapsed ? "精選指標" : "收合指標";
}

function applyOsCollapse() {
  $opensource.classList.toggle("collapsed", osCollapsed);
  $osToggle.setAttribute("aria-expanded", osCollapsed ? "false" : "true");
  $osToggle.classList.toggle("is-collapsed", osCollapsed);
}

function renderOpenSource(events) {
  const filtered = applyInterestFilter(events);
  const osEvents = filtered.filter((ev) => (ev.sources || []).some((s) => s.is_opensource));
  if (!osEvents.length) {
    $opensource.innerHTML = `<div class="empty" style="grid-column:1/-1">${escapeHtml(rangeWord(currentRange))}無開源生態事件。</div>`;
  } else {
    osEvents.sort((a, b) => (b.importance || 0) - (a.importance || 0));
    $opensource.innerHTML = osEvents.slice(0, 8).map(osCardHtml).join("");
  }
  applyOsCollapse();
  return osEvents.length;
}

// ─── Database (toolbar + tabs + list + pager) ───
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
        <span class="cat-badge" style="background:${tagColor}">${catIcon(ev.category)}${escapeHtml(catLabel(ev.category))}</span>
        ${ev.date ? `<span class="row-date">${escapeHtml(fmtDateShort(ev.date))}</span>` : ""}
        <span class="pill pill-importance">${ICON_STAR} ${ev.importance || 0}</span>
        ${mention > 1 ? `<span class="pill pill-mention">${mention} 報導</span>` : ""}
        ${pickBoxHtml(ev)}
      </div>
      <div class="row-title">${titleLink}</div>
      <div class="row-summary">${escapeHtml(ev.summary || "")}</div>
    </article>
  `;
}

function renderPager(total) {
  const pages = Math.max(1, Math.ceil(total / dbPageSize));
  if (dbPage > pages) dbPage = pages;
  if (pages <= 1) { $dbPager.innerHTML = ""; return; }

  // 頁碼視窗：目前頁前後各 2 頁
  const from = Math.max(1, Math.min(dbPage - 2, pages - 4));
  const to = Math.min(pages, Math.max(dbPage + 2, 5));
  const nums = [];
  for (let i = from; i <= to; i += 1) {
    nums.push(`<button type="button" class="page-num ${i === dbPage ? "active" : ""}" data-page="${i}">${i}</button>`);
  }

  $dbPager.innerHTML = `
    <button type="button" class="page-btn" data-page="1" ${dbPage === 1 ? "disabled" : ""}>« 第一頁</button>
    <button type="button" class="page-btn" data-page="${dbPage - 1}" ${dbPage === 1 ? "disabled" : ""}>‹ 上一頁</button>
    ${from > 1 ? `<span class="page-gap">…</span>` : ""}
    ${nums.join("")}
    ${to < pages ? `<span class="page-gap">…</span>` : ""}
    <button type="button" class="page-btn" data-page="${dbPage + 1}" ${dbPage === pages ? "disabled" : ""}>下一頁 ›</button>
    <button type="button" class="page-btn" data-page="${pages}" ${dbPage === pages ? "disabled" : ""}>末頁 »</button>
    <span class="page-info">第 ${dbPage} / ${pages} 頁</span>
  `;
  $dbPager.querySelectorAll("button[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = Number(btn.dataset.page);
      if (!p || p === dbPage || btn.disabled) return;
      dbPage = p;
      renderTabsAndList(currentEvents);
      $dbToolbar.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function renderTabsAndList(events) {
  const filtered = applyInterestFilter(events);
  const counts = { all: filtered.length };
  for (const ev of filtered) {
    const cid = CATEGORIES[ev.category] ? ev.category : "_other";
    counts[cid] = (counts[cid] || 0) + 1;
  }
  const visibleCats = CATEGORY_ORDER.filter((cid) => selectedCategories.has(cid) && counts[cid]);
  if (counts._other) visibleCats.push("_other");
  if (activeTab !== "all" && !visibleCats.includes(activeTab)) activeTab = "all";

  const entries = [["all", "全部"], ...visibleCats.map((cid) => [cid, cid === "_other" ? FALLBACK_CAT.label : catLabel(cid)])];
  $tabs.innerHTML = entries.map(([cid, label]) => `
    <button class="tab ${cid === activeTab ? "active" : ""}" data-cat="${cid}">
      ${label}
      <span class="tab-count">${counts[cid] || 0}</span>
    </button>
  `).join("");
  $tabs.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.cat;
      dbPage = 1;
      renderTabsAndList(events);
    });
  });

  const listSrc = activeTab === "all"
    ? filtered
    : filtered.filter((e) => (CATEGORIES[e.category] ? e.category : "_other") === activeTab);

  // 工具列：總數 + 每頁筆數
  const rangeText = rangeStart && rangeEnd
    ? (rangeStart === rangeEnd ? fmtDate(rangeStart) : `${rangeStart} ~ ${rangeEnd}`)
    : "";
  $dbToolbar.innerHTML = `
    <span class="db-count">${escapeHtml(rangeText)} 共 <b>${listSrc.length}</b> 則事件</span>
    <label class="db-size">每頁
      <select id="db-page-size" class="select select-sm">
        ${[10, 20, 50, 100].map((n) => `<option value="${n}" ${n === dbPageSize ? "selected" : ""}>${n} 則</option>`).join("")}
      </select>
    </label>
  `;
  const $size = document.getElementById("db-page-size");
  if ($size) {
    $size.addEventListener("change", (e) => {
      dbPageSize = Number(e.target.value) || 20;
      LS.set("ainews_db_page_size", String(dbPageSize));
      dbPage = 1;
      renderTabsAndList(events);
    });
  }

  if (!listSrc.length) {
    $eventList.innerHTML = `<div class="empty">這個範圍內沒有符合條件的事件。</div>`;
    $dbPager.innerHTML = "";
    return;
  }

  const pages = Math.max(1, Math.ceil(listSrc.length / dbPageSize));
  if (dbPage > pages) dbPage = pages;
  const start = (dbPage - 1) * dbPageSize;
  $eventList.innerHTML = listSrc.slice(start, start + dbPageSize).map(rowHtml).join("");
  renderPager(listSrc.length);
}

// ─── Analytics ───
function renderMetrics(events) {
  const filtered = applyInterestFilter(events);
  const totalDb = filtered.length;
  const catCount = new Set(filtered.map((e) => (CATEGORIES[e.category] ? e.category : "_other"))).size;
  const days = rangeStart && rangeEnd ? dayDiff(rangeEnd, rangeStart) + 1 : currentDates.length;
  const cards = [
    { label: "事件總數",   value: totalDb },
    { label: `${rangeLabel(currentRange)}精選`, value: currentPicks.length },
    { label: "覆蓋分類",   value: catCount },
    { label: "資料區間",   value: `${fmtRange(currentDates)}（${days} 天）` },
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
  // 與「最受關注主體」同一套計數規則：正規化主體名 + 同一事件內只算一次，
  // 兩個區塊的數字才不會互相打架
  const counts = new Map();   // key → { display, n }
  for (const ev of filtered) {
    const seenInThisEvent = new Set();
    for (const w of (ev.who || [])) {
      const k = _entityKey(w);
      if (!k || seenInThisEvent.has(k)) continue;
      seenInThisEvent.add(k);
      if (!counts.has(k)) counts.set(k, { display: String(w).trim(), n: 0 });
      counts.get(k).n += 1;
    }
  }
  const sorted = [...counts.values()]
    .map((v) => [v.display, v.n])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);
  if (!sorted.length) {
    $topEntities.innerHTML = `<div class="empty" style="padding:8px">無資料</div>`;
    return;
  }
  const max = sorted[0][1];
  $topEntities.innerHTML = sorted.map(([k, v]) => hbarRow(k, v, max, "#4f46e5")).join("");
}

// 分類分佈用甜甜圈圖：分類是「整體的組成」，佔比比長度更好讀
function renderCatDist(events) {
  const filtered = applyInterestFilter(events);
  const counts = {};
  for (const ev of filtered) {
    const cid = CATEGORIES[ev.category] ? ev.category : "_other";
    counts[cid] = (counts[cid] || 0) + 1;
  }
  const rows = [...CATEGORY_ORDER, "_other"]
    .filter((cid) => counts[cid])
    .sort((a, b) => counts[b] - counts[a]);
  if (!rows.length) {
    $catDist.innerHTML = `<div class="empty" style="padding:8px">無資料</div>`;
    return;
  }
  const total = rows.reduce((n, cid) => n + counts[cid], 0);
  const R = 54;
  const C = 2 * Math.PI * R;

  let offset = 0;
  const arcs = rows.map((cid) => {
    const n = counts[cid];
    const label = cid === "_other" ? FALLBACK_CAT.label : catLabel(cid);
    const color = cid === "_other" ? FALLBACK_CAT.color : catColor(cid);
    const len = (n / total) * C;
    // 每段之間留 1.5 的縫；整圈只有一段時不留，避免圓環斷開
    const gap = rows.length > 1 ? Math.min(1.5, len / 2) : 0;
    const seg = Math.max(0, len - gap);
    const arc = `
      <circle class="donut-arc" r="${R}" cx="70" cy="70"
        fill="none" stroke="${color}" stroke-width="20"
        stroke-dasharray="${seg} ${C - seg}"
        stroke-dashoffset="${-offset}">
        <title>${escapeHtml(label)}：${n} 則（${Math.round((n / total) * 100)}%）</title>
      </circle>
    `;
    offset += len;
    return arc;
  }).join("");

  const legend = rows.map((cid) => {
    const n = counts[cid];
    const label = cid === "_other" ? FALLBACK_CAT.label : catLabel(cid);
    const color = cid === "_other" ? FALLBACK_CAT.color : catColor(cid);
    return `
      <div class="donut-legend-row">
        <span class="donut-swatch" style="background:${color}"></span>
        <span class="donut-legend-label">${escapeHtml(label)}</span>
        <span class="donut-legend-pct">${Math.round((n / total) * 100)}%</span>
        <span class="donut-legend-count">${n}</span>
      </div>
    `;
  }).join("");

  $catDist.innerHTML = `
    <div class="donut-wrap">
      <div class="donut-chart">
        <svg viewBox="0 0 140 140" role="img" aria-label="事件分類分佈">
          <g transform="rotate(-90 70 70)">${arcs}</g>
        </svg>
        <div class="donut-center">
          <div class="donut-total">${total}</div>
          <div class="donut-total-label">則事件</div>
        </div>
      </div>
      <div class="donut-legend">${legend}</div>
    </div>
  `;
}

// ─── 電子報匯出列（浮動工具列 + 設定） ───
function ensureExportBar() {
  if (document.getElementById("export-bar")) return;
  const cfg = getNewsletterConfig();
  const bar = document.createElement("div");
  bar.id = "export-bar";
  bar.className = "export-bar hidden";
  bar.innerHTML = `
    <div class="export-row">
      <span class="export-count">已選 <b id="export-n">0</b> 則</span>
      <button id="export-cfg" class="export-btn export-btn-ghost" type="button" title="電子報頁首設定">版面設定</button>
      <button id="export-clear" class="export-btn export-btn-ghost" type="button">清空</button>
      <button id="export-go" class="export-btn export-btn-primary" type="button">產生電子報 PDF</button>
    </div>
    <div id="export-cfg-panel" class="export-cfg hidden">
      <label>刊名<input id="cfg-title" type="text" value="${escapeHtml(cfg.title)}" placeholder="洞悉AI雙週報" /></label>
      <label>期別<input id="cfg-issue" type="text" value="${escapeHtml(cfg.issue)}" placeholder="第0014期" /></label>
      <label>日期<input id="cfg-date" type="text" value="${escapeHtml(cfg.dateLabel)}" placeholder="留空＝自動用最新日期" /></label>
    </div>
  `;
  document.body.appendChild(bar);

  document.getElementById("export-clear").addEventListener("click", () => {
    exportSelected.clear();
    document.querySelectorAll(".export-check").forEach((cb) => { cb.checked = false; });
    updateExportBar();
  });
  document.getElementById("export-cfg").addEventListener("click", () => {
    document.getElementById("export-cfg-panel").classList.toggle("hidden");
  });
  for (const [id, key] of [["cfg-title", "title"], ["cfg-issue", "issue"], ["cfg-date", "dateLabel"]]) {
    document.getElementById(id).addEventListener("change", (e) => {
      saveNewsletterConfig({ [key]: e.target.value.trim() });
    });
  }
  document.getElementById("export-go").addEventListener("click", () => {
    exportEventsToPdf([...exportSelected.values()]);
  });

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

function syncExportChecks() {
  document.querySelectorAll(".export-check").forEach((cb) => {
    cb.checked = exportSelected.has(cb.dataset.eid);
  });
}

// ─── Orchestration ───
function updateSectionTitles() {
  const rl = rangeLabel(currentRange);
  if ($topPicksTitle) $topPicksTitle.textContent = `${rl}精選`;
  if ($osTitle)       $osTitle.textContent       = `開源生態與模型觀測站（${rl}）`;
  if ($metricsTitle)  $metricsTitle.textContent  = `${rl} AI 局勢數據看板`;
}

function updateRangeHint() {
  if (!$rangeHint) return;
  if (!rangeStart || !rangeEnd) { $rangeHint.textContent = ""; return; }
  const days = dayDiff(rangeEnd, rangeStart) + 1;
  $rangeHint.textContent = days === 1
    ? fmtDate(rangeEnd)
    : `${rangeStart} ~ ${rangeEnd}（${days} 天，${currentDates.length} 天有資料）`;
}

function renderAll() {
  updateSectionTitles();
  updateRangeHint();
  renderTopPicks(currentEvents);
  renderOpenSource(currentEvents);
  renderTabsAndList(currentEvents);
  renderMetrics(currentEvents);
  renderTopEntities(currentEvents);
  renderCatDist(currentEvents);
  syncExportChecks();
}

async function showRange(days) {
  currentRange = days;
  // 以「最新有資料的日期」為基準往回推 N 個日曆日
  const anchor = availableDates[0];
  rangeEnd = anchor;
  rangeStart = shiftDate(anchor, -(days - 1));

  $topPicks.innerHTML = `<div class="loading"><div class="spinner"></div><div>讀取中…</div></div>`;
  $opensource.innerHTML = "";
  $eventList.innerHTML = "";
  $dbPager.innerHTML = "";
  $dbToolbar.innerHTML = "";
  $metrics.innerHTML = "";
  $topEntities.innerHTML = "";
  $catDist.innerHTML = "";
  updateSectionTitles();
  updateRangeHint();

  try {
    currentEvents = await loadEventsInRange(rangeStart, rangeEnd);
    currentDates = [...new Set(currentEvents.map((e) => e.date).filter(Boolean))].sort().reverse();
    currentById = new Map(currentEvents.map((ev) => [eventKey(ev), ev]));
    for (const id of [...exportSelected.keys()]) {
      if (currentById.has(id)) exportSelected.set(id, currentById.get(id));
    }
    activeTab = "all";
    dbPage = 1;
    renderAll();
    updateExportBar();
  } catch (err) {
    console.error(err);
    $topPicks.innerHTML = `<div class="empty">讀取失敗：${escapeHtml(err.message || err)}</div>`;
  }
}

function wireControls() {
  // 精選則數
  $picksCount.value = String(picksCount);
  $picksCount.addEventListener("change", (e) => {
    picksCount = Number(e.target.value) || 6;
    LS.set("ainews_picks_count", String(picksCount));
    renderTopPicks(currentEvents);
    renderMetrics(currentEvents);
    syncExportChecks();
  });

  $metricReset.addEventListener("click", () => {
    selectedMetrics = new Set(DEFAULT_METRICS);
    LS.set("ainews_metrics", DEFAULT_METRICS.join(","));
    renderMetricList();
    renderTopPicks(currentEvents);
    syncExportChecks();
  });

  $metricAddAll.addEventListener("click", () => {
    for (const ev of currentPicks) exportSelected.set(eventKey(ev), ev);
    syncExportChecks();
    updateExportBar();
  });

  // 精選指標面板收合
  $pickToggle.addEventListener("click", () => {
    picksPanelCollapsed = !picksPanelCollapsed;
    LS.set("ainews_picks_panel_collapsed", picksPanelCollapsed ? "1" : "0");
    applyPicksPanelCollapse();
  });

  // 開源區收合
  $osToggle.addEventListener("click", () => {
    osCollapsed = !osCollapsed;
    LS.set("ainews_os_collapsed", osCollapsed ? "1" : "0");
    applyOsCollapse();
  });

  $rangeSelect.addEventListener("change", (e) => showRange(Number(e.target.value) || 1));
}

async function main() {
  try {
    dbPageSize = Number(LS.get("ainews_db_page_size", "20")) || 20;
    ensureExportBar();
    renderInterestChips();
    renderMetricList();
    wireControls();
    applyOsCollapse();
    applyPicksPanelCollapse();

    dataSource = await createDataSource();
    availableDates = await loadDates();
    if (!availableDates.length) {
      $topPicks.innerHTML = `<div class="empty">Firestore 還沒有資料。先跑 <code>scripts/migrate_legacy.py</code> 或等今日 cron 跑完。</div>`;
      return;
    }
    await showRange(Number($rangeSelect.value) || 1);
  } catch (err) {
    console.error(err);
    $topPicks.innerHTML = `<div class="empty">初始化失敗：${escapeHtml(err.message || err)}<br>請確認 Firestore Rules 是否允許 public read。</div>`;
  }
}

main();
