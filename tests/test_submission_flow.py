import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import classroom_client as cc
from src.classroom_client import ClassroomClient
from src.encryption import SubmissionCipher, generate_master_key, load_master_key
from src.github_manager import git_blob_sha
from src.submission_processor import SubmissionProcessor

KEY = load_master_key(generate_master_key())
DIR = "submissions/alice/hw-1"
PATH = f"{DIR}/work.ipynb.enc"


class FakeGitHub:
    def __init__(self):
        self.calls = []

    def get_or_create_branch(self, branch):
        self.calls.append(("branch", branch))

    def commit_files(self, files, branch, message, delete_paths):
        self.calls.append(("commit", [path for _, path in files], delete_paths))

    def create_or_update_pull_request(self, branch, title, body):
        self.calls.append(("pr", title))
        return "url"

    def dispatch_grading(self, branch):
        self.calls.append(("dispatch", branch))
        return True


def processor(github, tree=None):
    return SubmissionProcessor(None, github, SubmissionCipher(KEY), tree_reader=lambda b, d: tree or {})


def test_new_submission_is_committed_then_graded():
    github = FakeGitHub()
    assert processor(github).sync_submission("alice", "hw-1", {"work.ipynb": b"nb"}) is True
    kinds = [call[0] for call in github.calls]
    assert kinds == ["branch", "commit", "pr", "dispatch"]
    assert github.calls[1][1] == [PATH]


def test_unchanged_submission_makes_no_api_calls_at_all():
    """GITHUB_TOKEN allows 1000 requests an hour, so the hourly no-change pass must cost none."""
    github = FakeGitHub()
    encrypted = SubmissionCipher(KEY).encrypt(b"nb", "alice")
    tree = {PATH: git_blob_sha(encrypted)}
    assert processor(github, tree).sync_submission("alice", "hw-1", {"work.ipynb": b"nb"}) is False
    assert github.calls == []


def test_removed_attachment_is_deleted_from_the_branch():
    github = FakeGitHub()
    encrypted = SubmissionCipher(KEY).encrypt(b"nb", "alice")
    tree = {PATH: git_blob_sha(encrypted), f"{DIR}/old.ipynb.enc": "abc"}
    processor(github, tree).sync_submission("alice", "hw-1", {"work.ipynb": b"nb"})
    assert github.calls[1] == ("commit", [], [f"{DIR}/old.ipynb.enc"])


def test_force_grade_regrades_without_committing():
    github = FakeGitHub()
    encrypted = SubmissionCipher(KEY).encrypt(b"nb", "alice")
    processor(github, {PATH: git_blob_sha(encrypted)}).sync_submission(
        "alice", "hw-1", {"work.ipynb": b"nb"}, force_grade=True
    )
    assert [call[0] for call in github.calls] == ["dispatch"]


def test_committed_bytes_are_never_plaintext():
    captured = {}

    class Capture(FakeGitHub):
        def commit_files(self, files, branch, message, delete_paths):
            captured.update({path: content for content, path in files})

    processor(Capture()).sync_submission("alice", "hw-1", {"work.ipynb": b"SECRET-NOTEBOOK"})
    assert captured and all(b"SECRET-NOTEBOOK" not in content for content in captured.values())


def test_blob_sha_matches_git():
    assert git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


class FakeClassroom:
    def __init__(self, title="Homework 1"):
        self.title = title

    def list_course_work(self, course_id):
        return [{"id": "777", "title": self.title}]

    def get_submissions(self, course_id, coursework_id):
        return [
            {"id": "s0", "userId": "0", "state": "CREATED", "assignmentSubmission": {"attachments": [{}]}},
            {"id": "s1", "userId": "1", "state": "TURNED_IN", "assignmentSubmission": {"attachments": [{}]}},
            {"id": "s2", "userId": "2", "state": "TURNED_IN", "assignmentSubmission": {}},
        ]

    def get_student_email(self, course_id, user_id):
        return "alice"

    def download_attachment(self, attachment, directory):
        path = Path(directory) / "work.ipynb"
        path.write_bytes(b"nb")
        return path


def test_only_turned_in_submissions_with_files_are_processed():
    github = FakeGitHub()
    worker = SubmissionProcessor(FakeClassroom(), github, SubmissionCipher(KEY), tree_reader=lambda b, d: {})
    worker.process_course_submissions("c", "777")
    assert github.calls[0] == ("branch", "student-alice/assignment-homework-1")
    assert [call[0] for call in github.calls].count("dispatch") == 1
    assert worker.failures == 0


def test_non_latin_title_falls_back_to_the_coursework_id():
    github = FakeGitHub()
    worker = SubmissionProcessor(FakeClassroom("Домашка"), github, SubmissionCipher(KEY), tree_reader=lambda b, d: {})
    worker.process_course_submissions("c", "777")
    assert github.calls[0] == ("branch", "student-alice/assignment-777")


def test_a_failing_submission_is_counted_and_does_not_stop_the_rest():
    class Broken(FakeGitHub):
        def commit_files(self, *args):
            raise RuntimeError("boom")

    worker = SubmissionProcessor(FakeClassroom(), Broken(), SubmissionCipher(KEY), tree_reader=lambda b, d: {})
    worker.process_course_submissions("c", "777")
    assert worker.failures == 1


@pytest.fixture
def client(monkeypatch):
    """A client with fake Drive transport. Authentication is not involved."""

    class FakeDownloader:
        def __init__(self, buffer, request):
            self.buffer = buffer
            self.request = request

        def next_chunk(self):
            self.buffer.write(self.request)
            return None, True

    monkeypatch.setattr(cc, "MediaIoBaseDownload", FakeDownloader)
    instance = ClassroomClient.__new__(ClassroomClient)
    instance.drive_service = SimpleNamespace(
        files=lambda: SimpleNamespace(get_media=lambda fileId: b"student bytes")
    )
    return instance


@pytest.mark.parametrize("title", [
    "../../../src/encryption.py",
    "..\\..\\src\\encryption.py",
    "/etc/cron.d/evil",
    "a/../../../evil.py",
])
def test_attachment_title_cannot_escape_the_download_directory(client, tmp_path, title):
    download = tmp_path / "a" / "b" / "c"
    download.mkdir(parents=True)
    path = client.download_attachment({"driveFile": {"id": "1", "title": title}}, download)
    assert path.parent == download.resolve()
    assert path.read_bytes() == b"student bytes"
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [path]


def test_oversized_attachment_is_skipped(client, tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "MAX_ATTACHMENT_BYTES", 3)
    assert client.download_attachment({"driveFile": {"id": "1", "title": "big"}}, tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_token_loader_does_not_unpickle(tmp_path):
    """A pickled token file would run code on load, so loading must simply fail."""
    import pickle

    class Boom:
        def __reduce__(self):
            return (Path(tmp_path / "pwned").touch, ())

    token = tmp_path / "token.json"
    token.write_bytes(pickle.dumps(Boom()))
    instance = ClassroomClient.__new__(ClassroomClient)
    instance.token_path, instance.credentials_path = str(token), "missing.json"
    with pytest.raises(Exception):
        instance._authenticate()
    assert not (tmp_path / "pwned").exists()
