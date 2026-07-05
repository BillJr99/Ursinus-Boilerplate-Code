#!/usr/bin/env bash
#
# configure-course-repo.sh
#
# Configure a GitHub repository for use in the Ursinus courses.
#
# All settings are applied through the GitHub REST API using the `gh` CLI,
# which supplies YOUR OWN credentials at run time. No tokens or secrets are
# stored in this script -- you must already be authenticated with `gh auth
# login` (or have GH_TOKEN set) with admin rights on the target repository.
#
# What it configures:
#   1. Enables GitHub Actions and allows all actions and reusable workflows.
#   2. Gives workflows read & write permissions, and allows GitHub Actions
#      to create and approve pull requests.
#   3. Requires approval to run fork pull-request workflows for ALL external
#      contributors.
#   4. "Unprotects" the Pages branch (default: gh-pages) by allowing it to
#      deploy to the `github-pages` environment.
#
# Usage:
#   ./configure-course-repo.sh <owner>/<repo> [pages-branch]
#   ./configure-course-repo.sh Ursinus-CS374-Fall2026        # owner defaults to the authenticated user
#   ./configure-course-repo.sh BillJr99/Ursinus-CIE100-Fall2026 gh-pages
#
# Requirements: gh (https://cli.github.com), authenticated with admin scope.

set -euo pipefail

REPO_ARG="${1:-}"
PAGES_BRANCH="${2:-gh-pages}"

if [[ -z "$REPO_ARG" ]]; then
  echo "Usage: $0 <owner>/<repo> [pages-branch]" >&2
  exit 1
fi

command -v gh >/dev/null 2>&1 || { echo "error: gh CLI is required (https://cli.github.com)" >&2; exit 1; }

# Accept either "owner/repo" or just "repo" (owner defaults to the authenticated user).
if [[ "$REPO_ARG" == */* ]]; then
  REPO="$REPO_ARG"
else
  OWNER="$(gh api user --jq .login)"
  REPO="$OWNER/$REPO_ARG"
fi

echo "Configuring $REPO (pages branch: $PAGES_BRANCH) ..."

# 1) Enable Actions; allow all actions and reusable workflows.
echo "  [1/4] Enabling Actions (allow all actions & reusable workflows)"
gh api -X PUT "repos/$REPO/actions/permissions" \
  -F enabled=true \
  -f allowed_actions=all >/dev/null

# 2) Workflow permissions: read/write, and allow creating & approving PRs.
echo "  [2/4] Workflow permissions: read/write + allow GitHub Actions to create/approve PRs"
gh api -X PUT "repos/$REPO/actions/permissions/workflow" \
  -f default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=true >/dev/null

# 3) Require approval for fork PR workflows from ALL external contributors.
echo "  [3/4] Requiring approval for all external contributors' fork PR workflows"
gh api -X PUT "repos/$REPO/actions/permissions/fork-pr-contributor-approval" \
  -f approval_policy=all_external_contributors >/dev/null

# 4) Allow the Pages branch to deploy to the github-pages environment.
echo "  [4/4] Allowing '$PAGES_BRANCH' to deploy to the github-pages environment"
# Ensure the environment exists and uses custom branch policies.
gh api -X PUT "repos/$REPO/environments/github-pages" --input - >/dev/null <<'JSON'
{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
JSON
# Add the branch policy only if it is not already present (idempotent).
if gh api "repos/$REPO/environments/github-pages/deployment-branch-policies" \
     --jq '.branch_policies[].name' 2>/dev/null | grep -qx "$PAGES_BRANCH"; then
  echo "         ('$PAGES_BRANCH' deploy policy already present)"
else
  gh api -X POST "repos/$REPO/environments/github-pages/deployment-branch-policies" \
    -f name="$PAGES_BRANCH" -f type=branch >/dev/null
fi

echo "Done: $REPO configured for course use."
