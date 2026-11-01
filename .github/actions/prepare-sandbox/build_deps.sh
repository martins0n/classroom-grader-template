#!/usr/bin/env bash
# Build the sandbox virtualenv inside the sandbox image, as an unprivileged user.
# --system-site-packages keeps the user site enabled, so a notebook's "!pip install x"
# still works: pip falls back to a user install because /venv is read-only at run time.
set -euo pipefail

deps="$RUNNER_TEMP/sandbox-deps"
requirements="$RUNNER_TEMP/sandbox-requirements"
mkdir -p "$requirements"
cp sandbox/requirements.txt "$requirements/base.txt"
: > "$requirements/assignment.txt"
if [ -f "test_cases/$ASSIGNMENT/requirements.txt" ]; then
  cp "test_cases/$ASSIGNMENT/requirements.txt" "$requirements/assignment.txt"
fi

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/build-home \
  --mount "type=bind,src=$deps,dst=/venv" \
  --mount "type=bind,src=$requirements,dst=/requirements,readonly" \
  "$IMAGE" bash -euc '
    mkdir -p "$HOME"
    pip="/venv/bin/pip install --quiet --no-input --disable-pip-version-check"
    python -m venv --system-site-packages /venv
    $pip -r /requirements/base.txt
    if grep -qvE "^[[:space:]]*(#|$)" /requirements/assignment.txt; then
      $pip -r /requirements/assignment.txt
    fi
  '
