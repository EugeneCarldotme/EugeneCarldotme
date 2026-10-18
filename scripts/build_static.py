"""Render the cards that only change when I edit them: the hero, status chips,
section headers, projects, stack and contact badges.

Edit the data near the top of this file, then run it. It needs no network or
token, so it is safe to run locally before pushing.
"""

from __future__ import annotations

from svgkit import (
    MONO, THEMES, WIDTH, esc, pill, rect, svg, text, text_width, write,
)

STATUS = [
    ("Manila, PH", False),
    ("Kotlin by day", False),
    ("TypeScript by night", False),
    ("Building EC Stack", True),
]

SECTIONS = {
    "activity": "Activity",
    "projects": "Projects",
    "open-source": "Open source",
    "stack": "Stack",
    "contact": "Contact",
}

# (slug, name, tags, description, link label, dot colour). The dot uses
# GitHub's colour for the project's main language.
PROJECTS = [
    ("planthing", "PlanThing", "TypeScript · React · Convex",
     "A planner app for tasks and schedules, built on React and Convex.",
     "planthing.app", "#3178C6"),
    ("labtracker", "Mapua Library Lab Tracker", "Electron · Next.js · TypeScript · Offline first",
     "Replaced paper and Excel logging across 26 library workstations. Runs with no internet.",
     "Case study", "#3178C6"),
    ("ectrivia", "EC Trivia", "Android · Java · Kafka · WebSocket",
     "Kahoot-style multiplayer quiz. Kafka splits the game services, WebSockets keep players in sync.",
     "GitHub", "#B07219"),
]

STACK = [
    ("By day, backend", ["Kotlin", "Ktor", "Elide", "Go", "Google Cloud", "PostgreSQL"]),
    ("By night, full stack", ["TypeScript", "React", "React Native", "Vite+", "TanStack", "Next.js",
                              "Convex", "Electron"]),
    ("In open source", ["Swift", "SwiftUI", "AppKit", "macOS"]),
    ("Also shipped with", ["Java", "Android", "Apache Kafka", "WebSockets"]),
    ("Tooling", ["Git", "IntelliJ IDEA", "Postman", "GitHub Actions"]),
]

BADGES = ["Website", "LinkedIn", "Email"]


# Each code line is (indent in characters, [(colour key, text), ...]).
DAY_CODE = [
    (0, [("comment", "// by day, Kotlin on the backend")]),
    (0, [("keyword", "fun "), ("type", "Route"), ("text", ".users() = get("), ("string", '"/users/{id}"'),
         ("text", ") {")]),
    (4, [("text", "call.respond(repo.find(call.parameters["), ("string", '"id"'), ("text", "]))")]),
    (0, [("text", "}")]),
]

NIGHT_CODE = [
    (0, [("comment", "// by night, TypeScript on EC Stack")]),
    (0, [("keyword", "const "), ("property", "ecStack"), ("text", " = ["), ("string", '"EC Code"'),
         ("text", ", "), ("string", '"EC Review"'), ("text", "];")]),
    (0, [("keyword", "for "), ("text", "("), ("keyword", "const "), ("text", "tool "), ("keyword", "of "),
         ("text", "ecStack) "), ("keyword", "await "), ("type", "ship"), ("text", "(tool);")]),
]

# What each phone in the preview shows, as (title, subtitle).
ANDROID_ROWS = [
    ("GET /users/{id}", "200 OK"),
    ("POST /users", "201 Created"),
    ("GET /health", "200 OK"),
]
IOS_ROWS = ["EC Code", "EC Review"]

BEZEL = "#0B0B0D"


def code_block(lines, x0, y0, t, size=20, step=32):
    cw = size * 0.6
    out = ""
    for n, (indent, segs) in enumerate(lines):
        y = y0 + n * step
        out += text(x0 - 22, y, str(n + 1), t, size=16, fill=t["faint"], anchor="end", mono=True)
        spans = "".join(f'<tspan fill="{t[k]}">{esc(s)}</tspan>' for k, s in segs)
        out += (f'  <text x="{x0 + indent * cw:g}" y="{y}" font-family="{esc(MONO)}" '
                f'font-size="{size}" xml:space="preserve">{spans}</text>\n')
    return out


def sun(cx, cy, color):
    rays = "".join(
        f'<line x1="{cx + 7 * dx:g}" y1="{cy + 7 * dy:g}" x2="{cx + 10 * dx:g}" y2="{cy + 10 * dy:g}"/>'
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7))
    )
    return (f'  <circle cx="{cx}" cy="{cy}" r="4.5" fill="{color}"/>\n'
            f'  <g stroke="{color}" stroke-width="2" stroke-linecap="round">{rays}</g>\n')


def moon(cx, cy, color):
    return f'  <path d="M{cx + 3} {cy - 9} A9 9 0 1 0 {cx + 9} {cy + 4} A7 7 0 0 1 {cx + 3} {cy - 9} Z" fill="{color}"/>\n'


PHONE_W, PHONE_H = 180, 304


