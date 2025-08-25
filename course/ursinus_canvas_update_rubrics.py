#!/usr/bin/env python3
"""
sync_assignments_and_rubrics.py

Reads all deliverables from a syllabus markdown file, finds or creates the
corresponding Canvas assignments by name, and REPLACES their rubric by:

  1) deleting any existing rubric association (and rubric object if possible),
  2) recreating the rubric exactly from the deliverable's `rubricpath`.

This script does NOT delete assignments, modules, events, etc. It only
ensures assignment shells exist and replaces their rubrics.

Usage:
  python sync_assignments_and_rubrics.py \
      --courseid 12345 \
      --markdown /path/to/course.md \
      --webpage https://www.example.edu/course-home \
      --apikey XXX \
      --userid 9999 \
      [--timezone America/New_York] \
      [--duetime T045959Z|T035959Z]
"""

from canvasapi import Canvas, exceptions
import getopt
import sys
import frontmatter
from datetime import datetime, timedelta
import time
import random
from urllib import request, parse
import json
import pytz
import traceback
import os

# --------------------------
# Configuration defaults
# --------------------------
API_URL = "https://ursinus.instructure.com/"

CANVAS_TIME_ZONE = "America/New_York"
LOCALTIME = pytz.timezone(CANVAS_TIME_ZONE)
DUE_TIME_DST = "T035959Z"   # EDT next-morning cutoff in UTC
DUE_TIME_ST = "T045959Z"    # EST next-morning cutoff in UTC
DUE_DATE_OFFSET = 1         # add 1 day so due is "next morning" UTC after local midnight
DUE_DATE_FORMAT = "%Y%m%dT%H%M%SZ"

# Will be set in main()
API_KEY = None

# --------------------------
# Small utility helpers
# --------------------------
def printlog(msg, output=True):
    if output:
        print(msg)

def rchop(s, suffix):
    return s[:-len(suffix)] if (suffix and s.endswith(suffix)) else s

def lchop(text, prefix):
    return text[len(prefix):] if text.startswith(prefix) else text

def stripnobool(val):
    return "" if isinstance(val, bool) else str(val).strip()

def addslash(s):
    return s if s.endswith("/") else s + "/"

def makelink(base, url):
    return url if str(url).startswith("http") else base + url

def parseDate(dt, fmt='%Y/%m/%d'):
    return datetime.strptime(dt, fmt)

def parseTime(t):
    return datetime.strptime(t, '%I:%M %p')

def parseDateTimeCanvas(dt):
    return datetime.strftime(dt, '%Y-%m-%dT%H:%M:%SZ')

def adddays(dt, n):
    return dt + timedelta(days=n)

def addweeks(dt, n):
    return dt + timedelta(days=7*n)

def getDateString(dt, fmt='%Y%m%d'):
    return dt.strftime(fmt)

def get_local_time_suffix(dt_like):
    """
    Given a date/datetime or a date-like string, localize to CANVAS_TIME_ZONE
    and choose the correct UTC cutoff suffix (DST vs. ST).
    """
    try:
        if isinstance(dt_like, str):
            if 'T' in dt_like and 'Z' in dt_like:
                dt = datetime.strptime(dt_like, DUE_DATE_FORMAT)
            elif '/' not in dt_like:
                dt = datetime.strptime(dt_like, '%Y%m%d')
            else:
                dt = datetime.strptime(dt_like, '%Y/%m/%d')
        else:
            dt = dt_like
        localized = LOCALTIME.localize(dt)
        return DUE_TIME_DST if bool(localized.dst()) else DUE_TIME_ST
    except Exception as e:
        print(f"[get_local_time_suffix] {{e}}")
        traceback.print_exc()
        return DUE_TIME_DST

def getDayCodeNum(daycode):
    return {'M':0,'T':1,'W':2,'R':3,'F':4,'S':5,'U':6}.get(daycode, -1)

def getDayNum(dayidx, M, T, W, R, F, S, U):
    """
    Map day index within the meeting pattern to an absolute weekday number.
    Example: if meets on M, W, F and dayidx=1 -> Wednesday -> 2.
    """
    day_flags = [M, T, W, R, F, S, U]
    idx = int(dayidx)
    for i, flag in enumerate(day_flags):
        if flag:
            if idx == 0: return i
            idx -= 1
    return 0

