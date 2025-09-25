
#!/usr/bin/env python3
"""
Update Canvas assignment due dates and reorder modules from a syllabus Markdown file.

- Reads a Jekyll-style Markdown file with YAML frontmatter (e.g., syllabus2.md).
- Computes calendar dates from course_start_date and class meeting pattern.
- Sets Canvas assignment due dates for any deliverables whose titles end with "Due".
- Reorders Canvas Modules to match the chronological order of the syllabus schedule.

Assumptions
-----------
- The Canvas course and assignments/modules already exist.
- Assignment names in Canvas correspond to the deliverable titles with trailing
  markers like " Due" or " Handed Out" removed. For example:
    "Written Assignment: Warmup Due"  -> Canvas assignment named "Written Assignment: Warmup"
- Activity modules should match against "Activity: xxx"    
- Module titles in Canvas match the `title` field in each schedule entry.
- Timezone defaults to America/New_York.
- Due time defaults to 23:59:00 local time on the due date.

Configuration
-------------
Provide configuration via environment variables or a JSON file.

Environment variables:
  CANVAS_API_URL     e.g., https://ursinus.instructure.com
  CANVAS_API_TOKEN   (a valid access token)
  CANVAS_COURSE_ID   (numeric Canvas course id)
  TZ                 (optional, default America/New_York)

OR pass a JSON config with the same keys via --config /path/to/config.json

CLI
---
Dry-run (no changes):
  python canvas_update_schedule_from_md.py syllabus2.md

Apply changes:
  python canvas_update_schedule_from_md.py syllabus2.md --apply

Dependencies
------------
- PyYAML
- python-frontmatter (optional; we parse manually but this helps in other contexts)
- python-dateutil
- pytz
- canvasapi  (preferred)  OR requests (fallback if canvasapi unavailable)

Install: pip install PyYAML python-dateutil pytz canvasapi

Usage:

# 1) Install deps (one time)
pip install PyYAML python-dateutil pytz canvasapi requests

# 2) Export configuration (or use --config JSON)
export CANVAS_API_URL="https://<your_canvas_domain>"
export CANVAS_API_TOKEN="<your_token>"
export CANVAS_COURSE_ID="<numeric_course_id>"
export TZ="America/New_York"   # optional, default shown

# 3) Dry-run (shows intended changes, makes none)
python canvas_update_schedule_from_md.py /path/to/syllabus2.md

# 4) Apply changes to Canvas (assignments + modules)
python canvas_update_schedule_from_md.py /path/to/syllabus2.md --apply

# Optional: JSON config (keys: CANVAS_API_URL, CANVAS_API_TOKEN, CANVAS_COURSE_ID, TZ)
python canvas_update_schedule_from_md.py /path/to/syllabus2.md --config config.json --apply
"""

import argparse
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time, date
from typing import Any, Dict, List, Optional, Tuple

import yaml
from dateutil import tz
import requests

# Utilities

DAY_ORDER = ["M", "T", "W", "R", "F", "S", "U"]
DAY_TO_WEEKDAY = {"M": 0, "T": 1, "W": 2, "R": 3, "F": 4, "S": 5, "U": 6}

def _err(prefix: str, e: Exception) -> None:
    print(f"[{prefix}] {e}")
    traceback.print_exc()

def _load_config(path: Optional[str]) -> Dict[str, Any]:
    cfg = {}
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            _err("config", e)
            print("Proceeding without config file (relying on environment variables).")
    cfg["CANVAS_API_URL"] = os.getenv("CANVAS_API_URL", cfg.get("CANVAS_API_URL"))
    cfg["CANVAS_API_TOKEN"] = os.getenv("CANVAS_API_TOKEN", cfg.get("CANVAS_API_TOKEN"))
    cfg["CANVAS_COURSE_ID"] = os.getenv("CANVAS_COURSE_ID", cfg.get("CANVAS_COURSE_ID"))
    cfg["TZ"] = os.getenv("TZ", cfg.get("TZ", "America/New_York"))
    return cfg

def _split_frontmatter(md_text: str) -> Tuple[Dict[str, Any], str]:
    fm: Dict[str, Any] = {}
    body = md_text
    if md_text.startswith("---"):
        parts = md_text.split("---", 2)
        if len(parts) >= 3:
            _, yml, body = parts[0], parts[1], parts[2]
            try:
                fm = yaml.safe_load(yml) or {}
            except Exception as e:
                _err("frontmatter.parse", e)
    return fm, body

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()

