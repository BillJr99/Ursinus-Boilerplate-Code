"""Offline coverage of Canvas group-assignment planning and verification."""

from types import SimpleNamespace

import pytest

import ursinus_group_assignments as cli


class Group:
    def __init__(self, name, id, writes):
        self.name, self.id, self.writes = name, id, writes
        self.members = {}
        self.persist = True

    def get_memberships(self):
        return list(self.members.values())

    def create_membership(self, user_id):
        self.writes.append(("add", self.id, user_id))
        if self.persist:
            self.members[user_id] = SimpleNamespace(
                id=self.id * 100 + user_id, user_id=user_id, group_id=self.id, workflow_state="accepted",
                remove_self=lambda: self.delete(user_id),
            )

    def delete(self, user_id):
        self.writes.append(("remove", self.id, user_id))
        del self.members[user_id]


class Category:
    name, id = "Project Groups", 80

    def __init__(self, writes):
        self.groups, self.writes = [], writes

    def get_groups(self):
        return iter(self.groups)

    def create_group(self, *, name):
        group = Group(name, len(self.groups) + 100, self.writes)
        self.groups.append(group)
        self.writes.append(("group", name))
        return group


class Assignment:
    name, id = "Invented project", 3
    has_submitted_submissions = False
    grade_group_students_individually = True

    def __init__(self, writes):
        self.writes, self.group_category_id = writes, None

    def edit(self, *, assignment):
        self.writes.append(("attachment", assignment))
        self.group_category_id = assignment["group_category_id"]


class Course:
    id = 62

    def __init__(self):
        self.writes, self.categories = [], []
        self.assignment = Assignment(self.writes)

    def get_group_categories(self):
        return iter(self.categories)

    def create_group_category(self, name):
        assert name == Category.name
        self.writes.append(("category", name))
        group = Category(self.writes)
        self.categories.append(group)
        return group

    def get_assignments(self):
        return iter([self.assignment])

    def get_assignment(self, id):
        assert id == self.assignment.id
        return self.assignment


def test_check_is_offline_for_valid_csv_and_yaml(tmp_path, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "canvasapi", None)
    syllabus = tmp_path / "syllabus.md"
    syllabus.write_text("---\nschedule:\n- deliverables:\n  - {dtitle: Invented project, group: true}\n---\n")
    for filename, data in (("input.csv", "student,group\n1,One\n"),
                           ("input.yml", "- {student: 1, group: One}\n")):
        path = tmp_path / filename
        path.write_text(data)
        assert cli.main(["-m", str(syllabus), "--mapping", str(path), "--check"]) == 0


def test_dry_plan_apply_readback_and_second_run():
    course = Course()
    mapping, titles = {1: "One"}, {course.assignment.name}
    plan = cli.plan_changes(course, Category.name, mapping, titles)
    assert course.writes == []
    cli.apply_plan(course, Category.name, plan, mapping, titles, False)
    assert course.writes == [
        ("category", Category.name), ("group", "One"), ("add", 100, 1),
        ("attachment", {"group_category_id": 80}),
    ]
    assert course.assignment.grade_group_students_individually is True
    course.writes.clear()
    plan = cli.plan_changes(course, Category.name, mapping, titles)
    cli.apply_plan(course, Category.name, plan, mapping, titles, False)
    assert course.writes == []


def test_conflicting_membership_refuses_without_prune_and_moves_explicitly():
    course = Course()
    category = course.create_group_category(Category.name)
    group = category.create_group(name="One")
    group.create_membership(1)
    course.writes.clear()
    with pytest.raises(ValueError, match="already belongs"):
        cli.plan_changes(course, Category.name, {1: "Two"}, set())
    assert course.writes == []
    plan = cli.plan_changes(course, Category.name, {1: "Two"}, set(), True)
    cli.apply_plan(course, Category.name, plan, {1: "Two"}, set(), True,
                   cli.plan_digest(course, Category.name, plan, {1: "Two"}, set(), True))
    assert course.writes == [("group", "Two"), ("remove", 100, 1), ("add", 101, 1)]


def test_readback_refuses_success_without_membership_persistence():
    course = Course()
    category = course.create_group_category(Category.name)
    group = category.create_group(name="One")
    group.persist = False
    plan = cli.plan_changes(course, Category.name, {1: "One"}, {course.assignment.name})
    with pytest.raises(ValueError, match="did not verify the membership"):
        cli.apply_plan(course, Category.name, plan, {1: "One"}, {course.assignment.name}, False)
    assert course.assignment.group_category_id is None


def test_preflight_submitted_assignment_blocks_any_group_write():
    course = Course()
    course.assignment.has_submitted_submissions = True
    with pytest.raises(ValueError, match="has submissions"):
        cli.plan_changes(course, Category.name, {1: "One"}, {course.assignment.name})
    assert course.writes == []


