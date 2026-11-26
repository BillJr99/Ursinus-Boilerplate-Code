"""Shared group-set rules for Canvas deployment and assignment maintenance."""

import os


DEFAULT_GROUP_SET = "Project Groups"


def group_set_name(value=None):
    name = value if value is not None else os.environ.get("CANVAS_GROUP_SET", DEFAULT_GROUP_SET)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("group set name must be nonempty")
    return name.strip()


def deliverable_is_group(deliverable):
    value = deliverable.get("group", False)
    if not isinstance(value, bool):
        raise ValueError("deliverable %r: group must be a YAML boolean" % deliverable.get("dtitle"))
    return value


def syllabus_group_assignments(doc):
    """Return group assignment names using the deploy's title rules."""
    flags = {}
    for day in doc.get("schedule", []) or []:
        for deliverable in day.get("deliverables", []) or []:
            grouped = deliverable_is_group(deliverable)
            title = (deliverable.get("dtitle") or "").strip()
            lower = title.lower()
            if not title or " handed out" in lower or "quiz:" in lower:
                if grouped:
                    raise ValueError("group: true requires an assignment deliverable: %r" % title)
                continue
            name = title.removesuffix(" Due")
            if name in flags and flags[name] != grouped:
                raise ValueError("conflicting group flags for assignment %r" % name)
            flags[name] = grouped
    return {name for name, grouped in flags.items() if grouped}


def find_group_set(course, name):
    matches = [category for category in course.get_group_categories() if category.name == name]
    if len(matches) > 1:
        raise ValueError("multiple Canvas group sets named %r" % name)
    if not matches:
        return None
    category = matches[0]
    if getattr(category, "role", None) or getattr(category, "non_collaborative", False):
        raise ValueError("%r is not a regular collaborative Canvas group set" % name)
    return category


def ensure_group_set(course, name):
    category = find_group_set(course, name)
    if category is not None:
        return category
    return create_group_set(course, name)


def create_group_set(course, name):
    """Create a group set and verify that Canvas returns the same set."""
    created = course.create_group_category(name)
    category = find_group_set(course, name)
    if category is None or category.id != created.id:
        raise ValueError("Canvas group set could not be verified: %r" % name)
    return category


def check_assignment_group_set(assignment, category_id):
    """Return whether a change is necessary, refusing unverified conversions."""
    existing = getattr(assignment, "group_category_id", None)
    if existing not in (None, 0):
        if existing == category_id:
            return False
        raise ValueError("assignment %r is already attached to a different group set" % assignment.name)
    if getattr(assignment, "has_submitted_submissions", None) is not False:
        raise ValueError("assignment %r has submissions or its submission state is unknown" % assignment.name)
    return True


def check_membership_removals(course, category_id):
    """Return the reviewed assignment state for a destructive roster change."""
    attached = []
    for assignment in course.get_assignments():
        if getattr(assignment, "group_category_id", None) != category_id:
            continue
        fresh = course.get_assignment(assignment.id)
        if fresh.id != assignment.id or getattr(fresh, "group_category_id", None) != category_id:
            raise ValueError("attached assignment changed while checking group memberships")
        submitted = getattr(fresh, "has_submitted_submissions", None)
        if submitted is not False:
            raise ValueError("an attached assignment has submissions or its submission state is unknown")
        attached.append((fresh.id, submitted))
    return sorted(attached)


def verify_assignment_group_set(course, assignment_id, category_id, name):
    saved = course.get_assignment(assignment_id)
    if (saved.id != assignment_id or saved.name != name or
            getattr(saved, "group_category_id", None) != category_id):
        raise ValueError("Canvas did not verify the group set on assignment id %s" % assignment_id)


def ensure_assignment_group_set(course, assignment, category_id):
    fresh = course.get_assignment(assignment.id)
    if fresh.id != assignment.id or fresh.name != assignment.name:
        raise ValueError("Canvas assignment changed since group set planning")
    if check_assignment_group_set(fresh, category_id):
        fresh.edit(assignment={"group_category_id": category_id})
        verify_assignment_group_set(course, fresh.id, category_id, fresh.name)
