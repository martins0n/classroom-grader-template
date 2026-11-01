#!/usr/bin/env python3
"""Decrypt one student's submission into a directory outside the repository checkout.

The key stays in this process's memory. It is never written to disk, because every later
step of the job shares this machine's file system.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.encryption import EncryptionError, SubmissionCipher, load_master_key
from src.naming import is_valid_assignment, is_valid_student_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--assignment-id", required=True)
    parser.add_argument("--input-root", required=True, help="Directory holding submissions/ data")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    if not is_valid_student_id(args.student_id) or not is_valid_assignment(args.assignment_id):
        print("Invalid student or assignment id", file=sys.stderr)
        return 1

    source = Path(args.input_root) / args.student_id / args.assignment_id
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    files = sorted(source.glob("*.enc")) if source.is_dir() else []
    print(f"Found {len(files)} encrypted file(s)")

    try:
        cipher = SubmissionCipher(load_master_key())
        for encrypted in files:
            cipher.decrypt_file(encrypted, output / encrypted.name[: -len(".enc")], args.student_id)
    except EncryptionError as exc:
        print(f"Decryption failed: {exc}", file=sys.stderr)
        return 1
    print("Decrypted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
