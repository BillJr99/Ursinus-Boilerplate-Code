#!/usr/bin/env bash
# Run in a parent course checkout after merging its child. Stage the child's
# side of generated viz conflicts and leave all other conflicts for review.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
cd "$root"
merge_head=$(git rev-parse --git-path MERGE_HEAD)
if [[ ! -f "$merge_head" ]] || [[ $(wc -l < "$merge_head") -ne 1 ]]; then
    echo 'Expected a merge with one incoming child commit.' >&2
    exit 1
fi
read -r child < "$merge_head"
conflict=0

while IFS= read -r -d '' path; do
    case "$path" in
        viz/index.json|viz/catalog.json|viz/volatile.json|viz/expected/*|viz/traces/*|viz/qr/*|\
        viz/tours/*|viz/sessions/*|viz/terminals/*|viz/tracers/*|\
        viz/index.html|viz/viewer.css|viz/viewer.js|viz/langs.css|viz/langs.js|viz/figures.js|\
        viz/modes.css|viz/modes.js|viz/mode-explain.js|viz/mode-simulate.js|viz/mode-terminal.js|viz/terminal.css)
            if git cat-file -e "$child:$path" 2>/dev/null; then
                git --literal-pathspecs restore --source="$child" --staged --worktree -- "$path"
            else
                git --literal-pathspecs rm -f -- "$path"
            fi
            printf 'Staged child version of %s\n' "$path"
            ;;
        *)
            printf 'Manual resolution required for %s\n' "$path" >&2
            conflict=1
            ;;
    esac
done < <(git diff --name-only --diff-filter=U -z)

exit "$conflict"