def _strip_markers(title: str) -> str:
    """
    Normalize a deliverable/assignment title by:
      - removing common leading labels like 'Activity:', 'Assignment:', 'Quiz:' (case-insensitive)
      - removing trailing markers like ' Due' or ' Handed Out' (case-insensitive)
      - trimming surrounding whitespace

    Examples:
      'Activity: Warmup Due'      -> 'Warmup'
      'assignment: Project 1 Due' -> 'Project 1'
      'Quiz: Intro Handed Out'    -> 'Intro'
      'Warmup Due'                -> 'Warmup'
    """
    s = title.strip()

    # Strip one leading label of the form '<label>:' where label is in the set below.
    # Extend the set if your course uses other labels.
    s = re.sub(r'^(activity|assignment|quiz)\s*:\s*', '', s, flags=re.IGNORECASE)

    # Strip trailing status markers
    s = re.sub(r'\s+(Due|Handed Out)\s*$', '', s, flags=re.IGNORECASE)

    return s.strip()

def _parse_date_yyyy_slash_mm_slash_dd(s: str) -> date:
    return datetime.strptime(s, "%Y/%m/%d").date()

def _to_utc_iso(dt_local: datetime, zone_name: str) -> str:
    """
    Convert a naive local datetime (interpreted in zone_name) to a Zulu ISO 8601 string.
    """
    zone = tz.gettz(zone_name)
    dt_zoned = dt_local.replace(tzinfo=zone)
    dt_utc = dt_zoned.astimezone(tz.UTC)
    return dt_utc.replace(tzinfo=tz.UTC).isoformat().replace("+00:00", "Z")

# Data extraction

@dataclass
class Meeting:
    week: int
    ordinal_in_week: int
    title: str
    date: date
    link: Optional[str] = None  # NEW: the schedule item's main link
    activities: List[Dict[str, str]] = field(default_factory=list)  # [{"title": str, "url": optional str}]
    readings:  List[Dict[str, str]] = field(default_factory=list)   # [{"rtitle": str, "rlink": optional str}]

@dataclass
class Deliverable:
    title: str
    week: int
    ordinal_in_week: int
    due: bool

@dataclass
class SyllabusPlan:
    meetings: List[Meeting]
    deliverables_due: List[Deliverable]
    deliverables_handed_out: List["Deliverable"]

def _sorted_meeting_dates(plan: "SyllabusPlan") -> List[date]:
    return sorted({m.date for m in plan.meetings})

def _previous_meeting_on_or_before(d0: date, meeting_dates: List[date]) -> Optional[date]:
    prev = None
    for md in meeting_dates:
        if md > d0:
            break
        prev = md
    return prev

def _next_meeting_on_or_after(d0: date, meeting_dates: List[date]) -> Optional[date]:
    # Linear scan is fine at course scale; binary search if you prefer.
    for md in meeting_dates:
        if md >= d0:
            return md
    return None

def _assignment_url(a: Dict[str, Any]) -> Optional[str]:
    # Canvas assignments usually expose 'html_url'
    return a.get("html_url") or a.get("url")

def _active_days_from(fm: Dict[str, Any]) -> List[str]:
    info = fm.get("info", {})
    days = info.get("class_meets_days", {})
    active: List[str] = []
    for d in DAY_ORDER:
        if days.get(f"is{d}", False):
            active.append(d)
    return active

def _first_monday_on_or_before(d: date) -> date:
    return d - timedelta(days=d.weekday())

def _compute_date_for_week_and_ordinal(course_start: date, day_code: str, week: int) -> date:
    w0_monday = _first_monday_on_or_before(course_start)
    target_wd = DAY_TO_WEEKDAY[day_code]
    monday = w0_monday + timedelta(weeks=week)
    return monday + timedelta(days=target_wd)

