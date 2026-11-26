# Ursinus-Boilerplate-Code

Pull into individual website repository with:  
git submodule add <this url> code  

Update with:  
git submodule update --init --recursive  
git submodule update --remote --merge            
(automate with a workflow; use https link in .gitmodules file)
## Canvas group assignments

In the syllabus front matter, put `group: true` on the assignment's
deliverable, alongside `dtitle`, `dlink`, and `submission_types`.

```yaml
deliverables:
  - dtitle: "Project: Demo Due"
    dlink: projects/demo
    submission_types: presentation
    group: true
```

Omit the field or use `group: false` to leave the assignment's behavior
alone. This field belongs on the assignment deliverable, separate from
any quiz or handout row. Use a YAML boolean. A full deployment or an inline
`--apply` can attach the assignment to a Canvas group set before it has
members. The default set is **Project Groups**. Pass `--group-set NAME` or
set `CANVAS_GROUP_SET` to use a different set consistently across the tools.
A full deployment with `--noassignments` leaves assignments and group sets alone.

Run the inline script with `--generate` to see create and update operations
for group assignments. It names the intended set in the change document so
a later apply uses that same name. Inline `group: true` requests group
submissions, and a string such as `group: "Projects"` still selects a
gradebook assignment group. Use `group: true` with
`assignment_group: "Projects"` to set both on one inline operation.
With an existing assignment, the tools refuse
to change its group set if it has submissions or Canvas does not confirm
its submission state. If it belongs to a different set, resolve that
assignment in Canvas before applying the generated change.

Use `course/ursinus_group_assignments.py --help` to plan roster
assignments interactively or from a CSV or YAML file with `student` and
`group` fields. Use `--check` for offline validation, `--dry-run` to preview
changes, and `--apply` to write and verify them. Memberships are retained
by default. To remove memberships, supply a complete active roster mapping,
review the `--dry-run --prune` plan, and pass its digest to
`--apply --prune --expected-plan DIGEST`. Existing group objects are retained.
Run authorized Canvas operations through the institutional Canvas route.
