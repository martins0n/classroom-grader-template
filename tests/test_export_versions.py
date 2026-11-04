"""The teacher's key copy and the export of stored versions."""
import base64
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import setup_course
from src.encryption import SubmissionCipher, generate_master_key, load_master_key
from src.key_copy import key_path, load_key_copies, save_key_copy

ROOT = Path(__file__).resolve().parent.parent
STUDENT = "a_b_at_x_org"
ASSIGNMENT = "homework-1"
BRANCH = f"student-{STUDENT}/assignment-{ASSIGNMENT}"
DIRECTORY = f"submissions/{STUDENT}/{ASSIGNMENT}"


def run_git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd, check=True, capture_output=True,
    )


class Course:
    """A clone of a bare origin named owner/course.git, with one student branch."""

    def __init__(self, tmp_path):
        self.origin = tmp_path / "owner" / "course.git"
        self.origin.mkdir(parents=True)
        run_git(self.origin, "init", "--bare", "-q")
        self.clone = tmp_path / "clone"
        run_git(tmp_path, "clone", "-q", str(self.origin), str(self.clone))
        run_git(self.clone, "checkout", "-q", "-b", BRANCH)
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.output = tmp_path / "out"
        self.counter = 0

    def sync(self, key, content, name="work.ipynb"):
        self.counter += 1
        path = self.clone / DIRECTORY / f"{name}.enc"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(SubmissionCipher(load_master_key(key)).encrypt(content, STUDENT))
        run_git(self.clone, "add", "-A")
        run_git(self.clone, "commit", "-q", "-m", f"sync {self.counter}")
        run_git(self.clone, "push", "-q", "origin", BRANCH)

    def export(self, *extra, key=None, env=None, output=None):
        environment = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS", "ENCRYPTION_KEY")}
        environment["HOME"] = str(self.home)
        if key:
            environment["ENCRYPTION_KEY"] = key
        environment.update(env or {})
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/export_versions.py"), "--output-dir", str(output or self.output), *extra],
            cwd=self.clone, env=environment, capture_output=True, text=True,
        )

    def exported(self):
        folders = sorted((self.output / STUDENT / ASSIGNMENT).iterdir())
        return [(folder.name[:3], (folder / "work.ipynb").read_bytes()) for folder in folders]


@pytest.fixture
def course(tmp_path):
    return Course(tmp_path)


def test_every_version_comes_back_in_order_even_a_return_to_old_content(course):
    key = generate_master_key()
    for content in (b"one", b"two", b"one"):
        course.sync(key, content)
    result = course.export(key=key)
    assert result.returncode == 0, result.stderr
    assert course.exported() == [("v01", b"one"), ("v02", b"two"), ("v03", b"one")]
    assert "3 of 3 version(s)" in result.stdout


def test_versions_from_before_a_rotation_are_reported_not_fatal(course):
    old, new = generate_master_key(), generate_master_key()
    course.sync(old, b"old")
    course.sync(new, b"new")
    result = course.export(key=new)
    assert result.returncode == 0, result.stderr
    assert course.exported() == [("v02", b"new")]
    assert "no available key opens it" in result.stdout
    assert "1 of 2 version(s)" in result.stdout


def test_saved_copies_open_versions_from_before_and_after_a_rotation(course, monkeypatch):
    monkeypatch.setenv("HOME", str(course.home))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    old, new = generate_master_key(), generate_master_key()
    save_key_copy("owner/course", old)
    save_key_copy("owner/course", new)
    course.sync(old, b"old")
    course.sync(new, b"new")
    result = course.export()
    assert result.returncode == 0, result.stderr
    assert course.exported() == [("v01", b"old"), ("v02", b"new")]


def test_no_key_at_all_fails_clearly(course):
    course.sync(generate_master_key(), b"x")
    result = course.export()
    assert result.returncode == 1
    assert "No key found" in result.stderr


def test_nothing_decryptable_is_a_failure(course):
    course.sync(generate_master_key(), b"x")
    assert course.export(key=generate_master_key()).returncode == 1


