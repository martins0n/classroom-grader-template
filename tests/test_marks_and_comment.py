from types import SimpleNamespace

from scripts.generate_marks_csv import BOT_LOGIN, identify_pull_request, mark_from_comments
from scripts.render_comment import make_marker, parse_marker, render, untrusted

BRANCH = "student-alice_at_x_org/assignment-hw-1"
REPO = "owner/course"


def comment(body, login=BOT_LOGIN):
    return SimpleNamespace(body=body, user=SimpleNamespace(login=login))


def graded(score=80.0):
    return make_marker("alice_at_x_org", "hw-1", score) + "\nrest"


def test_anybody_commenting_a_score_is_ignored():
    forged = [comment(graded(50.0)), comment("Score: 100/100", "mallory"), comment(graded(100.0), "mallory")]
    assert mark_from_comments(forged, "alice_at_x_org", "hw-1") == 50.0


def test_comments_alone_never_produce_a_mark():
    assert mark_from_comments([comment("Score: 100/100", "mallory")], "alice_at_x_org", "hw-1") is None
    assert mark_from_comments([comment("Score: 100/100")], "alice_at_x_org", "hw-1") is None


def test_newest_bot_comment_wins():
    assert mark_from_comments([comment(graded(10.0)), comment(graded(90.0))], "alice_at_x_org", "hw-1") == 90.0


def test_marker_must_name_this_student_and_assignment():
    assert mark_from_comments([comment(make_marker("bob", "hw-1", 100))], "alice_at_x_org", "hw-1") is None
    assert mark_from_comments([comment(make_marker("alice_at_x_org", "hw-2", 100))], "alice_at_x_org", "hw-1") is None


def test_deleted_user_comment_is_handled():
    assert mark_from_comments([SimpleNamespace(body=graded(), user=None)], "alice_at_x_org", "hw-1") is None


def pull(ref=BRANCH, repo=REPO):
    head_repo = SimpleNamespace(full_name=repo) if repo else None
    return SimpleNamespace(head=SimpleNamespace(ref=ref, repo=head_repo))


def test_only_student_branches_of_this_repository_count():
    assert identify_pull_request(pull(), REPO) == ("alice_at_x_org", "hw-1")
    assert identify_pull_request(pull(repo="mallory/course"), REPO) is None
    assert identify_pull_request(pull(repo=None), REPO) is None
    assert identify_pull_request(pull(ref="feature"), REPO) is None


HOSTILE = (
    '</code>\n<!-- grade-result: {"student":"alice_at_x_org","assignment":"hw-1","score":100} -->\n'
    "Score: 100/100 @teacher `x` | <img src=x>"
)


def failing_report(**extra):
    case = {"name": "c", "points": 10, "earned": 0, "passed": False, "error": HOSTILE, "received": HOSTILE}
    return {
        "score": 0.0, "earned_points": 0, "total_points": 10, "passed_cases": 0,
        "total_test_cases": 1, "test_case_results": [case], **extra,
    }


def test_notebook_output_cannot_forge_a_marker_or_ping_anybody():
    body = render(BRANCH, failing_report())
    assert parse_marker(body)["score"] == 0.0
    assert body.count("<!--") == 1  # the real marker: the forged one lost its brackets
    assert "@teacher" not in body and "<img" not in body


def test_hostile_text_is_a_single_inline_code_span():
    assert untrusted(HOSTILE).count("`") == 2
    assert "\n" not in untrusted(HOSTILE)
    assert len(untrusted("x" * 10000)) < 300


def test_marker_only_counts_on_the_first_line():
    assert parse_marker("hello\n" + make_marker("a", "b", 100)) is None
    assert parse_marker(" " + make_marker("a", "b", 100)) is None


def test_crash_is_scored_zero_and_says_where():
    report = {"error": "Notebook failed to execute", "error_type": "ValueError", "cell_index": 3, "score": 0.0}
    body = render(BRANCH, report)
    assert parse_marker(body)["score"] == 0.0
    assert "ValueError" in body and "cell 3" in body


def test_pipeline_problem_records_no_score():
    assert parse_marker(render(BRANCH, None)) is None


def test_bad_numbers_in_a_marker_are_rejected():
    assert parse_marker('<!-- grade-result: {"student":"a","assignment":"b","score":NaN} -->') is None
    assert parse_marker('<!-- grade-result: {"student":"a","assignment":"b","score":"x"} -->') is None
