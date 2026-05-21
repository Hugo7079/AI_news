"""
AI 事件每日簡報 — Streamlit UI（事件中心版）
============================================

執行：
    streamlit run app_ainews.py

事件模型：
  ‣ 每張卡片 = 一個事件（人事時地物 + 摘要）
  ‣ 卡片下方可展開「證據來源」list — 多篇報導同一事件時這裡會列出 N 條
  ‣ 火焰徽章顯示被報導次數，反映影響力
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import pandas as pd

import streamlit as st

from config import CATEGORIES, OUTPUT_DIR
from ui_assets import (
    GLOBAL_CSS, CATEGORY_COLORS, FLAME_SVG,
    category_chip, cover_html, mention_badge_html,
    render_5w1h, render_sources,
)


# Streamlit Cloud：把 st.secrets 攤到環境變數，讓 pipeline / cover_image 可讀
def _bootstrap_secrets() -> None:
    try:
        for key in ("HF_TOKEN", "AINEWS_LLM_API_KEY", "AINEWS_LLM_BASE_URL",
                    "AINEWS_LLM_MODEL", "AINEWS_LLM_TIMEOUT"):
            if key in st.secrets and not os.getenv(key):
                os.environ[key] = str(st.secrets[key])
    except Exception:
        pass


_bootstrap_secrets()


st.set_page_config(
    page_title="AI 事件每日簡報",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# 資料載入
# ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_json(path_str: str) -> dict:
    with open(path_str, encoding="utf-8") as f:
        return json.load(f)


def list_history() -> list[Path]:
    return sorted(OUTPUT_DIR.glob("*_AI事件_資料庫.json"), reverse=True)


history_files = list_history()
date_options = [f.stem.replace("_AI事件_資料庫", "") for f in history_files[:30]]


def load_merged_top_events(selected_date: str, date_options: list[str], days: int = 3) -> list[dict]:
    """載入選定日期及前幾天（預設3天）的精選事件並去重。"""
    if not date_options or selected_date not in date_options:
        return []
    idx = date_options.index(selected_date)
    merged_events = []
    seen_titles = set()
    seen_ids = set()
    
    for i in range(idx, min(idx + days, len(date_options))):
        date_str = date_options[i]
        top_path = OUTPUT_DIR / f"{date_str}_AI事件_精選.json"
        if top_path.exists():
            try:
                with open(top_path, encoding="utf-8") as f:
                    day_data = json.load(f)
                day_events = day_data.get("events", []) or day_data.get("top_picks", []) or []
                for ev in day_events:
                    title = ev.get("title", "").strip()
                    ev_id = ev.get("id", "")
                    if not title:
                        continue
                    # 進行歸一化去重
                    norm_title = title.lower().replace(" ", "").replace("　", "")
                    if norm_title not in seen_titles and (not ev_id or ev_id not in seen_ids):
                        seen_titles.add(norm_title)
                        if ev_id:
                            seen_ids.add(ev_id)
                        # 保留副本並注入來源日期
                        ev_copy = dict(ev)
                        ev_copy["source_date"] = date_str
                        merged_events.append(ev_copy)
            except Exception:
                pass
    return merged_events


# ─── 側欄 ───
with st.sidebar:
    st.markdown("### 系統設定")
    selected_date = st.selectbox(
        "選擇日期",
        options=date_options or ["（尚無資料）"],
        index=0,
    )
    st.divider()

    st.markdown("### 即時爬搜與分析")
    days = st.slider("抓近幾天", 1, 14, 1)
    only_kinds = st.multiselect(
        "來源類型",
        options=["media", "vendor", "community", "podcast"],
        default=[],
        help="留空 = 全部；開源生態 (HF/GH/Ollama/OpenRouter) 永遠包含",
    )
    enable_google = st.checkbox("啟用 Google News 即時搜尋", value=True)
    run_btn = st.button("開始爬搜", type="primary", use_container_width=True)


# ─── 觸發 pipeline 或讀歷史 ───
db_data: dict | None = None
top_data: dict | None = None

if run_btn:
    from pipeline import run
    with st.spinner("執行中...抓 RSS → 開源生態 → LLM 抽事件 → 合併 → 封面圖"):
        result = run(
            days_back=days,
            enable_google_news=enable_google,
            only_kinds=set(only_kinds) if only_kinds else None,
        )
    _load_json.clear()
    db_data = _load_json(result["output_db_json"])
    if Path(result["output_json"]).exists():
        top_data = _load_json(result["output_json"])
    # 重新整理歷史清單與日期選項，以載入最新結果
    history_files = list_history()
    date_options = [f.stem.replace("_AI事件_資料庫", "") for f in history_files[:30]]
    if date_options:
        selected_date = date_options[0]
    st.success(f"完成。資料庫 {result['total_db']} 個事件，精選 {result['total_top']}")
elif date_options and selected_date != "（尚無資料）":
    db_path = OUTPUT_DIR / f"{selected_date}_AI事件_資料庫.json"
    top_path = OUTPUT_DIR / f"{selected_date}_AI事件_精選.json"
    if db_path.exists():
        db_data = _load_json(str(db_path))
    if top_path.exists():
        top_data = _load_json(str(top_path))


# ─── Hero header ───
st.markdown(
    """
    <div class="ai-hero">
      <div style="width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg,#4f46e5,#0891b2);
                   display:flex;align-items:center;justify-content:center;color:white;">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="26" height="26"
             fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/>
          <path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>
        </svg>
      </div>
      <div>
        <div class="ai-hero-title">AI 事件每日簡報</div>
        <div class="ai-hero-sub">以「事件」為單位整理 — 新聞是證據來源，不是版面主角</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


