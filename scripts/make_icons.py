"""
產生「晨誌」的識別圖示（PWA / favicon / iOS 主畫面）
====================================================

標誌概念：日出於界線之上。
  ‣ 半圓        = 晨（破曉的日）
  ‣ 粗橫線      = 報頭那條 3px 主線
  ‣ 底下短細線  = 條目之間的分隔線（誌）

幾何全部用正規化座標定義（GEO），SVG 與 PNG 共用同一組數字，不會走鐘。
刻意不用文字 —— 不依賴字型，而且 60px 的主畫面圖示上中文筆畫會糊掉。

用法：
  python3 scripts/make_icons.py          # 全部重新產生到 web/assets/
"""

from __future__ import annotations
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "web" / "assets"

# 與 web/style.css 同一組色
INK_BLUE = (40, 59, 105)      # #283B69
PAPER = (244, 245, 247)       # #F4F5F7

# 正規化幾何（0..1，相對於畫布邊長）
GEO = {
    "sun_cx": 0.500, "sun_cy": 0.565, "sun_r": 0.255,
    "rule_x0": 0.170, "rule_x1": 0.830, "rule_y0": 0.565, "rule_y1": 0.605,
    "sub_x0": 0.280, "sub_x1": 0.720, "sub_y0": 0.665, "sub_y1": 0.692,
}


def _draw(size: int, scale: float = 1.0, bg=INK_BLUE, fg=PAPER) -> Image.Image:
    """畫一張 size×size 的圖示。

    scale < 1 會把圖形往中心縮 —— maskable 圖示要留安全區，
    Android 會把四角裁掉（只保證中央 80% 直徑的圓內不被切）。
    先用 4 倍超取樣再縮小，邊緣才不會鋸齒。
    """
    ss = 4
    n = size * ss
    im = Image.new("RGB", (n, n), bg)
    d = ImageDraw.Draw(im)

    def X(v: float) -> float:
        return (0.5 + (v - 0.5) * scale) * n

    def L(v: float) -> float:   # 長度（不含位移）
        return v * scale * n

    cx, cy, r = X(GEO["sun_cx"]), X(GEO["sun_cy"]), L(GEO["sun_r"])
    # 上半圓：pieslice 的 180–360 度就是上半部
    d.pieslice([cx - r, cy - r, cx + r, cy + r], 180, 360, fill=fg)
    # 粗線（報頭主線）
    d.rectangle([X(GEO["rule_x0"]), X(GEO["rule_y0"]),
                 X(GEO["rule_x1"]), X(GEO["rule_y1"])], fill=fg)
    # 細短線（條目分隔）
    d.rectangle([X(GEO["sub_x0"]), X(GEO["sub_y0"]),
                 X(GEO["sub_x1"]), X(GEO["sub_y1"])], fill=fg)

    return im.resize((size, size), Image.LANCZOS)


def svg() -> str:
    g = GEO
    r = g["sun_r"]
    cx, cy = g["sun_cx"], g["sun_cy"]
    # 上半圓：從左端點畫一段弧到右端點再閉合
    arc = (f"M {cx - r:.4f} {cy:.4f} "
           f"A {r:.4f} {r:.4f} 0 0 1 {cx + r:.4f} {cy:.4f} Z")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1" width="512" height="512">
  <title>晨誌 Morning Ledger</title>
  <rect width="1" height="1" fill="#283B69"/>
  <path d="{arc}" fill="#F4F5F7"/>
  <rect x="{g['rule_x0']}" y="{g['rule_y0']}" width="{g['rule_x1'] - g['rule_x0']:.4f}" height="{g['rule_y1'] - g['rule_y0']:.4f}" fill="#F4F5F7"/>
  <rect x="{g['sub_x0']}" y="{g['sub_y0']}" width="{g['sub_x1'] - g['sub_x0']:.4f}" height="{g['sub_y1'] - g['sub_y0']:.4f}" fill="#F4F5F7"/>
</svg>
'''


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    (OUT / "icon.svg").write_text(svg(), encoding="utf-8")

    targets = [
        # iOS 主畫面。iOS 不吃 manifest 的圖示，一定要這張，
        # 而且不能有透明背景或自己畫圓角（系統會處理）。
        ("apple-touch-icon.png", 180, 1.0),
        ("icon-192.png", 192, 1.0),
        ("icon-512.png", 512, 1.0),
        # maskable：Android 可能裁成圓形／水滴形，圖形要縮進安全區
        ("icon-maskable-512.png", 512, 0.72),
        ("favicon-32.png", 32, 1.0),
        ("favicon-16.png", 16, 1.0),
    ]
    for name, size, scale in targets:
        img = _draw(size, scale)
        img.save(OUT / name, format="PNG", optimize=True)
        print(f"  {name:26s} {size}×{size}  {(OUT / name).stat().st_size:>6,} bytes")

    print(f"\n輸出到 {OUT}")


if __name__ == "__main__":
    main()