def test_unconfirmed_membership_blocks_mutation():
    course = Course()
    category = course.create_group_category(Category.name)
    group = category.create_group(name="One")
    group.create_membership(1)
    group.members[1].workflow_state = "invited"
    course.writes.clear()
    with pytest.raises(ValueError, match="unconfirmed"):
        cli.plan_changes(course, Category.name, {1: "One"}, set())
    assert course.writes == []


def test_identifier_collisions_and_duplicate_alias_are_refused():
    with pytest.raises(ValueError, match="does not identify one"):
        cli.resolve_mapping({"1": "One"}, {1: {}, 2: {"login_id": "1"}})
    with pytest.raises(ValueError, match="repeats an active"):
        cli.resolve_mapping({"1": "One", "neutral": "One"}, {1: {"login_id": "neutral"}})


def test_stale_plan_changes_nothing():
    course = Course()
    plan = cli.plan_changes(course, Category.name, {1: "One"}, set())
    course.create_group_category(Category.name)
    course.writes.clear()
    with pytest.raises(ValueError, match="state changed"):
        cli.apply_plan(course, Category.name, plan, {1: "One"}, set(), False)
    assert course.writes == []


def test_dry_run_uses_all_active_enrollments_without_writing(tmp_path, monkeypatch, capsys):
    import sys

    course = Course()

    def enrollments(**filters):
        assert filters == {"type": ["StudentEnrollment"], "state": ["active"]}
        yield SimpleNamespace(user_id=1, user={}, type="StudentEnrollment", enrollment_state="active")
        yield SimpleNamespace(user_id=1, user={}, type="StudentEnrollment", enrollment_state="active")
        yield SimpleNamespace(user_id=2, user={}, type="StudentEnrollment", enrollment_state="active")
        yield SimpleNamespace(user_id=3, user={}, type="StudentEnrollment", enrollment_state="inactive")

    course.get_enrollments = enrollments
    monkeypatch.setitem(sys.modules, "canvasapi", SimpleNamespace(
        Canvas=lambda *_: SimpleNamespace(get_course=lambda _: course),
    ))
    monkeypatch.setenv("URSINUS_CANVAS_API_KEY", "synthetic")
    syllabus = tmp_path / "syllabus.md"
    syllabus.write_text("---\nschedule:\n- deliverables:\n  - {dtitle: Invented project, group: true}\n---\n")
    mapping = tmp_path / "rows.csv"
    mapping.write_text("student,group\n1,One\n2,Two\n")
    args = ["-c", str(course.id), "-m", str(syllabus), "--mapping", str(mapping), "--dry-run", "--prune"]
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "Memberships to add: 2" in output
    digest = next(line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("Prune plan digest: "))
    assert len(digest) == 64
    assert course.writes == []

    apply_args = [arg for arg in args if arg != "--dry-run"] + ["--apply"]
    with pytest.raises(SystemExit) as error:
        cli.main(apply_args)
    assert error.value.code == 2
    assert cli.main(apply_args + ["--expected-plan", "stale"]) == 1
    assert course.writes == []
    assert cli.main(apply_args + ["--expected-plan", digest]) == 0
    course.writes.clear()

    mapping.write_text("student,group\n1,One\n")
    assert cli.main(args) == 1
    assert "complete nonempty active-roster mapping" in capsys.readouterr().err
    assert course.writes == []


def test_prune_requires_exact_reviewed_fresh_plan():
    course = Course()
    category = course.create_group_category(Category.name)
    group = category.create_group(name="One")
    group.create_membership(1)
    course.writes.clear()
    mapping = {1: "Two"}
    plan = cli.plan_changes(course, Category.name, mapping, set(), True)
    digest = cli.plan_digest(course, Category.name, plan, mapping, set(), True)
    with pytest.raises(ValueError, match="reviewed prune plan"):
        cli.apply_plan(course, Category.name, plan, mapping, set(), True)
    assert course.writes == []

    group.members[1].id += 1
    fresh = cli.plan_changes(course, Category.name, mapping, set(), True)
    with pytest.raises(ValueError, match="reviewed prune plan"):
        cli.apply_plan(course, Category.name, fresh, mapping, set(), True, digest)
    assert course.writes == []


def test_failed_move_never_removes_the_next_membership():
    course = Course()
    category = course.create_group_category(Category.name)
    first = category.create_group(name="One")
    second = category.create_group(name="Two")
    first.create_membership(1)
    first.create_membership(2)
    second.persist = False
    course.writes.clear()
    mapping = {1: "Two", 2: "Two"}
    plan = cli.plan_changes(course, Category.name, mapping, set(), True)
    digest = cli.plan_digest(course, Category.name, plan, mapping, set(), True)
    with pytest.raises(ValueError, match="did not verify the membership addition"):
        cli.apply_plan(course, Category.name, plan, mapping, set(), True, digest)
    assert course.writes == [("remove", first.id, 1), ("add", second.id, 1)]
    assert 2 in first.members