def status_bar(x, y, t, bold=False):
    out = text(x + 22, y + 26, "9:41", t, size=11, weight=600 if bold else None)
    out += rect(x + PHONE_W - 44, y + 18, 18, 9, "none", rx=2.5, stroke=t["text"])
    out += rect(x + PHONE_W - 42, y + 20, 12, 5, t["text"], rx=1)
    return out


def android(x, y, t):
    """Material 3 look: punch-hole camera, search bar, card rows, a FAB and a
    gesture bar."""
    w, h = PHONE_W, PHONE_H
    out = rect(x, y, w, h, BEZEL, rx=24)
    out += rect(x + 5, y + 5, w - 10, h - 10, t["bg"], rx=20)
    out += f'  <circle cx="{x + w / 2:g}" cy="{y + 21}" r="4.5" fill="{BEZEL}"/>\n'
    out += status_bar(x, y, t)
    out += text(x + 18, y + 60, "Ktor API", t, size=17, weight=600)
    out += rect(x + 14, y + 72, w - 28, 26, t["panel"], rx=13)
    out += text(x + 28, y + 89, "Search endpoints", t, size=11, fill=t["muted"])
    for i, (title, sub) in enumerate(ANDROID_ROWS):
        ry = y + 108 + i * 46
        out += rect(x + 14, ry, w - 28, 40, t["panel"], rx=12)
        out += f'  <circle cx="{x + 34}" cy="{ry + 20}" r="10" fill="{t["accent"]}" fill-opacity="0.25"/>\n'
        out += f'  <circle cx="{x + 34}" cy="{ry + 20}" r="4" fill="{t["accent"]}"/>\n'
        out += text(x + 52, ry + 18, title, t, size=12, weight=600)
        out += text(x + 52, ry + 32, sub, t, size=10, fill=t["muted"])
    out += rect(x + w - 58, y + h - 66, 40, 40, t["accent"], rx=12)
    out += text(x + w - 38, y + h - 38, "+", t, size=24, fill="#FFFFFF", anchor="middle")
    out += rect(x + w / 2 - 30, y + h - 15, 60, 3, t["muted"], rx=1.5)
    return out


def iphone(x, y, t):
    """iOS look: Dynamic Island, large title, an inset grouped list, a tab bar
    and a home indicator."""
    w, h = PHONE_W, PHONE_H
    out = rect(x, y, w, h, BEZEL, rx=32)
    out += rect(x + 5, y + 5, w - 10, h - 10, t["bg"], rx=28)
    out += rect(x + w / 2 - 30, y + 13, 60, 17, BEZEL, rx=8.5)
    out += status_bar(x, y, t, bold=True)
    out += text(x + 18, y + 70, "EC Stack", t, size=22, weight=700)
    out += text(x + 18, y + 88, "React Native · TypeScript", t, size=10, fill=t["muted"])
    top = y + 102
    out += rect(x + 12, top, w - 24, 36 * len(IOS_ROWS), t["panel"], rx=10)
    for i, label in enumerate(IOS_ROWS):
        ry = top + i * 36
        if i:
            out += rect(x + 46, ry, w - 58, 1, t["border"])
        out += rect(x + 22, ry + 8, 20, 20, t["accent2"], rx=5)
        out += text(x + 52, ry + 23, label, t, size=12)
        out += text(x + w - 24, ry + 23, "›", t, size=16, fill=t["muted"], anchor="end")
    tabs = y + h - 58
    out += rect(x + 5, tabs, w - 10, 1, t["border"])
    for i, label in enumerate(("Home", "Tools", "Profile")):
        cx = x + 34 + i * 56
        color = t["accent2"] if i == 0 else t["muted"]
        out += rect(cx - 7, tabs + 10, 14, 14, color, rx=4)
        out += text(cx, tabs + 36, label, t, size=9, fill=color, anchor="middle")
    out += rect(x + w / 2 - 32, y + h - 13, 64, 4, t["text"], rx=2)
    return out


