# https://canvasapi.readthedocs.io/en/stable/
# https://canvas.instructure.com/doc/api/

# canvasapi on pip is out of date, might need to install from https://github.com/ucfopen/canvasapi (git+https://github.com/ucfopen/canvasapi.git)
# pip install python-frontmatter

from canvasapi import Canvas, exceptions
import getopt
import sys
import frontmatter
from datetime import datetime, timedelta
import threading
import time
import random
from urllib import request, parse
import requests
import json
import pytz
import yaml
import os

# https://github.com/ucfopen/canvasapi/blob/develop/canvasapi/course.py
# https://github.com/ucfopen/canvasapi/blob/develop/canvasapi/canvas.py

# CONSIDERATION
# course.create_course_section - separate calendar?  duplicate assignments, etc?
# Change course calendar entries to timetables: which can possibly be done on a per-section basis
## https://canvas.instructure.com/doc/api/calendar_events.html#method.calendar_events_api.set_course_timetable

API_URL = "https://ursinus.instructure.com/"
# Generate key at API_URL + profile/settings
# Obtain User ID from API_URL + /api/v1/users/self

CANVAS_TIME_ZONE = "America/New_York"
LOCALTIME = pytz.timezone(CANVAS_TIME_ZONE)
DUE_TIME_DST = "T035959Z" 
DUE_TIME_ST = "T045959Z" 
DUE_DATE_OFFSET = 1 # add 1 day to make things due the next morning per the due time above if GMT is after midnight
DUE_DATE_FORMAT = "%Y%m%dT%H%M%SZ"

# Schedule items (deliverables and readings) may carry a "module:" key that
# moves their Canvas module ITEM into one of these standing modules, placed
# above the first class day. The item still keeps its own due date and its
# place on the syllabus web page - only the Canvas module placement changes.
MODULE_TAG_RESOURCE = "resource"
MODULE_TAG_OVERARCHING = "overarching"
MODULE_NAME_RESOURCE = "Resources"
MODULE_NAME_OVERARCHING = "Overarching Class Participation Activities"

def get_module_tag(entry):
    """Return the normalized module tag for a deliverable/reading, or None."""
    tag = str((entry or {}).get('module') or "").strip().lower()
    if tag in ("resource", "resources"):
        return MODULE_TAG_RESOURCE
    if tag in ("overarching", "participation", "overarching participation"):
        return MODULE_TAG_OVERARCHING
    if tag:
        print("Warning: unknown module tag '%s' - leaving the item on its own day" % tag)
    return None

def get_item_date(item, startdate, M, T, W, R, F, S, U):
    """The date a schedule entry falls on.

    A "cdate:" key (YYYY/MM/DD) pins the entry to a specific calendar date -
    for a session that does not sit on the normal week/day meeting grid, such
    as a Friday convocation. Otherwise the date is computed from week/date as
    usual. Unlike "reschedule:", which only relabels the entry, cdate drives
    the module name, the deliverable due dates, and the calendar events.
    """
    cdate = str(item.get('cdate') or "").strip()
    if cdate:
        return parseDate(cdate)
    return getCourseDate(startdate, item['week'], item.get('date', 0), M, T, W, R, F, S, U, tostring=False)

TABS_TO_HIDE = ["Outcomes", "Collaborations", "Files", "Pages", "Conferences", "BigBlueButton", "Chat", "New Analytics", "Panopto Video", "Zoom"] # which navigation pane items to hide if they are visible
TABS_TO_SHOW = ["Assignments", "Discussions", "Grades", "People", "Syllabus", "Modules", "Grizzly Gateway", "SPTQ", "Attendance", "Rubrics", "Quizzes", "Announcements" ] # which navigation pane items to force show if they are already hidden

child_threads = []

skipdiscussions = False
skipassignments = False
skipofficehours = False
skiplecturecalendar = False
skipalldeletes = False

def get_local_time(dt):
    # Convert string dates to datetime
    if(isinstance(dt, str)):
        if 'T' in dt and 'Z' in dt:
            dt = parseDate(dt, DUE_DATE_FORMAT)
        elif not ('/' in dt):
            dt = parseDate(dt, '%Y%m%d')
        else:
            dt = parseDate(dt)
        
    localized_dt = LOCALTIME.localize(dt)
    isDST = bool(localized_dt.dst())
    
    if isDST:
        return DUE_TIME_DST
    else:
        return DUE_TIME_ST
    
def canvas_http_request(endpoint, inputdict=None, method="GET"):
    header = {"Authorization": "Bearer %s" % API_KEY}

    if not (inputdict is None):
        data = parse.urlencode(inputdict).encode()
        header['Content-Type'] = 'application/x-www-form-urlencoded'
    else:
        data = None
    
    req =  request.Request(rchop(API_URL, '/') + endpoint, data=data, headers=header, method=method) 
    resp = request.urlopen(req)   
    return resp
    
def makelink(base, url):
    if url.startswith("http"):
        return url
    else:
        return base + url

def addslash(str):
    if not (str.endswith("/")):
        return str + "/"
    else:
        return str

def printlog(msg, output=True):
    if output:
        print(msg)
        
# https://stackoverflow.com/questions/3663450/remove-substring-only-at-the-end-of-string
def rchop(s, suffix):
    if suffix and s.endswith(suffix):
        return s[:-len(suffix)]
    return s
    
