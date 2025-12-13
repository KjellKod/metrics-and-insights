#!/usr/bin/env bash
# Pre-push validation script
# Run this before pushing to ensure CI will pass

set -euo pipefail  # Exit on first error (and undefined vars)

# Ensure we run from the repo root, so paths are stable.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

echo "🚀 Pre-Push Validation Script"
echo "=============================="
echo ""

PY_FILES=()
while IFS= read -r file; do
  PY_FILES+=("$file")
done < <(git ls-files '*.py')

if [ "${#PY_FILES[@]}" -eq 0 ]; then
  echo "ℹ️  No tracked Python files found; skipping format/lint."
  echo ""
else
  # 1. Format code with black
  echo "1️⃣  Formatting code with black..."
  python3 -m black "${PY_FILES[@]}" || { echo "❌ Black formatting failed"; exit 1; }
  echo "✅ Black formatting complete"
  echo ""

  # 2. Sort imports with isort
  echo "2️⃣  Sorting imports with isort..."
  python3 -m isort "${PY_FILES[@]}" || { echo "❌ isort failed"; exit 1; }
  echo "✅ Import sorting complete"
  echo ""

  # 3. Check linting with flake8 (only our tracked code, not virtualenvs)
  echo "3️⃣  Checking code quality with flake8..."
  python3 -m flake8 "${PY_FILES[@]}" --count --select=E9,F63,F7,F82 --show-source --statistics \
    || { echo "❌ Flake8 found critical errors"; exit 1; }
  echo "✅ Flake8 check passed"
  echo ""
fi

# 4. Run all tests
echo "4️⃣  Running test suite..."
TEST_TARGETS=()
for test_dir in git_metrics/tests jira_metrics/tests; do
  if [ -d "$test_dir" ]; then
    TEST_TARGETS+=("$test_dir")
  fi
done

if [ "${#TEST_TARGETS[@]}" -eq 0 ]; then
  echo "ℹ️  No test directories found; skipping pytest."
else
  python3 -m pytest "${TEST_TARGETS[@]}" -v --tb=short || { echo "❌ Tests failed"; exit 1; }
fi
echo "✅ All tests passed"
echo ""

# Summary
echo "=============================="
echo "🎉 All checks passed!"
echo "✅ Code formatted (black)"
echo "✅ Imports sorted (isort)"
echo "✅ Linting passed (flake8)"
echo "✅ Tests passed (pytest)"
echo ""
echo "👍 Ready to push to GitHub!"
echo "=============================="
