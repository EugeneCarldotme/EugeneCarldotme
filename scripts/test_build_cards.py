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
            calendar = {"totalContributions": count, "weeks": [{"contributionDays": [
                {"date": day, "contributionCount": count},
            ]}]}
            collection = {"contributionCalendar": calendar, "contributionYears": [now.year],
                          "totalCommitContributions": count, "totalPullRequestReviewContributions": 0,
                          "totalRepositoriesWithContributedCommits": 1}
            return {"user": {"name": "Eugene Carl", "createdAt": "2023-07-11T13:02:53Z",
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
                self.assertIn("4 contributions in the last year", new_svg)
                self.assertIn("Updated ", new_svg)
                self.assertIn("4 total contributions", (assets / "streak-dark.svg").read_text())
                for path in assets.glob("*.svg"):
                    ET.parse(path)


if __name__ == "__main__":
    unittest.main()
