"""Regression checks for calendar refreshes, cache invalidation, and week boundaries."""

import contextlib
import io
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import build_cards as cards
import svgkit


class WeeklyStreakTests(unittest.TestCase):
    def test_multiple_active_days_count_as_one_week(self):
        result = cards.weekly_streaks([("2026-10-18", 3), ("2026-10-21", 4)], date(2026, 10, 21))
        self.assertEqual((result["current"], result["longest"]), (1, 1))

    def test_unfinished_empty_week_keeps_previous_streak(self):
        result = cards.weekly_streaks([("2026-10-04", 1), ("2026-10-11", 1)], date(2026, 10, 21))
        self.assertEqual((result["current"], result["longest"]), (2, 2))
        self.assertEqual(result["current_end"], date(2026, 10, 17))

    def test_completed_empty_week_breaks_current_streak(self):
        result = cards.weekly_streaks([("2026-10-04", 1), ("2026-10-11", 1)], date(2026, 10, 25))
        self.assertEqual((result["current"], result["longest"]), (0, 2))
        self.assertIsNone(result["current_start"])

    def test_streak_crosses_new_year_and_sunday_boundary(self):
        result = cards.weekly_streaks([("2025-12-27", 1), ("2025-12-28", 1), ("2026-01-04", 1)], date(2026, 1, 4))
        self.assertEqual((result["current"], result["longest"]), (3, 3))
        self.assertEqual(result["current_start"], date(2025, 12, 21))
        self.assertEqual(result["current_end"], date(2026, 1, 4))

    def test_empty_history_and_future_days(self):
        for days in ([], [("2026-10-22", 10)], [("2026-10-21", 0)]):
            result = cards.weekly_streaks(days, date(2026, 10, 21))
            self.assertEqual((result["current"], result["longest"]), (0, 0))


class RefreshTests(unittest.TestCase):
    def test_new_contribution_changes_svg_and_readme_image_urls(self):
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        count = 3

        def live_response(query, variables):
            if query in (cards.PROFILE_QUERY, cards.VIEWER_PROFILE_QUERY):
                start = datetime.fromisoformat(variables["from"])
                self.assertEqual(start, datetime(now.year, 1, 1, tzinfo=timezone.utc))
                self.assertLessEqual(datetime.fromisoformat(variables["to"]), datetime.now(timezone.utc))
            calendar = {"totalContributions": count, "weeks": [{"contributionDays": [
                {"date": day, "contributionCount": count},
            ]}]}
            if query in (cards.PROFILE_QUERY, cards.VIEWER_PROFILE_QUERY):
                # Calendar week padding must not bring last year's days into this year's heat map.
                calendar["weeks"][0]["contributionDays"].insert(0, {
                    "date": f"{now.year - 1}-12-31", "contributionCount": 99,
                })
            collection = {"contributionCalendar": calendar, "contributionYears": [now.year],
                          "totalCommitContributions": count, "totalPullRequestReviewContributions": 0,
                          "totalRepositoriesWithContributedCommits": 1,
                          "commitContributionsByRepository": []}
            return {"user": {"id": "profile-id", "login": cards.LOGIN,
                             "name": "Eugene Carl", "createdAt": "2023-07-11T13:02:53Z",
                             "followers": {"totalCount": 6}, "pullRequests": {"totalCount": 2},
                             "issues": {"totalCount": 0}, "contributionsCollection": collection}}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assets = root / "assets"
            readme = root / "README.md"
            readme.write_text("<!-- activity:start --><!-- activity:end -->\n<!-- oss:start --><!-- oss:end -->")
            with (patch.object(cards, "ROOT", root), patch.object(cards, "ASSETS", assets),
                  patch.object(svgkit, "ROOT", root), patch.object(svgkit, "ASSETS", assets),
                  patch.object(cards, "graphql", side_effect=live_response),
                  patch.object(cards, "owned_repos", return_value=[]),
                  patch.object(cards, "merged_prs", return_value=[]),
                  patch.object(cards, "private_stats", return_value={"commits": 12, "contributed": 2}),
                  contextlib.redirect_stdout(io.StringIO())):
                cards.main()
                old_svg = (assets / "calendar-dark.svg").read_text()
                old_readme = readme.read_text()
                count += 1  # GitHub reports a new contribution on the next run.
                cards.main()
                new_svg = (assets / "calendar-dark.svg").read_text()
                new_readme = readme.read_text()
                self.assertNotEqual(old_svg, new_svg)
                self.assertNotEqual(old_readme, new_readme)
                calendar_url = r'calendar-dark\.svg\?v=[a-f0-9]+'
                self.assertNotEqual(re.search(calendar_url, old_readme).group(),
                                    re.search(calendar_url, new_readme).group())
                self.assertIn("4 contributions this year", new_svg)
                self.assertNotIn(f"{now.year - 1}-12-31", new_svg)
                self.assertIn("Total commits (this year)", (assets / "stats-dark.svg").read_text())
                self.assertIn("Total commits (this year): 16", (assets / "stats-dark.svg").read_text())
                self.assertIn("Updated ", new_svg)
                self.assertIn("4 total contributions", (assets / "streak-dark.svg").read_text())
                for path in assets.glob("*.svg"):
                    ET.parse(path)