# https://stackoverflow.com/questions/16891340/remove-a-prefix-from-a-string
def lchop(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return text   
    
def stripnobool(val):
    if type(val) is bool:
        result = ""
    else:
        result = str(val)
    
    return result.strip()

def load_site_config(syllabus_path=None):
    """Parse the site's _config.yml; return {} when it is absent or unreadable."""
    candidates = ["_config.yml"]
    if syllabus_path:
        # syllabus.md normally lives in _pages/, so the config sits one level up
        parent = os.path.dirname(os.path.dirname(os.path.abspath(syllabus_path)))
        candidates.append(os.path.join(parent, "_config.yml"))

    for candidate in candidates:
        try:
            with open(candidate, encoding="utf-8") as cf:
                return yaml.safe_load(cf) or {}
        except (OSError, yaml.YAMLError):
            continue

    return {}

def get_lia_base(cfg):
    """LiaScript render prefix, or None when this course has not opted in."""
    viewer = cfg.get('lia_viewer_url')
    pages = cfg.get('raw_pages_url')

    if viewer and pages:
        return stripnobool(viewer) + stripnobool(pages)

    return None

def is_liapage(entry):
    """True for `liapage: true`. stripnobool() blanks booleans on purpose, so the
    YAML boolean has to be read before any string coercion."""
    val = entry.get('liapage', False)

    if isinstance(val, bool):
        return val

    return str(val).strip().lower() == "true"

def lia_resolve(entry, url, lia_base):
    """Expand a liapage entry into its LiaScript render URL; leave every other link alone.

    The result is absolute, so the makelink() call downstream passes it through
    untouched rather than prepending the course homepage to it."""
    if lia_base and is_liapage(entry):
        return lia_base + stripnobool(url)

    return url

def dodelete(item, dosleep=True):
    repeat = True
    
    while repeat:
        if dosleep: # for rate limiting
            sleeptime = random.randint(5, 20)
            time.sleep(sleeptime)
            
        try:
            item.delete()
            printlog("Delete: Successful")
            repeat = False
        except exceptions.ResourceDoesNotExist:
            print("Deleting: Resource Does Not Exist")
            repeat = False
        except exceptions.Unauthorized:
            print("Deleting: Unauthorized")
            repeat = False
        except exceptions.Forbidden:
            print("Deleting: Forbidden - it is possible that the rate limit is exceeded")
            repeat = True
        except exceptions.CanvasException:
            print("Deleting: Canvas Error")
            repeat = True
        except Exception as ex:
            print("Deleting: Unknown Error - " + repr(ex))
            repeat = False
             
def delete_all_events(canvas, coursecontext):
    events = canvas.get_calendar_events(all_events = True, context_codes = [coursecontext])
    
    for event in events:
        t = threading.Thread(target=dodelete, args=(event,))
        child_threads.append(t)
        t.start()

def delete_all_assignments(course):
    if skipassignments:
        return
        
    assignments = course.get_assignments()

    for assignment in assignments:        
        t = threading.Thread(target=dodelete, args=(assignment,))
        child_threads.append(t)
        t.start()           

# DELETE /api/v1/courses/:course_id/rubrics/:id
def delete_rubric(rubric, dosleep=True):
    if dosleep: # for rate limiting
        sleeptime = random.randint(5, 20)
        time.sleep(sleeptime)
        
    rubric = None
    try:
        rubric = canvas_http_request('/api/v1/courses/' + str(courseid) + '/rubrics/' + str(rubric.id), method="DELETE")
    except:
        print("Error Deleting Rubric")
        
    return rubric
    
def delete_all_rubrics(course):
    if skipassignments:
        return
        
    rubrics = course.get_rubrics()
    for rubric in rubrics:        
        t = threading.Thread(target=delete_rubric, args=(rubric,))
        child_threads.append(t)
        t.start()  
        
def delete_all_modules(course):
    modules = course.get_modules()
    
    itemthreads = []
    
    for module in modules:
        items = module.get_module_items()
        
        for item in items:
            t = threading.Thread(target=dodelete, args=(item,))
            child_threads.append(t)
            itemthreads.append(t)
            t.start()                 
        
        for t in itemthreads:
            t.join()
            
        t = threading.Thread(target=dodelete, args=(module,))
        child_threads.append(t)
        t.start()   

def delete_all_quizzes(course):
    quizzes = course.get_quizzes()
        
    for quiz in quizzes:
        t = threading.Thread(target=dodelete, args=(quiz,))
        child_threads.append(t)
        t.start()         
        
def delete_all_assignment_groups(course):
    if skipassignments:
        return
        
    groups = course.get_assignment_groups()
    
    for group in groups:
        t = threading.Thread(target=dodelete, args=(group,))
        child_threads.append(t)
        t.start()         
        
def delete_all_discussion_topics(course):
    if skipdiscussions:
        return
        
    topics = course.get_discussion_topics()
    
    itemthreads = []
    for topic in topics:
        entries = topic.get_topic_entries()
        
        for entry in entries:
            t = threading.Thread(target=dodelete, args=(entry,))
            child_threads.append(t)
            itemthreads.append(t)
            t.start() 

        for t in itemthreads:
            t.join()
            
        t = threading.Thread(target=dodelete, args=(topic,))
        child_threads.append(t)
        t.start() 

def get_assignments_in_group(course, group):
    # Prefer the membership that came back with the group listing: asking for it there costs
    # no additional request, where listing every assignment in the course costs several pages
    assignments = getattr(group, 'assignments', None)

    if assignments is None: # older response without the include - fall back rather than assume empty
        assignments = []
        for assignment in course.get_assignments():
            if assignment.assignment_group_id == group.id:
                assignments.append({'name': assignment.name, 'points_possible': assignment.points_possible})

    return assignments

def delete_assignment_group_by_name(course, name):
    # Canvas deletes a group's assignments along with the group unless move_assignments_to is
    # given, so an assignment that matched no grade breakdown category would be created,
    # published, and then silently destroyed with the default group it was left in
    groups = course.get_assignment_groups(include=['assignments'])

    for group in groups:
        if group.name == name:
            stranded = get_assignments_in_group(course, group)

            if len(stranded) > 0:
                printlog("*** WARNING: NOT deleting the assignment group " + name + ": it still holds " + str(len(stranded)) + " assignment(s), which Canvas would delete along with it.")
                printlog("*** The following assignments matched no grade_breakdown category, so they are unweighted and will not count toward the final grade:")

                for assignment in stranded:
                    printlog("***\t" + str(assignment['name']) + " (" + str(assignment['points_possible']) + " points)")

                printlog("*** Prefix each name with a grade breakdown category (Category: Deliverable), or add a matching grade_breakdown category, and deploy again.")
            else:
                t = threading.Thread(target=dodelete, args=(group,))
                child_threads.append(t)
                t.start()

def delete_old_data(course, canvas, coursecontext):
    if skipalldeletes:
        return
        
    t1 = threading.Thread(target=delete_all_assignments, args=(course,))
    t2 = threading.Thread(target=delete_all_events, args=(canvas,coursecontext,))
    t3 = threading.Thread(target=delete_all_modules, args=(course,))
    t4 = threading.Thread(target=delete_all_assignment_groups, args=(course,))
    t5 = threading.Thread(target=delete_all_discussion_topics, args=(course,))
    t6 = threading.Thread(target=delete_all_rubrics, args=(course,))
    t7 = threading.Thread(target=delete_all_quizzes, args=(course,))
    
    child_threads.append(t1)
    child_threads.append(t2)
    child_threads.append(t3)
    child_threads.append(t4)
    child_threads.append(t5)
    child_threads.append(t6)
    child_threads.append(t7)
    
    t1.start()
    t2.start()
    t3.start()
    t4.start()
    t5.start()
    t6.start()
    t7.start()
    
    # Avoid a race condition in which newly added items are deleted when gathered by these threads
    for t in child_threads:
        t.join()

# https://canvas.instructure.com/doc/api/tabs.html#method.tabs.update
# https://canvas.instructure.com/doc/api/tabs.html#method.tabs.index
def arrange_tabs(course):
    tabs = course.get_tabs()
    
    for tab in tabs:
        if tab.label in TABS_TO_HIDE:
            tab.update(hidden=True)
        if tab.label in TABS_TO_SHOW:
            tab.update(hidden=False)

def omit_attendance_grade(course, ATTENDANCE_NAME="Roll Call Attendance"):
    # Retrieve assignments
    assignments = course.get_assignments()

    # Search for the Roll Call Attendance assignment
    attendance_assignment = None
    for assignment in assignments:
        if assignment.name.strip().lower() == ATTENDANCE_NAME.lower():
            attendance_assignment = assignment
            break  # Stop searching once found

    if attendance_assignment:
        printlog(f"Found attendance assignment: {attendance_assignment.name} (ID: {attendance_assignment.id})")

        # Update the assignment to be excluded from the final grade and hidden from students
        attendance_assignment.edit(
            assignment={
                "submission_types": ["none"],  # No submission
                "points_possible": 100,  # Points remain, but do not count toward the final grade
                "grading_type": "points",  # Enables attendance tracking
                "omit_from_final_grade": True,  # Ensures it's excluded from the final grade
                "published": False  # Hide the assignment from students by unpublishing it
            }
        )
        printlog(f"Updated assignment: {attendance_assignment.name} is now hidden and does not count toward the final grade.")
    else:
        printlog("Roll Call Attendance assignment not found.")    
            
# https://canvas.instructure.com/doc/api/discussion_topics.html
# https://canvas.instructure.com/doc/api/discussion_topics.html#method.discussion_topics.create
# https://canvasapi.readthedocs.io/en/stable/course-ref.html
def add_discussion_topic(course, inputdict):
    if skipdiscussions:
        return
        
    course.create_discussion_topic(**inputdict)
    
# https://canvas.instructure.com/doc/api/all_resources.html#method.content_migrations.create
# https://canvasapi.readthedocs.io/en/stable/course-ref.html#canvasapi.course.Course.create_content_migration
def create_quiz_content_migration(course, quiz_path, sleep_time=5):
    quiz_file_name = quiz_path.rsplit('/',1)[-1]
    
    inputdict = {}
    
    inputdict['migration_type'] = 'qti_converter'
    inputdict['pre_attachment'] = {}
    inputdict['pre_attachment']['name'] = quiz_file_name
    inputdict['settings'] = {}
    inputdict['settings']['overwrite_quizzes'] = True
    
    migration = course.create_content_migration(**inputdict)
    
    # now actually upload the file to the url given by the response to the module creation
    upload_url = migration.pre_attachment['upload_url']
    upload_file = open(quiz_path, 'rb')
    requests.post(upload_url, files={'file': upload_file}) # zip of qti
    
    # wait for upload 
    uploaddone = False
    while not uploaddone:
        progress = migration.get_progress()
        progress_url = progress.url
        print("Waiting for upload of " + quiz_path + " to complete, check progress at: " + progress_url)
        header = {"Authorization": "Bearer %s" % API_KEY}
        resp = requests.get(progress_url, headers=header)
        body = resp.text
        bodyjson = json.loads(body)
        status = bodyjson['workflow_state'] 
        completion = bodyjson['completion']
        if status != 'queued':
            uploaddone = True
        else:    
            print("Upload progress of " + quiz_path + str(completion) + ", waiting...")
            time.sleep(sleep_time)
            
    # Wait for creation to finish even after progress shows done
    time.sleep(sleep_time)
    
def add_grading_standard(course, inputdict):
    course.add_grading_standards(inputdict)
    
def countWeeks(d1, d2):
    # https://stackoverflow.com/questions/14191832/how-to-calculate-difference-between-two-dates-in-weeks-in-python
    monday1 = (d1 - timedelta(days=d1.weekday()))
    monday2 = (d2 - timedelta(days=d2.weekday()))

    # Canvas wants an integer count of recurrences.  Snapping both ends back to Monday above
    # already divides evenly and already gives a term that ends mid-week its final week of
    # meetings, so this rounds up rather than truncating only to keep that choice if the snap
    # ever changes: one extra event past the end of term is cheaper than a missing class
    # meeting.  Do not simplify to int(), which would silently pick truncation instead
    weeks = -(-(monday2 - monday1).days // 7) # ceiling division

    return max(0, min(weeks, 200)) # Canvas rejects a negative count, and caps duplicates at 200

def getDayCodeNum(daycode):
    if daycode == 'M':
        return 0
    elif daycode == 'T':
        return 1
    elif daycode == 'W':
        return 2
    elif daycode == 'R':
        return 3
    elif daycode == 'F':
        return 4
    elif daycode == 'S':
        return 5
    elif daycode == 'U':
        return 6
    else:
        return -1

def getDayNum(dayidx, M, T, W, R, F, S, U):
    result = 0
    
    if M:
        dayidx = dayidx - 1
        
        if dayidx == -1:
            result = 0
    
    if T:
        dayidx = dayidx - 1
        
        if dayidx == -1:
            result = 1

    if W:
        dayidx = dayidx - 1
        
        if dayidx == -1:
            result = 2

    if R:
        dayidx = dayidx - 1
        
        if dayidx == -1:
            result = 3

    if F:
        dayidx = dayidx - 1
        
        if dayidx == -1:
            result = 4

    if S:
        dayidx = dayidx - 1
        
        if dayidx == -1:
            result = 5

    if U:
        dayidx = dayidx - 1
        
        if dayidx == -1:
            result = 6

    return result
    
def getSectionName(coursesections, i):
    # course_sections is expected to line up with class_meets_locations; if it is short, say so
    # and carry on unnamed rather than failing the whole deploy over a label
    if i < len(coursesections):
        return stripnobool(coursesections[i].get('section') or "")

    printlog("Warning: course_sections has no entry " + str(i + 1) + " to match class_meets_locations; writing this section's events without a section name")

    return ""

def getTimeString(t):
    return t.strftime('%H%M%S')
    
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
    
def getCourseDate(startdate, weeknum, dayidx, M, T, W, R, F, S, U, tostring=True):
    dt = parseDate(startdate)
    weeknum = int(weeknum)
    dayidx = int(dayidx)
    
    dt = addweeks(dt, weeknum)
    daynum = getDayNum(dayidx, M, T, W, R, F, S, U)
    dt = adddays(dt, daynum)
    
    if tostring:
        return getDateString(dt)
    else:
        return dt
    
# Assumes the quiz has already been added to the shell with a name that matches the parameter
def find_quiz_by_title(course, quiz_name):
    quizzes = course.get_quizzes()
        
    for quiz in quizzes:
        if quiz.title == quiz_name:
            print("Found quiz: " + quiz.title + " while searching for: " + quiz_name)
        
            return quiz
            
    return None # not found
    
# Create Assignment Shells: https://canvasapi.readthedocs.io/en/stable/examples.html#create-an-assignment
def create_assignment(course, inputdict):
    if skipassignments:
        return

    asmt = course.create_assignment(inputdict)
    
    return asmt
    
def edit_quiz(quiz, inputdict):
    newquiz = quiz.edit(quiz=inputdict)

    return newquiz
    
# Create a Rubric
# https://canvas.instructure.com/doc/api/rubrics.html
# https://canvasapi.readthedocs.io/en/stable/rubric-ref.html#canvasapi.rubric.Rubric
# POST /api/v1/courses/:course_id/rubrics
def create_rubric(course, inputdict): 
    rubric = course.create_rubric(**inputdict)    
    return rubric
    
# Create Assignment Group: https://canvas.instructure.com/doc/api/assignment_groups.html#method.assignment_groups_api.create
def create_assignmentgroup(course, inputdict):
    asmtgroup = course.create_assignment_group(**inputdict)
    return asmtgroup

# Create a Module: https://canvas.instructure.com/doc/api/modules.html#method.context_modules_api.create
def create_module(course, inputdict, position=-1):
    module = course.create_module(inputdict)
    if position >= 1:
        module.edit(module={'position': position})
    return module
    
# Add an item to an existing module: https://canvas.instructure.com/doc/api/modules.html#method.context_module_items_api.create
def add_module_item(module, inputdict):
    moduleitem = module.create_module_item(inputdict)
    module.edit(module={'published': True})
    return moduleitem
    
def get_assignment_group_containing_label(groups, label):
    for group in groups:
        name = group.name
        
        if label in name:
            return group
    
    return None

def getposidxandinc(map, key):
    if not (key in map):
        map[key] = 1 # positions are 1 indexed
    
    pos = map[key]
    map[key] = map[key] + 1 # increment the position for the next call
    
    return pos
        
def add_assignments_to_groups(course, postdict):
    # Track positions for each group to order them in the Canvas view
    posidx = {}
    
    # Get all the assignments
    assignments = course.get_assignments()
    
    # Get all the assignment groups
    groups = course.get_assignment_groups()
    
    # If the assignment is already in the quiz group due to an import, don't move it
    quizgroup = get_assignment_group_containing_label(groups, 'Quiz') 
    
    # If Lab, Project, Assignment (etc...) is in the name, add it to the weight column with Lab, Project, or Assignment (etc...) in the name (you can prefix a deliverable name with the name of a grade breakdown column and it will add to that as well)
    for assignment in assignments:
        name = assignment.name
        asmtid = assignment.id
        asmtgroup = assignment.assignment_group_id
        
        group = None
        
        if 'Lab:' in name:
            group = get_assignment_group_containing_label(groups, 'Lab')
        elif 'Programming Assignment:' in name:
            group = get_assignment_group_containing_label(groups, 'Programming Assignment')
        elif 'Written Assignment:' in name:
            group = get_assignment_group_containing_label(groups, 'Written Assignment')
        elif 'Homework Assignment:' in name:
            group = get_assignment_group_containing_label(groups, 'Homework Assignment')            
        elif 'Project:' in name:
            group = get_assignment_group_containing_label(groups, 'Project')
        elif 'Exercise:' in name:
            group = get_assignment_group_containing_label(groups, 'Exercise')
        elif 'Participation:' in name:
            group = get_assignment_group_containing_label(groups, 'Participation') 
        elif 'Quiz:' in name or asmtgroup == quizgroup:
            group = quizgroup            
        else:
            if 'grade_breakdown' in postdict:
                # First sweep: the whole category name (less a trailing s) must appear in the
                # assignment name.  This runs to completion before the retry below, so anything
                # that groups today groups identically today
                for breakdown in (postdict['grade_breakdown'] or []): # the key can be present with no value
                    category = breakdown['category']

                    # remove last s if plural
                    categorylookup = category
                    if len(category) > 0 and category[-1] == 's':
                        categorylookup = category[:-1]

                    if categorylookup in name:
                        group = get_assignment_group_containing_label(groups, category)
                        break

                # Second sweep: only if nothing at all matched above, retry on the category text
                # ahead of a parenthetical, so that a category named "Essay 1 (1200-1500 words)"
                # can still claim "Essay 1: First Draft" instead of stranding it.  Do not merge
                # this into the sweep above: a later category's leading text would then be able to
                # beat an earlier category's whole-name match and re-home an assignment that is
                # grouped correctly today
                if group is None:
                    for breakdown in (postdict['grade_breakdown'] or []):
                        category = breakdown['category']

                        categorylookup = category.split(" (")[0]

                        if categorylookup == category or len(categorylookup) == 0:
                            continue # no parenthetical to drop, or nothing would be left to match on

                        # remove last s if plural
                        if categorylookup[-1] == 's':
                            categorylookup = categorylookup[:-1]

                        if len(categorylookup) > 0 and categorylookup in name:
                            group = get_assignment_group_containing_label(groups, category)
                            printlog("Grouping " + name + " under " + category + " by its leading text \"" + categorylookup + "\": the full category name does not appear in the assignment name")
                            break

        if not (group is None):
            pos = getposidxandinc(posidx, group)
            groupid = group.id
            
            assignment.edit(assignment={'assignment_group_id': groupid, 'position': pos})
    
    # Add quizzes to the Quiz group    
    if not (quizgroup is None):
        quizzes = course.get_quizzes()
        
        for quiz in quizzes:
            inputdict = {}
            
            groupid = quizgroup.id
            inputdict['assignment_group_id'] = groupid

            quiz = edit_quiz(quiz, inputdict)            
            
    # Enable assignment group weighted grading
    course.update(course={'apply_assignment_group_weights': True})
    
# Create Calendar: https://canvasapi.readthedocs.io/en/stable/canvas-ref.html (canvas.create_calendar_event, dict from https://canvas.instructure.com/doc/api/calendar_events.html)
def create_calendar_event(canvas, inputdict):
    try:
        canvas.create_calendar_event(inputdict)
    except exceptions.ResourceDoesNotExist:
        print("Calendar Event Creation: Resource Does Not Exist")

def create_late_policy(course, inputdict):
    try:
        course.create_late_policy(**inputdict)
    except: # if the late policy already exists, edit it
        course.edit_late_policy(**inputdict)
    
def process_markdown(fname, canvas, course, courseid, homepage):
    f = open(fname, 'r')
    mdcontents = f.read()
    
    post = frontmatter.loads(mdcontents)
    postdict = post.to_dict()
    
    coursecontext = 'course_' + str(courseid)

    coursenum = postdict['info']['course_number']
    coursename = postdict['info']['course_title']
    startdate = postdict['info']['course_start_date']
    enddate = postdict['info']['course_end_date']
    lia_base = get_lia_base(load_site_config(fname))

    # the last day the class actually meets, before the due date offset below: recurring events
    # have to count weeks against this, or a term ending on a Sunday picks up an extra week
    lastclassdate = enddate

    # offset the course end date by the same amount as assignments so that assignments can be due just past midnight if the grace period allows it; preserve the date string format so we can manipulate it consistently later
    enddate = getDateString(adddays(parseDate(enddate), DUE_DATE_OFFSET), fmt='%Y/%m/%d')
    
    isM = postdict['info']['class_meets_days']['isM']
    isT = postdict['info']['class_meets_days']['isT']
    isW = postdict['info']['class_meets_days']['isW']
    isR = postdict['info']['class_meets_days']['isR']
    isF = postdict['info']['class_meets_days']['isF']
    isS = postdict['info']['class_meets_days']['isS']
    isU = postdict['info']['class_meets_days']['isU']
    
    late_penalty_per_period = float(postdict['info']['late_penalty_per_period'])
    late_penalty_period = postdict['info']['late_penalty_period']
    
    printlog("Replacing Syllabus Page with Course Homepage...")
    
    course.update(course={'time_zone': CANVAS_TIME_ZONE}) # Set time zone to Eastern Time
    course.update(course={'syllabus_body': "<iframe src=\"" + homepage + "\" title=\"Course Homepage\" width=\"1024\" height=\"768\"></iframe>"}) # Set Syllabus to Course Webpage
    
    printlog("Deleting Old Data...")
    
    # Delete All Assignments, Events, etc.; Re-Initialize Here
    delete_old_data(course, canvas, coursecontext)
       
    printlog("Creating Discussion Board Topics...")
    
    # Create Discussion Topics
    inputdict = {}
    inputdict['title'] = "Introductions"
    inputdict['message'] = "Welcome!  Please use this space to introduce yourself.  Feel free to say anything about yourself that you are comfortable sharing, like a word on why you are taking this course and what you hope to get from it."
    inputdict['discussion_type'] = "threaded"
    inputdict['pinned'] = True
    inputdict['published'] = True
    add_discussion_topic(course, inputdict)
    
    inputdict = {}
    inputdict['title'] = "Class Activity Questions"
    inputdict['message'] = "This space will be used to answer class activity questions posed during the course."
    inputdict['discussion_type'] = "threaded"
    inputdict['pinned'] = True
    inputdict['published'] = True
    add_discussion_topic(course, inputdict)    
    
    inputdict = {}
    inputdict['title'] = "Readings Discussion and Questions"
    inputdict['message'] = "This is a space to pose questions and engage in thoughtful discussion about the course readings."
    inputdict['discussion_type'] = "threaded"
    inputdict['pinned'] = True
    inputdict['published'] = True
    add_discussion_topic(course, inputdict)    
    
    inputdict = {}
    inputdict['title'] = "Water Cooler"
    inputdict['message'] = "This is an open space - feel free to socialize here, post items that are on-topic or off-topic.  I do ask that you adhere to the classroom etiquitte and standards."
    inputdict['discussion_type'] = "threaded"
    inputdict['pinned'] = True
    inputdict['published'] = True
    add_discussion_topic(course, inputdict)    
    
    printlog("Writing Lecture Schedule...")
    
    moduleidx = 1 # module positions are 1-indexed
    asmtidx = 1 # assignment index position as well

    # Standing modules for tagged items, positioned above the first class day.
    # They are only created when something will actually go in them.
    tagged_modules = {}
    wants_resources = any(k in postdict['info'] for k in
        ('course_homepage', 'class_notebook', 'teamshelproom', 'chatlink', 'issspecifictutoring'))
    wants_overarching = False
    for scanitem in postdict['schedule']:
        for entry in list(scanitem.get('deliverables') or []) + list(scanitem.get('readings') or []):
            tag = get_module_tag(entry)
            if tag == MODULE_TAG_RESOURCE:
                wants_resources = True
            elif tag == MODULE_TAG_OVERARCHING:
                wants_overarching = True

    for tag, name, wanted in ((MODULE_TAG_RESOURCE, MODULE_NAME_RESOURCE, wants_resources),
                              (MODULE_TAG_OVERARCHING, MODULE_NAME_OVERARCHING, wants_overarching)):
        if wanted:
            inputdict = {}
            inputdict['name'] = name
            inputdict['published'] = True
            tagged_modules[tag] = create_module(course, inputdict, moduleidx)
            moduleidx = moduleidx + 1
    
    # Write the lecture schedule as a recurring event
    coursesections = postdict['info'].get('course_sections') or []

    for i in range(len(postdict['info']['class_meets_locations'])):
        section = getSectionName(coursesections, i)

        for meeting in postdict['info']['class_meets_locations'][i]['section']:
            day = meeting['day']
            daynum = getDayCodeNum(meeting['day'])
            
            dt = parseDate(startdate)
            dt = adddays(dt, daynum)
            
            dtstart = getDateString(dt)
            dtstart = dtstart + "T"
            dtstart = dtstart + getTimeString(parseTime(meeting['starttime'])) 
            
            dtend = getDateString(dt) # Assume event ends on the same day
            dtend = dtend + "T"
            dtend = dtend + getTimeString(parseTime(meeting['endtime'])) # leave in local time

            location = meeting.get('place') or ""

            if len(section) > 0:
                summary = coursenum + " " + coursename + " Section " + section + " Class Meeting"
            else:
                summary = coursenum + " " + coursename + " Class Meeting"

            # Write lecture schedule events
            if not skiplecturecalendar:
                inputdict = {}
                inputdict['context_code'] = coursecontext
                inputdict['title'] = summary.strip()
                inputdict['description'] = summary.strip()
                inputdict['location_name'] = stripnobool(location)
                inputdict['start_at'] = dtstart
                inputdict['end_at'] = dtend            
                inputdict['time_zone_edited'] = CANVAS_TIME_ZONE 
                inputdict['all_day'] = False
                inputdict['duplicate'] = {}
                inputdict['duplicate']['frequency'] = "weekly"
                inputdict['duplicate']['count'] = countWeeks(parseDate(startdate), parseDate(lastclassdate))
            
                create_calendar_event(canvas, inputdict)

    # The standing course links are resources, not first-day business, so they
    # live in the Resources module rather than being injected into day one.
    if MODULE_TAG_RESOURCE in tagged_modules:
        for infokey, itemtitle in (
                ('course_homepage', "Course Homepage"),
                ('class_notebook', "Access the Class Notebook"),
                ('teamshelproom', "Access the Class Teams Help Room Channel"),
                ('chatlink', "Access the Class Group Chat"),
                ('issspecifictutoring', "ISS Group Tutoring and Individual Tutoring Sign-Up")):
            if infokey in postdict['info']:
                inputdict = {}
                inputdict['title'] = itemtitle
                inputdict['type'] = "ExternalUrl"
                inputdict['external_url'] = postdict['info'][infokey]
                inputdict['new_tab'] = True
                inputdict['published'] = True
                add_module_item(tagged_modules[MODULE_TAG_RESOURCE], inputdict)

    printlog("Writing Assignments...")
    scheduleitems = 0
    for item in postdict['schedule']:   
        weekidx = item.get('week', 0)
        dayidx = item.get('date', 0)
        if 'title' in item:
            title = item['title']
        else:
            title = "N/A"
        # an absent or empty link is fine and reads as no link at all, the same test the
        # deliverable links below already use
        if 'link' in item and len(str(item['link']).strip()) > 0 and str(item['link']).strip().lower() != "false":
            link = lia_resolve(item, item['link'], lia_base)
        else:
            link = ""

        coursedt = get_item_date(item, startdate, isM, isT, isW, isR, isF, isS, isU)
        startd = getDateString(coursedt)
        coursedtstr = coursedt.strftime('%a, %b %d, %Y')
        if 'reschedule' in item:
            coursedtstr = item['reschedule']
        
        if 'cdate' in item and str(item['cdate']).strip():
            # a custom-dated session is off the meeting grid, so a day index would lie
            weekdayidx = "(Week " + str(int(weekidx)+1) + ")"
        else:
            weekdayidx = "(Week " + str(int(weekidx)+1) + " Day " + str(int(dayidx)+1) + ")"
        
        # Create a module for this entry
        inputdict = {}
        inputdict['name'] = coursedtstr + " - " + title   
        inputdict['published'] = True
        module = create_module(course, inputdict, moduleidx)
        moduleidx = moduleidx + 1 # for positioning
        
        scheduleitems = scheduleitems + 1
        
        # Create a Module Entry for Class Notes Link
        if link:
            inputdict = {}
            inputdict['title'] = "Activity: " + title
            inputdict['type'] = "ExternalUrl"
            inputdict['external_url'] = makelink(addslash(homepage), stripnobool(link))
            inputdict['new_tab'] = True
            inputdict['published'] = True
            add_module_item(module, inputdict)
            
        if 'deliverables' in item:
            for deliverable in (item['deliverables'] or []): # the key can be present with no value
                dtitle = deliverable['dtitle']
                if 'dlink' in deliverable and len(str(deliverable['dlink']).strip()) > 0 and str(deliverable['dlink']).strip().lower() != "false":
                    dlink = lia_resolve(deliverable, deliverable['dlink'], lia_base)
                else:
                    dlink = None
                    
                if 'points' in deliverable:
                    points = int(deliverable['points'])
                else:
                    points = 100                    
                
                description = dtitle.strip() 

                # Create an Assignment Shell
                if (not (' handed out' in description.lower()) and not ('quiz:' in description.lower())):
                    description = rchop(description, " Due")
                    
                    duedate = getDateString(adddays(coursedt, DUE_DATE_OFFSET)) # offset the due date as needed for the due time which is in UTC
                    
                    # read the submission types once: the key can be present with no value
                    submissiontypes = str(deliverable.get('submission_types') or "").lower()

                    inputdict = {}
                    inputdict['name'] = description
                    inputdict['submission_types'] = []
                    if "onpaper" in submissiontypes:
                        inputdict['submission_types'].append('on_paper')
                    elif "noupload" in submissiontypes:
                        inputdict['submission_types'].append('online_text_entry')                    
                    else:
                        inputdict['submission_types'].append('online_upload')
                        inputdict['allowed_extensions'] = []
                        inputdict['allowed_extensions'].append('zip')
                        inputdict['allowed_extensions'].append('bz2')
                        inputdict['allowed_extensions'].append('tar')
                        inputdict['allowed_extensions'].append('gz')
                        inputdict['allowed_extensions'].append('rar')
                        inputdict['allowed_extensions'].append('7z')
                        if "written" in submissiontypes:
                            inputdict['submission_types'].append('online_text_entry')
                            inputdict['allowed_extensions'].append('pdf')
                            inputdict['allowed_extensions'].append('doc')
                            inputdict['allowed_extensions'].append('docx')
                            inputdict['allowed_extensions'].append('txt')
                    inputdict['notify_of_update'] = True
                    inputdict['published'] = True
                    inputdict['points_possible'] = points
                    
                    if dlink is None:
                        inputdict['description'] = description 
                    else:
                        inputdict['description'] = description + " (<a href=\"" + makelink(addslash(homepage), stripnobool(dlink)) + "\">" + makelink(addslash(homepage), stripnobool(dlink)) + "</a>)"
                        
                    inputdict['due_at'] = parseDateTimeCanvas(datetime.strptime(duedate + get_local_time(duedate), DUE_DATE_FORMAT)) 
                    inputdict['lock_at'] = parseDateTimeCanvas(datetime.strptime(enddate.replace('/', '') + get_local_time(enddate), DUE_DATE_FORMAT)) # lock out assignments on the last day of the class
                    inputdict['position'] = asmtidx
                    
                    printlog("Adding Assignment: " + description + " due at: " + str(duedate))
                            
                    assignment = create_assignment(course, inputdict)
                    asmtidx = asmtidx + 1
                    
                    assignmentid = assignment.id
                    
                    # Create a Rubric for this Assignment if Specified
                    if "rubricpath" in deliverable:
                        inputdict = {}
                        
                        rubricpath = deliverable['rubricpath']
                        printlog("Adding Rubric from " + rubricpath)
                        rubricf = open(rubricpath, 'r')
                        rubricmdcontents = rubricf.read()
                        rubricpost = frontmatter.loads(rubricmdcontents)
                        rubricpostdict = rubricpost.to_dict()  
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
                                criteriapoints = (points * float(criteria['weight']) / 100)
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
                                criteriaidx = criteriaidx + 1

                        create_rubric(course, inputdict)
                    
                    # Create a Module Entry for the Assignment
                    inputdict = {}
                    inputdict['title'] = description
                    inputdict['type'] = 'Assignment'
                    inputdict['content_id'] = assignmentid
                    inputdict['published'] = True
                    add_module_item(module, inputdict)
                elif ('quiz:' in description.lower()):
                    if 'qtizippath' in deliverable:
                        # upload the quiz automatically
                        quiz_path = deliverable['qtizippath']
                        
                        print("Uploading Quiz: " + quiz_path)
                        
                        create_quiz_content_migration(course, quiz_path)
                    else:
                        # prompt the user to upload the quiz
                        input("Import the QTI for this quiz under Settings - Import Course Content on Canvas and press enter to continue: " + description)
                        
                    quiz_name = lchop(description, "Quiz: ")
                    quiz = find_quiz_by_title(course, quiz_name)
                    if not (quiz is None):
                        duedate = adddays(coursedt, DUE_DATE_OFFSET) # offset the due date as needed for the due time which is in UTC
                        opendate = adddays(duedate, -2) # unlock the quiz 2 days before
                        duedate = getDateString(duedate)
                        opendate = getDateString(opendate)
                        
                        inputdict = {}
                        inputdict['quiz_type'] = "assignment"
                        inputdict['unlock_at'] = parseDateTimeCanvas(datetime.strptime(opendate + get_local_time(opendate), DUE_DATE_FORMAT))
                        inputdict['due_at'] = parseDateTimeCanvas(datetime.strptime(duedate + get_local_time(duedate), DUE_DATE_FORMAT)) 
                        inputdict['lock_at'] = parseDateTimeCanvas(datetime.strptime(enddate.replace('/', '') + get_local_time(enddate), DUE_DATE_FORMAT)) # lock out assignments on the last day of the class
                        inputdict['show_correct_answers'] = True
                        inputdict['published'] = True
                        inputdict['show_correct_answers_at'] = parseDateTimeCanvas(datetime.strptime(duedate + get_local_time(duedate), DUE_DATE_FORMAT)) # show quiz results after the deadline
                        
                        quiz = edit_quiz(quiz, inputdict) # we'll move the quiz if needed into the right assignment group with other assignments, once the groups are created 
                    else:
                        print("Warning: quiz " + quiz_name + " not found.")
                else:
                    # Create a Module Entry for the Deliverable.
                    # A tagged deliverable keeps its assignment, points, and due date
                    # above; only the module item moves to the standing module.
                    inputdict = {}
                    inputdict['title'] = dtitle
                    if dlink is None:
                        inputdict['type'] = "SubHeader"
                    else:
                        inputdict['type'] = "ExternalUrl"
                        inputdict['external_url'] = makelink(addslash(homepage), stripnobool(dlink))
                        inputdict['new_tab'] = True            
                    inputdict['published'] = True
                    add_module_item(tagged_modules.get(get_module_tag(deliverable), module), inputdict)  
                    
        if 'readings' in item:
            for reading in (item['readings'] or []): # the key can be present with no value
                rtitle = reading['rtitle']
                if 'rlink' in reading and len(str(reading['rlink']).strip()) > 0 and str(reading['rlink']).strip().lower() != "false":
                    rlink = lia_resolve(reading, reading['rlink'], lia_base)
                else:
                    rlink = None  
                
                # Create a Module Entry for the Reading Activity.
                # A tagged reading keeps its place on the syllabus page; only the
                # Canvas module item moves to the standing module.
                inputdict = {}
                inputdict['title'] = rtitle
                inputdict['published'] = True
                if rlink is None:
                    inputdict['type'] = "SubHeader"
                else:
                    inputdict['type'] = "ExternalUrl"
                    inputdict['external_url'] = makelink(addslash(homepage), stripnobool(rlink))
                    inputdict['new_tab'] = True            
                
                add_module_item(tagged_modules.get(get_module_tag(reading), module), inputdict) 

    printlog("Omitting attendance grade...")
    omit_attendance_grade(course)                
    
    # https://canvas.instructure.com/doc/api/late_policy.html
    printlog("Writing Late Policy...")
    inputdict = {}
    inputdict['late_policy'] = {}
    inputdict['late_policy']['late_submission_deduction_enabled'] = True
    inputdict['late_policy']['missing_submission_deduction_enabled'] = True
    inputdict['late_policy']['missing_submission_deduction'] = 100
    inputdict['late_policy']['late_submission_deduction'] = late_penalty_per_period
    inputdict['late_policy']['late_submission_interval'] = late_penalty_period
    create_late_policy(course, inputdict)
    
    if skipofficehours == False:
        printlog("Writing Office Hours...")
        
        # Write Office Hours as a Recurring Event
        for instructor in (postdict.get('instructors') or []):
            instructorname = instructor['name']

            # a Writing Fellow, lab assistant, or other staff member may hold no scheduled
            # drop-in hours at all, so the key can be missing or present with no value
            for officehour in (instructor.get('officehours') or []):
                day = officehour['day']
                daynum = getDayCodeNum(officehour['day'])
                
                dt = parseDate(startdate)
                dt = adddays(dt, daynum)
                
                dtstart = getDateString(dt)
                dtstart = dtstart + "T"
                dtstart = dtstart + getTimeString(parseTime(officehour['starttime'])) 

                dtend = getDateString(dt) # assume no event overlaps a day boundary, ends on start date
                dtend = dtend + "T"
                dtend = dtend + getTimeString(parseTime(officehour['endtime'])) # leave in local time

                location = officehour.get('location') or ""
                
                summary = coursenum + " " + coursename + " Drop-In / Office Hours with " + instructorname
                
                inputdict = {}
                inputdict['context_code'] = coursecontext
                inputdict['title'] = summary.strip()
                inputdict['description'] = summary.strip()
                inputdict['location_name'] = stripnobool(location)
                inputdict['start_at'] = dtstart
                inputdict['end_at'] = dtend
                inputdict['time_zone_edited'] = CANVAS_TIME_ZONE 
                inputdict['all_day'] = False
                inputdict['duplicate'] = {}
                inputdict['duplicate']['frequency'] = "weekly"
                inputdict['duplicate']['count'] = countWeeks(parseDate(startdate), parseDate(lastclassdate))
                
                create_calendar_event(canvas, inputdict)  

    printlog("Writing Exams...")
    
    # Write Exam Dates
    # a course with no exams can omit these keys, and a section can be missing an entry
    midtermexams = postdict['info'].get('midtermexam') or []
    finalexams = postdict['info'].get('finalexam') or []

    for i in range(len(postdict['info']['class_meets_locations'])):
        section = getSectionName(coursesections, i)

        if i < len(midtermexams) and not (midtermexams[i]['mdate'] == "TBD"):
            startd = getDateString(parseDate(midtermexams[i]['mdate']))
            startd = startd + "T"
            startd = startd + getTimeString(parseTime(midtermexams[i]['mstarttime'])) # leave in local time

            endd = getDateString(parseDate(midtermexams[i]['mdate']))
            endd = endd + "T"
            endd = endd + getTimeString(parseTime(midtermexams[i]['mendtime'])) # leave in local time

            dtitle = "Midterm Exam"
            location = midtermexams[i].get('mroom') or ""
            
            # Write the exam:
            if not skiplecturecalendar:
                inputdict = {}
                inputdict['context_code'] = coursecontext
                inputdict['title'] = dtitle.strip()
                inputdict['description'] = dtitle.strip()
                inputdict['location_name'] = stripnobool(location)
                inputdict['start_at'] = startd
                inputdict['end_at'] = endd
                inputdict['time_zone_edited'] = CANVAS_TIME_ZONE 
                inputdict['all_day'] = False
                
                create_calendar_event(canvas, inputdict)  

        if i < len(finalexams) and not (finalexams[i]['fdate'] == "TBD"):
            startd = getDateString(parseDate(finalexams[i]['fdate']))
            startd = startd + "T"
            startd = startd + getTimeString(parseTime(finalexams[i]['fstarttime'])) # leave in local time, timezone info given above assuming Eastern Time

            endd = getDateString(parseDate(finalexams[i]['fdate']))
            endd = endd + "T"
            endd = endd + getTimeString(parseTime(finalexams[i]['fendtime'])) # leave in local time, timezone info given above assuming Eastern Time

            dtitle = "Final Exam"
            location = finalexams[i].get('froom') or ""
            
            # Write the exam:
            if not skiplecturecalendar:
                inputdict = {}
                inputdict['context_code'] = coursecontext
                inputdict['title'] = dtitle.strip()
                inputdict['description'] = dtitle.strip()
                inputdict['location_name'] = stripnobool(location)
                inputdict['start_at'] = startd
                inputdict['end_at'] = endd
                inputdict['time_zone_edited'] = CANVAS_TIME_ZONE 
                inputdict['all_day'] = False
                
                create_calendar_event(canvas, inputdict)    
    
    printlog("Creating Assignment Groups...")
    
    # Write Out Assignment Groups   
    if 'grade_breakdown' in postdict:
        for breakdown in (postdict['grade_breakdown'] or []): # the key can be present with no value
            inputdict = {}
            
            inputdict['name'] = breakdown['category']
            inputdict['group_weight'] = float(rchop(breakdown['weight'], '%'))
            
            # The Assignments group might exist by default - don't call anything that group name as an assignment category or grade breakdown just in case
            create_assignmentgroup(course, inputdict)
            
        add_assignments_to_groups(course, postdict)
        
        # Delete the default Assignments and Imported Assignments gradebook groups; don't use these on syllabi
        delete_assignment_group_by_name(course, "Assignments")        
        delete_assignment_group_by_name(course, "Imported Assignments")         

def get_courseid(canvas, user):
    courses = user.get_courses()
    
    for course in courses:
        print(course)
        
    courseid = input("Which Course ID? ")

    return int(courseid)

def usage():
    print("Usage:")
    print("\t[-h | --help]\tUsage Documentation")
    print("\t[-c | --courseid]\tCanvas Course ID number (can be found using canvas link after logging in); omit for a course listing here")
    print("\t[-m | --markdown]\tPath to course syllabus markdown file")  
    print("\t[-w | --webpage]\tURL of hosted course homepage (https://www.yourhomepage.com/course)")
    print("\t[-a | --apikey]\tAPI Key (get from API_URL + /profile/settings)")
    print("\t[-u | --userid]\tUser ID Number (get from API_URL + /api/v1/users/self)")
    print("\t[-t | --timezone]\tTime Zone (i.e. America/New_York)")
    print("\t[-e | --duetime]\t Due Times in UTC for Your Time Zone for standard time and daylight time (i.e., T045959Z|T035959Z for Eastern Time)")
    print("\t[-d | --nodiscussions]\tDo not delete or re-create discussion topics and entries")
    print("\t[-s | --noassignments]\tDo not delete or re-create assignments (but still re-arrange existing ones in modules view)")
    print("\t[-o | --noofficehours]\tDo not delete or re-create office hours")
    print("\t[-l | --nolecturecalendar]\tDo not upload lecture calendar")
    print("\t[-k | --nodeletes]\tDo not delete old data")
    print("\nDo not create an assignment group called Assignments, and do prefix assignment names with the desired Assignment Group Name: Deliverable")
    
# Only run the deployment when invoked as a script, so that these functions can be imported
if __name__ == "__main__":
    # Parse user options
    # https://docs.python.org/3/library/getopt.html
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hc:m:w:a:u:t:e:dsolk", ["help", "courseid=", "markdown=", "webpage=", "apikey=", "userid=", "timezone=", "duetime=", "nodiscussions", "noassignments", "noofficehours", "nolecturecalendar", "nodeletes"])
    except getopt.GetoptError as err:
        # print help information and exit:
        print(err)  # will print something like "option -z not recognized"
        usage()
        sys.exit(2)

    courseid = -1
    markdownfile = None
    coursehomepage = None
    USER_ID = None
    API_KEY = None

    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
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
            LOCALTIME = pytz.timezone(CANVAS_TIME_ZONE) # or get_local_time keeps deciding DST in the default zone
        elif o in ("-e", "--duetime"):
            atimes = a.split("|")
            DUE_TIME_ST = atimes[0]
            DUE_TIME_DST = atimes[1]
        elif o in ("-d", "--nodiscussions"):
            skipdiscussions = True
        elif o in ("-s", "--noassignments"):
            skipassignments = True
        elif o in ("-o", "--noofficehours"):
            skipofficehours = True   
        elif o in ("-l", "--nolecturecalendar"):
            skiplecturecalendar = True
        elif o in ("-k", "--nodeletes"):
            skipalldeletes = True

    if USER_ID is None:
        USER_ID = input("Enter User ID (get from API_URL + /api/v1/users/self): ")
    if API_KEY is None:
        API_KEY = input("Enter API Key (get from API_URL + /profile/settings): ")
    
    printlog("Instantiating Canvas...")
    # Instantiate Canvas and Course
    canvas = Canvas(API_URL, API_KEY)
    user = canvas.get_user(USER_ID)

    if courseid == -1:
        courseid = get_courseid(canvas, user)
    if markdownfile is None:
        markdownfile = input("Enter path to course syllabus markdown file: ")
    if coursehomepage is None:
        coursehomepage = input("Enter course website (https://www.yourhomepage.com/course): ")
    
    course = canvas.get_course(courseid)

    printlog("Reading Markdown...")
    # Read Course Markdown File
    process_markdown(markdownfile, canvas, course, courseid, coursehomepage)

    printlog("Hiding/Showing Tabs...")
    # Hide Navigation Tabs
    arrange_tabs(course)

    printlog("Finished: Waiting for Child Threads to Terminate")
    # Clean Up
    for t in child_threads:
            t.join()