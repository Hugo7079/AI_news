"""
UI 視覺資產：分類色 / SVG icon / CSS / 圖片解析
======================================================

每個分類用一個 Lucide icon (MIT 授權) — 完全用 SVG, 不放 emoji。
"""

from __future__ import annotations
import base64
from pathlib import Path
from typing import Optional

from config import OUTPUT_DIR


# ─── 配色：5 大類 + uncategorized ───
CATEGORY_COLORS: dict[str, str] = {
    "tech_research":     "#4f46e5",  # indigo
    "industry_business": "#059669",  # emerald
    "hardware_infra":    "#d97706",  # amber
    "products_apps":     "#0891b2",  # cyan
    "policy_society":    "#db2777",  # pink
    "uncategorized":     "#64748b",  # slate
}


# ─── Lucide SVG icons (24×24, currentColor) ───
# 來源 https://lucide.dev — ISC License
CATEGORY_ICONS: dict[str, str] = {
    "tech_research": (
        # atom（原子）— 視覺辨識度高、適合「研究」
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="1"/>'
        '<path d="M20.2 20.2c2.04-2.03.02-7.36-4.5-11.9-4.54-4.52-9.87-6.54-11.9-4.5-2.04 2.03-.02 7.36 4.5 11.9 4.54 4.52 9.87 6.54 11.9 4.5Z"/>'
        '<path d="M15.7 15.7c4.52-4.54 6.54-9.87 4.5-11.9-2.03-2.04-7.36-.02-11.9 4.5-4.52 4.54-6.54 9.87-4.5 11.9 2.03 2.04 7.36.02 11.9-4.5Z"/>'
        '</svg>'
    ),
    "industry_business": (
        # trending-up
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>'
    ),
    "hardware_infra": (
        # cpu
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
        '<path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/>'
        '<path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/></svg>'
    ),
    "products_apps": (
        # app-window
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 4v4"/>'
        '<path d="M2 8h20"/><path d="M6 4v4"/></svg>'
    ),
    "policy_society": (
        # scale
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
        '<path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
        '<path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/></svg>'
    ),
    "uncategorized": (
        # circle-help
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>'
    ),
}


# ─── 全域 CSS（用一次 inject）───
GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Outfit:wght@400;500;600;700;800&display=swap');

:root {
    --radius: 16px;
    --primary: #4f46e5;
    --primary-light: #818cf8;
    --cyan: #0891b2;
    --cyan-light: #22d3ee;
    --background: #f8fafc;
    --text-main: #0f172a;
    --text-muted: #64748b;
}

/* 全域字型套用，排除 Streamlit 的 icon 元素以避免破壞 Material Icons 字型渲染 */
html, body, [data-testid="stAppViewContainer"], .stApp {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* 隱藏 Streamlit 預設 header / footer 留白與背景調優 */
header[data-testid="stHeader"] { background: transparent !important; }
.stApp {
    background-color: var(--background) !important;
}
.block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 1320px; }

/* 標題與標籤字型重設 */
.ai-hero-title, .ai-section-title, .ai-pick-title, .ai-metric-value, .opensource-title {
    font-family: 'Outfit', sans-serif !important;
}

/* Hero Header Banner */
.ai-hero {
    display: flex; align-items: center; gap: 18px;
    padding: 16px 20px;
    background: rgba(255, 255, 255, 0.7);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(226, 232, 240, 0.8);
    border-radius: var(--radius);
    margin-bottom: 24px;
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.02), 0 4px 6px -4px rgba(0, 0, 0, 0.02);
}
.ai-hero-title {
    font-size: 2.1rem; font-weight: 800; letter-spacing: -0.03em;
    background: linear-gradient(135deg, var(--primary), var(--cyan));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.ai-hero-sub { color: var(--text-muted); font-size: 0.98rem; font-weight: 500; margin-top: 2px; }

/* Metric Dashboard */
.ai-metric-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 14px 0 24px; }
@media (max-width: 768px) {
    .ai-metric-row { grid-template-columns: repeat(2, 1fr); }
}
.ai-metric {
    background: rgba(255, 255, 255, 0.8);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(226, 232, 240, 0.8);
    border-radius: var(--radius);
    padding: 18px 20px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02), inset 0 1px 0 0 rgba(255, 255, 255, 0.6);
    transition: transform 0.2s ease;
}
.ai-metric:hover {
    transform: translateY(-2px);
}
.ai-metric-label { color: var(--text-muted); font-size: 0.8rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }
.ai-metric-value { font-size: 1.8rem; font-weight: 800; color: var(--text-main); line-height: 1.1; margin-top: 6px; }