class PrivateStatsTests(unittest.TestCase):
    def test_private_commits_paginate_and_do_not_count_already_included_repos(self):
        def repo(repo_id, count):
            return {"id": repo_id, "defaultBranchRef": {"target": {"history": {"totalCount": count}}}}

        responses = [
            {"viewer": {"repositories": {
                "nodes": [repo("already-counted", 50), repo("private-1", 12), repo("inactive", 0)],
                "pageInfo": {"hasNextPage": True, "endCursor": "page-2"},
            }}},
            {"viewer": {"repositories": {
                "nodes": [repo("private-2", 8), {"id": "empty", "defaultBranchRef": None}],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }}},
        ]
        user = {"id": "profile-id", "contributionsCollection": {
            "commitContributionsByRepository": [{"repository": {"id": "already-counted", "isPrivate": True}}],
        }}
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 10, 21, tzinfo=timezone.utc)
        with (patch.dict("os.environ", {"GH_STATS_TOKEN": "test-token"}),
              patch.object(cards, "graphql", side_effect=responses) as api,
              contextlib.redirect_stderr(io.StringIO())):
            self.assertEqual(cards.private_stats(user, start, end), {"commits": 20, "contributed": 2})
            self.assertEqual(api.call_args_list[1].args[1]["after"], "page-2")
            self.assertEqual(api.call_args_list[0].args[1]["author"], "profile-id")

    def test_private_repository_details_never_enter_open_source_cards(self):
        response = {"search": {
            "nodes": [{"repository": {"isPrivate": True, "nameWithOwner": "private/name"}},
                      {"repository": {"isPrivate": False, "nameWithOwner": "public/name"}}],
            "pageInfo": {"hasNextPage": False},
        }}
        with patch.object(cards, "graphql", return_value=response) as api:
            result = cards.merged_prs()
            self.assertEqual([r["repository"]["nameWithOwner"] for r in result], ["public/name"])
            self.assertIn("is:public", api.call_args.args[1]["q"])

    def test_missing_contents_permission_does_not_silently_return_public_only_counts(self):
        user = {"id": "profile-id", "contributionsCollection": {"commitContributionsByRepository": []}}
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        with (patch.dict("os.environ", {"GH_STATS_TOKEN": "test-token"}),
              patch.object(cards, "graphql", side_effect=cards.GitHubAPIError("Resource not accessible"))):
            with self.assertRaisesRegex(cards.GitHubAPIError, "read-only Contents"):
                cards.private_stats(user, now, now)


if __name__ == "__main__":
    unittest.main()