def getCourseDate(startdate, weeknum, dayidx, M, T, W, R, F, S, U, tostring=True):
    dt = parseDate(startdate)
    dt = addweeks(dt, int(weeknum))
    daynum = getDayNum(int(dayidx), M, T, W, R, F, S, U)
    dt = adddays(dt, daynum)
    return getDateString(dt) if tostring else dt

def safe_sleep_for_rate_limit():
    time.sleep(random.randint(2, 6))

# --------------------------
# Raw HTTP for endpoints not surfaced by canvasapi
# --------------------------
def canvas_http_request(endpoint, inputdict=None, method="GET", api_key=None):
    """
    Lightweight helper for Canvas endpoints that canvasapi does not expose directly.
    """
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        data = None
        if inputdict is not None:
            data = parse.urlencode(inputdict).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        req = request.Request(rchop(API_URL, '/') + endpoint, data=data, headers=headers, method=method)
        return request.urlopen(req)
    except Exception as e:
        print(f"[canvas_http_request] {{e}}")
        traceback.print_exc()
        raise

# --------------------------
# Rubric helpers (delete & recreate)
# --------------------------
def get_assignment_rubric_meta(course, assignment_id, api_key):
    """
    Returns {'rubric_id': int|None, 'rubric_association_id': int|None} for the assignment.
    """
    try:
        safe_sleep_for_rate_limit()
        resp = canvas_http_request(
            f"/api/v1/courses/{course.id}/assignments/{assignment_id}",
            method="GET",
            api_key=api_key
        )
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        rs = data.get('rubric_settings') or {}
        return {
            'rubric_id': rs.get('id'),
            'rubric_association_id': rs.get('rubric_association_id')
        }
    except Exception as e:
        print(f"[get_assignment_rubric_meta] {{e}}")
        traceback.print_exc()
        return {'rubric_id': None, 'rubric_association_id': None}

def delete_rubric_association(course, rubric_association_id, api_key):
    """
    Deletes a rubric association by id (no-op if id is falsy).
    """
    if not rubric_association_id:
        return False
    try:
        safe_sleep_for_rate_limit()
        canvas_http_request(
            f"/api/v1/courses/{course.id}/rubric_associations/{rubric_association_id}",
            method="DELETE",
            api_key=api_key
        )
        printlog(f"Deleted rubric association {rubric_association_id}")
        return True
    except Exception as e:
        print(f"[delete_rubric_association] {{e}}")
        traceback.print_exc()
        return False

def delete_rubric_by_id(course, rubric_id, api_key):
    """
    Deletes a rubric object by id (no-op if id is falsy).
    Some tenants may restrict deletion of shared/reused rubrics.
    """
    if not rubric_id:
        return False
    try:
        safe_sleep_for_rate_limit()
        canvas_http_request(
            f"/api/v1/courses/{course.id}/rubrics/{rubric_id}",
            method="DELETE",
            api_key=api_key
        )
        printlog(f"Deleted rubric {rubric_id}")
        return True
    except Exception as e:
        print(f"[delete_rubric_by_id] {{e}}")
        traceback.print_exc()
        return False

