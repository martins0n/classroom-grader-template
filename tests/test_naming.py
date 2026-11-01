import pytest

from src.naming import (
    email_from_student_id,
    make_branch_name,
    parse_branch,
    safe_filename,
    sanitize_assignment_name,
    student_id_from_email,
)


@pytest.mark.parametrize("title,expected", [
    ("../../src/encryption.py", "encryption.py"),
    ("..\\..\\evil.py", "evil.py"),
    ("/etc/passwd", "passwd"),
    ("..", "untitled"),
    (".", "untitled"),
    ("", "untitled"),
    (None, "untitled"),
    ("a/b/..", "untitled"),
    ("Домашка 1.ipynb", "Домашка 1.ipynb"),
    ("evil\x00name\n.ipynb", "evilname.ipynb"),
])
def test_safe_filename(title, expected):
    assert safe_filename(title) == expected


def test_long_names_keep_their_extension():
    name = safe_filename("x" * 500 + ".ipynb")
    assert name.endswith(".ipynb") and len(name) <= 120


@pytest.mark.parametrize("branch", [
    "",
    "main",
    "student-a/assignment-b/extra",
    "student-../assignment-b",
    "student-a/assignment-../../x",
    "student-a b/assignment-c",
    'student-a";curl evil;"/assignment-c',
    "student-a/assignment-$(id)",
    "student-a/assignment-B",
    "refs/heads/student-a/assignment-b",
    "student-a/assignment-b\n",
])
def test_parse_branch_rejects(branch):
    with pytest.raises(ValueError):
        parse_branch(branch)


def test_parse_branch_accepts_real_shapes():
    assert parse_branch("student-a_b_at_x_org/assignment-homework-1") == ("a_b_at_x_org", "homework-1")
    assert parse_branch("student-100923/assignment-820061") == ("100923", "820061")
    assert parse_branch("student-a+tag_at_x_org/assignment-hw") == ("a+tag_at_x_org", "hw")


def test_student_id_is_always_a_valid_branch_component():
    student = student_id_from_email("o'neil.$(id)@x.org")
    assert parse_branch(make_branch_name(student, "hw"))[0] == student


def test_email_round_trip():
    assert email_from_student_id(student_id_from_email("john.doe@example.com")) == "john.doe@example.com"


def test_non_latin_title_needs_a_fallback():
    assert sanitize_assignment_name("Домашка") == ""
    assert sanitize_assignment_name("Homework 1 - Variables!") == "homework-1-variables"
