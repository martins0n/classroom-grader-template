#!/usr/bin/env python3
"""Build a CSV of marks from the grading comments on student pull requests.

The repository is public, so anybody with a GitHub account can comment on its pull requests
and anybody can open one from a fork. A mark only counts when all of these hold:
  - the pull request comes from a student-* branch of this repository, not a fork
  - the comment was written by the github-actions bot
  - the comment starts with the grade marker, and the marker names that same student and assignment
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, Tuple

from github import Auth, Github

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.render_comment import parse_marker
from src.naming import SELFTEST_STUDENT, email_from_student_id, parse_branch

BOT_LOGIN = "github-actions[bot]"


def mark_from_comments(comments, student_id: str, assignment: str) -> Optional[float]:
    """Return the newest trusted score among comments listed oldest first."""
    for comment in reversed(list(comments)):
        if comment.user is None or comment.user.login != BOT_LOGIN:
            continue
        marker = parse_marker(comment.body)
        if marker and marker["student"] == student_id and marker["assignment"] == assignment:
            return marker["score"]
    return None


def identify_pull_request(pull, repo_name: str) -> Optional[Tuple[str, str]]:
    """Return (student_id, assignment) for a genuine submission PR, else None."""
    head_repo = pull.head.repo
    if head_repo is None or head_repo.full_name != repo_name:
        return None
    try:
        return parse_branch(pull.head.ref)
    except ValueError:
        return None


def collect_marks(repo, repo_name: str) -> Dict[str, Dict[str, float]]:
    marks = defaultdict(dict)
    for pull in repo.get_pulls(state="all"):
        identity = identify_pull_request(pull, repo_name)
        if identity is None or identity[0] == SELFTEST_STUDENT:
            continue
        score = mark_from_comments(pull.get_issue_comments(), *identity)
        if score is not None:
            marks[email_from_student_id(identity[0])][identity[1]] = score
    return marks


def student_names(course_id: str) -> Dict[str, str]:
    from src.classroom_client import ClassroomClient

    names = {}
    for student in ClassroomClient().list_students(course_id):
        profile = student.get("profile", {})
        email = (profile.get("emailAddress") or "").lower()
        if email:
            names[email] = profile.get("name", {}).get("fullName", "")
    return names


def write_csv(marks: Dict[str, Dict[str, float]], names: Dict[str, str], output: Path) -> None:
    homeworks = sorted({homework for row in marks.values() for homework in row})
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow((["Student Name"] if names else []) + ["Student Email"] + homeworks)
        for student in sorted(marks):
            identity = ([names.get(student.lower(), "")] if names else []) + [student]
            scores = [marks[student].get(h) for h in homeworks]
            writer.writerow(identity + ["" if s is None else f"{s:.1f}" for s in scores])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", default="reports/marks.csv")
    parser.add_argument("--course-id", help="Also fetch student names from this course")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1
    marks = collect_marks(Github(auth=Auth.Token(token)).get_repo(args.repo), args.repo)
    names = {}
    if args.course_id:
        try:
            names = student_names(args.course_id)
        except Exception as exc:
            print(f"Continuing without student names: {exc}")
    write_csv(marks, names, Path(args.output))
    print(f"Students: {len(marks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
