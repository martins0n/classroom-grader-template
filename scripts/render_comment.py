#!/usr/bin/env python3
"""Turn a grading report into the PR comment.

The first line is a machine-readable marker, and it is the only thing the marks CSV trusts.
Text derived from notebook output is untrusted, so it is flattened into an inline code span
and can neither form a marker, mention anybody nor inject markup.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.naming import parse_branch

MARKER_PREFIX = "<!-- grade-result: "
MARKER_SUFFIX = " -->"
MARKER_RE = re.compile(r"\A<!-- grade-result: (\{[^\n]*\}) -->(?:\n|\Z)")
MAX_TEXT_LENGTH = 200


def untrusted(text) -> str:
    cleaned = re.sub(r"[`<>@\\|\r\n\t\x00-\x1f]+", " ", str(text)).strip()
    if len(cleaned) > MAX_TEXT_LENGTH:
        cleaned = cleaned[:MAX_TEXT_LENGTH] + "..."
    return f"`{cleaned}`" if cleaned else "`-`"


def number(value) -> float:
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("not a finite number")
    return result


def make_marker(student_id: str, assignment: str, score: float, earned=None, total=None) -> str:
    payload = {"student": student_id, "assignment": assignment, "score": round(number(score), 4)}
    if earned is not None and total is not None:
        payload.update(earned=number(earned), total=number(total))
    return MARKER_PREFIX + json.dumps(payload, sort_keys=True) + MARKER_SUFFIX


def parse_marker(body: str) -> Optional[dict]:
    match = MARKER_RE.match(body or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        data["score"] = number(data["score"])
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(data.get("student"), str) or not isinstance(data.get("assignment"), str):
        return None
    return data


def render(branch: str, report: Optional[dict], run_url: str = "") -> str:
    student_id, assignment = parse_branch(branch)
    header = f"## 🤖 Grading Results\n\n**Student:** {student_id}\n**Assignment:** {assignment}\n\n"
    details = f"\n\n[Workflow run]({run_url})\n" if run_url else "\n"

    if report is None:
        return header + "⚠️ Grading did not finish because of a pipeline problem. No score was recorded." + details

    if "error" in report:
        body = f"### ❌ {untrusted(report['error'])[1:-1]}\n\n"
        if report.get("error_type"):
            body += f"Error type: {untrusted(report['error_type'])}"
            if isinstance(report.get("cell_index"), int):
                body += f", in cell {report['cell_index']} (counting from 0)"
            body += "\n\n"
        body += "**Score: 0**"
        return make_marker(student_id, assignment, 0.0) + "\n" + header + body + details

    if "note" in report:
        return header + f"ℹ️ {untrusted(report['note'])[1:-1]}" + details

    score = number(report.get("score", 0))
    if "test_case_results" in report:
        earned, total = number(report["earned_points"]), number(report["total_points"])
        body = f"### Score: {earned:g}/{total:g} ({score:.2f}%)\n\n"
        body += f"**Passed:** {int(report['passed_cases'])}/{int(report['total_test_cases'])} test cases\n"
        failed = [case for case in report["test_case_results"] if not case.get("passed")]
        if failed:
            body += "\n### Failed test cases\n\n"
            for case in failed:
                body += f"- ❌ **{untrusted(case.get('name'))[1:-1]}** ({number(case['earned']):g}/{number(case['points']):g})"
                body += f": {untrusted(case['error'])}\n" if case.get("error") else "\n"
        return make_marker(student_id, assignment, score, earned, total) + "\n" + header + body + details

    body = f"### Score: {score:.2f}%\n\n**Matches:** {int(report.get('matches', 0))}/{int(report.get('total_expected', 0))}\n"
    return make_marker(student_id, assignment, score) + "\n" + header + body + details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-url", default="")
    args = parser.parse_args()

    path = Path(args.report)
    report = json.loads(path.read_text()) if path.is_file() else None
    Path(args.output).write_text(render(args.branch, report, args.run_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
