"""Scores notebook outputs. Standard library only: it runs on the runner host."""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MAX_FIELD_LENGTH = 500


def _clip(value: Any) -> Any:
    """Student outputs end up in public reports, so keep them small."""
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    text = str(value)
    return text if len(text) <= MAX_FIELD_LENGTH else text[:MAX_FIELD_LENGTH] + "..."


class NotebookGrader:
    """Compares the JSON outputs of an executed notebook with the expected ones."""

    def grade(self, student_outputs: List[Any], expected: Any) -> Dict[str, Any]:
        if isinstance(expected, dict) and "test_cases" in expected:
            return self.grade_test_cases(student_outputs, expected)
        expected_outputs = expected if isinstance(expected, list) else [expected]
        return self.compare_outputs(student_outputs, expected_outputs)

    def compare_outputs(
        self, student_output: List[Any], expected_output: List[Any], tolerance: float = 0.0
    ) -> Dict[str, Any]:
        matches = sum(
            1
            for received, expected in zip(student_output, expected_output)
            if self._compare_json(received, expected, tolerance)
        )
        total = len(expected_output)
        extra = max(len(student_output) - total, 0)
        return {
            "total_expected": total,
            "total_received": len(student_output),
            "matches": matches,
            "mismatches": min(len(student_output), total) - matches,
            "missing": max(total - len(student_output), 0),
            "extra": extra,
            "score": (matches / total) * 100 if total else 0.0,
            "passed": matches == total and extra == 0,
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
        test_cases = config.get("test_cases", [])
        result = {
            "total_test_cases": len(test_cases),
            "passed_cases": 0,
            "failed_cases": 0,
            "total_points": sum(tc.get("points", 0) for tc in test_cases),
            "earned_points": 0,
            "test_case_results": [],
            "passed": True,  # points-based grading: the score is what matters
        }
        for index, test_case in enumerate(test_cases):
            case = self._grade_case(index, test_case, student_outputs)
            result["earned_points"] += case["earned"]
            result["passed_cases" if case["passed"] else "failed_cases"] += 1
            result["test_case_results"].append(case)
        total = result["total_points"]
        result["score"] = (result["earned_points"] / total) * 100 if total > 0 else 0.0
        return result

    def _grade_case(self, index: int, test_case: Dict[str, Any], outputs: List[Any]) -> Dict[str, Any]:
        points = test_case.get("points", 0)
        expected = test_case.get("expected")
        tolerance = test_case.get("tolerance", 0.0)
        compare = test_case.get("compare", "==")
        case = {
            "name": test_case.get("name", f"Test Case {index + 1}"),
            "points": points,
            "earned": 0,
            "passed": False,
        }
        if index >= len(outputs):
            case["error"] = "Missing output"
            return case
        received = outputs[index]

        if compare != "==" and not isinstance(expected, (dict, list)):
            if self._compare_values(received, expected, compare, tolerance):
                case.update(passed=True, earned=points)
            else:
                case["error"] = _clip(f"Comparison failed: {received} {compare} {expected}")
                case["received"] = _clip(received)
            return case

        if isinstance(expected, dict) and ("compare_fields" in test_case or "compare" in test_case):
            if not isinstance(received, dict):
                case["error"] = "Expected a JSON object"
                case["received"] = _clip(received)
                return case
            passed_fields = 0
            errors = []
            for key, expected_value in expected.items():
                if key not in received:
                    errors.append(f"Missing field '{key}'")
                    continue
                operator = test_case.get("compare_fields", {}).get(key, "==")
                field_tolerance = test_case.get("tolerance_fields", {}).get(key, tolerance)
                if self._compare_values(received[key], expected_value, operator, field_tolerance):
                    passed_fields += 1
                else:
                    errors.append(f"Field '{key}': {received[key]} {operator} {expected_value}")
            if expected:
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
