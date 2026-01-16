#!/usr/bin/env python3
"""PR readiness checks (aligns with CI)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def ensure_project_root() -> None:
    if not Path("requirements.txt").is_file():
        print("❌ Error: Run this script from the project root directory")
        sys.exit(1)


def apply_ci_env_defaults() -> None:
    # Match CI env expectations with safe placeholders
    os.environ.setdefault("USER_EMAIL", "your_email@example.com")
    os.environ.setdefault("JIRA_API_KEY", "your_jira_api_key")
    os.environ.setdefault("JIRA_LINK", "https://your_jira_instance.atlassian.net")
    os.environ.setdefault("GITHUB_TOKEN_READONLY_WEB", "your_github_token")
    os.environ.setdefault("GITHUB_METRIC_OWNER_OR_ORGANIZATION", "your_github_repo_owner")
    os.environ.setdefault("GITHUB_METRIC_REPO", "your_github_repo_name")
    os.environ.setdefault("JIRA_PROJECTS", "MYPROJECT, ENG, ETC")
    os.environ.setdefault("TEAM_SWE", "Swedes")
    os.environ.setdefault("CUSTOM_FIELD_TEAM", "10075")
    os.environ.setdefault("CUSTOM_FIELD_WORK_TYPE", "10079")
    # Ensure requests can find certs in restricted environments
    try:
        import certifi

        cert_path = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", cert_path)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", cert_path)
    except Exception:
        pass


def run_pytest() -> None:
    print("Running unit tests (pytest + coverage)...")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov",
            "--junitxml=junit.xml",
            "-o",
            "junit_family=legacy",
            "--cov-branch",
            "--cov-fail-under=47",
        ],
        check=True,
    )
    print("✅ Tests passed\n")


def run_pylint() -> None:
    print("Running pylint (score must be >= 9.50)...")
    result = subprocess.run(
        ["pylint", *subprocess.check_output(["git", "ls-files", "*.py"]).decode().split()],
        text=True,
        capture_output=True,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if output:
        print(output.rstrip())
    match = re.search(r"Your code has been rated at ([0-9.]+)", output)
    score = float(match.group(1)) if match else 0.0
    print(f"Pylint score: {score:.2f}")
    if score >= 9.50:
        print("✅ Pylint score is 9.50 or higher.\n")
        return
    print("❌ Pylint score is below 9.50.")
    sys.exit(1)


def main() -> None:
    print("PR Readiness Checks")
    print("===================")
    print("")

    ensure_project_root()
    apply_ci_env_defaults()
    run_pylint()
    run_pytest()

    print("===================")
    print("🎉 All checks passed!")
    print("===================")


if __name__ == "__main__":
    main()
