import json
from pathlib import Path

import pytest

from conftest import ROOT
from src.grader import NotebookGrader


def test_legacy_format():
    grader = NotebookGrader()
    report = grader.grade([{"a": 1}, {"b": 3}], [{"a": 1}, {"b": 2}])
    assert report["score"] == 50 and report["passed"] is False and report["mismatches"] == 1


def test_test_cases_with_tolerance_and_operators():
    config = {"test_cases": [
        {"name": "t", "points": 10, "tolerance": 0.01, "expected": {"pi": 3.14}},
        {"name": "c", "points": 20, "expected": {"f1": 0.5}, "compare_fields": {"f1": ">="}},
        {"name": "single", "points": 10, "expected": 5, "compare": "<"},
    ]}
    report = NotebookGrader().grade([{"pi": 3.141}, {"f1": 0.7}, 3], config)
    assert report["earned_points"] == 40 and report["score"] == 100


def test_partial_field_credit():
    config = {"test_cases": [{"name": "c", "points": 10, "expected": {"a": 1, "b": 2}, "compare_fields": {"a": ">="}}]}
    report = NotebookGrader().grade([{"a": 1, "b": 0}], config)
    assert report["earned_points"] == 5 and report["failed_cases"] == 1


@pytest.mark.parametrize("hostile", [5, "text", None, [1], True])
def test_output_of_the_wrong_shape_fails_the_case_instead_of_crashing_the_grader(hostile):
    config = {"test_cases": [{"name": "c", "points": 10, "expected": {"a": 1}, "compare_fields": {"a": ">="}}]}
    report = NotebookGrader().grade([hostile], config)
    assert report["earned_points"] == 0 and report["score"] == 0


def test_student_text_in_reports_is_clipped():
    config = {"test_cases": [{"name": "c", "points": 10, "expected": {"a": 1}}]}
    report = NotebookGrader().grade(["x" * 100000], config)
    assert len(json.dumps(report)) < 2000


@pytest.mark.parametrize("assignment", ["homework-1-example", "homework-2-example", "homework-3-performance"])
def test_examples_are_valid_json(assignment):
    assert json.loads((ROOT / "test_cases" / assignment / "expected_output.json").read_text())
