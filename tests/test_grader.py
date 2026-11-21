import json

import pytest

from conftest import ROOT
from sandbox.runner import json_objects
from src.grader import NotebookGrader, expected_objects

HW2 = json.loads((ROOT / "test_cases" / "homework-2-example" / "expected_output.json").read_text())
A1 = {"sum": 15, "product": 50}
A2 = {"result": "Hello, World!", "length": 13}
A3 = {"pi": 3.14159, "e": 2.71828}
A4 = {"sorted": [1, 2, 3, 4, 5], "reversed": [5, 4, 3, 2, 1]}


def test_legacy_format():
    grader = NotebookGrader()
    report = grader.grade([{"a": 1}, {"b": 3}], [{"a": 1}, {"b": 2}])
    assert report["score"] == 50 and report["passed"] is False and report["mismatches"] == 1


def test_test_cases_with_tolerance_and_operators():
    config = {"test_cases": [
        {"name": "t", "points": 10, "tolerance": 0.01, "expected": {"pi": 3.14}},
        {"name": "c", "points": 20, "expected": {"f1": 0.5}, "compare_fields": {"f1": ">="}},
        {"name": "all fields", "points": 10, "expected": {"n": 5, "m": 5}, "compare": "<"},
    ]}
    report = NotebookGrader().grade([{"pi": 3.141}, {"f1": 0.7}, {"n": 3, "m": 4}], config)
    assert report["earned_points"] == 40 and report["score"] == 100


def test_partial_field_credit():
    config = {"test_cases": [{"name": "c", "points": 10, "expected": {"a": 1, "b": 2}, "compare_fields": {"a": ">="}}]}
    report = NotebookGrader().grade([{"a": 1, "b": 0}], config)
    assert report["earned_points"] == 5 and report["failed_cases"] == 1


@pytest.mark.parametrize("hostile", [5, "text", None, [1], True, {}, {"other": 1}])
def test_output_of_the_wrong_shape_fails_the_case_instead_of_crashing_the_grader(hostile):
    config = {"test_cases": [{"name": "c", "points": 10, "expected": {"a": 1}, "compare_fields": {"a": ">="}}]}
    report = NotebookGrader().grade([hostile], config)
    assert report["earned_points"] == 0 and report["score"] == 0


def test_student_text_in_reports_is_clipped():
    config = {"test_cases": [{"name": "c", "points": 10, "expected": {"a": 1}}]}
    report = NotebookGrader().grade([{"a": "x" * 100000}], config)
    assert len(json.dumps(report)) < 2000


def test_outputs_are_found_by_keys_whatever_else_the_notebook_prints():
    outputs = [3, {"debug": 1}, A4, [1, 2], 0.5, A2, "text", A1, A3, {"epoch": 2}]
    report = NotebookGrader().grade(outputs, HW2)
    assert report["earned_points"] == 50


def test_a_missing_answer_costs_only_its_own_check():
    report = NotebookGrader().grade([A1, A3, A4], HW2)
    assert report["earned_points"] == 40
    failed = [case for case in report["test_case_results"] if not case["passed"]]
    assert [case["name"] for case in failed] == ["String operations"]
    assert failed[0]["error"] == "No output with keys length, result"


def test_an_object_with_a_field_missing_still_gets_partial_credit():
    config = {"test_cases": [
        {"name": "a", "points": 10, "expected": {"x": 1, "y": 2}, "compare_fields": {"x": "=="}},
        {"name": "b", "points": 10, "expected": {"z": 3}},
    ]}
    report = NotebookGrader().grade([{"z": 3}, {"x": 1}], config)
    assert report["earned_points"] == 15


def test_the_closest_object_wins():
    config = {"test_cases": [
        {"name": "short", "points": 10, "expected": {"a": 1}},
        {"name": "long", "points": 10, "expected": {"a": 1, "b": 2}},
    ]}
    report = NotebookGrader().grade([{"a": 1, "b": 2}, {"a": 1}], config)
    assert report["earned_points"] == 20


def test_checks_with_the_same_keys_take_outputs_in_order():
    config = {"test_cases": [
        {"name": "first", "points": 10, "expected": {"mae": 1}},
        {"name": "second", "points": 10, "expected": {"mae": 2}},
    ]}
    assert NotebookGrader().grade([{"mae": 1}, {"mae": 2}], config)["earned_points"] == 20
    assert NotebookGrader().grade([{"mae": 2}, {"mae": 1}], config)["earned_points"] == 0


def test_extra_objects_in_the_plain_format_do_not_fail_it():
    report = NotebookGrader().grade([{"debug": 1}, A2, A1], [A1, A2])
    assert report["score"] == 100 and report["passed"] is True and report["extra"] == 1


@pytest.mark.parametrize("expected", [
    {"test_cases": [{"name": "single", "points": 10, "expected": 5, "compare": "<"}]},
    {"test_cases": [{"name": "empty", "points": 10, "expected": {}}]},
    {"test_cases": {"name": "not a list"}},
    [{"a": 1}, [1, 2]],
])
def test_a_check_that_does_not_expect_an_object_is_a_config_error(expected):
    with pytest.raises(ValueError):
        NotebookGrader().grade([{"a": 1}], expected)


@pytest.mark.parametrize(
    "path", sorted((ROOT / "test_cases").glob("*/expected_output.json")), ids=lambda path: path.parent.name
)
def test_every_assignment_expects_objects(path):
    expected_objects(json.loads(path.read_text()))


@pytest.mark.parametrize("text,objects", [
    ('{"a": 1}\n', [{"a": 1}]),
    ('{\n  "a": 1\n}\n', [{"a": 1}]),
    ('checking...\n{"a": 1}\ndone\n', [{"a": 1}]),
    ('{"a": 1}\n{"b": 2}\n', [{"a": 1}, {"b": 2}]),
    ("3\n", []),
    ("[1, 2]\n", []),
    ("{'a': 1}\n", []),
    ("epoch 1\n0.5\n", []),
    ("[" * 100000, []),
    (None, []),
])
def test_runner_keeps_only_json_objects(text, objects):
    assert json_objects(text) == objects
