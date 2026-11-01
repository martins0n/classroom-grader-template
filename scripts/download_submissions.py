#!/usr/bin/env python3
"""Sync submissions from Google Classroom into the repository. Runs in GitHub Actions."""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.classroom_client import ClassroomClient
from src.encryption import SubmissionCipher, load_master_key
from src.github_manager import GitHubManager
from src.submission_processor import SubmissionProcessor

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("download")


def build_processor() -> SubmissionProcessor:
    # Check the key first: failing here is better than downloading everything and then failing.
    cipher = SubmissionCipher(load_master_key())
    github = GitHubManager(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    return SubmissionProcessor(ClassroomClient(), github, cipher)


def main() -> int:
    processor = build_processor()
    course_id = os.getenv("COURSE_ID", "").strip()
    coursework_id = os.getenv("COURSEWORK_ID", "").strip()

    if course_id and coursework_id:
        processor.process_course_submissions(course_id, coursework_id)
    else:
        course_ids = [c.strip() for c in os.getenv("COURSE_IDS", "").split(",") if c.strip()]
        if not course_ids:
            logger.error("COURSE_IDS is not set. Run scripts/setup_course.py.")
            return 1
        for cid in course_ids:
            for work in processor.classroom.list_course_work(cid):
                if work.get("state") == "PUBLISHED":
                    processor.process_course_submissions(cid, work["id"], work.get("title"))

    if processor.failures:
        logger.error("%d submission(s) failed to sync", processor.failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