def build_rubric_payload_exact(rubricpath, assignmentid, description, points):
    """
    Builds the rubric creation payload EXACTLY in the structure requested.

    Structure:
        inputdict['rubric_association_id'] = assignmentid
        inputdict['rubric'] = {..., 'criteria': {...}}
        inputdict['rubric_association'] = {..., 'association_id': assignmentid, ...}
    """
    with open(rubricpath, 'r', encoding='utf-8') as f:
        rubricmd = f.read()
    rubricpost = frontmatter.loads(rubricmd)
    rubricpostdict = rubricpost.to_dict()

    inputdict = {}

    if "info" in rubricpostdict and "rubric" in rubricpostdict['info']:
        rubric = rubricpostdict['info']['rubric']

        inputdict['rubric_association_id'] = assignmentid

        inputdict['rubric'] = {}
        inputdict['rubric']['title'] = description + " Rubric"
        inputdict['rubric']['points_possible'] = points
        inputdict['rubric']['free_form_criterion_comments'] = False
        inputdict['rubric']['skip_updating_points_possible'] = False
        inputdict['rubric']['read_only'] = False
        inputdict['rubric']['reusable'] = True
        inputdict['rubric']['criteria'] = {}

        inputdict['rubric_association'] = {}
        inputdict['rubric_association']['use_for_grading'] = True
        inputdict['rubric_association']['purpose'] = "grading"
        inputdict['rubric_association']['association_id'] = assignmentid
        inputdict['rubric_association']['association_type'] = "Assignment"
        inputdict['rubric_association']['bookmarked'] = True

        criteriaidx = 0
        for criteria in rubric:
            criteriadict = {}
            criteriadict['description'] = criteria['description']
            criteriadict['long_description'] = criteria['description']
            criteriadict['criterion_use_range'] = True
            criteriapoints = (points * float(criteria['weight']) / 100.0)
            criteriadict['points'] = criteriapoints

            criteriadict['ratings'] = {}

            ratingdict = {}
            ratingdict['description'] = "Pre-Emerging"
            ratingdict['long_description'] = criteria['preemerging']
            ratingdict['points'] = (criteriapoints * 0.25)
            criteriadict['ratings'][0] = ratingdict

            ratingdict = {}
            ratingdict['description'] = "Beginning"
            ratingdict['long_description'] = criteria['beginning']
            ratingdict['points'] = (criteriapoints * 0.50)
            criteriadict['ratings'][1] = ratingdict

            ratingdict = {}
            ratingdict['description'] = "Progressing"
            ratingdict['long_description'] = criteria['progressing']
            ratingdict['points'] = (criteriapoints * 0.85)
            criteriadict['ratings'][2] = ratingdict

            ratingdict = {}
            ratingdict['description'] = "Proficient"
            ratingdict['long_description'] = criteria['proficient']
            ratingdict['points'] = (criteriapoints * 1.00)
            criteriadict['ratings'][3] = ratingdict

            inputdict['rubric']['criteria'][criteriaidx] = criteriadict
            criteriaidx += 1

    return inputdict

def replace_assignment_rubric_delete_then_recreate(course, assignment, rubricpath, total_points):
    """
    Deletes any existing rubric association (and underlying rubric if present), then
    recreates the rubric from `rubricpath` and associates it to `assignment`.

    Returns True on success, False on failure.
    """
    try:
        # 1) discover existing rubric metadata
        meta = get_assignment_rubric_meta(course, assignment.id, API_KEY)
        assoc_id = meta.get('rubric_association_id')
        rubric_id = meta.get('rubric_id')

        # 2) delete any existing association first
        if assoc_id:
            delete_rubric_association(course, assoc_id, API_KEY)

        # 3) optionally delete the underlying rubric object (clean slate)
        if rubric_id:
            delete_rubric_by_id(course, rubric_id, API_KEY)

        # 4) build the payload exactly as requested
        payload = build_rubric_payload_exact(
            rubricpath=rubricpath,
            assignmentid=assignment.id,
            description=assignment.name,
            points=total_points
        )

        # 5) create rubric + association in one call
        course.create_rubric(**payload)
        printlog(f"Rubric recreated for assignment '{assignment.name}' from {rubricpath}")
        return True

    except exceptions.Forbidden as e:
        print(f"[replace_assignment_rubric_delete_then_recreate] Forbidden {{e}}")
        traceback.print_exc()
    except exceptions.Unauthorized as e:
        print(f"[replace_assignment_rubric_delete_then_recreate] Unauthorized {{e}}")
        traceback.print_exc()
    except Exception as e:
        print(f"[replace_assignment_rubric_delete_then_recreate] Unexpected {{e}}")
        traceback.print_exc()
    return False

