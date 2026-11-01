#!/usr/bin/env python3
"""Send a sample notebook through the real pipeline, with no Google involved.

Commits the encrypted sample to a test branch, opens a pull request and starts grading,
using the same token and key a real submission would. Marks and grade CSVs ignore this student.
"""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.encryption import SubmissionCipher, load_master_key
from src.github_manager import GitHubManager
from src.naming import SELFTEST_ASSIGNMENT, SELFTEST_STUDENT
from src.submission_processor import SubmissionProcessor

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    sample = Path("test_cases") / SELFTEST_ASSIGNMENT / "solution.ipynb"
    github = GitHubManager(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    processor = SubmissionProcessor(None, github, SubmissionCipher(load_master_key()))
    started = processor.sync_submission(
        SELFTEST_STUDENT,
        SELFTEST_ASSIGNMENT,
        {"solution.ipynb": sample.read_bytes()},
        title="Pipeline self-test",
        state="SELFTEST",
        force_grade=True,
    )
    print("Grading started" if started else "Could not start grading")
    return 0 if started else 1


if __name__ == "__main__":
    sys.exit(main())