if not db_data:
    st.info("尚無資料。從側欄按「開始爬搜」或選一份歷史結果。")
    st.stop()


# ─── 關注領域過濾器 (Persona Interest Filter) ───
st.markdown(
    """
    <div style="margin-top: 15px; margin-bottom: 5px; display: flex; align-items: center; gap: 8px;">
      <div style="width: 20px; height: 20px; color: #4f46e5; display: inline-flex; align-items: center;">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="18" height="18">
          <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
        </svg>
      </div>
      <span style="font-size: 1.05rem; font-weight: 800; color: #0f172a; font-family: 'Outfit', sans-serif;">客製化簡報視角 / 您的關注領域 (Your AI Interests)</span>
    </div>
    <div style="font-size: 0.82rem; color: #64748b; margin-bottom: 12px; line-height: 1.4;">
      請點擊選擇或移除您有興趣的 AI 領域。系統將即時動態過濾下方所有區塊，僅呈現與您的關注領域高度關聯的內容。
    </div>
    """,
    unsafe_allow_html=True
)

selected_categories = st.multiselect(
    label="選擇關注領域 (Select Interest Fields)",
    options=list(CATEGORIES.keys()),
    default=list(CATEGORIES.keys()),
    format_func=lambda x: CATEGORIES[x]["label"],
    label_visibility="collapsed"
)

# 避免全部清空導致完全空白的 Fallback
if not selected_categories:
    st.info("提示：您目前沒有選擇任何領域，系統已預設為您展示所有領域的新聞。")
    filtered_categories = list(CATEGORIES.keys())
else:
    filtered_categories = selected_categories


# ─── 取資料與個人化過濾 ───
events: list[dict] = db_data.get("events", []) or db_data.get("items", [])

# 載入並合併多日精選項目
raw_top_events = load_merged_top_events(selected_date, date_options, days=3)
if not raw_top_events and top_data:
    raw_top_events = top_data.get("events", []) or top_data.get("top_picks", []) or []

# 進行關注領域過濾
filtered_events = [ev for ev in events if ev.get("category") in filtered_categories]
filtered_top_events = [ev for ev in raw_top_events if ev.get("category") in filtered_categories]

# 計算過濾後事件統計
by_cat: dict[str, int] = {}
total_sources = 0
for ev in filtered_events:
    cid = ev.get("category", "uncategorized")
    by_cat[cid] = by_cat.get(cid, 0) + 1
    total_sources += ev.get("mention_count", 1)


# ─── SVG 與開源生態等 UI 圖示/資源定義 ───
STAR_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="11" height="11" '
    'fill="currentColor" stroke="none">'
    '<path d="M12 2 14.91 8.84 22 9.27l-5.45 4.73L18.18 21 12 17.27 5.82 21l1.63-6.99L2 9.27l7.09-.43L12 2z"/>'
    '</svg>'
)

