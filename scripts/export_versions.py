#!/usr/bin/env python3
"""Decrypt every stored version of submissions onto the teacher's machine.

Each sync is a commit on the student's branch, so the branch history holds every version.
Run this from a clone of the course repository. It reads keys from ENCRYPTION_KEY and from
the copies setup_course.py saved. Nothing is executed. The output is untrusted student code.
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.encryption import EncryptionError, SubmissionCipher, load_master_key
from src.key_copy import load_key_copies, refuse_in_ci
from src.naming import is_valid_assignment, is_valid_student_id, parse_branch, safe_filename

REMOTE_PREFIX = "refs/remotes/origin/"


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def course_repo() -> Optional[str]:
    url = git("remote", "get-url", "origin").decode().strip()
    match = re.search(r"[:/]([^/:]+/[^/:]+?)(?:\.git)?/?$", url)
    return match.group(1) if match else None


def available_ciphers() -> List[SubmissionCipher]:
    keys = load_key_copies(course_repo() or "")
    if os.environ.get("ENCRYPTION_KEY"):
        keys.insert(0, load_master_key())
    return [SubmissionCipher(key) for key in keys]


def student_branches(student: Optional[str], assignment: Optional[str]) -> List[Tuple[str, str, str]]:
    # A pattern's * stops at a slash and branch names contain one, so filter here instead.
    listing = git("for-each-ref", "--format=%(refname)", REMOTE_PREFIX.rstrip("/")).decode()
    found = []
    for ref in listing.split():
        try:
            branch_student, branch_assignment = parse_branch(ref[len(REMOTE_PREFIX):])
        except ValueError:
            continue
        if student in (None, branch_student) and assignment in (None, branch_assignment):
            found.append((ref, branch_student, branch_assignment))
    return found


def stored_files(commit: str, directory: str) -> Dict[str, str]:
    files = {}
    for entry in git("ls-tree", "-r", "-z", commit, "--", directory).split(b"\0"):
        if entry:
            meta, path = entry.split(b"\t", 1)
            if path.endswith(b".enc"):
                files[os.fsdecode(path)] = meta.split()[2].decode()
    return files


def versions(ref: str, directory: str) -> Iterator[Tuple[str, str, Dict[str, str]]]:
    """Yield (commit, date, files) for each commit that changed the stored files."""
    log = git("log", "--reverse", "--format=%H %cI", ref, "--", directory).decode()
    previous: Dict[str, str] = {}
    for line in log.splitlines():
        commit, date = line.split(" ", 1)
        files = stored_files(commit, directory)
        if files and files != previous:
            yield commit, date, files
        previous = files


def decrypt_blob(blob: str, student: str, ciphers: List[SubmissionCipher]) -> Optional[bytes]:
    payload = git("cat-file", "blob", blob)
    for cipher in ciphers:
        try:
            return cipher.decrypt(payload, student)
        except EncryptionError:
            continue
    return None


def export_branch(ref: str, student: str, assignment: str, output: Path, ciphers) -> Tuple[int, int]:
    """Returns (versions found, versions at least partly decrypted)."""
    print(f"{student} / {assignment}")
    found = readable = 0
    for found, (commit, date, files) in enumerate(versions(ref, f"submissions/{student}/{assignment}/"), 1):
        synced = datetime.fromisoformat(date).astimezone(timezone.utc).strftime("%Y%m%d-%H%M")
        folder = output / student / assignment / f"v{found:02d}-{synced}-{commit[:7]}"
        written = 0
        for path, blob in files.items():
            plaintext = decrypt_blob(blob, student, ciphers)
            if plaintext is not None:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / safe_filename(os.path.basename(path)[: -len(".enc")])).write_bytes(plaintext)
                written += 1
        readable += 1 if written else 0
        status = f"{written} of {len(files)} file(s)" if written else "no available key opens it"
        print(f"  v{found:02d} {synced} {commit[:7]}: {status}")
    return found, readable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", required=True, help="Must be outside this repository")
    parser.add_argument("--student", help="Student id, e.g. a_b_at_gmail_com. Default: everyone")
    parser.add_argument("--assignment", help="Assignment name, e.g. homework-1. Default: all")
    args = parser.parse_args()

    refuse_in_ci()
    os.umask(0o077)
    if args.student and not is_valid_student_id(args.student):
        print("Invalid student id", file=sys.stderr)
        return 1
    if args.assignment and not is_valid_assignment(args.assignment):
        print("Invalid assignment name", file=sys.stderr)
        return 1

    try:
        root = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
        output = Path(args.output_dir).expanduser().resolve()
        # The repository is public: plaintext inside the checkout is one "git add" from leaking.
        if output == root or root in output.parents:
            print("--output-dir must be outside this repository", file=sys.stderr)
            return 1
        ciphers = available_ciphers()
        if not ciphers:
            print("No key found. See 'Reading stored versions' in README.md.", file=sys.stderr)
            return 1
        git("fetch", "--quiet", "origin", f"+refs/heads/student-*:{REMOTE_PREFIX}student-*")
        branches = student_branches(args.student, args.assignment)
        if not branches:
            print("No matching student branches", file=sys.stderr)
            return 1
        totals = [export_branch(*branch, output, ciphers) for branch in branches]
    except EncryptionError as exc:
        print(f"Key problem: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"git {exc.cmd[1]} failed: {exc.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        return 1

    found, readable = sum(item[0] for item in totals), sum(item[1] for item in totals)
    print(f"\n{readable} of {found} version(s) decrypted into {output}")
    if readable < found:
        print("The others were encrypted with a key that is not available here.")
    print("This is untrusted student code. Do not run it on this machine.")
    return 0 if readable else 1


if __name__ == "__main__":
    sys.exit(main())
