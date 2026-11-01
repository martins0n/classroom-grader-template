#!/usr/bin/env python3
"""Run a decrypted notebook in the sandbox, then score its outputs here on the host.

Exit status: 0 whenever a verdict was reached, including a notebook that crashes (that is
the student's score, not a pipeline failure). Non-zero only when the pipeline itself failed.

Logs are public, so only numbers and teacher-written test names are printed. Nothing that
came out of the notebook goes to stdout, which also rules out workflow-command injection.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.grader import NotebookGrader
from src.naming import is_valid_assignment, is_valid_student_id
from src.sandbox import SandboxError, run_notebook


def grade(student_id: str, assignment_id: str, submission_dir: Path, test_cases_root: Path) -> dict:
    base = {"student_id": student_id, "assignment_id": assignment_id}
    notebooks = sorted(submission_dir.glob("*.ipynb")) if submission_dir.is_dir() else []
    if not notebooks:
        return {**base, "error": "No Jupyter notebooks found in submission", "score": 0.0, "passed": False}

    execution = run_notebook(notebooks[0])
    if not execution.ok:
        return {
            **base,
            "error": "Notebook failed to execute",
            "error_type": execution.error_type,
            "cell_index": execution.cell_index,
            "score": 0.0,
            "passed": False,
        }

    expected_path = test_cases_root / assignment_id / "expected_output.json"
    if not expected_path.exists():
        return {**base, "note": "No expected outputs configured for this assignment", "outputs_found": len(execution.outputs)}

    expected = json.loads(expected_path.read_text())
    return {**base, **NotebookGrader().grade(execution.outputs, expected)}


def print_summary(report: dict) -> None:
    if "error" in report:
        print(f"Result: {report['error']}")
        if report.get("error_type"):
            print(f"Cell: {report.get('cell_index')}, type: {report['error_type']}")
    elif "note" in report:
        print(f"Result: {report['note']}")
    else:
        print(f"Score: {float(report['score']):.2f}%")
        for case in report.get("test_case_results", []):
            print(f"  {'PASS' if case['passed'] else 'FAIL'} {case['name']}: {case['earned']}/{case['points']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--assignment-id", required=True)
    parser.add_argument("--submission-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--test-cases-root", default="test_cases")
    args = parser.parse_args()

    if not is_valid_student_id(args.student_id) or not is_valid_assignment(args.assignment_id):
        print("Invalid student or assignment id", file=sys.stderr)
        return 1
    try:
        report = grade(
            args.student_id, args.assignment_id, Path(args.submission_dir), Path(args.test_cases_root)
        )
    except SandboxError as exc:
        print(f"Pipeline failure: {exc}", file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