DOWNLOAD_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="10" height="10" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'
    '</svg>'
)

UPVOTE_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="10" height="10" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<polyline points="18 15 12 9 6 15"/>'
    '</svg>'
)

CTX_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="10" height="10" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'
    '</svg>'
)

TAG_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="10" height="10" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>'
    '</svg>'
)


def render_os_badges(ev: dict) -> str:
    """彙整事件中所有開源生態來源的指標。"""
    os_sources = [s for s in ev.get("sources", []) if s.get("is_opensource")]
    if not os_sources:
        return ""

    stars_val = ""
    pulls_val = ""
    downloads_val = 0
    likes_val = 0
    upvotes_val = 0
    context_val = 0
    task_val = ""

    for s in os_sources:
        if s.get("stars") and not stars_val:
            stars_val = str(s["stars"])
        if s.get("pulls") and not pulls_val:
            pulls_val = str(s["pulls"])
        if s.get("downloads"):
            try:
                downloads_val = max(downloads_val, int(s["downloads"]))
            except Exception:
                pass
        if s.get("likes"):
            try:
                likes_val = max(likes_val, int(s["likes"]))
            except Exception:
                pass
        if s.get("upvotes"):
            try:
                upvotes_val = max(upvotes_val, int(s["upvotes"]))
            except Exception:
                pass
        if s.get("context_length"):
            try:
                context_val = max(context_val, int(s["context_length"]))
            except Exception:
                pass
        if s.get("task") and not task_val:
            task_val = str(s["task"])

    badges = []
    if stars_val:
        badges.append(f'<span class="glow-badge">{STAR_SVG}{stars_val} stars</span>')
    if pulls_val:
        badges.append(f'<span class="glow-badge">{DOWNLOAD_ICON}{pulls_val} pulls</span>')
    if downloads_val > 0:
        badges.append(f'<span class="glow-badge">{DOWNLOAD_ICON}{downloads_val:,} dl</span>')
    if likes_val > 0:
        badges.append(f'<span class="glow-badge-alt">{UPVOTE_ICON}{likes_val:,} likes</span>')
    if upvotes_val > 0:
        badges.append(f'<span class="glow-badge-alt">{UPVOTE_ICON}{upvotes_val} upvotes</span>')
    if context_val > 0:
        ctx_str = f"{context_val//1024}k" if context_val >= 1024 else str(context_val)
        badges.append(f'<span class="glow-badge">{CTX_ICON}Ctx {ctx_str}</span>')
    if task_val:
        badges.append(f'<span class="glow-badge-alt">{TAG_ICON}{task_val}</span>')

    if not badges:
        return ""
    return f'<div style="margin-top:8px; display:flex; flex-wrap:wrap; gap:6px;">{"".join(badges)}</div>'