/* 分類分佈條 */
.ai-bar-row { margin: 10px 0 26px; }
.ai-bar-track {
    display: flex; width: 100%; height: 16px; border-radius: 999px; overflow: hidden;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.06), inset 0 0 0 1px #e2e8f0;
    background: #f1f5f9;
}
.ai-bar-seg { height: 100%; transition: width 0.3s ease; }
.ai-bar-legend { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 14px; font-size: 0.88rem; color: #334155; }
.ai-bar-legend .dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; margin-right: 8px; vertical-align: middle; }

/* 區塊標題 */
.ai-section-title {
    display: flex; align-items: center; gap: 10px;
    font-size: 1.3rem; font-weight: 800; color: var(--text-main);
    margin: 36px 0 16px;
    letter-spacing: -0.01em;
}
.ai-section-title .accent { width: 5px; height: 22px; background: linear-gradient(to bottom, var(--primary), var(--cyan)); border-radius: 3px; }

/* 統計分析面板摺疊容器 */
.stExpander {
    background: rgba(255, 255, 255, 0.7) !important;
    border: 1px solid rgba(226, 232, 240, 0.8) !important;
    border-radius: var(--radius) !important;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02) !important;
    overflow: hidden !important;
}

/* 精選卡片網格 (Glassmorphism) */
.ai-pick-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;
}
@media (max-width: 1024px) { .ai-pick-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 680px)  { .ai-pick-grid { grid-template-columns: 1fr; } }

.ai-pick-card {
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(226, 232, 240, 0.8);
    border-radius: var(--radius);
    overflow: hidden; display: flex; flex-direction: column;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.03), 0 2px 4px -2px rgba(0,0,0,0.03), inset 0 1px 0 0 rgba(255, 255, 255, 0.6);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.ai-pick-card:hover {
    transform: translateY(-6px) scale(1.008);
    box-shadow: 0 20px 25px -5px rgba(79, 70, 229, 0.1), 0 8px 10px -6px rgba(79, 70, 229, 0.05);
    border-color: rgba(79, 70, 229, 0.4);
}

/* 封面與 Fallback 晶片插圖 */
.ai-cover {
    width: 100%; aspect-ratio: 16 / 9; background-size: cover; background-position: center;
    position: relative;
    border-bottom: 1px solid rgba(226, 232, 240, 0.4);
}
.ai-cover-fallback {
    width: 100%; aspect-ratio: 16 / 9; display: flex; align-items: center; justify-content: center;
    color: #ffffff; position: relative; overflow: hidden;
    border-bottom: 1px solid rgba(226, 232, 240, 0.4);
}
.ai-cover-fallback::before {
    content: ""; position: absolute;
    width: 160px; height: 160px;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.18) 0%, transparent 70%);
    border-radius: 50%;
    top: -40px; right: -40px;
}
.ai-cover-fallback::after {
    content: ""; position: absolute;
    width: 120px; height: 120px;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.12) 0%, transparent 70%);
    border-radius: 50%;
    bottom: -30px; left: -30px;
}
.fallback-glow-icon {
    filter: drop-shadow(0 0 12px rgba(255, 255, 255, 0.3));
    opacity: 0.9;
    transform: scale(2.4);
    display: inline-flex; align-items: center;
}
.fallback-glow-icon svg { width: 28px; height: 28px; stroke-width: 1.5; }

