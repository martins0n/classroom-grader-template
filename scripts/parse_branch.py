#!/usr/bin/env python3
"""Validate a student branch name and print GITHUB_OUTPUT lines for it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.naming import parse_branch


def main() -> int:
    try:
        student_id, assignment = parse_branch(sys.argv[1] if len(sys.argv) > 1 else "")
    except ValueError:
        print("Refusing to grade: not a student-<id>/assignment-<name> branch", file=sys.stderr)
        return 1
    print(f"student_id={student_id}")
    print(f"assignment_id={assignment}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