# --------------------------
# Assignment synchronization
# --------------------------
def ensure_assignment(course, description, duedate_dt, enddate_str, deliverable, homepage, asmt_position=1):
    """
    Finds by name or creates an assignment shell consistent with your defaults.
    Returns the assignment object (existing or newly created).
    """
    # Search by exact name
    for a in course.get_assignments():
        if a.name.strip() == description.strip():
            printlog(f"Found existing assignment: {a.name}")
            return a

    # Not found -> create it
    points = int(deliverable.get('points', 100))
    dlink = deliverable.get('dlink', None)
    if dlink is not None:
        dlink = str(dlink).strip()
        if not dlink or dlink.lower() == "false":
            dlink = None

    inputdict = {
        'name': description,
        'submission_types': [],
        'notify_of_update': True,
        'published': True,
        'points_possible': points,
        'position': asmt_position,
    }

    # submission types and extensions
    stypes = deliverable.get('submission_types', '')
    stypes_lower = stypes.lower() if isinstance(stypes, str) else ''
    if "onpaper" in stypes_lower:
        inputdict['submission_types'].append('on_paper')
    elif "noupload" in stypes_lower:
        inputdict['submission_types'].append('online_text_entry')
    else:
        inputdict['submission_types'].append('online_upload')
        exts = ['zip','bz2','tar','gz','rar','7z']
        if "written" in stypes_lower:
            inputdict['submission_types'].append('online_text_entry')
            exts += ['pdf','doc','docx','txt']
        inputdict['allowed_extensions'] = exts

    # description with link (if any)
    if dlink is None:
        inputdict['description'] = description
    else:
        link = makelink(addslash(homepage), stripnobool(dlink))
        inputdict['description'] = f'{description} (<a href="{link}">{link}</a>)'

    # due and lock times
    duedate_str = getDateString(adddays(duedate_dt, DUE_DATE_OFFSET))
    due_suffix = get_local_time_suffix(duedate_dt)
    lock_suffix = get_local_time_suffix(enddate_str.replace('/',''))

    inputdict['due_at'] = parseDateTimeCanvas(datetime.strptime(duedate_str + due_suffix, DUE_DATE_FORMAT))
    inputdict['lock_at'] = parseDateTimeCanvas(datetime.strptime(enddate_str.replace('/', '') + lock_suffix, DUE_DATE_FORMAT))

    printlog(f"Creating assignment: {description} (due {duedate_str})")
    a = course.create_assignment(inputdict)
    return a

def process_markdown_assignments_only(fname, canvas, course, courseid, homepage):
    """
    Lightweight pass over the syllabus markdown:
      - compute dates with your same calendar logic,
      - for each deliverable that is an actual assignment,
        ensure the assignment exists and then delete+recreate its rubric from `rubricpath`.
    """
    with open(fname, 'r', encoding='utf-8') as f:
        mdcontents = f.read()

    post = frontmatter.loads(mdcontents)
    postdict = post.to_dict()

    # Course info & calendar parameters
    startdate = postdict['info']['course_start_date']
    enddate = postdict['info']['course_end_date']
    # keep the lock-day offset like your original script
    enddate = getDateString(adddays(parseDate(enddate), DUE_DATE_OFFSET), fmt='%Y/%m/%d')

    isM = postdict['info']['class_meets_days']['isM']
    isT = postdict['info']['class_meets_days']['isT']
    isW = postdict['info']['class_meets_days']['isW']
    isR = postdict['info']['class_meets_days']['isR']
    isF = postdict['info']['class_meets_days']['isF']
    isS = postdict['info']['class_meets_days']['isS']
    isU = postdict['info']['class_meets_days']['isU']

    asmt_position = 1
    for item in postdict['schedule']:
        weekidx = item['week']
        dayidx = item['date']
        _title = item.get('title', 'N/A')

        class_dt = getCourseDate(startdate, weekidx, dayidx, isM, isT, isW, isR, isF, isS, isU, tostring=False)

        if 'deliverables' not in item:
            continue

        for deliverable in item['deliverables']:
            dtitle = deliverable['dtitle']
            description = rchop(dtitle.strip(), " Due")

            # Skip non-assignments and quizzes (same as your original logic)
            lower_desc = description.lower()
            if ' handed out' in lower_desc:
                continue
            if 'quiz:' in lower_desc:
                continue

            # ensure assignment exists (or create)
            assignment = ensure_assignment(
                course=course,
                description=description,
                duedate_dt=class_dt,
                enddate_str=enddate,
                deliverable=deliverable,
                homepage=homepage,
                asmt_position=asmt_position
            )
            asmt_position += 1

            # Replace rubric if specified
            rubricpath = deliverable.get('rubricpath', None)
            if rubricpath and os.path.exists(rubricpath):
                points = int(deliverable.get('points', 100))
                ok = replace_assignment_rubric_delete_then_recreate(course, assignment, rubricpath, points)
                if not ok:
                    printlog(f"WARNING: Could not replace rubric for '{assignment.name}' from {rubricpath}")
            elif rubricpath:
                printlog(f"WARNING: rubricpath '{rubricpath}' not found for assignment '{description}'")

