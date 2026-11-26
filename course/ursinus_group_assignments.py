#!/usr/bin/env python3
"""Plan or apply Canvas group memberships and attach syllabus group assignments."""

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from canvas_group_sets import (
    check_assignment_group_set,
    check_membership_removals,
    create_group_set,
    ensure_assignment_group_set,
    find_group_set,
    group_set_name,
    syllabus_group_assignments,
)


def read_syllabus(path):
    rows = path.read_text(encoding="utf-8-sig").splitlines()
    if not rows or rows[0].strip() != "---":
        raise ValueError("syllabus must begin with YAML front matter")
    end = next((i for i, row in enumerate(rows[1:], 1) if row.strip() == "---"), None)
    if end is None:
        raise ValueError("syllabus front matter has no closing delimiter")
    data = yaml.safe_load("\n".join(rows[1:end]))
    if not isinstance(data, dict):
        raise ValueError("syllabus front matter must be a mapping")
    return syllabus_group_assignments(data)


def read_mapping(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        if path.suffix.lower() == ".csv":
            reader = csv.DictReader(stream, strict=True)
            if sorted(reader.fieldnames or []) != ["group", "student"]:
                raise ValueError("CSV requires student and group columns")
            return validate_mapping(list(reader))
        if path.suffix.lower() in (".yaml", ".yml"):
            return validate_mapping(yaml.safe_load(stream))
    raise ValueError("group mapping must be CSV or YAML")


def validate_mapping(rows):
    if not isinstance(rows, list):
        raise ValueError("group mapping must be a list of student/group rows")
    mapping = {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.keys() != {"student", "group"}:
            raise ValueError(f"mapping row {index} requires student and group")
        student, group = row["student"], row["group"]
        if type(student) not in (str, int) or not isinstance(group, str):
            raise ValueError(f"mapping row {index} has an invalid student or group")
        student, group = str(student).strip(), group.strip()
        if not student or not group or any(ord(char) < 32 or ord(char) == 127 for char in student + group):
            raise ValueError(f"mapping row {index} has an empty or invalid student or group")
        if student in mapping:
            raise ValueError(f"duplicate student identifier at mapping row {index}")
        mapping[student] = group
    return mapping


def roster(course):
    entries = course.get_enrollments(type=["StudentEnrollment"], state=["active"])
    return {
        entry.user_id: entry.user
        for entry in entries
        if entry.type == "StudentEnrollment" and entry.enrollment_state == "active"
    }


def resolve_mapping(mapping, students):
    aliases = {}
    for user_id, student in students.items():
        for alias in (str(user_id), student.get("login_id"), student.get("sis_user_id")):
            if alias:
                aliases.setdefault(alias, set()).add(user_id)

    resolved = {}
    for row, (identifier, group) in enumerate(mapping.items(), 1):
        matches = aliases.get(identifier, set())
        if len(matches) != 1:
            raise ValueError(f"mapping row {row} does not identify one active student")
        user_id = next(iter(matches))
        if user_id in resolved:
            raise ValueError(f"mapping row {row} repeats an active student by another identifier")
        resolved[user_id] = group
    return resolved


def interactive_mapping(students):
    print("Assign an active student by Canvas user ID. Enter a blank group to skip.")
    rows = []
    for user_id, user in sorted(students.items()):
        group = input(f"{user.get('name') or 'Student'} ({user_id}): ").strip()
        if group:
            rows.append({"student": user_id, "group": group})
    return validate_mapping(rows)


def group_index(category):
    groups = {}
    for group in category.get_groups():
        if group.name in groups:
            raise ValueError("multiple Canvas groups have the same name in this set")
        groups[group.name] = group
    return groups


def group_members(group):
    members = {}
    for member in group.get_memberships():
        if getattr(member, "group_id", None) != group.id or getattr(member, "workflow_state", None) != "accepted":
            raise ValueError("unconfirmed group membership prevents safe planning")
        if member.user_id in members:
            raise ValueError("multiple memberships found for one student in this set")
        members[member.user_id] = member
    return members


def group_state(category):
    if category is None:
        return {}, {}
    groups, members = group_index(category), {}
    for name, group in groups.items():
        for user_id, member in group_members(group).items():
            if user_id in members:
                raise ValueError("multiple memberships found for one student in this set")
            members[user_id] = (name, member)
    return groups, members


@dataclass
class Plan:
    category: object
    new_groups: list
    removals: list
    additions: list
    assignments: list
    group_snapshot: list
    membership_snapshot: list
    assignment_snapshot: list
    removal_assignment_snapshot: list


def plan_changes(course, name, mapping, titles, prune=False):
    category = find_group_set(course, name)
    groups, members = group_state(category)
    removal, addition = [], []
    for user_id, group_name in mapping.items():
        prior = members.get(user_id)
        if prior and prior[0] == group_name:
            continue
        if prior:
            if not prune:
                raise ValueError("a mapped student already belongs to another group; review an explicit --prune plan")
            removal.append((user_id, prior[0], prior[1].id))
        addition.append((user_id, group_name))
    if prune:
        removal.extend((user_id, group_name, member.id)
                       for user_id, (group_name, member) in members.items() if user_id not in mapping)

    assignments, assignment_snapshot = [], []
    if titles:
        by_name = {}
        for assignment in course.get_assignments():
            if assignment.name in titles:
                by_name.setdefault(assignment.name, []).append(assignment)
        for title in sorted(titles):
            matches = by_name.get(title, [])
            if len(matches) != 1:
                raise ValueError(f"expected exactly one Canvas assignment named {title!r}")
            assignment = course.get_assignment(matches[0].id)
            if assignment.id != matches[0].id or assignment.name != title:
                raise ValueError(f"assignment changed while planning: {title!r}")
            assignment_snapshot.append((title, assignment.id, getattr(assignment, "group_category_id", None)))
            if check_assignment_group_set(assignment, category.id if category is not None else None):
                assignments.append(assignment)
    removal_assignment_snapshot = check_membership_removals(course, category.id) if removal else []
    new_groups = sorted(set(mapping.values()) - groups.keys())
    group_snapshot = sorted((name, group.id) for name, group in groups.items())
    membership_snapshot = sorted(
        (uid, name, member.id) for uid, (name, member) in members.items()
    )
    return Plan(category, new_groups, sorted(removal), sorted(addition), assignments,
                group_snapshot, membership_snapshot, assignment_snapshot, removal_assignment_snapshot)


def plan_digest(course, name, plan, mapping, titles, prune):
    payload = {
        "version": 2,
        "course": course.id,
        "group_set": name,
        "category": getattr(plan.category, "id", None),
        "prune": prune,
        "mapping": sorted(mapping.items()),
        "titles": sorted(titles),
        "groups": plan.group_snapshot,
        "memberships": plan.membership_snapshot,
        "assignments": plan.assignment_snapshot,
        "removal_assignments": plan.removal_assignment_snapshot,
        "create_groups": plan.new_groups,
        "remove_memberships": plan.removals,
        "add_memberships": plan.additions,
        "attach_assignments": [item.id for item in plan.assignments],
    }
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("ascii")).hexdigest()


def describe(plan, mapping, titles, prune):
    print(f"Group set: {'reuse existing' if plan.category else 'create'}")
    print(f"Groups to create: {len(plan.new_groups)}")
    print(f"Memberships to add: {len(plan.additions)}")
    print(f"Memberships to remove: {len(plan.removals)}")
    print(f"Assignments to attach: {len(plan.assignments)} of {len(titles)}")
    print(f"Active students mapped: {len(mapping)}")
    if prune:
        print("Prune removes memberships omitted from the mapping or assigned elsewhere. Groups are retained.")


def pace_writes():
    # Do not retry a mutation whose result is unknown. A fresh reviewed run can
    # reconcile partial progress using the current state.
    time.sleep(2)


def apply_plan(course, name, plan, mapping, titles, prune, expected_plan=None):
    fresh = plan_changes(course, name, mapping, titles, prune)
    fresh_digest = plan_digest(course, name, fresh, mapping, titles, prune)
    if prune and fresh_digest != expected_plan:
        raise ValueError("reviewed prune plan digest missing or changed; review a fresh dry run")
    if fresh_digest != plan_digest(course, name, plan, mapping, titles, prune):
        raise ValueError("Canvas state changed after planning; review a fresh dry run")
    category = fresh.category
    if category is None:
        pace_writes()
        if find_group_set(course, name) is not None:
            raise ValueError("Canvas group set appeared after planning")
        category = create_group_set(course, name)

    group_ids = dict(plan.group_snapshot)

    def current_groups():
        current = find_group_set(course, name)
        if current is None or current.id != category.id:
            raise ValueError("Canvas group set changed after planning")
        groups = group_index(current)
        if {group_name: group.id for group_name, group in groups.items()} != group_ids:
            raise ValueError("Canvas groups changed after planning")
        return current, groups

    current_groups()
    for group_name in plan.new_groups:
        pace_writes()
        current, _ = current_groups()
        created = current.create_group(name=group_name)
        group_ids[group_name] = created.id
        current_groups()

    if plan.removals and check_membership_removals(course, category.id) != plan.removal_assignment_snapshot:
        raise ValueError("attached assignments changed after planning")

    def remove_membership(user_id, group_name, membership_id, destination=None):
        pace_writes()
        _, groups = current_groups()
        if destination is not None and user_id in group_members(groups[destination]):
            raise ValueError("planned move destination membership changed")
        current = group_members(groups[group_name]).get(user_id)
        if current is None or current.id != membership_id:
            raise ValueError("a membership changed after planning")
        _, groups = current_groups()
        group = groups[group_name]
        group.remove_user(user_id)
        if user_id in group_members(group):
            raise ValueError("Canvas did not verify the membership removal")

    def add_membership(user_id, group_name):
        pace_writes()
        _, groups = current_groups()
        if user_id in group_members(groups[group_name]):
            raise ValueError("a membership changed after planning")
        _, groups = current_groups()
        group = groups[group_name]
        group.create_membership(user_id)
        if user_id not in group_members(group):
            raise ValueError("Canvas did not verify the membership addition")

    removals = {user_id: (group_name, member_id) for user_id, group_name, member_id in plan.removals}
    for user_id, group_name in plan.additions:
        if user_id in removals:
            remove_membership(user_id, *removals.pop(user_id), destination=group_name)
        add_membership(user_id, group_name)
    for user_id, (group_name, member_id) in removals.items():
        remove_membership(user_id, group_name, member_id)

    for assignment in plan.assignments:
        pace_writes()
        current_groups()
        ensure_assignment_group_set(course, assignment, category.id)
    verified = plan_changes(course, name, mapping, titles, prune)
    if (verified.category is None or verified.category.id != category.id or verified.new_groups
            or verified.removals or verified.additions or verified.assignments):
        raise ValueError("Canvas read-back still differs from the plan")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--courseid", type=int, help="verified Canvas course ID")
    parser.add_argument("-m", "--markdown", "--syllabus", type=Path, required=True, help="syllabus Markdown")
    parser.add_argument("--group-set", help="Canvas group set name; defaults to CANVAS_GROUP_SET or Project Groups")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mapping", type=Path, help="CSV or YAML rows with student and group fields")
    source.add_argument("--interactive", action="store_true", help="prompt for a group per active student locally")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="validate local files without contacting Canvas")
    action.add_argument("--dry-run", action="store_true", help="read Canvas and print plan counts (default)")
    action.add_argument("--apply", action="store_true", help="apply and verify the plan")
    parser.add_argument("--prune", action="store_true", help="remove memberships not present in the mapping")
    parser.add_argument("--expected-plan", help="reviewed dry-run digest required with --apply --prune")
    args = parser.parse_args(argv)
    if args.expected_plan is not None and not (args.prune and args.apply):
        parser.error("--expected-plan requires --prune --apply")
    if args.prune and args.apply and not args.expected_plan:
        parser.error("--prune --apply requires the reviewed --expected-plan digest")
    try:
        name = group_set_name(args.group_set)
        titles = read_syllabus(args.markdown)
        mapping = read_mapping(args.mapping) if args.mapping else None
        if args.check:
            if mapping is None:
                parser.error("--check requires --mapping")
            print(f"Local check passed: {len(mapping)} mapping rows, {len(titles)} group assignments.")
            return 0
        if not args.courseid or args.courseid < 1:
            parser.error("--courseid must be a positive integer for Canvas access")
        if args.interactive and not sys.stdin.isatty():
            parser.error("--interactive requires a local terminal")
        key = os.environ.get("URSINUS_CANVAS_API_KEY") or os.environ.get("CANVAS_API_KEY")
        if not key:
            parser.error("set URSINUS_CANVAS_API_KEY or CANVAS_API_KEY")
        from canvasapi import Canvas

        root = os.environ.get("URSINUS_CANVAS_ROOT", "https://ursinus.instructure.com/")
        course = Canvas(root, key).get_course(args.courseid)
        if course.id != args.courseid:
            raise ValueError("Canvas returned a different course")
        students = roster(course)
        if mapping is None:
            mapping = interactive_mapping(students)
        mapping = resolve_mapping(mapping, students)
        if args.prune and (not mapping or set(mapping) != students.keys()):
            raise ValueError("--prune requires a complete nonempty active-roster mapping")
        plan = plan_changes(course, name, mapping, titles, args.prune)
        describe(plan, mapping, titles, args.prune)
        if args.prune:
            print(f"Prune plan digest: {plan_digest(course, name, plan, mapping, titles, True)}")
        if args.apply and (mapping or titles):
            active_now = roster(course)
            if not mapping.keys() <= active_now.keys() or (args.prune and mapping.keys() != active_now.keys()):
                raise ValueError("active roster changed after planning; review a fresh dry run")
            apply_plan(course, name, plan, mapping, titles, args.prune, args.expected_plan)
            print("Canvas read-back verified.")
        elif args.apply:
            print("No group assignments or memberships were requested.")
        else:
            print("Dry run. No changes were written.")
        return 0
    except (ValueError, OSError, csv.Error, yaml.YAMLError, EOFError) as exc:
        # Local parser exceptions can quote source data. Report their type only.
        msg = str(exc) if type(exc) is ValueError else type(exc).__name__
        print(f"Group assignment planning or verification failed: {msg}", file=sys.stderr)
        return 1
    except Exception as exc:
        # SDK exceptions can contain request or response body text.
        print(f"Canvas request failed ({type(exc).__name__}). Check current state before retrying.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