def hero(t: dict) -> str:
    h, split = 448, 744

    out = (f'  <defs><clipPath id="win"><rect x="1" y="1" width="{WIDTH - 2}" height="{h - 2}" '
           f'rx="16"/></clipPath></defs>\n')
    out += '  <g clip-path="url(#win)">\n'
    out += rect(0, 0, WIDTH, h, t["bg"])
    out += rect(split, 48, WIDTH - split, h - 48, t["pane"])
    out += rect(split, 48, 1, h - 48, t["border"])

    # Title bar with one tab per language.
    out += rect(0, 0, WIDTH, 48, t["chrome"])
    out += rect(0, 47, WIDTH, 1, t["border"])
    for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        out += f'  <circle cx="{28 + 24 * i}" cy="24" r="7" fill="{c}"/>\n'
    out += rect(104, 8, 150, 40, t["bg"], rx=8)
    out += rect(104, 44, 150, 4, t["bg"])
    out += f'  <path d="M120 16 H136 L128 24 L136 32 H120 Z" fill="{t["accent"]}"/>\n'
    out += text(146, 31, "Day.kt", t, size=18)
    out += rect(262, 8, 160, 40, t["chrome"], rx=8, stroke=t["border"])
    out += rect(262, 44, 160, 4, t["chrome"])
    out += rect(278, 16, 16, 16, t["accent2"], rx=3)
    out += text(286, 28.5, "TS", t, size=9, weight=700, fill="#FFFFFF", anchor="middle")
    out += text(304, 31, "Night.ts", t, size=18)
    out += text(WIDTH - 24, 31, f'<tspan fill="{t["accent"]}">Kotlin</tspan><tspan fill="{t["muted"]}"> · </tspan>'
                f'<tspan fill="{t["accent2"]}">TypeScript</tspan><tspan fill="{t["muted"]}"> · </tspan>'
                f'<tspan fill="{t["swift"]}">Swift</tspan>', t, size=18, anchor="end", raw=True)

    # Editor, day on top and night below.
    out += sun(48, 82, t["accent"])
    out += text(70, 88, "BY DAY  ·  KOTLIN BACKEND", t, size=14, fill=t["muted"], spacing=1.4)
    out += code_block(DAY_CODE, 70, 128, t, step=32)
    out += rect(24, 250, split - 48, 1, t["border"])
    out += moon(44, 284, t["accent2"])
    out += text(70, 290, "BY NIGHT  ·  EC STACK", t, size=14, fill=t["muted"], spacing=1.4)
    out += code_block(NIGHT_CODE, 70, 334, t, step=32)

    # Preview pane, an Android phone and an iPhone.
    out += text(split + 26, 80, "PREVIEW", t, size=16, fill=t["muted"], spacing=1.6)
    out += android(784, 96, t)
    out += iphone(988, 96, t)
    out += text(784 + PHONE_W / 2, 426, "Android · Kotlin", t, size=14, fill=t["accent"], anchor="middle")
    out += text(988 + PHONE_W / 2, 426, "iOS · React Native", t, size=14, fill=t["accent2"], anchor="middle")
    out += "  </g>\n"
    out += rect(1, 1, WIDTH - 2, h - 2, "none", rx=16, stroke=t["border"])
    return svg(WIDTH, h, HERO_ALT, out)


HERO_ALT = ("Eugene Carl, Kotlin developer by day and TypeScript developer by night. An editor shows a Ktor "
            "route above an EC Stack snippet. The preview shows an Android phone listing the Ktor routes "
            "and an iPhone running EC Stack.")


def status(t: dict) -> str:
    out, x = "", 0
    for label, accent in STATUS:
        chip, w = pill(x, 4, label, t, accent=accent)
        out += chip
        x += w + 10
    return svg(WIDTH, 48, ". ".join(s for s, _ in STATUS) + ".", out)


def section(title: str, t: dict) -> str:
    out = text(0, 38, title, t, size=30, weight=600)
    out += rect(0, 53, WIDTH, 1, t["border"])
    return svg(WIDTH, 58, title, out)


def project(name: str, tags: str, desc: str, link: str, dot: str, t: dict) -> str:
    out = rect(0.5, 0.5, WIDTH - 1, 103, t["panel"], rx=14, stroke=t["border"])
    out += f'  <circle cx="24" cy="52" r="5" fill="{dot}"/>\n'
    out += text(46, 36, name, t, size=24, weight=600)
    out += text(46, 62, tags, t, size=16, fill=t["muted"])
    out += text(46, 88, desc, t, size=18)
    out += text(WIDTH - 24, 58, link, t, size=18, fill=t["muted"], anchor="end")
    return svg(WIDTH, 112, name, out)


def stack(t: dict) -> str:
    out, y = "", 0
    for group, items in STACK:
        out += text(0, y + 14, group.upper(), t, size=16, weight=600, fill=t["muted"], spacing=1.4)
        x, row_y = 0, y + 26
        for item in items:
            w = round(text_width(item, 20) + 36)
            if x + w > WIDTH:
                x, row_y = 0, row_y + 50
            chip, w = pill(x, row_y, item, t)
            out += chip
            x += w + 10
        y = row_y + 66
    label = "; ".join(f"{g}: {', '.join(i)}" for g, i in STACK)
    return svg(WIDTH, y - 16, label, out)


def badge(label: str, t: dict) -> str:
    w = round(text_width(label, 20) + 50)
    out = rect(0.5, 0.5, w - 1, 43, t["panel"], rx=11, stroke=t["border"])
    out += f'  <circle cx="18" cy="22" r="4" fill="{t["muted"]}"/>\n'
    out += text(32, 29, label, t, size=20)
    return svg(w, 44, label, out)


def main() -> None:
    for name, t in THEMES.items():
        write("hero", name, hero(t))
        write("status", name, status(t))
        for slug, title in SECTIONS.items():
            write(f"sec-{slug}", name, section(title, t))
        for slug, pname, tags, desc, link, dot in PROJECTS:
            write(f"project-{slug}", name, project(pname, tags, desc, link, dot, t))
        write("stack", name, stack(t))
        for label in BADGES:
            write(f"badge-{label.lower()}", name, badge(label, t))
    print("static cards written")


if __name__ == "__main__":
    main()
