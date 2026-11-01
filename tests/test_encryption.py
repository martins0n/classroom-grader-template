import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT
from src.encryption import (
    MAGIC,
    NONCE_SIZE,
    EncryptionError,
    SubmissionCipher,
    generate_master_key,
    load_master_key,
)

KEY = load_master_key(generate_master_key())


def test_round_trip():
    cipher = SubmissionCipher(KEY)
    assert cipher.decrypt(cipher.encrypt(b"notebook", "alice"), "alice") == b"notebook"


def test_unchanged_submission_gives_identical_bytes():
    cipher = SubmissionCipher(KEY)
    assert cipher.encrypt(b"notebook", "alice") == cipher.encrypt(b"notebook", "alice")


def test_other_student_or_key_cannot_decrypt():
    cipher = SubmissionCipher(KEY)
    payload = cipher.encrypt(b"notebook", "alice")
    with pytest.raises(EncryptionError):
        cipher.decrypt(payload, "bob")
    with pytest.raises(EncryptionError):
        SubmissionCipher(load_master_key(generate_master_key())).decrypt(payload, "alice")


def test_tampering_is_detected():
    cipher = SubmissionCipher(KEY)
    payload = bytearray(cipher.encrypt(b"notebook", "alice"))
    payload[-1] ^= 1
    with pytest.raises(EncryptionError):
        cipher.decrypt(bytes(payload), "alice")


def test_public_nonce_does_not_let_anyone_test_a_guess():
    """The old nonce was an unkeyed hash of id + plaintext, computable from a guessed notebook."""
    payload = SubmissionCipher(KEY).encrypt(b"notebook", "alice")
    nonce = payload[len(MAGIC):len(MAGIC) + NONCE_SIZE]
    assert nonce != hashlib.blake2s(b"alice" + b"notebook", digest_size=NONCE_SIZE).digest()


def test_identical_notebooks_of_two_students_look_unrelated():
    cipher = SubmissionCipher(KEY)
    assert cipher.encrypt(b"same", "alice")[4:] != cipher.encrypt(b"same", "bob")[4:]


@pytest.mark.parametrize("bad", ["", "   ", "not base64!!", "c2hvcnQ="])
def test_bad_keys_fail_closed_without_echoing_the_value(bad):
    with pytest.raises(EncryptionError) as error:
        load_master_key(bad)
    if bad.strip():
        assert bad not in str(error.value)


def test_missing_key_does_not_generate_one(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(EncryptionError):
        load_master_key()


def test_decrypt_script_never_writes_the_key_to_disk(tmp_path):
    """The hole in the previous design: the key stayed in a file next to the student's code."""
    encoded = generate_master_key()
    source = tmp_path / "enc" / "alice" / "hw-1"
    source.mkdir(parents=True)
    payload = SubmissionCipher(load_master_key(encoded)).encrypt(b"plain notebook", "alice")
    (source / "work.ipynb.enc").write_bytes(payload)
    output = tmp_path / "out"

    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "decrypt_submission.py"),
         "--student-id", "alice", "--assignment-id", "hw-1",
         "--input-root", str(tmp_path / "enc"), "--output-dir", str(output)],
        capture_output=True, text=True, cwd=tmp_path,
        env={**os.environ, "ENCRYPTION_KEY": encoded},
    )
    assert done.returncode == 0, done.stderr
    assert (output / "work.ipynb").read_bytes() == b"plain notebook"
    assert encoded not in done.stdout + done.stderr
    raw_key = load_master_key(encoded)
    for path in Path(tmp_path).rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert encoded.encode() not in content and raw_key not in content, path
    assert not (tmp_path / "student_keys").exists()


def test_decrypt_script_refuses_traversal_in_ids(tmp_path):
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "decrypt_submission.py"),
         "--student-id", "../..", "--assignment-id", "hw-1",
         "--input-root", str(tmp_path), "--output-dir", str(tmp_path / "out")],
        capture_output=True, text=True,
        env={**os.environ, "ENCRYPTION_KEY": generate_master_key()},
    )
    assert done.returncode == 1