def render_opensource_card(ev: dict) -> str:
    """開源生態專屬卡片。"""
    os_sources = [s for s in ev.get("sources", []) if s.get("is_opensource")]
    if not os_sources:
        return ""

    source_names = []
    stars_val = ""
    pulls_val = ""
    downloads_val = 0
    likes_val = 0
    upvotes_val = 0
    context_val = 0
    task_val = ""

    for s in os_sources:
        sname = s.get("source_name", "")
        if sname not in source_names:
            source_names.append(sname)
        if s.get("stars") and not stars_val:
            stars_val = str(s["stars"])
        if s.get("pulls") and not pulls_val:
            pulls_val = str(s["pulls"])
        if s.get("downloads"):
            try:
                downloads_val = max(downloads_val, int(s["downloads"]))
            except Exception:
                pass
        if s.get("likes"):
            try:
                likes_val = max(likes_val, int(s["likes"]))
            except Exception:
                pass
        if s.get("upvotes"):
            try:
                upvotes_val = max(upvotes_val, int(s["upvotes"]))
            except Exception:
                pass
        if s.get("context_length"):
            try:
                context_val = max(context_val, int(s["context_length"]))
            except Exception:
                pass
        if s.get("task") and not task_val:
            task_val = str(s["task"])

    src_label = " / ".join(source_names)
    title = ev.get("title", "(無標題)")
    summary = ev.get("summary", "")
    url = ev["sources"][0].get("url", "") if ev.get("sources") else "#"

    badges = []
    if stars_val:
        badges.append(f'<span class="glow-badge">{STAR_SVG}{stars_val} stars</span>')
    if pulls_val:
        badges.append(f'<span class="glow-badge">{DOWNLOAD_ICON}{pulls_val} pulls</span>')
    if downloads_val > 0:
        badges.append(f'<span class="glow-badge">{DOWNLOAD_ICON}{downloads_val:,} dl</span>')
    if likes_val > 0:
        badges.append(f'<span class="glow-badge-alt">{UPVOTE_ICON}{likes_val:,} likes</span>')
    if upvotes_val > 0:
        badges.append(f'<span class="glow-badge-alt">{UPVOTE_ICON}{upvotes_val} upvotes</span>')
    if context_val > 0:
        ctx_str = f"{context_val//1024}k" if context_val >= 1024 else str(context_val)
        badges.append(f'<span class="glow-badge">{CTX_ICON}Ctx {ctx_str}</span>')
    if task_val:
        badges.append(f'<span class="glow-badge-alt">{TAG_ICON}{task_val}</span>')

    badges_html = f'<div class="opensource-stats">{"".join(badges)}</div>' if badges else ""

    code_icon = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="11" height="11" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'
        '</svg>'
    )

    return (
        f'<div class="opensource-card">'
        f'  <div class="opensource-source">{code_icon}{src_label}</div>'
        f'  <div class="opensource-name"><a href="{url}" target="_blank" rel="noopener">{title}</a></div>'
        f'  <div class="opensource-desc">{summary}</div>'
        f'  {badges_html}'
        f'</div>'
    )


# ─── 事件卡片與列表項渲染 ───
def render_event_card(ev: dict) -> str:
    """精選卡片（含封面）。"""
    cid = ev.get("category", "uncategorized")
    clabel = CATEGORIES.get(cid, {}).get("label", "未分類")
    cover = cover_html(ev.get("cover_image"), cid, clabel, variant="card")
    title = ev.get("title", "(無標題)")
    summary = ev.get("summary", "")
    importance = ev.get("importance", 0)
    mention_badge = mention_badge_html(ev.get("mention_count", 1))
    w5h1 = render_5w1h(ev)
    sources_html = render_sources(ev.get("sources", []))
    os_badges = render_os_badges(ev)
    
    # 處理非本日精選的日期徽章標記
    source_date = ev.get("source_date", "")
    date_badge = ""
    if source_date and source_date != selected_date:
        parts = source_date.split("-")
        short_date = f"{parts[1]}/{parts[2]}" if len(parts) == 3 else source_date
        date_badge = f'<span class="ai-date-badge" style="background:rgba(99,102,241,0.1); color:#4f46e5; border:1px solid rgba(99,102,241,0.2); font-size:0.7rem; padding:2px 8px; border-radius:4px; font-weight:700; margin-left:8px;">{short_date} 精選</span>'
        
    return (
        '<article class="ai-pick-card">'
        f'{cover}'
        '<div class="ai-pick-body">'
        f'<div class="ai-pick-title">{title}</div>'
        '<div class="ai-pick-meta">'
        f'<span class="ai-importance">{STAR_SVG}{importance}</span>'
        f'{mention_badge}'
        f'{date_badge}'
        '</div>'
        f'<div class="ai-pick-summary">{summary}</div>'
        f'{os_badges}'
        f'{w5h1}'
        f'{sources_html}'
        '</div>'
        '</article>'
    )


def render_event_row(ev: dict) -> str:
    """分類 tab 內的列表項（含視覺封面）。"""
    cid = ev.get("category", "uncategorized")
    clabel = CATEGORIES.get(cid, {}).get("label", "未分類")
    cover = cover_html(ev.get("cover_image"), cid, clabel, variant="row")
    title = ev.get("title", "(無標題)")
    summary = ev.get("summary", "")
    importance = ev.get("importance", 0)
    chip = category_chip(cid, clabel)
    mention_badge = mention_badge_html(ev.get("mention_count", 1))
    mention_segment = ("&nbsp;" + mention_badge) if mention_badge else ""
    w5h1 = render_5w1h(ev)
    sources_html = render_sources(ev.get("sources", []))
    os_badges = render_os_badges(ev)
    return (
        '<div class="ai-row">'
        f'{cover}'
        '<div>'
        f'<div>{chip}'
        f'<span class="ai-importance" style="margin-left:8px;">{STAR_SVG}{importance}</span>'
        f'{mention_segment}'
        '</div>'
        f'<div class="ai-row-title" style="margin-top:6px;">{title}</div>'
        f'<div class="ai-row-summary">{summary}</div>'
        f'{os_badges}'
        f'{w5h1}'
        f'{sources_html}'
        '</div>'
        '</div>'
    )