.ai-cover-tag {
    position: absolute; top: 12px; left: 12px;
    background: rgba(15, 23, 42, 0.82); color: #ffffff;
    padding: 5px 12px; border-radius: 999px; font-size: 0.75rem; font-weight: 600;
    display: inline-flex; align-items: center; gap: 7px; backdrop-filter: blur(6px);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15), inset 0 0.5px 0 0 rgba(255, 255, 255, 0.2);
}
.ai-cover-tag svg { width: 13px; height: 13px; }

/* 卡片與 Row 主體 */
.ai-pick-body { padding: 18px 18px 20px; display: flex; flex-direction: column; gap: 10px; flex: 1; }
.ai-pick-title {
    font-size: 1.08rem; font-weight: 800; color: var(--text-main); line-height: 1.4;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    letter-spacing: -0.01em;
}
.ai-pick-title a { color: inherit; text-decoration: none; }
.ai-pick-title a:hover { color: var(--primary); }
.ai-pick-meta { font-size: 0.8rem; color: var(--text-muted); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

.ai-importance {
    display: inline-flex; align-items: center; gap: 4px;
    background: #f1f5f9; padding: 3px 10px; border-radius: 999px;
    font-weight: 700; color: #1e293b; font-size: 0.75rem;
}
.ai-mention {
    display: inline-flex; align-items: center; gap: 5px;
    background: linear-gradient(135deg, #f97316, #ea580c);
    color: #ffffff; padding: 3px 12px; border-radius: 999px;
    font-weight: 800; font-size: 0.72rem;
    box-shadow: 0 2px 4px rgba(234, 88, 12, 0.2);
}
.ai-mention svg { width: 12px; height: 12px; }

/* 最受關注事件榜 */
.ai-trending {
    background: rgba(255, 255, 255, 0.8);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(226, 232, 240, 0.8);
    border-radius: var(--radius);
    padding: 18px 20px; margin: 4px 0 12px;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02);
}
.ai-trending-title {
    display: flex; align-items: center; gap: 8px;
    font-size: 0.95rem; font-weight: 800; color: var(--text-main);
    margin-bottom: 12px; letter-spacing: 0.02em;
    text-transform: uppercase;
}
.ai-trending-title svg { width: 18px; height: 18px; color: #f97316; }
.ai-trending-list { display: flex; flex-direction: column; gap: 10px; }
.ai-trending-item {
    display: grid; grid-template-columns: 28px 1fr auto; gap: 12px;
    align-items: center; font-size: 0.92rem;
    padding: 6px 8px; border-radius: 8px;
    transition: background-color 0.15s ease;
}
.ai-trending-item:hover {
    background-color: #f1f5f9;
}
.ai-trending-rank {
    font-weight: 900; font-size: 0.95rem; color: #f97316;
    text-align: center;
}
.ai-trending-text { color: #1e293b; line-height: 1.4; font-weight: 500; }
.ai-trending-count {
    background: #fff7ed; color: #ea580c;
    padding: 3px 10px; border-radius: 999px;
    font-size: 0.75rem; font-weight: 800; white-space: nowrap;
    border: 1px solid #ffedd5;
}
.ai-pick-summary {
    color: #334155; font-size: 0.9rem; line-height: 1.6;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}

/* 分類 Tab 列表項 */
.ai-row {
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(226, 232, 240, 0.8);
    border-radius: var(--radius);
    padding: 18px 20px; margin-bottom: 12px;
    display: grid; grid-template-columns: 140px 1fr; gap: 20px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02), inset 0 1px 0 0 rgba(255, 255, 255, 0.6);
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
@media (max-width: 768px) {
    .ai-row { grid-template-columns: 1fr; gap: 16px; }
}
.ai-row:hover {
    border-color: rgba(8, 145, 178, 0.4);
    box-shadow: 0 12px 20px -8px rgba(8, 145, 178, 0.12);
    transform: translateY(-3px);
}
.ai-row-thumb {
    width: 140px; aspect-ratio: 16/9; background-size: cover; background-position: center;
    border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #fff;
    position: relative; overflow: hidden;
    border: 1px solid rgba(226, 232, 240, 0.4);
}
@media (max-width: 768px) {
    .ai-row-thumb { width: 100%; max-width: 240px; }
}
.ai-row-thumb::before {
    content: ""; position: absolute;
    width: 100px; height: 100px;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.15) 0%, transparent 70%);
    border-radius: 50%;
}
.fallback-glow-icon-small {
    filter: drop-shadow(0 0 8px rgba(255, 255, 255, 0.3));
    opacity: 0.85;
    transform: scale(1.6);
    display: inline-flex; align-items: center;
}
.fallback-glow-icon-small svg { width: 22px; height: 22px; stroke-width: 2; }

.ai-row-title { font-size: 1.05rem; font-weight: 700; color: var(--text-main); line-height: 1.4; letter-spacing: -0.01em; }
.ai-row-title a { color: inherit; text-decoration: none; }
.ai-row-title a:hover { color: var(--primary); }
.ai-row-summary { color: #334155; font-size: 0.9rem; line-height: 1.6; margin-top: 6px; }

/* 5W1H 標籤行 */
.ai-5w1h {
    display: flex; flex-wrap: wrap; gap: 8px 12px;
    margin-top: 10px; font-size: 0.78rem; color: #475569;
}
.ai-5w1h .kv { display: inline-flex; align-items: center; gap: 5px; }
.ai-5w1h .k { color: var(--text-muted); font-weight: 700; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.04em; }
.ai-5w1h .v { color: #1e293b; font-weight: 500; }
.ai-5w1h .pill {
    background: #f1f5f9; padding: 2px 10px; border-radius: 6px;
    font-size: 0.75rem; color: #334155; font-weight: 600;
    border: 1px solid #e2e8f0;
}

/* 證據來源摺疊區 */
.ai-sources {
    margin-top: 12px; border-top: 1px dashed #e2e8f0; padding-top: 10px;
}
.ai-sources summary {
    cursor: pointer; font-size: 0.8rem; font-weight: 700; color: var(--text-muted);
    list-style: none; user-select: none;
    display: inline-flex; align-items: center; gap: 6px;
    transition: color 0.15s ease;
}
.ai-sources summary::-webkit-details-marker { display: none; }
.ai-sources summary::before {
    content: "▸"; transition: transform .15s ease; display: inline-block;
}
.ai-sources[open] summary::before { transform: rotate(90deg); }
.ai-sources summary:hover { color: var(--primary); }
.ai-sources ul {
    list-style: none; padding: 10px 0 0 16px; margin: 0;
    display: flex; flex-direction: column; gap: 6px;
}
.ai-sources li {
    font-size: 0.8rem; color: #475569; line-height: 1.5;
    display: flex; flex-wrap: wrap; align-items: center; gap: 4px;
}
.ai-sources li a { color: var(--primary); text-decoration: none; font-weight: 600; }
.ai-sources li a:hover { text-decoration: underline; color: var(--primary-light); }
.ai-sources li .src-name { color: var(--text-muted); margin-right: 6px; font-size: 0.75rem; font-weight: 500; }

/* Category Badge Chip */
.ai-chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px; border-radius: 8px; font-size: 0.72rem; font-weight: 700;
    color: #ffffff; text-transform: uppercase; letter-spacing: 0.04em;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.ai-chip svg { width: 12px; height: 12px; }

/* ─────────────────────────────────────────────────────────────
   開源生態與模型觀測看板 (Open Source Radar) Premium CSS
   ───────────────────────────────────────────────────────────── */
.opensource-section {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    border: 1px solid rgba(51, 65, 85, 0.8);
    border-radius: var(--radius);
    padding: 24px;
    margin: 20px 0 28px;
    color: #f8fafc;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.15), 0 10px 10px -6px rgba(0, 0, 0, 0.1), inset 0 1px 0 0 rgba(255, 255, 255, 0.08);
    position: relative;
    overflow: hidden;
}
.opensource-section::before {
    content: ""; position: absolute;
    width: 300px; height: 300px;
    background: radial-gradient(circle, rgba(8, 145, 178, 0.15) 0%, transparent 70%);
    top: -150px; left: -100px;
    border-radius: 50%;
}
.opensource-header {
    display: flex; align-items: center; gap: 12px;
    margin-bottom: 20px;
    position: relative; z-index: 2;
}
.opensource-title {
    font-size: 1.4rem; font-weight: 800;
    background: linear-gradient(135deg, #22d3ee, #818cf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.01em;
}
.opensource-grid {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
    position: relative; z-index: 2;
}
@media (max-width: 1200px) { .opensource-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px)  { .opensource-grid { grid-template-columns: 1fr; } }

.opensource-card {
    background: rgba(30, 41, 59, 0.6);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(71, 85, 105, 0.5);
    border-radius: 12px;
    padding: 16px;
    display: flex; flex-direction: column; gap: 8px;
    transition: all 0.25s ease;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}
.opensource-card:hover {
    transform: translateY(-4px);
    background: rgba(30, 41, 59, 0.85);
    border-color: rgba(34, 211, 238, 0.5);
    box-shadow: 0 10px 15px -3px rgba(34, 211, 238, 0.15);
}
.opensource-source {
    font-size: 0.65rem; font-weight: 800; color: #22d3ee;
    text-transform: uppercase; letter-spacing: 0.08em;
    display: flex; align-items: center; gap: 5px;
}
.opensource-source svg { width: 11px; height: 11px; }

.opensource-name {
    font-size: 0.95rem; font-weight: 700; color: #f8fafc;
    line-height: 1.3;
    display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden;
    word-break: break-all;
}
.opensource-name a { color: inherit; text-decoration: none; }
.opensource-name a:hover { color: #22d3ee; }

.opensource-desc {
    font-size: 0.8rem; color: #94a3b8; line-height: 1.5;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    flex: 1; margin: 2px 0 4px;
}
.opensource-stats {
    display: flex; flex-wrap: wrap; gap: 8px;
    font-size: 0.72rem; font-weight: 700;
}
.glow-badge {
    background: rgba(34, 211, 238, 0.1);
    color: #22d3ee;
    padding: 2px 8px; border-radius: 6px;
    border: 1px solid rgba(34, 211, 238, 0.2);
    display: inline-flex; align-items: center; gap: 4px;
}
.glow-badge svg { width: 10px; height: 10px; }

.glow-badge-alt {
    background: rgba(129, 140, 248, 0.1);
    color: #818cf8;
    padding: 2px 8px; border-radius: 6px;
    border: 1px solid rgba(129, 140, 248, 0.2);
    display: inline-flex; align-items: center; gap: 4px;
}
.glow-badge-alt svg { width: 10px; height: 10px; }

</style>
"""


# ─── 工具函式 ───
def category_icon_html(category_id: str, color: Optional[str] = None) -> str:
    icon = CATEGORY_ICONS.get(category_id, CATEGORY_ICONS["uncategorized"])
    c = color or CATEGORY_COLORS.get(category_id, CATEGORY_COLORS["uncategorized"])
    return f'<span style="color:{c}; display:inline-flex; align-items:center;">{icon}</span>'


def category_chip(category_id: str, label: str) -> str:
    color = CATEGORY_COLORS.get(category_id, CATEGORY_COLORS["uncategorized"])
    icon = CATEGORY_ICONS.get(category_id, CATEGORY_ICONS["uncategorized"])
    return f'<span class="ai-chip" style="background:{color}">{icon}{label}</span>'


def resolve_cover(cover_image: Optional[dict], category_id: str) -> dict:
    """
    回傳 dict：{type: "img"|"fallback", url|color, category}
    """
    if not isinstance(cover_image, dict):
        return {"type": "fallback", "color": CATEGORY_COLORS.get(category_id, "#64748b"), "category": category_id}

    kind = cover_image.get("kind")
    if kind == "remote" and cover_image.get("url"):
        return {"type": "img", "url": cover_image["url"], "category": category_id}
    if kind == "local" and cover_image.get("url"):
        local_path = OUTPUT_DIR / cover_image["url"]
        if local_path.exists():
            try:
                data = base64.b64encode(local_path.read_bytes()).decode("ascii")
                ext = local_path.suffix.lstrip(".").lower() or "png"
                return {"type": "img", "url": f"data:image/{ext};base64,{data}", "category": category_id}
            except Exception:
                pass
    return {"type": "fallback", "color": CATEGORY_COLORS.get(category_id, "#64748b"), "category": category_id}


# 火焰 icon — 用在熱度榜與 mention badge
FLAME_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>'
    '</svg>'
)


def mention_badge_html(count: int) -> str:
    if not count or count <= 1:
        return ""
    return f'<span class="ai-mention">{FLAME_SVG}{count} 篇報導</span>'


def render_5w1h(event: dict) -> str:
    """事件的人事時地物（5W1H）橫排顯示。"""
    who = event.get("who") or []
    what = event.get("what") or ""
    when = event.get("when") or ""
    where = event.get("where") or ""
    bits = []
    if who:
        who_str = "、".join(who[:4])
        bits.append(f'<span class="kv"><span class="k">主體</span>'
                    f'<span class="v pill">{who_str}</span></span>')
    if what:
        bits.append(f'<span class="kv"><span class="k">動作</span>'
                    f'<span class="v pill">{what}</span></span>')
    if when:
        bits.append(f'<span class="kv"><span class="k">時間</span>'
                    f'<span class="v">{when}</span></span>')
    if where:
        bits.append(f'<span class="kv"><span class="k">地點</span>'
                    f'<span class="v">{where}</span></span>')
    if not bits:
        return ""
    return f'<div class="ai-5w1h">{"".join(bits)}</div>'


def render_sources(sources: list) -> str:
    """證據來源摺疊區。"""
    if not sources:
        return ""
    items_html = []
    for s in sources:
        url = s.get("url", "")
        sname = s.get("source_name", "")
        stitle = s.get("title", "") or url
        pub = (s.get("published") or "")[:10]
        meta = f"{sname}{' · ' + pub if pub else ''}"
        items_html.append(
            f'<li><span class="src-name">{meta}</span>'
            f'<a href="{url}" target="_blank" rel="noopener">{stitle}</a></li>'
        )
    return (
        '<details class="ai-sources">'
        f'<summary>{len(sources)} 個證據來源</summary>'
        f'<ul>{"".join(items_html)}</ul>'
        '</details>'
    )


def cover_html(cover_image: Optional[dict], category_id: str, category_label: str,
               variant: str = "card") -> str:
    """
    產出封面 HTML：variant="card"（大）或 "row"（縮圖）。
    card 上會疊一個分類 tag；row 不疊。
    """
    info = resolve_cover(cover_image, category_id)
    if info["type"] == "img":
        if variant == "card":
            tag = (
                f'<span class="ai-cover-tag">'
                f'{CATEGORY_ICONS.get(category_id, CATEGORY_ICONS["uncategorized"])}{category_label}'
                f'</span>'
            )
            return f'<div class="ai-cover" style="background-image:url({info["url"]});">{tag}</div>'
        return f'<div class="ai-row-thumb" style="background-image:url({info["url"]});"></div>'
    # fallback
    color = info["color"]
    icon = CATEGORY_ICONS.get(category_id, CATEGORY_ICONS["uncategorized"])
    if variant == "card":
        tag = f'<span class="ai-cover-tag">{icon}{category_label}</span>'
        return (
            f'<div class="ai-cover-fallback" style="background:linear-gradient(135deg, {color}, {color}cc);">'
            f'<span class="fallback-glow-icon">{icon}</span>{tag}</div>'
        )
    return (
        f'<div class="ai-row-thumb" style="background:linear-gradient(135deg, {color}, {color}cc);">'
        f'<span class="fallback-glow-icon-small">{icon}</span></div>'
    )
