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

// orderBy 仍用於 daily_summary（單欄位排序不需要複合索引）

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
const $dateSelect = document.getElementById("date-select");
const $metrics    = document.getElementById("metrics");
const $bar        = document.getElementById("bar");
const $topPicks   = document.getElementById("top-picks");
const $tabs       = document.getElementById("category-tabs");
const $eventList  = document.getElementById("event-list");

let currentDate = null;
let currentEvents = [];
let activeCategory = "all";

// ─── helpers ───
const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

const catColor = (cid) => CATEGORIES[cid]?.color ?? CATEGORIES.uncategorized.color;
const catLabel = (cid) => CATEGORIES[cid]?.label ?? "未分類";

function fmtDate(s) {
  // "2026-05-21" → "2026/05/21 (週四)"
  if (!s) return "";
  const [y, m, d] = s.split("-");
  const dt = new Date(Number(y), Number(m) - 1, Number(d));
  const weekday = ["日","一","二","三","四","五","六"][dt.getDay()];
  return `${y}/${m}/${d} (週${weekday})`;
}

// ─── load dates ───
async function loadDates() {
  const snap = await getDocs(query(collection(db, "daily_summary"), orderBy("date", "desc")));
  const dates = snap.docs.map((d) => d.id);
  $dateSelect.innerHTML = dates
    .map((d) => `<option value="${d}">${fmtDate(d)}</option>`)
    .join("");
  return dates;
}

// ─── load events for a date ───
async function loadEvents(date) {
  // 只用 where 避免複合索引；單日 ~125 筆內，在 client 排序很快
  const snap = await getDocs(
    query(collection(db, "events"), where("date", "==", date)),
  );
  const events = snap.docs.map((d) => d.data());
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

// ─── renderers ───
function renderMetrics(summary, events) {
  if (!summary) {
    $metrics.innerHTML = "";
    return;
  }
  const topCount = events.filter((e) => e.is_top).length;
  const catCount = Object.keys(summary.by_category_label || {}).length;
  const cards = [
    { label: "事件總數",     value: summary.total_db ?? events.length },
    { label: "今日精選",     value: topCount },
    { label: "覆蓋分類",     value: catCount },
    { label: "資料更新",     value: fmtDate(summary.date) },
  ];
  $metrics.innerHTML = cards
    .map((c) => `
      <div class="metric">
        <div class="metric-label">${escapeHtml(c.label)}</div>
        <div class="metric-value">${escapeHtml(c.value)}</div>
      </div>
    `)
    .join("");
}

function renderBar(events) {
  const counts = {};
  for (const ev of events) {
    const cid = ev.category || "uncategorized";
    counts[cid] = (counts[cid] || 0) + 1;
  }
  const total = events.length || 1;
  const order = ["tech_research","industry_business","hardware_infra","products_apps","policy_society","uncategorized"]
    .filter((cid) => counts[cid]);

  const segs = order.map((cid) => {
    const w = (counts[cid] / total) * 100;
    return `<div class="bar-seg" style="width:${w}%;background:${catColor(cid)}" title="${catLabel(cid)} ${counts[cid]}"></div>`;
  }).join("");

  const legend = order.map((cid) => `
    <span><span class="dot" style="background:${catColor(cid)}"></span>${catLabel(cid)} ${counts[cid]}</span>
  `).join("");

  $bar.innerHTML = `
    <div class="bar-track">${segs}</div>
    <div class="bar-legend">${legend}</div>
  `;
}

function coverHtml(ev) {
  const cover = ev.cover_image || {};
  const tagColor = catColor(ev.category);
  const tag = `
    <div class="cover-tag" style="background:${tagColor}cc">
      ${ICONS[ev.category] || ICONS.uncategorized}
      <span>${escapeHtml(catLabel(ev.category))}</span>
    </div>
  `;
  if (cover.kind === "remote" && cover.url) {
    return `<div class="cover" style="background-image:url('${escapeHtml(cover.url)}')">${tag}</div>`;
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
        </div>
        ${sourceChips ? `<div class="sources">${sourceChips}</div>` : ""}
      </div>
    </article>
  `;
}

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
      </div>
      <div class="row-title">${titleLink}</div>
      <div class="row-summary">${escapeHtml(ev.summary || "")}</div>
    </article>
  `;
}

function renderTopPicks(events) {
  const tops = events.filter((e) => e.is_top);
  if (!tops.length) {
    $topPicks.innerHTML = `<div class="empty">這一天沒有精選事件。</div>`;
    return;
  }
  $topPicks.innerHTML = tops.map(cardHtml).join("");
}

function renderTabs(events) {
  const counts = { all: events.length };
  for (const ev of events) {
    const cid = ev.category || "uncategorized";
    counts[cid] = (counts[cid] || 0) + 1;
  }
  const entries = [
    ["all", "全部"],
    ...Object.entries(CATEGORIES)
      .filter(([cid]) => counts[cid])
      .map(([cid, meta]) => [cid, meta.label]),
  ];
  $tabs.innerHTML = entries.map(([cid, label]) => `
    <button class="tab ${cid === activeCategory ? "active" : ""}" data-cat="${cid}">
      ${label}
      <span class="tab-count">${counts[cid] || 0}</span>
    </button>
  `).join("");

  $tabs.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeCategory = btn.dataset.cat;
      renderTabs(events);
      renderList(events);
    });
  });
}

function renderList(events) {
  const filtered = activeCategory === "all"
    ? events
    : events.filter((e) => (e.category || "uncategorized") === activeCategory);
  if (!filtered.length) {
    $eventList.innerHTML = `<div class="empty">這個分類沒有事件。</div>`;
    return;
  }
  $eventList.innerHTML = filtered.map(rowHtml).join("");
}

// ─── orchestration ───
async function showDate(date) {
  currentDate = date;
  $topPicks.innerHTML = `<div class="loading"><div class="spinner"></div><div>讀取中…</div></div>`;
  $eventList.innerHTML = "";
  $metrics.innerHTML = "";
  $bar.innerHTML = "";

  try {
    const [events, summary] = await Promise.all([loadEvents(date), loadSummary(date)]);
    currentEvents = events;
    activeCategory = "all";
    renderMetrics(summary, events);
    renderBar(events);
    renderTopPicks(events);
    renderTabs(events);
    renderList(events);
  } catch (err) {
    console.error(err);
    $topPicks.innerHTML = `<div class="empty">讀取失敗：${escapeHtml(err.message || err)}</div>`;
  }
}

async function main() {
  try {
    const dates = await loadDates();
    if (!dates.length) {
      $topPicks.innerHTML = `<div class="empty">Firestore 還沒有資料。先跑 <code>scripts/migrate_legacy.py</code> 或等今日 cron 跑完。</div>`;
      return;
    }
    $dateSelect.addEventListener("change", (e) => showDate(e.target.value));
    await showDate(dates[0]);
  } catch (err) {
    console.error(err);
    $topPicks.innerHTML = `<div class="empty">初始化失敗：${escapeHtml(err.message || err)}<br>請確認 Firestore Rules 是否允許 public read。</div>`;
  }
}

main();