# --------------------------
# CLI / entry point
# --------------------------
def usage():
    print("Usage:")
    print("\t[-h | --help]\tUsage Documentation")
    print("\t[-c | --courseid]\tCanvas Course ID number")
    print("\t[-m | --markdown]\tPath to course syllabus markdown file")
    print("\t[-w | --webpage]\tURL of hosted course homepage (https://www.yourhomepage.com/course)")
    print("\t[-a | --apikey]\tAPI Key")
    print("\t[-u | --userid]\tUser ID Number")
    print("\t[-t | --timezone]\tTime Zone (i.e. America/New_York)")
    print("\t[-e | --duetime]\tDue Times in UTC for standard|daylight (e.g., T045959Z|T035959Z for ET)")

def main(argv):
    global API_KEY, CANVAS_TIME_ZONE, LOCALTIME, DUE_TIME_ST, DUE_TIME_DST

    try:
        opts, args = getopt.getopt(
            argv, "hc:m:w:a:u:t:e:",
            ["help", "courseid=", "markdown=", "webpage=", "apikey=", "userid=", "timezone=", "duetime="]
        )
    except getopt.GetoptError as err:
        print(err)
        usage()
        sys.exit(2)

    courseid = -1
    markdownfile = None
    coursehomepage = None
    USER_ID = None
    API_KEY = None

    for o, a in opts:
        if o in ("-h", "--help"):
            usage(); sys.exit(0)
        elif o in ("-c", "--courseid"):
            courseid = int(a)
        elif o in ("-m", "--markdown"):
            markdownfile = a
        elif o in ("-w", "--webpage"):
            coursehomepage = a
        elif o in ("-a", "--apikey"):
            API_KEY = a
        elif o in ("-u", "--userid"):
            USER_ID = a
        elif o in ("-t", "--timezone"):
            CANVAS_TIME_ZONE = a
        elif o in ("-e", "--duetime"):
            atimes = a.split("|")
            DUE_TIME_ST = atimes[0]; DUE_TIME_DST = atimes[1]

    if USER_ID is None:
        USER_ID = input("Enter User ID (get from API_URL + /api/v1/users/self): ")
    if API_KEY is None:
        API_KEY = input("Enter API Key (get from API_URL + /profile/settings): ")
    if courseid == -1:
        print("Course id is required."); usage(); sys.exit(2)
    if markdownfile is None:
        markdownfile = input("Enter path to course syllabus markdown file: ")
    if coursehomepage is None:
        coursehomepage = input("Enter course website (https://www.yourhomepage.com/course): ")

    LOCALTIME = pytz.timezone(CANVAS_TIME_ZONE)

    printlog("Instantiating Canvas...")
    canvas = Canvas(API_URL, API_KEY)

    try:
        _ = canvas.get_user(USER_ID)
    except Exception as e:
        print(f"[main:get_user] {{e}}")
        traceback.print_exc()

    course = canvas.get_course(courseid)

    printlog("Syncing assignments and replacing rubrics (no deletions of assignments/modules/etc.)...")
    process_markdown_assignments_only(markdownfile, canvas, course, courseid, coursehomepage)

    printlog("Done.")

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:
        print(f"[main] {{e}}")
        traceback.print_exc()
        sys.exit(1)
