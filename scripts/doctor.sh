#!/usr/bin/env bash
# Checks local tool versions against versions.env. Exits non-zero if any tool is missing or off-version.
set -uo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source versions.env

failures=0

# version_ge A B -> true when A >= B
version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

# first x.y[.z] number in the given text
extract_version() { grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' <<<"$1" | head -n1; }

report() { # tool rule required found status
  printf '%-10s %-8s %-10s %-10s %s\n' "$1" "$2" "$3" "$4" "$5"
}

check() { # tool rule(exact|min) required version-command...
  local tool=$1 rule=$2 required=$3
  shift 3
  local raw found
  if ! command -v "$1" >/dev/null 2>&1; then
    report "$tool" "$rule" "$required" "missing" "FAIL"
    failures=$((failures + 1))
    return
  fi
  raw=$("$@" 2>/dev/null)
  found=$(extract_version "$raw")
  if [ -z "$found" ]; then
    report "$tool" "$rule" "$required" "unknown" "FAIL"
    failures=$((failures + 1))
  elif { [ "$rule" = exact ] && [ "$found" = "$required" ]; } ||
       { [ "$rule" = min ] && version_ge "$found" "$required"; }; then
    report "$tool" "$rule" "$required" "$found" "ok"
  else
    report "$tool" "$rule" "$required" "$found" "FAIL"
    failures=$((failures + 1))
  fi
}

report TOOL RULE REQUIRED FOUND STATUS
check terraform exact "$TERRAFORM_VERSION"  terraform version
check docker    min   "$DOCKER_MIN_VERSION" docker version --format '{{.Client.Version}}'
check make      min   "$MAKE_MIN_VERSION"   make --version
check uv        min   "$UV_MIN_VERSION"     uv --version
# `python`, not `python3`: on Windows python3 is the Microsoft Store alias.
check python    min   "$PYTHON_MIN_VERSION" python --version

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  report docker-daemon - running running ok
else
  report docker-daemon - running "not running" "FAIL"
  failures=$((failures + 1))
fi

if [ "$failures" -gt 0 ]; then
  echo "doctor: $failures check(s) failed" >&2
  exit 1
fi
echo "doctor: all tools ok"
