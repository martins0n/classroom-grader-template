#!/usr/bin/env python3
"""Aggregate downloaded grading reports into one CSV per assignment."""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.naming import (
    SELFTEST_STUDENT,
    email_from_student_id,
    is_valid_assignment,
    is_valid_student_id,
)


def extract_grade(report: dict):
    """Return (grade, max_points), or None when the report holds no grade."""
    if "note" in report:
        return None
    if "error" in report:
        return 0, 100
    if "test_case_results" in report:
        return report.get("earned_points", 0), report.get("total_points", 100)
    return report.get("score", 0), 100


def aggregate(artifacts_dir: Path, output_dir: Path, assignment_filter: str = None) -> int:
    grades = defaultdict(list)
    for report_file in sorted(artifacts_dir.glob("*/grade_report.json")):
        try:
            report = json.loads(report_file.read_text())
        except ValueError:
            print(f"Skipping unreadable report: {report_file.parent.name}")
            continue
        student_id, assignment = report.get("student_id"), report.get("assignment_id")
        if not is_valid_student_id(student_id) or not is_valid_assignment(assignment):
            print(f"Skipping report with invalid ids: {report_file.parent.name}")
            continue
        if student_id == SELFTEST_STUDENT or (assignment_filter and assignment != assignment_filter):
            continue
        grade = extract_grade(report)
        if grade is not None:
            grades[assignment].append((email_from_student_id(student_id), *grade))

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for assignment, rows in grades.items():
        with open(output_dir / f"grades_{assignment}.csv", "w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Student Email", "Grade", "Max Points", "Timestamp", "Assignment"])
            for email, grade, max_points in sorted(rows):
                writer.writerow([email, grade, max_points, timestamp, assignment])
        print(f"grades_{assignment}.csv: {len(rows)} student(s)")
    return len(grades)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--assignment-id")
    args = parser.parse_args()
    count = aggregate(Path(args.artifacts_dir), Path(args.output_dir), args.assignment_id)
    print(f"Assignments aggregated: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
