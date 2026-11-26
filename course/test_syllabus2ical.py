"""Offline tests for the calendar generated from a synthetic syllabus."""

import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


SCRIPT = Path(__file__).with_name("syllabus2ical.py").resolve()


def render_calendar(start, end, schedule=()):
    evening = {"day": "M", "starttime": "9:00 PM", "endtime": "10:00 PM"}
    doc = {
        "info": {
            "course_number": "TEST 010",
            "course_title": "Calendar Fixture",
            "course_start_date": start,
            "course_end_date": end,
            "course_homepage": "https://course.example/",
            "class_meets_days": {f"is{day}": day == "M" for day in "MTWRFSU"},
            "course_sections": [{"section": "A"}],
            "class_meets_locations": [{"section": [{**evening, "place": "Fixture room"}]}],
            "midtermexam": [{"mdate": "TBD"}],
            "finalexam": [{"fdate": "TBD"}],
        },
        "instructors": [{"name": "Fixture", "officehours": [{**evening, "location": "Fixture room"}]}],
        "schedule": list(schedule),
        "university": {"semester": "Fall", "fallholidays": [], "fall": []},
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


class SyllabusCalendarTest(unittest.TestCase):
    def test_pinned_deliverable_uses_the_explicit_class_date(self):
        calendar = render_calendar("2026/10/19", "2026/10/26", [{
            "week": 0, "date": 0, "cdate": "2026/10/22", "title": "Rescheduled class",
            "deliverables": [{"dtitle": "Fixture project due"}],
        }])
        event = next(event for event in calendar.split("BEGIN:VEVENT\n")
                     if "SUMMARY:TEST 010 Calendar Fixture: Fixture project due" in event)
        self.assertIn("DTSTART;VALUE=DATE:20261022\n", event)


if __name__ == "__main__":
    unittest.main()
