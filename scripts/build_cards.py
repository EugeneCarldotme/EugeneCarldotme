"""Render live GitHub stats, all-time weekly streaks, languages, and the heat map.
Also rewrites the activity and open source blocks in README.md and changes
image URLs whenever their contents change, bypassing GitHub's image cache.

Needs a token in GH_STATS_TOKEN or GITHUB_TOKEN. A fine-grained personal
token with read-only Metadata on all my repos adds private repos to the
languages bar. The workflow token only sees public ones.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from svgkit import ASSETS, ROOT, stamp_readme, THEMES, WIDTH, esc, rect, svg, text, text_width, write

LOGIN = "EugeneCarldotme"
CDN = f"https://raw.githubusercontent.com/{LOGIN}/{LOGIN}/main/assets"
MAX_REPOS = 6
MAX_MERGES = 3

PROFILE_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    name
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    contributionsCollection(from: $from, to: $to) {
      contributionYears
      totalCommitContributions
      totalPullRequestReviewContributions
      totalRepositoriesWithContributedCommits
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

HISTORY_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

# Fine-grained tokens only list private repos through viewer, so the personal
# token asks as viewer. The workflow token belongs to a bot, so it asks for
# the user by login and sees public repos only.
REPO_FIELDS = """
repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false) {
  pageInfo { hasNextPage endCursor }
  nodes {
    isPrivate
    stargazerCount
    languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
      edges { size node { name color } }
    }
  }
}
"""
VIEWER_REPOS = "query($after: String) { owner: viewer { " + REPO_FIELDS + " } }"
USER_REPOS = "query($login: String!, $after: String) { owner: user(login: $login) { " + REPO_FIELDS + " } }"

PR_QUERY = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 100, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        title
        number
        url
        mergedAt
        repository {
          nameWithOwner
          description
          url
          stargazerCount
          primaryLanguage { name color }
        }
      }
    }
  }
}
"""


