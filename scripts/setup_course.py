#!/usr/bin/env python3
"""One-time setup for a new course repository. Run once from a clone of your copy.

Needs the GitHub CLI (gh auth login) and, unless --skip-google is given, a credentials.json
for a Google OAuth desktop client. It:
  1. logs in to Google and lets you pick the courses
  2. generates a new encryption key for this course
  3. stores everything as GitHub secrets
  4. applies the repository settings the pipeline relies on

The encryption key is generated in memory and sent straight to GitHub. No file gets a copy.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.encryption import generate_master_key


def gh(*args, stdin=None) -> str:
    return subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, check=True
    ).stdout.strip()


def set_secret(repo: str, name: str, value: str) -> None:
    # Through stdin, so the value never appears in a process list.
    gh("secret", "set", name, "--repo", repo, stdin=value)
    print(f"  secret {name}: set")


def existing_secrets(repo: str) -> set:
    return {item["name"] for item in json.loads(gh("secret", "list", "--repo", repo, "--json", "name"))}


def choose_courses(client) -> list:
    courses = [c for c in client.list_courses() if c.get("courseState") == "ACTIVE"]
    if not courses:
        sys.exit("No active courses found for this Google account.")
    for index, course in enumerate(courses, 1):
        print(f"  {index}. {course.get('name')} {course.get('section', '')} (id {course['id']})")
    picked = input("Courses to grade (numbers separated by spaces): ").split()
    try:
        return [courses[int(item) - 1]["id"] for item in picked]
    except (ValueError, IndexError):
        sys.exit("Invalid selection.")


def setup_google(repo: str, credentials: Path, course_ids: list) -> None:
    from src.classroom_client import ClassroomClient

    token = Path("token.json")
    print("Logging in to Google (a browser window will open)...")
    client = ClassroomClient(credentials_path=str(credentials), token_path=str(token))
    course_ids = course_ids or choose_courses(client)
    if not course_ids:
        sys.exit("No courses selected.")
    set_secret(repo, "GOOGLE_TOKEN", token.read_text())
    set_secret(repo, "COURSE_IDS", ",".join(course_ids))
    token.unlink()
    print("  token.json removed: it now lives only in the GOOGLE_TOKEN secret")


def apply_repo_settings(repo: str) -> None:
    # GITHUB_TOKEN stays read-only unless a job asks for more, but may open pull requests.
    gh(
        "api", "-X", "PUT", f"repos/{repo}/actions/permissions/workflow",
        "-f", "default_workflow_permissions=read",
        "-F", "can_approve_pull_request_reviews=true",
    )
    print("  Actions: read-only token by default, pull request creation allowed")
    # A public repository accepts pull requests from anybody. Their workflows run without
    # secrets, but should not run at all until somebody looked at them.
    gh(
        "api", "-X", "PUT", f"repos/{repo}/actions/permissions/fork-pr-contributor-approval",
        "-f", "approval_policy=all_external_contributors",
    )
    print("  Actions: fork pull requests need approval before running")
    gh("variable", "set", "GRADER_ENABLED", "--repo", repo, "--body", "true")
    print("  variable GRADER_ENABLED: true (scheduled workflows are now on)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--credentials", default="credentials.json")
    parser.add_argument("--course-ids", default="", help="Comma-separated; skips the interactive choice")
    parser.add_argument("--rotate-key", action="store_true", help="Replace an existing encryption key")
    parser.add_argument("--skip-google", action="store_true", help="Only key and repository settings")
    args = parser.parse_args()

    repo = gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    print(f"Repository: {repo}")

    if not args.skip_google:
        credentials = Path(args.credentials)
        if not credentials.is_file():
            sys.exit(f"{credentials} not found. See README.md for how to create it.")
        setup_google(repo, credentials, [c.strip() for c in args.course_ids.split(",") if c.strip()])

    if "ENCRYPTION_KEY" in existing_secrets(repo) and not args.rotate_key:
        print("  secret ENCRYPTION_KEY: already set, kept (use --rotate-key to replace it)")
    else:
        set_secret(repo, "ENCRYPTION_KEY", generate_master_key())

    apply_repo_settings(repo)
    print("\nDone. Next: run the 'Selftest: pipeline' workflow in the Actions tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