@pytest.mark.parametrize("name", ["..\\..\\evil.ipynb", "evil\n.ipynb"])
def test_a_hostile_file_name_stays_inside_the_version_folder(course, tmp_path, name):
    key = generate_master_key()
    course.sync(key, b"x", name=name)
    result = course.export(key=key)
    assert result.returncode == 0, result.stderr
    written = [p for p in course.output.rglob("*") if p.is_file()]
    assert len(written) == 1
    assert written[0].parent.parent == course.output / STUDENT / ASSIGNMENT
    assert "\n" not in written[0].name
    assert not list(tmp_path.glob("evil*"))


def test_output_inside_the_public_checkout_is_refused(course):
    key = generate_master_key()
    course.sync(key, b"x")
    result = course.export(key=key, output=course.clone / "versions")
    assert result.returncode == 1
    assert "outside this repository" in result.stderr
    assert not (course.clone / "versions").exists()


@pytest.mark.parametrize("variable", ["CI", "GITHUB_ACTIONS"])
def test_export_refuses_to_run_in_ci(course, variable):
    key = generate_master_key()
    course.sync(key, b"x")
    result = course.export(key=key, env={variable: "true"})
    assert result.returncode != 0
    assert not course.output.exists()


def test_filters_select_one_work_and_bad_values_are_refused(course):
    key = generate_master_key()
    course.sync(key, b"x")
    assert course.export("--student", "someone_else", key=key).returncode == 1
    assert course.export("--student", "../../etc", key=key).returncode == 1
    assert course.export("--assignment", "--upload-pack=x", key=key).returncode != 0
    assert course.export("--student", STUDENT, "--assignment", ASSIGNMENT, key=key).returncode == 0


def test_the_key_never_appears_in_the_output(course):
    key = generate_master_key()
    course.sync(key, b"x")
    result = course.export(key=key)
    assert key not in result.stdout + result.stderr


def test_exported_files_are_private(course):
    key = generate_master_key()
    course.sync(key, b"x")
    course.export(key=key)
    written = next(p for p in course.output.rglob("*") if p.is_file())
    assert stat.S_IMODE(written.stat().st_mode) == 0o600


# ---------- setup_course.py ----------


@pytest.fixture
def teacher(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    calls = {"secrets": {}, "existing": ""}

    def fake_gh(*args, stdin=None):
        if args[:2] == ("repo", "view"):
            return "owner/course"
        if args[0] == "api" and "actions/secrets" in args[1]:
            return calls["existing"]
        if args[:2] == ("secret", "set"):
            calls["secrets"][args[2]] = stdin
        return ""

    monkeypatch.setattr(setup_course, "gh", fake_gh)
    return calls


def run_setup(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["setup_course.py", "--skip-google", *args])
    return setup_course.main()


def test_setup_saves_the_same_key_it_sends_and_keeps_it_private(teacher, monkeypatch, capsys):
    assert run_setup(monkeypatch) == 0
    path = key_path("owner/course")
    assert path.read_text().strip() == teacher["secrets"]["ENCRYPTION_KEY"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert teacher["secrets"]["ENCRYPTION_KEY"] not in capsys.readouterr().out


def test_rotation_keeps_the_old_copy(teacher, monkeypatch):
    run_setup(monkeypatch)
    first = teacher["secrets"]["ENCRYPTION_KEY"]
    teacher["existing"] = "ENCRYPTION_KEY"
    run_setup(monkeypatch, "--rotate-key")
    second = teacher["secrets"]["ENCRYPTION_KEY"]
    assert first != second
    assert key_path("owner/course").read_text().strip() == second
    assert set(load_key_copies("owner/course")) == {load_master_key(first), load_master_key(second)}


def test_setup_with_an_existing_key_writes_nothing(teacher, monkeypatch):
    teacher["existing"] = "ENCRYPTION_KEY"
    run_setup(monkeypatch)
    assert "ENCRYPTION_KEY" not in teacher["secrets"]
    assert not key_path("owner/course").exists()


def test_setup_in_ci_refuses_before_touching_the_secret(teacher, monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(SystemExit):
        run_setup(monkeypatch)
    assert "ENCRYPTION_KEY" not in teacher["secrets"]
    assert not key_path("owner/course").exists()


def test_no_workflow_uses_the_key_copy_or_the_export():
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text()
        assert "export_versions" not in text, workflow.name
        assert "key_copy" not in text, workflow.name
