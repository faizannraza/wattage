#!/usr/bin/env bash
# Entrypoint for action.yml. Runs `wattage ci`, posts the PR comment when
# running on a pull_request event, and always surfaces the real exit code
# (0-4, per doc §11.3) as both the action's own exit status and the
# `exit-code` output — never swallowed, never guessed at.
set -uo pipefail

ARGS=("$INPUT_SOURCE")
[ -n "${INPUT_BASELINE:-}" ] && ARGS+=(--baseline "$INPUT_BASELINE")
[ -n "${INPUT_PRICING:-}" ] && ARGS+=(--pricing "$INPUT_PRICING")
[ -n "${INPUT_QUALITY:-}" ] && ARGS+=(--quality "$INPUT_QUALITY")
[ -n "${INPUT_FAIL_ON:-}" ] && ARGS+=(--fail-on "$INPUT_FAIL_ON")

PR_COMMENT_FILE="$(mktemp)"
ARGS+=(--pr-comment-out "$PR_COMMENT_FILE")

SARIF_OUT="${INPUT_SARIF_OUT:-wattage.sarif}"
ARGS+=(--sarif-out "$SARIF_OUT")

[ -n "${INPUT_JUNIT_OUT:-}" ] && ARGS+=(--junit-out "$INPUT_JUNIT_OUT")
[ -n "${INPUT_BADGE_OUT:-}" ] && ARGS+=(--badge-out "$INPUT_BADGE_OUT")

wattage ci "${ARGS[@]}"
EXIT_CODE=$?

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "exit-code=$EXIT_CODE" >> "$GITHUB_OUTPUT"
fi

should_comment="${INPUT_PR_COMMENT:-true}"
is_pull_request="${GITHUB_EVENT_NAME:-}"
if [ "$should_comment" = "true" ] && [ "$is_pull_request" = "pull_request" ] && [ -s "$PR_COMMENT_FILE" ]; then
  pr_number=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['pull_request']['number'])" "$GITHUB_EVENT_PATH")
  gh pr comment "$pr_number" --body-file "$PR_COMMENT_FILE" --repo "$GITHUB_REPOSITORY"
fi

exit "$EXIT_CODE"
