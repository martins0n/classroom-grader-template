"""Names derived from untrusted input: branches, student ids and file names.

Everything here is standard library only, because the grading job imports it.
"""
import re
from typing import Tuple

SELFTEST_STUDENT = "selftest_at_example_com"
SELFTEST_ASSIGNMENT = "homework-2-example"

_STUDENT_RE = r"[A-Za-z0-9_+-]{1,200}"
_ASSIGNMENT_RE = r"[a-z0-9][a-z0-9-]{0,99}"
_BRANCH_RE = re.compile(rf"student-({_STUDENT_RE})/assignment-({_ASSIGNMENT_RE})")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
MAX_FILENAME_LENGTH = 120


def sanitize_assignment_name(title: str) -> str:
    """Turn an assignment title into a name safe for branches and paths.

    Only Latin letters and digits survive, so a purely non-Latin title returns "".
    Callers fall back to the coursework id in that case.
    """
    name = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return name[:50].rstrip("-")


def student_id_from_email(email: str) -> str:
    """Encode an email as a student id, e.g. a.b@x.org -> a_b_at_x_org."""
    encoded = email.replace("@", "_at_").replace(".", "_")
    return re.sub(r"[^A-Za-z0-9_+-]", "_", encoded)


def email_from_student_id(student_id: str) -> str:
    """Best-effort reverse of student_id_from_email (underscores become dots)."""
    return student_id.replace("_at_", "@").replace("_", ".")


def make_branch_name(student_id: str, assignment: str) -> str:
    branch = f"student-{student_id}/assignment-{assignment}"
    parse_branch(branch)
    return branch


def parse_branch(branch: str) -> Tuple[str, str]:
    """Return (student_id, assignment) or raise ValueError for anything unexpected."""
    match = _BRANCH_RE.fullmatch(branch or "")
    if not match:
        raise ValueError("not a student branch")
    return match.group(1), match.group(2)


def is_valid_student_id(value: str) -> bool:
    return bool(re.fullmatch(_STUDENT_RE, value or ""))


def is_valid_assignment(value: str) -> bool:
    return bool(re.fullmatch(_ASSIGNMENT_RE, value or ""))


def safe_filename(title: str, default: str = "untitled") -> str:
    """Reduce a student-controlled attachment title to a single path component.

    Drive titles may contain slashes, so a title such as ../../src/encryption.py
    must never be joined to a directory as is.
    """
    name = (title or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL_CHARS_RE.sub("", name).strip()
    if name in ("", ".", ".."):
        return default
    if len(name) > MAX_FILENAME_LENGTH:
        stem, dot, suffix = name.rpartition(".")
        if dot and len(suffix) <= 16:
            name = stem[: MAX_FILENAME_LENGTH - len(suffix) - 1] + "." + suffix
        else:
            name = name[:MAX_FILENAME_LENGTH]
    return name