# ─── 1. 精選事件 ───
st.markdown(
    '<div class="ai-section-title"><span class="accent"></span>精選事件 (Featured Events)</div>',
    unsafe_allow_html=True,
)
if not filtered_top_events:
    st.info("您關注的領域中今日暫無精選事件。")
else:
    cards = "".join(render_event_card(ev) for ev in filtered_top_events)
    st.markdown(f'<div class="ai-pick-grid">{cards}</div>', unsafe_allow_html=True)


# ─── 2. 本日最受關注事件 ───
trending = sorted(
    [ev for ev in filtered_events if (ev.get("mention_count") or 1) > 1],
    key=lambda x: (x.get("mention_count", 1), x.get("importance", 0)),
    reverse=True,
)[:5]

if trending:
    rows = []
    for rank, ev in enumerate(trending, 1):
        title = ev.get("title", "")
        cnt = ev.get("mention_count", 1)
        cid = ev.get("category", "uncategorized")
        clabel = CATEGORIES.get(cid, {}).get("label", "未分類")
        chip = category_chip(cid, clabel)
        rows.append(
            '<div class="ai-trending-item">'
            f'<div class="ai-trending-rank">{rank:02d}</div>'
            f'<div class="ai-trending-text">{chip}&nbsp;{title}</div>'
            f'<div class="ai-trending-count">{cnt} 篇</div>'
            '</div>'
        )
    st.markdown(
        '<div class="ai-trending">'
        f'<div class="ai-trending-title">{FLAME_SVG}本日最受關注事件（被報導次數）</div>'
        f'<div class="ai-trending-list">{"".join(rows)}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


# ─── 3. 分類瀏覽 ───
st.markdown(
    '<div class="ai-section-title"><span class="accent"></span>分類瀏覽 (Category Browse)</div>',
    unsafe_allow_html=True,
)

# 僅顯示使用者選擇的分類 Tabs，完全隱藏不感興趣的領域
tab_labels = ["全部"] + [CATEGORIES[cid]["label"] for cid in filtered_categories]
tabs = st.tabs(tab_labels)

with tabs[0]:
    if not filtered_events:
        st.info("沒有符合您關注領域的事件報導")
    else:
        sorted_ev = sorted(
            filtered_events,
            key=lambda e: (e.get("importance", 0), e.get("mention_count", 0)),
            reverse=True,
        )
        st.markdown("".join(render_event_row(ev) for ev in sorted_ev),
                    unsafe_allow_html=True)

for tab, cid in zip(tabs[1:], filtered_categories):
    with tab:
        st.caption(CATEGORIES[cid]["desc"])
        sub = [ev for ev in filtered_events if ev.get("category") == cid]
        if not sub:
            st.info("本類別今日沒有事件報導")
            continue
        sub.sort(key=lambda e: (e.get("importance", 0), e.get("mention_count", 0)),
                 reverse=True)
        st.markdown("".join(render_event_row(ev) for ev in sub), unsafe_allow_html=True)


# ─── 4. 今日 AI 局勢數據看板 ───
entity_counts = {}
for ev in filtered_events:
    for w in ev.get("who", []):
        w_norm = w.strip()
        if w_norm:
            entity_counts[w_norm] = entity_counts.get(w_norm, 0) + 1

sorted_entities = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:10]

cat_counts = []
for cid in filtered_categories:
    n = by_cat.get(cid, 0)
    if n > 0:
        cat_counts.append((CATEGORIES[cid]["label"], n))
n_uncat = by_cat.get("uncategorized", 0)
if "uncategorized" in filtered_categories and n_uncat > 0:
    cat_counts.append(("未分類", n_uncat))

