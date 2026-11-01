"""Downloads submissions from Classroom, encrypts them and starts grading.

Plaintext only ever exists in a temporary directory outside the repository checkout.
No student code runs in this process: it holds the Google token and the master key.
"""
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .encryption import SubmissionCipher
from .github_manager import git_blob_sha, local_tree_blobs
from .naming import make_branch_name, safe_filename, sanitize_assignment_name

logger = logging.getLogger(__name__)

GRADABLE_STATES = ("TURNED_IN", "RETURNED")


class SubmissionProcessor:
    def __init__(self, classroom, github, cipher: SubmissionCipher, tree_reader=local_tree_blobs):
        self.classroom = classroom
        self.github = github
        self.cipher = cipher
        self.tree_reader = tree_reader
        self.failures = 0

    def process_course_submissions(
        self, course_id: str, coursework_id: str, coursework_title: Optional[str] = None
    ) -> None:
        if not coursework_title:
            for work in self.classroom.list_course_work(course_id):
                if work["id"] == coursework_id:
                    coursework_title = work.get("title")
                    break
        assignment = sanitize_assignment_name(coursework_title or "") or coursework_id
        logger.info("Assignment %s -> %s", coursework_title, assignment)

        for submission in self.classroom.get_submissions(course_id, coursework_id):
            try:
                self.process_single_submission(
                    course_id, coursework_id, submission, assignment, coursework_title
                )
            except Exception as exc:
                self.failures += 1
                logger.error("Error processing submission %s: %s", submission.get("id"), exc)

    def process_single_submission(
        self,
        course_id: str,
        coursework_id: str,
        submission: Dict,
        assignment: str,
        title: Optional[str] = None,
    ) -> None:
        if submission.get("state") not in GRADABLE_STATES:
            return
        attachments = submission.get("assignmentSubmission", {}).get("attachments", [])
        if not attachments:
            return

        student_id = self.classroom.get_student_email(course_id, submission["userId"])
        temp_dir = Path(tempfile.mkdtemp(prefix="submission-"))
        try:
            downloaded = [
                path
                for path in (
                    self.classroom.download_attachment(item, temp_dir) for item in attachments
                )
                if path
            ]
            if not downloaded:
                logger.warning("No files downloaded for submission %s", submission.get("id"))
                return
            files = {path.name: path.read_bytes() for path in downloaded}
            self.sync_submission(
                student_id, assignment, files, course_id, coursework_id, title,
                submission.get("state"),
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def sync_submission(
        self,
        student_id: str,
        assignment: str,
        files: Dict[str, bytes],
        course_id: Optional[str] = None,
        coursework_id: Optional[str] = None,
        title: Optional[str] = None,
        state: Optional[str] = None,
        force_grade: bool = False,
    ) -> bool:
        """Bring the student's branch in line with these files. Returns True if grading started."""
        branch = make_branch_name(student_id, assignment)
        directory = f"submissions/{student_id}/{assignment}"

        encrypted = {
            f"{directory}/{safe_filename(name)}.enc": self.cipher.encrypt(content, student_id)
            for name, content in files.items()
        }
        current = self.tree_reader(branch, directory)
        changed = [
            (content, path)
            for path, content in encrypted.items()
            if current.get(path) != git_blob_sha(content)
        ]
        stale = sorted(path for path in current if path.endswith(".enc") and path not in encrypted)

        if not changed and not stale:
            if not force_grade:
                logger.info("No changes for %s", branch)
                return False
        else:
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.github.get_or_create_branch(branch)
            self.github.commit_files(
                changed, branch, f"Submission sync for {assignment} at {timestamp}", stale
            )
            self.github.create_or_update_pull_request(
                branch,
                f"Submission: {student_id} - {title or assignment}",
                self._pull_request_body(
                    student_id, assignment, title, timestamp, state, encrypted,
                    course_id, coursework_id,
                ),
            )
        return self.github.dispatch_grading(branch)

    @staticmethod
    def _pull_request_body(
        student_id, assignment, title, timestamp, state, encrypted, course_id, coursework_id
    ) -> str:
        names = sorted(path.rsplit("/", 1)[-1][: -len(".enc")] for path in encrypted)
        lines = [
            "## Student Submission",
            "",
            f"**Student:** {student_id}",
            f"**Assignment:** {title or assignment}",
            f"**Submitted:** {timestamp}",
            f"**State:** {state or 'UNKNOWN'}",
            "",
            "<!-- METADATA",
            f"course_id: {course_id}",
            f"coursework_id: {coursework_id}",
            f"assignment_name: {assignment}",
            "-->",
            "",
            "### Files",
            *[f"- `{name.replace('`', '')}`" for name in names],
        ]
        return "\n".join(lines) + "\n"
