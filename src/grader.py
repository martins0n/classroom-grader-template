"""Scores notebook outputs. Standard library only: it runs on the runner host."""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_FIELD_LENGTH = 500


def _clip(value: Any) -> Any:
    """Student outputs end up in public reports, so keep them small."""
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    text = str(value)
    return text if len(text) <= MAX_FIELD_LENGTH else text[:MAX_FIELD_LENGTH] + "..."


def expected_objects(expected: Any) -> List[Dict[str, Any]]:
    """The object every check expects. Raises ValueError for anything else.

    Outputs are found by the keys of these objects, so a check can't expect a bare value.
    """
    if isinstance(expected, dict) and "test_cases" in expected:
        cases = expected["test_cases"]
        if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
            raise ValueError("test_cases must be a list of objects")
        items = [case.get("expected") for case in cases]
    else:
        items = expected if isinstance(expected, list) else [expected]
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not item:
            raise ValueError(f"Check {index} must expect a non-empty JSON object, got {_clip(item)!r}")
    return items


def match_outputs(expected: List[Dict[str, Any]], outputs: List[Any]) -> List[Optional[Dict[str, Any]]]:
    """Pick the output for every expected object by its keys, so position does not matter.

    Other output anywhere in the notebook then shifts nothing. Each output is used once. The
    best one shares the most keys with the expected object, then has the fewest other keys.
    On a tie the earlier output wins, so checks with the same keys take outputs in order.
    """
    candidates = [output for output in outputs if isinstance(output, dict)]
    used = set()
    matched: List[Optional[Dict[str, Any]]] = []
    for wanted in expected:
        best, best_rank = None, None
        for index, output in enumerate(candidates):
            shared = len(wanted.keys() & output.keys())
            if index in used or not shared:
                continue
            rank = (shared, -len(output.keys() - wanted.keys()))
            if best_rank is None or rank > best_rank:
                best, best_rank = index, rank
        if best is not None:
            used.add(best)
        matched.append(None if best is None else candidates[best])
    return matched


class NotebookGrader:
    """Compares the JSON objects printed by an executed notebook with the expected ones."""

    def grade(self, student_outputs: List[Any], expected: Any) -> Dict[str, Any]:
        objects = expected_objects(expected)
        if isinstance(expected, dict) and "test_cases" in expected:
            return self.grade_test_cases(student_outputs, expected)
        return self.compare_outputs(student_outputs, objects)

    def compare_outputs(
        self, student_output: List[Any], expected_output: List[Any], tolerance: float = 0.0
    ) -> Dict[str, Any]:
        found = [
            (received, expected)
            for received, expected in zip(match_outputs(expected_output, student_output), expected_output)
            if received is not None
        ]
        matches = sum(1 for received, expected in found if self._compare_json(received, expected, tolerance))
        total = len(expected_output)
        received_objects = sum(1 for output in student_output if isinstance(output, dict))
        return {
            "total_expected": total,
            "total_received": received_objects,
            "matches": matches,
            "mismatches": len(found) - matches,
            "missing": total - len(found),
            "extra": received_objects - len(found),
            "score": (matches / total) * 100 if total else 0.0,
            "passed": matches == total,
        }

    def _compare_values(
        self, value: Any, expected: Any, operator: str = "==", tolerance: float = 0.0
    ) -> bool:
        if isinstance(value, (int, float)) and isinstance(expected, (int, float)):
            if operator in ("==", "eq"):
                if tolerance > 0:
                    if expected == 0:
                        return abs(value) <= tolerance
                    return abs(value - expected) / abs(expected) <= tolerance
                return value == expected
            if operator in ("<", "lt"):
                return value < expected
            if operator in ("<=", "lte"):
                return value <= expected
            if operator in (">", "gt"):
                return value > expected
            if operator in (">=", "gte"):
                return value >= expected
            if operator in ("!=", "ne"):
                return value != expected
            logger.warning("Unknown operator '%s', defaulting to '=='", operator)
            return value == expected
        if operator in ("!=", "ne"):
            return value != expected
        return value == expected

    def _compare_json(self, received: Any, expected: Any, tolerance: float = 0.0) -> bool:
        if isinstance(received, (int, float)) and isinstance(expected, (int, float)):
            if tolerance > 0:
                if expected == 0:
                    return abs(received) <= tolerance
                return abs(received - expected) / abs(expected) <= tolerance
            return received == expected
        if type(received) != type(expected):
            return False
        if isinstance(received, dict):
            if set(received) != set(expected):
                return False
            return all(self._compare_json(received[k], expected[k], tolerance) for k in received)
        if isinstance(received, list):
            if len(received) != len(expected):
                return False
            return all(self._compare_json(a, b, tolerance) for a, b in zip(received, expected))
        return received == expected

    def grade_test_cases(self, student_outputs: List[Any], config: Dict[str, Any]) -> Dict[str, Any]:
        test_cases = config["test_cases"]
        matched = match_outputs([test_case["expected"] for test_case in test_cases], student_outputs)
        result = {
            "total_test_cases": len(test_cases),
            "passed_cases": 0,
            "failed_cases": 0,
            "total_points": sum(tc.get("points", 0) for tc in test_cases),
            "earned_points": 0,
            "test_case_results": [],
            "passed": True,  # points-based grading: the score is what matters
        }
        for index, (test_case, received) in enumerate(zip(test_cases, matched)):
            case = self._grade_case(index, test_case, received)
            result["earned_points"] += case["earned"]
            result["passed_cases" if case["passed"] else "failed_cases"] += 1
            result["test_case_results"].append(case)
        total = result["total_points"]
        result["score"] = (result["earned_points"] / total) * 100 if total > 0 else 0.0
        return result

    def _grade_case(
        self, index: int, test_case: Dict[str, Any], received: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        points = test_case.get("points", 0)
        expected = test_case["expected"]
        tolerance = test_case.get("tolerance", 0.0)
        case = {
            "name": test_case.get("name", f"Test Case {index + 1}"),
            "points": points,
            "earned": 0,
            "passed": False,
        }
        if received is None:
            case["error"] = _clip("No output with keys " + ", ".join(sorted(expected)))
            return case

        if "compare_fields" in test_case or "compare" in test_case:
            default_operator = test_case.get("compare", "==")
            passed_fields = 0
            errors = []
            for key, expected_value in expected.items():
                if key not in received:
                    errors.append(f"Missing field '{key}'")
                    continue
                operator = test_case.get("compare_fields", {}).get(key, default_operator)
                field_tolerance = test_case.get("tolerance_fields", {}).get(key, tolerance)
                if self._compare_values(received[key], expected_value, operator, field_tolerance):
                    passed_fields += 1
                else:
                    errors.append(f"Field '{key}': {received[key]} {operator} {expected_value}")
            case["earned"] = min((passed_fields / len(expected)) * points, points)
            if passed_fields == len(expected):
                case["passed"] = True
            else:
                case["error"] = _clip("; ".join(errors))
                case["received"] = _clip(received)
            return case

        if self._compare_json(received, expected, tolerance):
            case.update(passed=True, earned=points)
        else:
            case["error"] = "Output does not match expected"
            case["received"] = _clip(received)
        return case