def _as_items_list(obj: Any, default_prefix: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Normalize a list-like field into [{"title": ..., "url": ...}, ...].

    Accepts items as strings or dicts. For dicts, we look for:
      - title/name/rtitle
      - url/link/rlink
    If default_prefix is provided and the title doesn't already start with a label
    (e.g., "Activity:"), we prefix it.
    """
    out: List[Dict[str, str]] = []
    if obj is None:
        return out

    def _canon_title(t: str) -> str:
        t = (t or "").strip()
        if not t:
            return t
        if default_prefix and not _starts_with_label(t):
            return f"{default_prefix} {t}"
        return t

    if isinstance(obj, str):
        t = obj.strip()
        if t:
            out.append({"title": _canon_title(t)})
        return out

    if isinstance(obj, list):
        for it in obj:
            if isinstance(it, str):
                t = it.strip()
                if t:
                    out.append({"title": _canon_title(t)})
            elif isinstance(it, dict):
                # titles: title | name | rtitle
                t = (it.get("title") or it.get("name") or it.get("rtitle") or "").strip()
                # urls: url | link | rlink
                u = (it.get("url") or it.get("link") or it.get("rlink") or "").strip()
                if not t:
                    continue
                rec = {"title": _canon_title(t)}
                if u:
                    rec["url"] = u
                out.append(rec)
    return out

def _extract_plan(fm: Dict[str, Any]) -> SyllabusPlan:
    info = fm.get("info", {})
    course_start = _parse_date_yyyy_slash_mm_slash_dd(info["course_start_date"])
    active_days = _active_days_from(fm)
    if not active_days:
        raise ValueError("No active meeting days found in frontmatter info.class_meets_days")

    schedule = fm.get("schedule", [])
    meetings: List[Meeting] = []
    deliverables_due: List[Deliverable] = []
    deliverables_handed_out: List[Deliverable] = []

    for entry in schedule:
        try:
            w = int(entry["week"]); ordinal = int(entry["date"])
        except Exception:
            continue
        if ordinal < 0 or ordinal >= len(active_days):
            continue

        day_code = active_days[ordinal]
        when = _compute_date_for_week_and_ordinal(course_start, day_code, w)

        title = (entry.get("title", "") or "").strip()
        main_link = (entry.get("link", "") or "").strip()

        # Accept variants for activities and readings
        acts_raw = (
            entry.get("activities", None)
            or entry.get("activity", None)
            or entry.get("in_class", None)
            or []
        )
        # readings is an array of {rtitle, rlink} (rlink optional)
        reads_raw = entry.get("readings", []) or []

        acts  = _as_items_list(acts_raw,  default_prefix="Activity:")
        # normalize readings into [{"title":..., "url":...}] shape where url may be missing
        reads: List[Dict[str, str]] = []
        for r in reads_raw:
            if isinstance(r, dict):
                rt = (r.get("rtitle") or r.get("title") or "").strip()
                ru = (r.get("rlink")  or r.get("url")   or "").strip()
                if rt:
                    rec = {"title": rt}
                    if ru:
                        rec["url"] = ru
                    reads.append(rec)
            elif isinstance(r, str):
                t = r.strip()
                if t:
                    reads.append({"title": t})

        meetings.append(
            Meeting(
                week=w,
                ordinal_in_week=ordinal,
                title=title,
                date=when,
                link=main_link,
                activities=acts,
                readings=reads,
            )
        )

        for d in entry.get("deliverables", []) or []:
            dtitle = (d.get("dtitle", "") or "").strip()
            if not dtitle:
                continue
            if re.search(r"\bDue\b$", dtitle, flags=re.IGNORECASE):
                deliverables_due.append(Deliverable(title=dtitle, week=w, ordinal_in_week=ordinal, due=True))
            elif re.search(r"\bHanded\s+Out\b$", dtitle, flags=re.IGNORECASE):
                deliverables_handed_out.append(Deliverable(title=dtitle, week=w, ordinal_in_week=ordinal, due=False))

    meetings.sort(key=lambda m: (m.week, m.ordinal_in_week))
    deliverables_due.sort(key=lambda d: (d.week, d.ordinal_in_week, _norm(d.title)))
    deliverables_handed_out.sort(key=lambda d: (d.week, d.ordinal_in_week, _norm(d.title)))

    return SyllabusPlan(
        meetings=meetings,
        deliverables_due=deliverables_due,
        deliverables_handed_out=deliverables_handed_out,
    )

# Canvas client (requests-only to keep surface small for this utility)

class CanvasClient:
    def __init__(self, api_url: str, token: str, course_id: str):
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.course_id = str(course_id)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _next_link(self, link_header: Optional[str]) -> Optional[str]:
        if not link_header:
            return None
        for p in [p.strip() for p in link_header.split(",")]:
            m = re.match(r'<([^>]+)>\s*;\s*rel="next"', p)
            if m:
                return m.group(1)
        return None

    def list_assignments(self) -> List[Dict[str, Any]]:
        out = []
        url = f"{self.api_url}/api/v1/courses/{self.course_id}/assignments"
        params = {"per_page": 100}
        while url:
            r = requests.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            out.extend(r.json())
            url = self._next_link(r.headers.get("Link"))
            params = None
        return out

    def update_assignment(self, assignment_id: int, **fields) -> Optional[Dict[str, Any]]:
        url = f"{self.api_url}/api/v1/courses/{self.course_id}/assignments/{assignment_id}"
        r = requests.put(url, headers=self.headers, json={"assignment": fields})
        if r.status_code >= 400:
            print(f"[requests.update_assignment] HTTP {r.status_code}: {r.text[:200]}")
            return None
        return r.json()

    def list_modules(self) -> List[Dict[str, Any]]:
        out = []
        url = f"{self.api_url}/api/v1/courses/{self.course_id}/modules"
        params = {"per_page": 100}
        while url:
            r = requests.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            out.extend(r.json())
            url = self._next_link(r.headers.get("Link"))
            params = None
        return out
        
    def delete_module(self, module_id: int) -> bool:
        url = f"{self.api_url}/api/v1/courses/{self.course_id}/modules/{module_id}"
        r = requests.delete(url, headers=self.headers)
        if r.status_code >= 400:
            print(f"[requests.delete_module] HTTP {r.status_code}: {r.text[:200]}")
            return False
        return True

    def list_module_items(self, module_id: int) -> List[Dict[str, Any]]:
        out = []
        url = f"{self.api_url}/api/v1/courses/{self.course_id}/modules/{module_id}/items"
        params = {"per_page": 100}
        while url:
            r = requests.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            out.extend(r.json())
            url = self._next_link(r.headers.get("Link"))
            params = None
        return out

    def create_module(self, name: str, position: Optional[int] = None, published: bool = True) -> Optional[Dict[str, Any]]:
        url = f"{self.api_url}/api/v1/courses/{self.course_id}/modules"
        payload = {"module": {"name": name, "published": published}}
        if position is not None:
            payload["module"]["position"] = position
        r = requests.post(url, headers=self.headers, json=payload)
        if r.status_code >= 400:
            print(f"[requests.create_module] HTTP {r.status_code}: {r.text[:200]}")
            return None
        return r.json()

    def create_module_item(self, module_id: int, **fields) -> Optional[Dict[str, Any]]:
        """
        fields example for assignment:
            {"type": "Assignment", "content_id": <assignment_id>, "published": True}
        fields example for page:
            {"type": "Page", "page_url": <slug>, "published": True}
        """
        url = f"{self.api_url}/api/v1/courses/{self.course_id}/modules/{module_id}/items"
        r = requests.post(url, headers=self.headers, json={"module_item": fields})
        if r.status_code >= 400:
            print(f"[requests.create_module_item] HTTP {r.status_code}: {r.text[:200]}")
            return None
        return r.json()

    def list_pages(self) -> List[Dict[str, Any]]:
        """
        Returns course wiki pages (title + url slug).
        Note: Canvas paginates; we fetch them all.
        """
        out = []
        url = f"{self.api_url}/api/v1/courses/{self.course_id}/pages"
        params = {"per_page": 100}
        while url:
            r = requests.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            out.extend(r.json())
            url = self._next_link(r.headers.get("Link"))
            params = None
        return out        

def _activity_title_label(title: str) -> str:
    """
    Ensure activity titles have a single leading 'Activity:' label.
    Examples:
      'Introduction: Tools'      -> 'Activity: Introduction: Tools'
      'Activity: Tools'          -> 'Activity: Tools'   (unchanged)
      'Activity: Activity: X'    -> 'Activity: X'
    """
    s = (title or "").strip()
    # Strip any existing leading <label>:
    s = re.sub(r'^[A-Za-z][A-Za-z0-9 ]*\s*:\s*', lambda m: '' if m.group(0).lower().startswith('activity') else s, s, count=1, flags=re.IGNORECASE) if s.lower().startswith('activity:') else s
    # Also collapse any accidental doubled "Activity: " prefixes
    s = re.sub(r'^(?:activity\s*:\s*)+', '', s, flags=re.IGNORECASE)
    return f"Activity: {s}" if s else "Activity:"


def _resolve_url(url: Optional[str], base_url: Optional[str]) -> Optional[str]:
    """
    Resolve URLs with the following rules:
    - If url is None/empty -> None.
    - If url starts with http:// or https:// -> return as-is.
    - Otherwise, if base_url is provided, append the url *verbatim* to base_url with a single '/'.
      IMPORTANT: We do NOT strip '../' segments — they must remain in the final URL.
      Example: base_url='https://site.edu/course', url='../Ursinus-CS357-Overview'
               => 'https://site.edu/course/../Ursinus-CS357-Overview'
    """
    if not url:
        return None
    s = url.strip()
    if re.match(r'^https?://', s, flags=re.IGNORECASE):
        return s
    if base_url:
        return f"{base_url.rstrip('/')}/{s}"
    return None

def _is_url(s: Optional[str]) -> bool:
    """
    Treat absolute web URLs AND site-relative / repo-relative paths as valid links.

    Examples that return True:
      - https://example.com/page
      - http://example.com/page
      - /docs/syllabus
      - ../Ursinus-CS357-Overview
      - ../../assets/handout.pdf
      - ./slides/intro.html
    """
    if not s:
        return False
    u = s.strip()
    # absolute http(s)
    if re.match(r'^(https?://)', u, flags=re.IGNORECASE):
        return True
    # site-relative or repo-relative paths (/..., ../..., ../../..., ./...)
    if re.match(r'^(/|(\.\./)+|\./)', u):
        return True
    return False

def _canonical_activity_title(schedule_title: str) -> str:
    raw = schedule_title.strip()
    return raw if _starts_with_label(raw) else f"Activity: {raw}"

def _canonical_item_title(s: str, default_prefix: Optional[str] = None, always_prefix: bool = False) -> str:
    """
    Return a canonical display title.

    - If always_prefix is True and default_prefix is provided:
        * Prepend the prefix unless the string already starts with that exact label
          (case-insensitive), e.g., avoid "Activity: Activity: X".
    - Else, prepend default_prefix only when the string doesn't already start with any label ("X: ").
    """
    s = (s or "").strip()
    if not s:
        return s

    if always_prefix and default_prefix:
        # If s already starts with the same label, don't add it again
        label = default_prefix.strip()
        if re.match(rf"^{re.escape(label)}\s*", s, flags=re.IGNORECASE):
            return s
        return f"{label} {s}"

    return s if _starts_with_label(s) or not default_prefix else f"{default_prefix} {s}"

def _starts_with_label(s: str) -> bool:
    return bool(re.match(r'^[A-Za-z][A-Za-z0-9 ]*\s*:\s*', s.strip()))

def _date_header(d: date) -> str:
    # 'Tue, Sep 23, 2025'
    return datetime(d.year, d.month, d.day).strftime("%a, %b %d, %Y")

def _local_is_dst(d: date, tz_name: str) -> bool:
    zone = tz.gettz(tz_name)
    # 12:00 (noon) local minimizes DST transition edge concerns
    naive_noon = datetime.combine(d, time(12, 0, 0))
    localized = naive_noon.replace(tzinfo=zone)
    return bool(localized.dst())

def due_date_for(d: Deliverable, plan: SyllabusPlan) -> date:
    for m in plan.meetings:
        if m.week == d.week and m.ordinal_in_week == d.ordinal_in_week:
            return m.date
    raise ValueError(f"Meeting not found for deliverable {d.title} (week {d.week} ordinal {d.ordinal_in_week})")

def build_due_map(plan: SyllabusPlan, tz_name: str) -> Dict[str, str]:
    """
    Mapping: normalized assignment name -> ISO8601 Z (UTC) due_at
    Original semantics:
      - due date is meeting date + 1 day
      - due time is 03:59:59Z (if local DST) or 04:59:59Z (if local standard time)
    """
    due_map: Dict[str, str] = {}
    for d in plan.deliverables_due:
        base_date = due_date_for(d, plan)
        eff_date = base_date + timedelta(days=1)  # +1 day
        if _local_is_dst(eff_date, tz_name):
            # 03:59:59Z
            due_iso = datetime(eff_date.year, eff_date.month, eff_date.day, 3, 59, 59, tzinfo=tz.UTC).isoformat().replace("+00:00", "Z")
        else:
            # 04:59:59Z
            due_iso = datetime(eff_date.year, eff_date.month, eff_date.day, 4, 59, 59, tzinfo=tz.UTC).isoformat().replace("+00:00", "Z")

        # NOTE: use generalized marker stripping (leading label + trailing markers), then normalize
        key = _norm(_strip_markers(d.title))
        due_map[key] = due_iso
    return due_map

def find_best_assignment_match(assignments: List[Dict[str, Any]], target_key: str) -> Optional[Dict[str, Any]]:
    # First pass: exact match after applying the same normalization to Canvas names
    for a in assignments:
        nm = _norm(_strip_markers(a.get("name", "")))
        if nm == target_key:
            return a

    # Second pass: prefix or substring match, again with normalized names
    for a in assignments:
        nm = _norm(_strip_markers(a.get("name", "")))
        if nm.startswith(target_key) or target_key in nm:
            return a

    return None

def _index_assignments_by_base_name(assignments: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Map normalized base name -> assignment object.
    Base name is _strip_markers(name) (drops ' Due'/' Handed Out' and leading Activity:/Assignment:/Quiz:).
    """
    out = {}
    for a in assignments:
        base = _norm(_strip_markers(a.get("name","") or ""))
        out[base] = a
    return out

def _index_pages_by_title(pages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Map normalized page title -> page (contains 'url' slug we need to add to a module).
    """
    out = {}
    for p in pages:
        title = p.get("title","") or ""
        out[_norm(title)] = p
    return out
    
def rebuild_all_modules(client: CanvasClient, plan: SyllabusPlan, tz_name: str, apply: bool, base_url: Optional[str] = None) -> List[str]:
    actions: List[str] = []

    # 1) Delete existing modules (items first)
    existing = client.list_modules()
    for mod in existing:
        for it in client.list_module_items(mod["id"]):
            url = f"{client.api_url}/api/v1/courses/{client.course_id}/modules/{mod['id']}/items/{it['id']}"
            if apply:
                r = requests.delete(url, headers=client.headers)
                if r.status_code >= 400:
                    actions.append(f"[error] Failed to delete module item id={it['id']} in module id={mod['id']}: {r.status_code}")
                else:
                    actions.append(f"[del-item] '{it.get('title','')}' from '{mod.get('name','')}'")
            else:
                actions.append(f"[del-item] (dry-run) '{it.get('title','')}' from '{mod.get('name','')}'")
        if apply:
            ok = client.delete_module(mod["id"])
            actions.append(f"[del-module] '{mod.get('name','')}'" if ok else f"[error] Failed to delete module id={mod['id']}")
        else:
            actions.append(f"[del-module] (dry-run) '{mod.get('name','')}'")

    # 2) Create fresh date modules (one per meeting) — title is "DATE - <meeting.title>" (no "Activity:")
    date_to_module_id: Dict[date, int] = {}
    position = 1
    for mtg in plan.meetings:
        mod_name = f"{_date_header(mtg.date)} - {mtg.title.strip()}"
        if apply:
            mod = client.create_module(mod_name, position=position, published=True)
            if not mod:
                actions.append(f"[error] Failed to create module '{mod_name}' at pos {position}")
                continue
            mod_id = mod["id"]
            # Ensure module published
            url = f"{client.api_url}/api/v1/courses/{client.course_id}/modules/{mod_id}"
            r = requests.put(url, headers=client.headers, json={"module": {"published": True}})
            if r.status_code < 400:
                actions.append(f"[publish] Module '{mod_name}' explicitly set to published")
            else:
                actions.append(f"[warn] Could not re-publish module '{mod_name}': {r.status_code}")
        else:
            mod_id = -position
        actions.append(f"[create-module] '{mod_name}' at position {position}")
        date_to_module_id[mtg.date] = mod_id
        position += 1

    meeting_dates = _sorted_meeting_dates(plan)

    # 3) Lookups
    assignments = client.list_assignments()
    assign_by_base = _index_assignments_by_base_name(assignments)
    pages = client.list_pages()
    pages_by_title = _index_pages_by_title(pages)

    # 4) De-dup guards
    attached_assignments: set[tuple[int, int]] = set()   # (module_id, assignment_id)
    attached_links: set[tuple[int, str]] = set()         # (module_id, external_url)
    attached_pages: set[tuple[int, str]] = set()         # (module_id, page_url)
    attached_subheaders: set[tuple[int, str]] = set()    # (module_id, title) for non-link readings
    attached_handouts: set[tuple[int, str]] = set()      # (module_id, url) to avoid repeated handouts

    def _publish_item(mod_id: int, item_id: int, title_for_log: str):
        if not apply:
            return
        u = f"{client.api_url}/api/v1/courses/{client.course_id}/modules/{mod_id}/items/{item_id}"
        r = requests.put(u, headers=client.headers, json={"module_item": {"published": True}})
        if r.status_code < 400:
            actions.append(f"[publish] Item '{title_for_log}' in module id={mod_id}")
        else:
            actions.append(f"[warn] Could not publish item '{title_for_log}' in module id={mod_id}: {r.status_code}")

    def _add_page_or_url(mod_id: int, title: str, url: Optional[str]):
        # Normalize single "Activity:" prefix for activities only — assume caller passed the correct title
        title = re.sub(r'^(?:activity\s*:\s*){2,}', 'Activity: ', title.strip(), flags=re.IGNORECASE)

        # 1) Try Canvas page by title
        p = pages_by_title.get(_norm(title))
        if p:
            key = (mod_id, p["url"])
            if key in attached_pages:
                actions.append(f"[skip] Page '{title}' already in module id={mod_id}")
                return
            if apply:
                created = client.create_module_item(mod_id, type="Page", page_url=p["url"], published=True)
                if created:
                    attached_pages.add(key)
                    _publish_item(mod_id, created["id"], title)
                actions.append(f"[add] Page '{title}' -> module id={mod_id}" if created else f"[error] Failed to add page '{title}' to module id={mod_id}")
            else:
                actions.append(f"[add] (dry-run) Page '{title}' -> module id={mod_id}")
            return

        # 2) Fall back to external URL (resolve relative links through base_url, preserving '../')
        url_resolved = _resolve_url(url, base_url)
        if url_resolved:
            key = (mod_id, url_resolved)
            if key in attached_links:
                actions.append(f"[skip] Link '{title or url_resolved}' already in module id={mod_id}")
                return
            if apply:
                created = client.create_module_item(
                    mod_id,
                    type="ExternalUrl",
                    external_url=url_resolved,
                    new_tab=True,
                    title=title or None,
                    published=True
                )
                if created:
                    attached_links.add(key)
                    _publish_item(mod_id, created["id"], title or url_resolved)
                actions.append(f"[add] Link '{title or url_resolved}' -> module id={mod_id}" if created else f"[error] Failed to add link '{title or url_resolved}' to module id={mod_id}")
            else:
                actions.append(f"[add] (dry-run) Link '{title or url_resolved}' -> module id={mod_id}")
            return

        actions.append(f"[skip] No Canvas page and no URL found for '{title}'")

    def _add_subheader(mod_id: int, title: str):
        t = (title or "").strip()
        if not t:
            return
        key = (mod_id, t)
        if key in attached_subheaders:
            actions.append(f"[skip] Note '{t}' already in module id={mod_id}")
            return
        if apply:
            created = client.create_module_item(mod_id, type="SubHeader", title=t, published=True)
            if created:
                attached_subheaders.add(key)
                _publish_item(mod_id, created["id"], t)
            actions.append(f"[add] Note '{t}' -> module id={mod_id}" if created else f"[error] Failed to add note '{t}' to module id={mod_id}")
        else:
            actions.append(f"[add] (dry-run) Note '{t}' -> module id={mod_id}")

    def _attach_assignment_by_base(mod_id: int, base_key_norm: str, label_for_log: str):
        a = assign_by_base.get(base_key_norm)
        if not a:
            actions.append(f"[warn] No assignment object found for base '{base_key_norm}' to attach ({label_for_log})")
            return
        key = (mod_id, a["id"])
        if key in attached_assignments:
            actions.append(f"[skip] Assignment '{a.get('name')}' already in module id={mod_id}")
            return
        if apply:
            created = client.create_module_item(mod_id, type="Assignment", content_id=a["id"], published=True)
            if created:
                attached_assignments.add(key)
                _publish_item(mod_id, created["id"], a.get("name",""))
            actions.append(f"[add] Assignment '{a.get('name')}' -> module id={mod_id}" if created else f"[error] Failed to add assignment '{a.get('name')}' to module id={mod_id}")
        else:
            actions.append(f"[add] (dry-run) Assignment '{a.get('name')}' -> module id={mod_id}")

    # 5) Populate modules
    for mtg in plan.meetings:
        mod_id = date_to_module_id.get(mtg.date)
        if mod_id is None:
            continue

        # 5a) Main lecture link as an Activity ExternalUrl (skip if no link)
        if getattr(mtg, "link", None):
            _add_page_or_url(mod_id, _activity_title_label(mtg.title), mtg.link)

        # 5b) Activities (by date) — title must be "Activity: ..."
        for act in mtg.activities:
            atitle = _activity_title_label(act.get("title", "") or "")
            _add_page_or_url(mod_id, atitle, act.get("url"))

        # 5c) Readings (by date). If rlink missing/false, add as a non-link note (SubHeader).
        for rd in mtg.readings:
            rtitle = (rd.get("title", "") or "").strip()
            rurl = rd.get("url")
            if rurl:
                _add_page_or_url(mod_id, rtitle, rurl)
            else:
                _add_subheader(mod_id, rtitle)

    # 6) Handed-out deliverables: add a single ExternalUrl to the assignment on the *meeting day*.
    for d in plan.deliverables_handed_out:
        handout_day = due_date_for(d, plan)  # meeting day for that row
        mod_id = date_to_module_id.get(handout_day)
        if mod_id is None:
            actions.append(f"[warn] No date module exists for handout day {handout_day} for '{d.title}'")
            continue
        base_key_norm = _norm(_strip_markers(d.title))  # drop 'Handed Out' + leading labels
        a = assign_by_base.get(base_key_norm)
        if not a:
            actions.append(f"[warn] No assignment found to link for handout '{d.title}' (base='{base_key_norm}')")
            continue
        url = _assignment_url(a)
        if not url:
            actions.append(f"[warn] Assignment has no html_url for handout '{a.get('name','')}'")
            continue

        url = _resolve_url(url, base_url)
        key = (mod_id, url)
        if key in attached_handouts:
            actions.append(f"[skip] Handout link already present for '{a.get('name','')}' in module id={mod_id}")
            continue

        link_title = f"{_strip_markers(d.title)} Handed Out"
        if apply:
            created = client.create_module_item(
                mod_id,
                type="ExternalUrl",
                external_url=url,
                new_tab=True,
                title=link_title,
                published=True,
            )
            if created:
                attached_handouts.add(key)
                _publish_item(mod_id, created["id"], link_title)
            actions.append(f"[add] Handout link '{link_title}' -> module '{_date_header(handout_day)}'"
                           if created else f"[error] Failed to add handout link '{link_title}' to module '{_date_header(handout_day)}'")
        else:
            actions.append(f"[add] (dry-run) Handout link '{link_title}' -> module '{_date_header(handout_day)}'")

    # 7) Due submissions: place in the group that corresponds to the *student-facing due day*.
    #    Policy: cutoff is 3:59 AM local next morning; students think of it as due the previous day.
    #    So: nominal_due = meeting_day + 1; student_due_day = nominal_due - 1.
    for d in plan.deliverables_due:
        meeting_day = due_date_for(d, plan)               # day the assignment was introduced
        nominal_due_date = meeting_day + timedelta(days=1) # 3:59 AM following day
        student_due_day = nominal_due_date - timedelta(days=1)

        # If there's a meeting *on* the student-facing due day, use that module; else the next on/after.
        if student_due_day in date_to_module_id:
            target_day = student_due_day
        else:
            target_day = _next_meeting_on_or_after(student_due_day, meeting_dates)

        if target_day is None:
            actions.append(f"[warn] No meeting on/after student-facing due day {student_due_day} for '{d.title}'")
            continue

        mod_id = date_to_module_id.get(target_day)
        if mod_id is None:
            actions.append(f"[warn] No module exists for resolved day {target_day} for '{d.title}'")
            continue

        base_key_norm = _norm(_strip_markers(d.title))  # drop 'Due' + leading labels
        _attach_assignment_by_base(mod_id, base_key_norm, "due")

    # 8) Unpublish any modules that ended up empty (no items)
    if apply:
        for mtg in plan.meetings:
            mod_id = date_to_module_id.get(mtg.date)
            if mod_id is None or mod_id < 0:
                continue
            items = client.list_module_items(mod_id)
            if not items:
                u = f"{client.api_url}/api/v1/courses/{client.course_id}/modules/{mod_id}"
                r = requests.put(u, headers=client.headers, json={"module": {"published": False}})
                if r.status_code < 400:
                    actions.append(f"[unpublish] Module '{_date_header(mtg.date)} - {mtg.title.strip()}' (empty)")
                else:
                    actions.append(f"[warn] Failed to unpublish empty module id={mod_id}: {r.status_code}")

    return actions

def apply_due_dates(client: CanvasClient, due_map: Dict[str, str], apply: bool) -> List[str]:
    actions: List[str] = []
    assignments = client.list_assignments()

    for key, iso_due in due_map.items():
        a = find_best_assignment_match(assignments, key)
        if not a:
            actions.append(f"[warn] No Canvas assignment matched '{key}'")
            continue
        current_due = a.get("due_at")
        if current_due == iso_due:
            actions.append(f"[skip] '{a.get('name')}' due_at already {iso_due}")
            continue
        actions.append(f"[update] '{a.get('name')}' due_at: {current_due} -> {iso_due}")
        if apply:
            updated = client.update_assignment(a["id"], due_at=iso_due)
            if not updated:
                actions.append(f"[error] Failed to update assignment id={a['id']}")
    return actions

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Update Canvas due dates and rebuild modules from syllabus MD.")
    parser.add_argument("syllabus_md", help="Path to syllabus Markdown with YAML frontmatter")
    parser.add_argument("--config", help="Optional JSON config path with Canvas settings", default=None)
    parser.add_argument("--apply", action="store_true", help="Apply changes to Canvas (otherwise dry-run)")
    parser.add_argument("--base-url", dest="base_url", default=None,
                        help="Base URL to prepend to relative links (e.g., https://example.edu/course)")
    args = parser.parse_args(argv)

    try:
        cfg = _load_config(args.config)
        api_url  = cfg.get("CANVAS_API_URL")
        token    = cfg.get("CANVAS_API_TOKEN")
        course_id= cfg.get("CANVAS_COURSE_ID")
        tz_name  = cfg.get("TZ", "America/New_York")
        if not (api_url and token and course_id):
            raise ValueError("Missing Canvas configuration. Provide CANVAS_API_URL, CANVAS_API_TOKEN, CANVAS_COURSE_ID.")

        with open(args.syllabus_md, "r", encoding="utf-8") as f:
            md_text = f.read()
        fm, _ = _split_frontmatter(md_text)
        plan = _extract_plan(fm)

        due_map = build_due_map(plan, tz_name)

        print("Planned assignment due dates (normalized_name -> iso_due):")
        for k, v in due_map.items():
            print(f"  - {k} -> {v}")
        print()

        client = CanvasClient(api_url, token, str(course_id))
        actions: List[str] = []

        # 1) Update due dates
        actions += apply_due_dates(client, due_map, args.apply)
        # 2) Rebuild modules (now passes base_url) and populate
        actions += rebuild_all_modules(client, plan, tz_name, args.apply, base_url=args.base_url)

        print("\nActions:")
        for a in actions:
            print(" ", a)

        added = sum(1 for a in actions if a.startswith("[add]"))
        skips = sum(1 for a in actions if a.startswith("[skip]"))
        warns = sum(1 for a in actions if a.startswith("[warn]") or a.startswith("[error]"))
        actions.append(f"[summary] added={added} skipped={skips} warnings_or_errors={warns}")

        if args.apply:
            print("\n[applied] Updates sent to Canvas.")
        else:
            print("\n[dry-run] No changes were sent to Canvas. Re-run with --apply to commit updates.")
        return 0
    except Exception as e:
        _err("main", e)
        return 1

if __name__ == "__main__":
    sys.exit(main())
