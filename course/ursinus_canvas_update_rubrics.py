#!/usr/bin/env python3
"""
sync_assignments_and_rubrics.py

Reads all deliverables from a syllabus markdown file, finds the
corresponding Canvas assignments by name, and REPLACES their rubric by:

  1) deleting any existing rubric association (and rubric object if possible),
  2) recreating the rubric exactly from the deliverable's `rubricpath`.

This script does NOT delete assignments, modules, events, etc., and it doesn't 
create assignments that don't exist, either.  It only replaces rubrics for
existing assignments.

Usage:
  python sync_assignments_and_rubrics.py \
      --courseid 12345 \
      --markdown /path/to/course.md \
      --apikey XXX \
      --userid 9999 
"""

from canvasapi import Canvas, exceptions
import getopt
import sys
import frontmatter
import time
import random
from urllib import request, parse
import json
import traceback
import os

# --------------------------
# Configuration defaults
# --------------------------
API_URL = "https://ursinus.instructure.com/"

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
        print(f"[canvas_http_request] {e}")
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
        print(f"[get_assignment_rubric_meta] {e}")
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
        print(f"[delete_rubric_association] {e}")
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
        print(f"[delete_rubric_by_id] {e}")
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
        print(f"[replace_assignment_rubric_delete_then_recreate] Forbidden {e}")
        traceback.print_exc()
    except exceptions.Unauthorized as e:
        print(f"[replace_assignment_rubric_delete_then_recreate] Unauthorized {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"[replace_assignment_rubric_delete_then_recreate] Unexpected {e}")
        traceback.print_exc()
    return False

# --------------------------
# Assignment identification
# --------------------------
def ensure_assignment(course, description):
    """
    Finds an existing assignment by name.
    If not found, prints a warning and returns None (no new assignments created).
    """
    # Search by exact name
    for a in course.get_assignments():
        if a.name.strip() == description.strip():
            printlog(f"Found existing assignment: {a.name}")
            return a

    # Not found -> skip with warning
    printlog(f"WARNING: Assignment '{description}' not found in Canvas. Skipping.")
    return None

def process_markdown_assignments_only(fname, course):
    """
    Lightweight pass over the syllabus markdown:
      - for each deliverable that is an actual assignment,
        ensure the assignment exists and then delete+recreate its rubric from `rubricpath`.
    """
    with open(fname, 'r', encoding='utf-8') as f:
        mdcontents = f.read()

    post = frontmatter.loads(mdcontents)
    postdict = post.to_dict()

    for item in postdict.get('schedule', []):
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

            # ensure assignment exists 
            assignment = ensure_assignment(
                course=course,
                description=description
            )
            
            if assignment is None:
                continue # skip assignments that don't exist; use main script to add them

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
    print("\t[-a | --apikey]\tAPI Key")
    print("\t[-u | --userid]\tUser ID Number")

def main(argv):
    global API_KEY

    try:
        opts, args = getopt.getopt(
            argv, "hc:m:a:u:",
            ["help", "courseid=", "markdown=", "apikey=", "userid="]
        )
    except getopt.GetoptError as err:
        print(err)
        usage()
        sys.exit(2)

    courseid = -1
    markdownfile = None
    USER_ID = None
    API_KEY = None

    for o, a in opts:
        if o in ("-h", "--help"):
            usage(); sys.exit(0)
        elif o in ("-c", "--courseid"):
            courseid = int(a)
        elif o in ("-m", "--markdown"):
            markdownfile = a
        elif o in ("-a", "--apikey"):
            API_KEY = a
        elif o in ("-u", "--userid"):
            USER_ID = a

    if USER_ID is None:
        USER_ID = input("Enter User ID (get from API_URL + /api/v1/users/self): ")
    if API_KEY is None:
        API_KEY = input("Enter API Key (get from API_URL + /profile/settings): ")
    if courseid == -1:
        print("Course id is required."); usage(); sys.exit(2)
    if markdownfile is None:
        markdownfile = input("Enter path to course syllabus markdown file: ")

    printlog("Instantiating Canvas...")
    canvas = Canvas(API_URL, API_KEY)

    try:
        _ = canvas.get_user(USER_ID)
    except Exception as e:
        print(f"[main:get_user] {e}")
        traceback.print_exc()

    course = canvas.get_course(courseid)

    printlog("Replacing rubrics for existing assignments (no creation/deletion of assignments/modules/etc.)...")
    process_markdown_assignments_only(markdownfile, course)
    printlog("Done.")

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:
        print(f"[main] {e}")
        traceback.print_exc()
        sys.exit(1)
