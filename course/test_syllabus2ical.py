"""Offline tests for the calendar generated from a synthetic syllabus."""

from datetime import datetime
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
import yaml


SCRIPT = Path(__file__).with_name("syllabus2ical.py").resolve()
EASTERN = ZoneInfo("America/New_York")


def render_calendar(start, end, schedule=(), *, holidays=(), starttime="9:00 PM", endtime="10:00 PM"):
    monday = {"day": "M", "starttime": starttime, "endtime": endtime}
    doc = {
        "info": {
            "course_number": "TEST 010",
            "course_title": "Calendar Fixture",
            "course_start_date": start,
            "course_end_date": end,
            "course_homepage": "https://course.example/",
            "class_meets_days": {f"is{day}": day == "M" for day in "MTWRFSU"},
            "course_sections": [{"section": "A"}],
            "class_meets_locations": [{"section": [{**monday, "place": "Fixture room"}]}],
            "midtermexam": [{"mdate": "TBD"}],
            "finalexam": [{"fdate": "TBD"}],
        },
        "instructors": [{"name": "Fixture", "officehours": [{**monday, "location": "Fixture room"}]}],
        "schedule": list(schedule),
        "university": {"semester": "Fall", "fallholidays": [{"date": date} for date in holidays], "fall": []},
    }
    with tempfile.TemporaryDirectory() as directory:
        syllabus = Path(directory) / "syllabus.md"
        syllabus.write_text("---\n" + yaml.safe_dump(doc) + "---\n", encoding="utf-8")
        cwd = Path.cwd()
        try:
            os.chdir(directory)
            with patch.object(sys, "argv", [str(SCRIPT), str(syllabus)]):
                runpy.run_path(str(SCRIPT), run_name="__main__")
            return (Path("files") / "TEST 010.ics").read_text(encoding="utf-8")
        finally:
            os.chdir(cwd)


def recurring_events(calendar):
    for event in calendar.split("BEGIN:VEVENT\n")[1:]:
        lines = event.splitlines()
        recurrence = [line for line in lines if line.startswith(("DTSTART", "RRULE", "EXDATE"))]
        summary = next(line.removeprefix("SUMMARY:") for line in lines if line.startswith("SUMMARY:"))
        yield summary, recurrence


class SyllabusCalendarTest(unittest.TestCase):
    def test_pinned_deliverable_uses_the_explicit_class_date(self):
        calendar = render_calendar("2026/10/19", "2026/10/26", [{
            "week": 0, "date": 0, "cdate": "2026/10/22", "title": "Rescheduled class",
            "deliverables": [{"dtitle": "Fixture project due"}],
        }])
        event = next(event for event in calendar.split("BEGIN:VEVENT\n")
                     if "SUMMARY:TEST 010 Calendar Fixture: Fixture project due" in event)
        self.assertIn("DTSTART;VALUE=DATE:20261022\n", event)

    def test_evening_recurrences_include_last_eastern_day(self):
        for start, end in (("2026/10/19", "2026/10/26"), ("2026/11/02", "2026/11/09")):
            last = datetime.strptime(end + " 21:00", "%Y/%m/%d %H:%M").replace(tzinfo=EASTERN)
            with self.subTest(end=end):
                events = list(recurring_events(render_calendar(start, end)))
                self.assertEqual(len(events), 2)
                for summary, recurrence in events:
                    dates = list(rrulestr("\n".join(recurrence), tzids={"US-Eastern": EASTERN}))
                    self.assertEqual(len(dates), 2, summary)
                    self.assertEqual(dates[-1], last, summary)

    def test_evening_recurrences_exclude_only_matching_weekday_holidays(self):
        calendar = render_calendar(
            "2026/10/19", "2026/11/09", holidays=("2026/10/26", "2026/11/03"),
        )
        expected = [datetime(2026, month, day, 21, tzinfo=EASTERN)
                    for month, day in ((10, 19), (11, 2), (11, 9))]
        events = list(recurring_events(calendar))
        self.assertEqual(len(events), 2)
        for summary, recurrence in events:
            with self.subTest(summary=summary):
                self.assertEqual(
                    [line for line in recurrence if line.startswith("EXDATE")],
                    ["EXDATE;TZID=US-Eastern:20261026T210000"],
                )
                dates = rrulestr("\n".join(recurrence), tzids={"US-Eastern": EASTERN})
                self.assertEqual(list(dates), expected)

    def test_daytime_recurrences_keep_both_mondays(self):
        calendar = render_calendar(
            "2026/11/02", "2026/11/09", starttime="11:00 AM", endtime="12:00 PM",
        )
        events = list(recurring_events(calendar))
        self.assertEqual(len(events), 2)
        for summary, recurrence in events:
            with self.subTest(summary=summary):
                dates = rrulestr("\n".join(recurrence), tzids={"US-Eastern": EASTERN})
                self.assertEqual(list(dates), [
                    datetime(2026, 11, 2, 11, tzinfo=EASTERN),
                    datetime(2026, 11, 9, 11, tzinfo=EASTERN),
                ])


if __name__ == "__main__":
    unittest.main()
