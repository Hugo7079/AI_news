"""
本地網站伺服器（不需要 Firebase）
=================================

一個程序同時提供：
  1. 靜態前端         web/ 底下的 index.html / app.js / style.css / assets
  2. 資料 API         讀 output/store/*.json
  3. 封面圖           /media/... → output/ 底下的檔案

只用 Python 標準函式庫，不需要額外套件；前端靠 /config.json 回報的 mode=local
自動切換成打這台伺服器的 API，不會去載入 Firebase SDK。

執行：
    python3 src/server.py --port 8080
環境變數：
    AINEWS_WEB_PORT   埠號（預設 8080）
    AINEWS_WEB_HOST   綁定位址（預設 0.0.0.0）
"""

from __future__ import annotations
import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from config import BASE_DIR, OUTPUT_DIR
import local_store

WEB_DIR = Path(os.getenv("AINEWS_WEB_DIR", "").strip() or (BASE_DIR / "web"))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _today_tw() -> str:
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def _rewrite_cover(ev: dict) -> dict:
    """本地封面圖（images/{date}/x.png）→ /media/images/{date}/x.png，
    前端就能當成一般圖片網址直接用。"""
    cover = ev.get("cover_image")
    if isinstance(cover, dict) and cover.get("kind") == "local" and cover.get("url"):
        url = str(cover["url"]).lstrip("/")
        ev = dict(ev)
        ev["cover_image"] = {"kind": "remote", "url": "/media/" + url}
    return ev


class Handler(SimpleHTTPRequestHandler):
    server_version = "AINewsLocal"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    # ── 共用回應工具 ──
    def _json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, cache: str = "public, max-age=3600"):
        if not path.is_file():
            self._json({"error": "not found", "path": str(path.name)}, 404)
            return
        ctype = self.guess_type(str(path))
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    # ── 路由 ──
    def do_GET(self):
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        qs = parse_qs(parsed.query)

        if route in ("/api/health", "/api/config"):
            return self._json({"ok": True, "mode": "local", "today": _today_tw()})

        # 覆寫靜態的 web/config.json：告訴前端「這裡是本地模式」
        if route == "/config.json":
            return self._json({"mode": "local"})

        if route == "/api/dates":
            return self._json({"dates": local_store.list_dates()})

        if route == "/api/summaries":
            return self._json({"summaries": local_store.load_summaries()})

        if route == "/api/events":
            dates = local_store.list_dates()
            if not dates:
                return self._json({"events": [], "start": "", "end": ""})
            end = (qs.get("end") or [dates[0]])[0]
            start = (qs.get("start") or [end])[0]
            if not DATE_RE.match(start) or not DATE_RE.match(end):
                return self._json({"error": "start/end need YYYY-MM-DD"}, 400)
            if start > end:
                start, end = end, start
            events = [_rewrite_cover(ev) for ev in local_store.load_events(start, end)]
            return self._json({"events": events, "start": start, "end": end,
                               "total": len(events)})

        if route.startswith("/media/"):
            rel = route[len("/media/"):]
            target = (OUTPUT_DIR / rel).resolve()
            if not str(target).startswith(str(Path(OUTPUT_DIR).resolve())):
                return self._json({"error": "forbidden"}, 403)
            return self._send_file(target)

        if route.startswith("/api/"):
            return self._json({"error": "unknown endpoint"}, 404)

        # 靜態檔；找不到就回 index.html（單頁應用）
        target = (WEB_DIR / route.lstrip("/")).resolve()
        if route in ("", "/") or not target.is_file():
            if route.startswith("/assets/"):
                return self._json({"error": "not found"}, 404)
            return self._send_file(WEB_DIR / "index.html", cache="no-cache")
        return super().do_GET()

    def log_message(self, fmt, *args):
        # 只留下錯誤與 API 呼叫，避免靜態檔洗版
        msg = fmt % args
        if " 200 " in msg and "/api/" not in msg and "/media/" not in msg:
            return
        print(f"[web] {self.address_string()} {msg}")


def main():
    ap = argparse.ArgumentParser(description="AI新聞 本地網站伺服器")
    ap.add_argument("--port", type=int,
                    default=int(os.getenv("AINEWS_WEB_PORT", "8080")))
    ap.add_argument("--host", default=os.getenv("AINEWS_WEB_HOST", "0.0.0.0"))
    args = ap.parse_args()

    print(f"[web] 前端目錄 : {WEB_DIR}")
    print(f"[web] 資料目錄 : {local_store.store_dir()}")
    print(f"[web] 圖片目錄 : {OUTPUT_DIR}")
    print(f"[web] 已有資料 : {len(local_store.list_dates())} 天")
    print(f"[web] 監聽 http://{args.host}:{args.port}")

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