st.markdown(
    '<div class="ai-section-title"><span class="accent"></span>今日 AI 局勢數據看板 (Today\'s AI Insights)</div>',
    unsafe_allow_html=True,
)

with st.expander("今日 AI 局勢數據看板 (Today's AI Insights)", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### 熱門被提及主體 (Top Mentioned Entities)")
        if sorted_entities:
            df_entities = pd.DataFrame(sorted_entities, columns=["Entity", "Mentions / 提及次數"]).set_index("Entity")
            st.bar_chart(df_entities, color="#4f46e5")
        else:
            st.info("所選領域中暫無足夠的主體數據")
    with col2:
        st.markdown("##### 事件分類分佈 (Event Category Distribution)")
        if cat_counts:
            df_cats = pd.DataFrame(cat_counts, columns=["Category", "Events / 事件數量"]).set_index("Category")
            st.bar_chart(df_cats, color="#0891b2")
        else:
            st.info("所選領域中暫無分類數據")
            
    # ─── 同步過濾的分類分布條 ───
    total_filtered = len(filtered_events)
    if total_filtered > 0:
        seg_html = []
        legend_html = []
        for cid in filtered_categories:
            n = by_cat.get(cid, 0)
            if n == 0:
                continue
            pct = n / total_filtered * 100
            color = CATEGORY_COLORS.get(cid, "#64748b")
            seg_html.append(
                f'<div class="ai-bar-seg" title="{CATEGORIES[cid]["label"]} {n} 件" '
                f'style="width:{pct:.2f}%; background:{color};"></div>'
            )
            legend_html.append(
                f'<span><span class="dot" style="background:{color};"></span>'
                f'{CATEGORIES[cid]["label"]} <strong>{n}</strong></span>'
            )
        
        st.markdown(
            f"""
            <div class="ai-bar-row" style="margin-top: 20px; padding: 0 10px;">
              <div class="ai-bar-track">{"".join(seg_html)}</div>
              <div class="ai-bar-legend">{"".join(legend_html)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ─── 5. 開源生態與模型觀測站 (Open Source Radar) ───
os_events = [ev for ev in filtered_events if any(s.get("is_opensource") for s in ev.get("sources", []))]

if os_events:
    os_cards = "".join(render_opensource_card(ev) for ev in os_events[:8])
    st.markdown(
        f"""
        <div class="opensource-section">
          <div class="opensource-header">
            <div style="width:36px;height:36px;border-radius:8px;background:rgba(34, 211, 238, 0.15);
                         display:flex;align-items:center;justify-content:center;color:#22d3ee;
                         border: 1px solid rgba(34, 211, 238, 0.3); margin-right: 4px;">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20"
                   fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="12 2 2 7 12 12 22 7 12 2"/>
                <polyline points="2 17 12 22 22 17"/>
                <polyline points="2 12 12 17 22 12"/>
              </svg>
            </div>
            <div class="opensource-title">開源生態與模型觀測站 (Open Source Radar)</div>
          </div>
          <div class="opensource-grid">
            {os_cards}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─── 6. 指標統計數據列 (置底) ───
st.markdown(
    f"""
    <div class="ai-metric-row" style="margin-top: 30px;">
      <div class="ai-metric"><div class="ai-metric-label">日期</div>
        <div class="ai-metric-value">{db_data.get("date","-")}</div></div>
      <div class="ai-metric"><div class="ai-metric-label">關注事件數 / 總數</div>
        <div class="ai-metric-value">{len(filtered_events)} <span style="font-size:1.1rem; color:#94a3b8; font-weight:500;">/ {len(events)}</span></div></div>
      <div class="ai-metric"><div class="ai-metric-label">關注精選數</div>
        <div class="ai-metric-value">{len(filtered_top_events)}</div></div>
      <div class="ai-metric"><div class="ai-metric-label">關注證據來源</div>
        <div class="ai-metric-value">{total_sources}</div></div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ─── Footer ───
st.markdown(
    f"""
    <div style="margin-top:36px;padding-top:18px;border-top:1px solid #e2e8f0;
                color:#94a3b8;font-size:0.78rem;text-align:center;">
      generated {db_data.get("generated_at","")} · 以事件為單位 ·
      資料來源含 HuggingFace / GitHub Trending / Ollama / OpenRouter
    </div>
    """,
    unsafe_allow_html=True,
)