def graphql(query: str, variables: dict) -> dict:
    token = os.environ.get("GH_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("set GH_STATS_TOKEN or GITHUB_TOKEN")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": LOGIN},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        sys.exit(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def streaks(days: list[tuple[str, int]]) -> tuple[int, int]:
    """Return (current, longest). Today does not break the current streak
    until it ends, so an empty today counts from yesterday instead."""
    counts = [c for _, c in sorted(days)]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    if counts and counts[-1] == 0:
        counts = counts[:-1]
    current = 0
    for c in reversed(counts):
        if not c:
            break
        current += 1
    return current, longest


def contribution_history(years: list[int], now: datetime) -> list[tuple[str, int]]:
    """Fetch each calendar year once, without counting boundary days twice."""
    days = {}
    for year in sorted(years):
        end = min(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        data = graphql(HISTORY_QUERY, {
            "login": LOGIN, "from": f"{year}-01-01T00:00:00Z", "to": end.isoformat(),
        })["user"]["contributionsCollection"]["contributionCalendar"]
        for week in data["weeks"]:
            for day in week["contributionDays"]:
                if day["date"].startswith(str(year)):
                    days[day["date"]] = day["contributionCount"]
    return sorted(days.items())


def weekly_streaks(days: list[tuple[str, int]], today: date) -> dict:
    """Sunday-to-Saturday weeks. An unfinished empty week has a grace period."""
    def week_start(day: date) -> date:
        return day - timedelta(days=(day.weekday() + 1) % 7)

    this_week = week_start(today)
    active = {week_start(date.fromisoformat(d)) for d, count in days if count and d <= today.isoformat()}
    best_start = best_end = run_start = previous = None
    longest = run = 0
    for week in sorted(active):
        if previous is not None and week == previous + timedelta(days=7):
            run += 1
        else:
            run, run_start = 1, week
        if run > longest:
            longest, best_start, best_end = run, run_start, week
        previous = week

    end = this_week if this_week in active else this_week - timedelta(days=7)
    cursor, current = end, 0
    while cursor in active:
        current += 1
        cursor -= timedelta(days=7)
    return {
        "current": current, "longest": longest,
        "current_start": cursor + timedelta(days=7) if current else None,
        "current_end": min(end + timedelta(days=6), today) if current else None,
        "longest_start": best_start,
        "longest_end": min(best_end + timedelta(days=6), today) if best_end else None,
    }


def stats_grade(stats: dict) -> tuple[str, float]:
    """GitHub Readme Stats' heuristic, not an official GitHub ranking.

    Adapted from anuraghazra/github-readme-stats/src/calculateRank.js.
    MIT license: licenses/github-readme-stats.txt.
    """
    score = (
        2 * (1 - 2 ** (-stats["commits"] / 250))
        + 3 * (1 - 2 ** (-stats["prs"] / 50))
        + (1 - 2 ** (-stats["issues"] / 25))
        + (1 - 2 ** (-stats["reviews"] / 2))
        + 4 * stats["stars"] / (stats["stars"] + 50)
        + stats["followers"] / (stats["followers"] + 10)
    ) / 12
    percentile = (1 - score) * 100
    for threshold, grade in zip((1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100),
                                ("S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C")):
        if percentile <= threshold:
            return grade, score
    return "C", score


def owned_repos() -> list[dict]:
    personal = bool(os.environ.get("GH_STATS_TOKEN"))
    query = VIEWER_REPOS if personal else USER_REPOS
    variables = {} if personal else {"login": LOGIN}
    repos, after = [], None
    while True:
        page = graphql(query, {**variables, "after": after})["owner"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    private = sum(1 for r in repos if r["isPrivate"])
    print(f"repos counted for languages: {len(repos)} ({private} private)", file=sys.stderr)
    return repos


def merged_prs() -> list[dict]:
    q = f"is:pr author:{LOGIN} is:merged -user:{LOGIN}"
    prs, after = [], None
    while True:
        data = graphql(PR_QUERY, {"q": q, "after": after})["search"]
        prs += [n for n in data["nodes"] if n]
        if not data["pageInfo"]["hasNextPage"] or len(prs) >= 500:
            return prs
        after = data["pageInfo"]["endCursor"]


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def clip(s: str, size: float, limit: float) -> str:
    if text_width(s, size) <= limit:
        return s
    while s and text_width(s + "...", size) > limit:
        s = s[:-1]
    return s.rstrip() + "..."


def activity_theme(theme: str) -> dict:
    return {**THEMES[theme], **({
        "panel": "#0D1117", "border": "#8B949E", "text": "#F0F6FC",
        "muted": "#C9D1D9", "accent2": "#56D4F4", "faint": "#193B46",
    } if theme == "dark" else {
        "panel": "#FFFFFF", "border": "#8C959F", "text": "#1F2328",
        "muted": "#57606A", "accent2": "#007F99", "faint": "#DCEEF2",
    })}


def stats_card(stats: dict, t: dict) -> str:
    height = 470
    out = rect(1, 1, WIDTH - 2, height - 2, t["panel"], rx=12, stroke=t["border"])
    out += text(62, 88, f"{stats['name']}'s GitHub stats", t, size=40, weight=700, fill=t["accent2"])
    icons = [
        "M12 2l3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z",
        "M3 12a9 9 0 1 0 3-7M3 2v6h6M12 7v5l3 2",
        "M6 6v12M16 6c4 0 4 5 0 6v6M3 3h6v6H3zM13 15h6v6h-6z",
        "M12 8v5M12 16v1M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20",
        "M4 3h15v17H4zM7 17h9M8 20v3",
    ]
    rows = [
        ("Total stars earned", stats["stars"]),
        ("Total commits (this year)", stats["commits"]),
        ("Total PRs", stats["prs"]),
        ("Total issues", stats["issues"]),
        ("Contributed to (this year)", stats["contributed"]),
    ]
    for i, ((label, value), path) in enumerate(zip(rows, icons)):
        y = 173 + i * 60
        out += (f'<path d="{path}" transform="translate(63 {y - 28}) scale(1.45)" '
                f'fill="none" stroke="{t["accent2"]}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>\n')
        out += text(124, y, label + ":", t, size=29, weight=600)
        out += text(720, y, f"{value:,}", t, size=30, weight=700, anchor="end")
    grade, score = stats_grade(stats)
    out += '<g><title>GitHub Readme Stats heuristic grade. This is not an official GitHub ranking.</title>'
    out += f'<circle cx="980" cy="265" r="103" fill="none" stroke="{t["faint"]}" stroke-width="14"/>\n'
    out += (f'<circle cx="980" cy="265" r="103" fill="none" stroke="{t["accent2"]}" stroke-width="14" '
            f'pathLength="100" stroke-dasharray="{score * 100:.2f} 100" stroke-linecap="round" transform="rotate(-90 980 265)"/>\n')
    out += text(980, 287, grade, t, size=64, weight=700, anchor="middle")
    out += '</g>'
    label = ", ".join(f"{label}: {value:,}" for label, value in rows)
    return svg(WIDTH, height, label, out)


def date_range(start: date | None, end: date | None) -> str:
    if start is None or end is None:
        return "No contributions yet"
    return f"{start:%b} {start.day}, {start.year} - {end:%b} {end.day}, {end.year}"


def streak_card(stats: dict, weekly: dict, t: dict) -> str:
    height = 470
    out = rect(1, 1, WIDTH - 2, height - 2, t["panel"], rx=12, stroke=t["border"])
    for x in (400, 800):
        out += f'<path d="M{x} 66V405" stroke="{t["border"]}" stroke-width="2"/>\n'
    out += text(200, 194, f"{stats['all_time']:,}", t, size=66, weight=700, fill=t["accent2"], anchor="middle")
    out += text(200, 279, "Total contributions", t, size=31, fill=t["accent2"], anchor="middle")
    joined = date.fromisoformat(stats["joined"][:10])
    out += text(200, 352, f"{joined:%b} {joined.day}, {joined.year} - Present", t, size=25, weight=600, anchor="middle")

    # Leave an opening at the top of the ring for the flame.
    out += (f'<circle cx="600" cy="168" r="96" fill="none" stroke="{t["accent2"]}" stroke-width="11" '
            'pathLength="100" stroke-dasharray="90 10" transform="rotate(-72 600 168)"/>\n')
    out += (f'<path d="M600 45c13 17 22 29 11 42-10 10-28 4-28-9 0-8 6-15 11-21 '
            f'1 8 5 11 8 8 4-4 0-13-2-20z" fill="{t["accent2"]}"/>\n')
    out += text(600, 192, str(weekly["current"]), t, size=66, weight=700, fill=t["accent2"], anchor="middle")
    out += text(600, 325, "Week streak", t, size=34, weight=700, fill=t["accent2"], anchor="middle")
    out += text(600, 387, date_range(weekly["current_start"], weekly["current_end"]), t, size=24, weight=600, anchor="middle")

    out += text(1000, 194, str(weekly["longest"]), t, size=66, weight=700, fill=t["accent2"], anchor="middle")
    out += text(1000, 279, "Longest week streak", t, size=31, fill=t["accent2"], anchor="middle")
    out += text(1000, 352, date_range(weekly["longest_start"], weekly["longest_end"]), t, size=24, weight=600, anchor="middle")
    label = (f"{stats['all_time']:,} total contributions since joining GitHub. "
             f"{weekly['current']} week current streak, {weekly['longest']} week longest streak. "
             "Weeks run Sunday to Saturday. The current week remains open until Saturday ends.")
    return svg(WIDTH, height, label, out)


def activity(stats: dict, langs: list[tuple[str, str, int]], t: dict) -> str:
    top = 0
    out = ""
    total = sum(size for _, _, size in langs) or 1
    shown = langs[:6]
    h = 136
    out += rect(0.5, top + 0.5, WIDTH - 1, h - 1, t["panel"], rx=14, stroke=t["border"])
    out += text(22, top + 38, "Languages, by bytes of code in my repos", t, size=18, fill=t["muted"])
    bar_x, bar_w = 22, WIDTH - 44
    out += f'  <clipPath id="bar"><rect x="{bar_x}" y="{top + 56}" width="{bar_w}" height="12" rx="6"/></clipPath>\n'
    out += f'  <g clip-path="url(#bar)">\n'
    out += rect(bar_x, top + 56, bar_w, 12, t["border"])
    x = bar_x
    for name, color, size in shown:
        w = bar_w * size / total
        out += rect(x, top + 56, w, 12, color or t["muted"])
        x += w
    out += "  </g>\n"
    x = 22
    for name, color, size in shown:
        label = f"{name} {size / total:.0%}"
        out += f'  <circle cx="{x + 6}" cy="{top + 107}" r="6" fill="{color or t["muted"]}"/>\n'
        out += text(x + 20, top + 114, label, t, size=18)
        x += text_width(label, 18) + 48
    height = top + h
    label = "Languages by bytes of code: " + ", ".join(n for n, _, _ in shown) + "."
    return svg(WIDTH, height, label, out)


# Contribution levels from empty to busiest, in TypeScript blue.
CALENDAR_SHADES = {
    "dark": ["#393B40", "#0E3A6B", "#1A5FA8", "#2F80D9", "#58A6FF"],
    "light": ["#E4E6EB", "#B6D4F5", "#7AAEEA", "#3B82D6", "#1E5FAF"],
}


def calendar(days: list[tuple[str, int]], total: int, theme: str, t: dict, updated: str = "") -> str:
    """A contribution calendar like the one on the profile page, one column
    per week and one row per weekday starting on Sunday."""
    shades = CALENDAR_SHADES[theme]
    cell, step, left, top = 17, 21, 46, 74
    first = date.fromisoformat(days[0][0])
    start = date.fromordinal(first.toordinal() - (first.weekday() + 1) % 7)

    # Split the busy days into quartiles so a single huge day doesn't wash
    # out the rest of the year.
    busy = sorted(c for _, c in days if c)
    cuts = [busy[len(busy) * q // 4] for q in (1, 2, 3)] if busy else [0, 0, 0]

    def level(c: int) -> int:
        return 0 if not c else 1 + sum(c > cut for cut in cuts)

    weeks = (date.fromisoformat(days[-1][0]) - start).days // 7 + 1
    # Centre the grid in a full-width card so it lines up with the others.
    left = 46 + (WIDTH - 68 - weeks * step) // 2
    width = WIDTH
    height = top + 7 * step + 46
    out = rect(0.5, 0.5, width - 1, height - 1, t["panel"], rx=14, stroke=t["border"])
    out += text(22, 38, f"{total:,} contributions this year", t, size=18, fill=t["muted"])
    if updated:
        out += text(WIDTH - 22, 38, f"Updated {updated} PHT", t, size=16, fill=t["muted"], anchor="end")

    labels = []
    for d, c in days:
        day = date.fromisoformat(d)
        col = (day - start).days // 7
        row = (day.weekday() + 1) % 7
        x, y = left + col * step, top + row * step
        if row == 0 and (not labels or labels[-1][1] != day.strftime("%b")):
            labels.append((col, day.strftime("%b")))
        out += f'<g><title>{esc(d)}: {plural(c, "contribution")}</title>'
        out += rect(x, y, cell, cell, shades[level(c)], rx=4)
        out += '</g>\n'
    # Drop a month label when the next one starts within three weeks, so a
    # partial month at either edge doesn't crowd its neighbour.
    for i, (col, month) in enumerate(labels):
        if i + 1 < len(labels) and labels[i + 1][0] - col < 3:
            continue
        if col < weeks - 2:
            out += text(left + col * step, top - 10, month, t, size=14, fill=t["muted"])
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        out += text(left - 10, top + row * step + 13, label, t, size=13, fill=t["muted"], anchor="end")

    legend_y = top + 7 * step + 14
    x = width - 22 - 5 * step - text_width("More", 13)
    out += text(x - 8, legend_y + 13, "Less", t, size=13, fill=t["muted"], anchor="end")
    for i, shade in enumerate(shades):
        out += rect(x + i * step, legend_y, cell, cell, shade, rx=4)
    out += text(x + 5 * step + 4, legend_y + 13, "More", t, size=13, fill=t["muted"])
    return svg(width, height, f"Contribution calendar, {total:,} contributions this year.", out)


def caption(label: str, t: dict) -> str:
    return svg(WIDTH, 36, label, text(0, 24, label, t, size=18, fill=t["muted"]))


def lang_color(repo: dict, t: dict) -> str:
    """GitHub's colour for the repo's main language, so a Swift repo reads
    orange and a TypeScript one blue."""
    return (repo.get("primaryLanguage") or {}).get("color") or t["muted"]


def repo_card(repo: dict, count: int, t: dict) -> str:
    out = rect(0.5, 0.5, WIDTH - 1, 79, t["panel"], rx=14, stroke=t["border"])
    lang = repo.get("primaryLanguage") or {}
    out += f'  <circle cx="24" cy="40" r="5" fill="{lang_color(repo, t)}"/>\n'
    out += text(46, 34, repo["nameWithOwner"], t, size=22, weight=600)
    meta = " · ".join(x for x in (lang.get("name"), f"★ {repo['stargazerCount']:,}") if x)
    out += text(46, 62, clip(f"{meta} · {repo.get('description') or ''}".rstrip(" ·"), 16, 900), t, size=16,
                fill=t["muted"])
    out += text(WIDTH - 24, 46, f"{count} merged", t, size=18, fill=lang_color(repo, t), anchor="end")
    return svg(WIDTH, 88, repo["nameWithOwner"], out)


def merge_card(pr: dict, t: dict) -> str:
    out = rect(0.5, 0.5, WIDTH - 1, 55, t["panel"], rx=12, stroke=t["border"])
    ref = f"{pr['repository']['nameWithOwner']}#{pr['number']}"
    out += text(22, 35, ref, t, size=17, fill=lang_color(pr["repository"], t), mono=True)
    start = 22 + text_width(ref, 17, mono=True) + 18
    merged = datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00")).strftime("%b %-d, %Y")
    out += text(start, 35, clip(pr["title"], 18, WIDTH - start - 180), t, size=18)
    out += text(WIDTH - 22, 35, merged, t, size=16, fill=t["muted"], anchor="end")
    return svg(WIDTH, 64, f"{ref}: {pr['title']}", out)


def more_card(n: int, t: dict) -> str:
    label = f"and {n} more"
    return svg(WIDTH, 40, label, text(WIDTH / 2, 26, label, t, size=18, fill=t["muted"], anchor="middle"))


def picture(name: str, alt: str, href: str | None = None) -> str:
    block = (
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="{CDN}/{name}-dark.svg">\n'
        f'  <source media="(prefers-color-scheme: light)" srcset="{CDN}/{name}-light.svg">\n'
        f'  <img src="{CDN}/{name}-dark.svg" width="100%" alt="{esc(alt)}">\n'
        "</picture>"
    )
    return f'<a href="{href}">\n{block}\n</a>' if href else block


def main() -> None:
    now = datetime.now(timezone.utc)
    local_now = now.astimezone(ZoneInfo("Asia/Manila"))
    # Use GitHub's calendar dates, starting January 1 rather than a rolling year.
    year_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    user = graphql(PROFILE_QUERY, {
        "login": LOGIN, "from": year_start.isoformat(), "to": now.isoformat(),
    })["user"]
    cal = user["contributionsCollection"]["contributionCalendar"]
    days = [(d["date"], d["contributionCount"]) for w in cal["weeks"] for d in w["contributionDays"]]
    today = local_now.date().isoformat()
    days = [d for d in days if year_start.date().isoformat() <= d[0] <= today]
    current, longest = streaks(days)

    sizes: dict[str, list] = {}
    owned = owned_repos()
    for repo in owned:
        for edge in repo["languages"]["edges"]:
            entry = sizes.setdefault(edge["node"]["name"], [edge["node"]["color"], 0])
            entry[1] += edge["size"]
    langs = sorted(((n, c, s) for n, (c, s) in sizes.items()), key=lambda x: -x[2])

    prs = merged_prs()
    by_repo: OrderedDict[str, list] = OrderedDict()
    for pr in sorted(prs, key=lambda p: p["mergedAt"], reverse=True):
        by_repo.setdefault(pr["repository"]["nameWithOwner"], []).append(pr)
    repos = sorted(by_repo.values(), key=lambda v: (-len(v), v[0]["mergedAt"]))

    stats = {
        "total": sum(c for _, c in days),
        "current": current,
        "longest": longest,
        "merged": len(prs),
        "best": max((c for _, c in days), default=0),
        "active": sum(1 for _, c in days if c),
        "name": user["name"] or LOGIN,
        "joined": user["createdAt"],
        "stars": sum(r["stargazerCount"] for r in owned if not r["isPrivate"]),
        "commits": user["contributionsCollection"]["totalCommitContributions"],
        "reviews": user["contributionsCollection"]["totalPullRequestReviewContributions"],
        "contributed": user["contributionsCollection"]["totalRepositoriesWithContributedCommits"],
        "prs": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "followers": user["followers"]["totalCount"],
    }
    history = contribution_history(user["contributionsCollection"]["contributionYears"], now)
    # The year-to-date calendar is the freshest response for recent dates.
    history = sorted({**dict(history), **dict(days)}.items())
    history = [(d, c) for d, c in history if stats["joined"][:10] <= d <= today]
    stats["all_time"] = sum(c for _, c in history)
    weekly = weekly_streaks(history, local_now.date())

    # Drop last run's open source cards so a shorter list leaves no orphans.
    for old in ASSETS.glob("oss-*.svg"):
        old.unlink()
    for name, t in THEMES.items():
        card_theme = activity_theme(name)
        write("stats", name, stats_card(stats, card_theme))
        write("streak", name, streak_card(stats, weekly, card_theme))
        write("activity", name, activity(stats, langs, card_theme))
        write("calendar", name, calendar(days, stats["total"], name, card_theme, local_now.strftime("%b %d, %Y %H:%M")))
        write("oss-caption", name, caption("Merged pull requests to repositories I don't own", t))
        write("oss-merges-caption", name, caption("Latest merges", t))
        for i, group in enumerate(repos[:MAX_REPOS]):
            write(f"oss-repo-{i:02d}", name, repo_card(group[0]["repository"], len(group), t))
        for i, pr in enumerate(sorted(prs, key=lambda p: p["mergedAt"], reverse=True)[:MAX_MERGES]):
            write(f"oss-merge-{i:02d}", name, merge_card(pr, t))
        if len(repos) > MAX_REPOS:
            write("oss-more", name, more_card(len(repos) - MAX_REPOS, t))

    parts = [picture("oss-caption", "Merged pull requests to repositories I don't own")]
    for i, group in enumerate(repos[:MAX_REPOS]):
        repo = group[0]["repository"]
        parts.append(picture(f"oss-repo-{i:02d}", repo["nameWithOwner"], repo["url"]))
    if len(repos) > MAX_REPOS:
        search = f"https://github.com/search?q=is%3Apr+author%3A{LOGIN}+is%3Amerged+-user%3A{LOGIN}&type=pullrequests"
        parts.append(picture("oss-more", f"and {len(repos) - MAX_REPOS} more", search))
    if prs:
        parts.append(picture("oss-merges-caption", "Latest merges"))
        for i, pr in enumerate(sorted(prs, key=lambda p: p["mergedAt"], reverse=True)[:MAX_MERGES]):
            ref = f"{pr['repository']['nameWithOwner']}#{pr['number']}"
            parts.append(picture(f"oss-merge-{i:02d}", ref, pr["url"]))

    readme = ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")
    activity_cards = [
        picture("stats", "GitHub stats: stars earned, commits this year, pull requests, issues, and repositories contributed to this year."),
        picture("streak", "Total contributions since joining GitHub, current weekly streak, and longest weekly streak."),
        picture("calendar", "Contribution heat map from January 1 through today. Refreshed hourly with the last update time in Manila."),
        picture("activity", "Languages by bytes of code in my repositories."),
    ]
    content = re.sub(r"<!-- activity:start -->.*?<!-- activity:end -->",
                     lambda _: "<!-- activity:start -->\n" + "\n\n".join(activity_cards) + "\n<!-- activity:end -->",
                     content, flags=re.S)
    content = re.sub(r"<!-- oss:start -->.*<!-- oss:end -->",
                     lambda _: "<!-- oss:start -->\n" + "\n".join(parts) + "\n<!-- oss:end -->",
                     content, flags=re.S)
    readme.write_text(content, encoding="utf-8")
    stamp_readme()
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
