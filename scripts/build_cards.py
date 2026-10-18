"""Render the cards that come from live GitHub data: the activity panel and the
open source list. Also rewrites the open source block in README.md, because
the number of repos there changes over time.

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
from datetime import date, datetime

from svgkit import ASSETS, ROOT, stamp_readme, THEMES, WIDTH, esc, rect, svg, text, text_width, write

LOGIN = "EugeneCarldotme"
CDN = f"https://raw.githubusercontent.com/{LOGIN}/{LOGIN}/main/assets"
MAX_REPOS = 6
MAX_MERGES = 3

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
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


def activity(stats: dict, langs: list[tuple[str, str, int]], t: dict) -> str:
    tile_w, tile_h, gap = 386, 110, 21
    tiles = [
        ("Contributions (12 mo)", f"{stats['total']:,}"),
        ("Current streak", plural(stats["current"], "day")),
        ("Longest streak (12 mo)", plural(stats["longest"], "day")),
        ("Merged PRs in other repos", f"{stats['merged']:,}"),
        ("Best day (12 mo)", plural(stats["best"], "contribution")),
        ("Active days (12 mo)", f"{stats['active']:,}"),
    ]
    out = ""
    for i, (label, value) in enumerate(tiles):
        x = (i % 3) * (tile_w + (WIDTH - 3 * tile_w) / 2)
        y = (i // 3) * (tile_h + gap)
        out += rect(x + 0.5, y + 0.5, tile_w - 1, tile_h - 1, t["panel"], rx=14, stroke=t["border"])
        out += text(x + 22, y + 38, label, t, size=18, fill=t["muted"])
        out += text(x + 22, y + 88, value, t, size=40, weight=600, fill=t["text"])

    top = 2 * (tile_h + gap)
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
    label = (f"{stats['total']:,} contributions in the last year, {plural(stats['current'], 'day')} current streak, "
             f"{stats['merged']} merged PRs in other repos. Top languages: "
             + ", ".join(n for n, _, _ in shown) + ".")
    return svg(WIDTH, height, label, out)


def caption(label: str, t: dict) -> str:
    return svg(WIDTH, 36, label, text(0, 24, label, t, size=18, fill=t["muted"]))


def repo_card(repo: dict, count: int, t: dict) -> str:
    out = rect(0.5, 0.5, WIDTH - 1, 79, t["panel"], rx=14, stroke=t["border"])
    lang = repo.get("primaryLanguage") or {}
    out += f'  <circle cx="24" cy="40" r="5" fill="{lang.get("color") or t["accent"]}"/>\n'
    out += text(46, 34, repo["nameWithOwner"], t, size=22, weight=600)
    meta = " · ".join(x for x in (lang.get("name"), f"★ {repo['stargazerCount']:,}") if x)
    out += text(46, 62, clip(f"{meta} · {repo.get('description') or ''}".rstrip(" ·"), 16, 900), t, size=16,
                fill=t["muted"])
    out += text(WIDTH - 24, 46, f"{count} merged", t, size=18, fill=t["muted"], anchor="end")
    return svg(WIDTH, 88, repo["nameWithOwner"], out)


def merge_card(pr: dict, t: dict) -> str:
    out = rect(0.5, 0.5, WIDTH - 1, 55, t["panel"], rx=12, stroke=t["border"])
    ref = f"{pr['repository']['nameWithOwner']}#{pr['number']}"
    out += text(22, 35, ref, t, size=17, fill=t["muted"], mono=True)
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
    user = graphql(PROFILE_QUERY, {"login": LOGIN})["user"]
    cal = user["contributionsCollection"]["contributionCalendar"]
    days = [(d["date"], d["contributionCount"]) for w in cal["weeks"] for d in w["contributionDays"]]
    today = date.today().isoformat()
    days = [d for d in days if d[0] <= today]
    current, longest = streaks(days)

    sizes: dict[str, list] = {}
    for repo in owned_repos():
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
        "total": cal["totalContributions"],
        "current": current,
        "longest": longest,
        "merged": len(prs),
        "best": max((c for _, c in days), default=0),
        "active": sum(1 for _, c in days if c),
    }

    # Drop last run's open source cards so a shorter list leaves no orphans.
    for old in ASSETS.glob("oss-*.svg"):
        old.unlink()
    for name, t in THEMES.items():
        write("activity", name, activity(stats, langs, t))
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
    content = re.sub(r"<!-- oss:start -->.*<!-- oss:end -->",
                     lambda _: "<!-- oss:start -->\n" + "\n".join(parts) + "\n<!-- oss:end -->",
                     content, flags=re.S)
    readme.write_text(content, encoding="utf-8")
    stamp_readme()
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
