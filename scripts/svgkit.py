"""Shared drawing helpers for the profile cards.

Every card comes in a dark and a light variant. The README picks one with a
<picture> element and prefers-color-scheme, so each builder takes a theme and
returns SVG text.
"""

from __future__ import annotations

import hashlib
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
WIDTH = 1200

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

# Colours follow the IntelliJ "New UI" editor schemes. Kotlin purple is the
# main accent and TypeScript blue the second. The dark accent is lighter so it keeps contrast on #1E1F22.
THEMES = {
    "dark": {
        "bg": "#1E1F22",
        "chrome": "#2B2D30",
        "panel": "#2B2D30",
        "pane": "#191A1C",
        "border": "#393B40",
        "text": "#DFE1E5",
        "muted": "#8C8F96",
        "faint": "#4E5157",
        "accent": "#A97BFF",
        "accent2": "#4E9BF5",
        "swift": "#F05138",
        "on_accent": "#FFFFFF",
        "comment": "#7A7E85",
        "keyword": "#CF8E6D",
        "string": "#6AAB73",
        "type": "#56A8F5",
        "annotation": "#B3AE60",
        "property": "#C77DBB",
        "ok": "#5FB865",
    },
    "light": {
        "bg": "#FFFFFF",
        "chrome": "#F2F3F5",
        "panel": "#F7F8FA",
        "pane": "#F7F8FA",
        "border": "#D3D5DB",
        "text": "#1F2328",
        "muted": "#6C707E",
        "faint": "#AEB3C2",
        "accent": "#7F52FF",
        "accent2": "#3178C6",
        "swift": "#D9402A",
        "on_accent": "#FFFFFF",
        "comment": "#8C8C8C",
        "keyword": "#0033B3",
        "string": "#067D17",
        "type": "#00627A",
        "annotation": "#9E880D",
        "property": "#871094",
        "ok": "#208A3C",
    },
}

def esc(text: str) -> str:
    return escape(str(text), quote=True)


def text_width(text: str, size: float, mono: bool = False) -> float:
    """Estimate rendered width. SVG has no layout engine, so pills and
    right-aligned rows size themselves from this."""
    if mono:
        return len(text) * size * 0.6
    width = 0.0
    for ch in text:
        if ch in "il.,:;|!'`":
            width += 0.28
        elif ch in "fjrt ()[]":
            width += 0.36
        elif ch in "mwMW@":
            width += 0.86
        elif ch.isupper() or ch.isdigit():
            width += 0.64
        else:
            width += 0.54
    return width * size


def svg(width: int, height: int, label: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{esc(label)}">\n'
        f"{body}</svg>\n"
    )


def text(x, y, content, t, size=20, fill=None, weight=None, anchor=None, mono=False, spacing=None, raw=False):
    attrs = [f'x="{x:g}"', f'y="{y:g}"']
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    attrs.append(f'font-family="{MONO if mono else SANS}"')
    attrs.append(f'font-size="{size}"')
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if spacing:
        attrs.append(f'letter-spacing="{spacing}"')
    attrs.append(f'fill="{fill or t["text"]}"')
    inner = content if raw else esc(content)
    return f'  <text {" ".join(attrs)}>{inner}</text>\n'


def rect(x, y, w, h, fill, rx=0, stroke=None):
    s = f' stroke="{stroke}"' if stroke else ""
    r = f' rx="{rx}"' if rx else ""
    return f'  <rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"{r} fill="{fill}"{s}/>\n'


def pill(x, y, label, t, accent=False, size=20, height=40):
    """A rounded chip. Returns (svg, width) so callers can lay chips out in a row.
    An accent chip gets a purple outline and label instead of a solid fill."""
    w = round(text_width(label, size) + 36)
    fill = t["panel"]
    stroke = t["accent"] if accent else t["border"]
    color = t["accent"] if accent else t["text"]
    out = rect(x, y, w, height, fill, rx=10, stroke=stroke)
    out += text(x + 18, y + height / 2 + size * 0.35, label, t, size=size, fill=color)
    return out, w


def write(name: str, theme: str, content: str) -> Path:
    ASSETS.mkdir(exist_ok=True)
    path = ASSETS / f"{name}-{theme}.svg"
    path.write_text(content, encoding="utf-8")
    return path


def stamp_readme() -> None:
    """Put a short hash of each SVG on its README URL. jsDelivr tells browsers
    to cache images for a week, so an image only refreshes when its URL
    changes. Hashing the content changes the URL exactly when the card does."""
    readme = ROOT / "README.md"

    def stamp(m: re.Match) -> str:
        path = ASSETS / m.group(2)
        if not path.exists():
            return m.group(0)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
        return f"{m.group(1)}{m.group(2)}?v={digest}"

    content = readme.read_text(encoding="utf-8")
    content = re.sub(r"(@main/assets/)([\w-]+\.svg)(\?v=\w+)?", stamp, content)
    readme.write_text(content, encoding="utf-8")
