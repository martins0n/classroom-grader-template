"""Encryption of student submissions stored in the public repository.

There is one master key per course. It exists only as the ENCRYPTION_KEY GitHub secret
and is never written to disk. Each student gets keys derived from it with HKDF.

Encryption is deterministic so an unchanged submission produces an identical file and
no new commit. The nonce is an HMAC of the plaintext under a secret key. An unkeyed hash
would let anyone with the public ciphertext test whether it matches a notebook they hold.
"""
import base64
import binascii
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_ENV_VAR = "ENCRYPTION_KEY"
MASTER_KEY_SIZE = 32
MAGIC = b"HWG3"
NONCE_SIZE = 12


class EncryptionError(Exception):
    """Raised for a missing or invalid key and for files that fail to decrypt."""


def generate_master_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(MASTER_KEY_SIZE)).decode("ascii")


def load_master_key(value: str = None) -> bytes:
    """Decode the master key from an argument or the environment.

    Fails closed. Generating a key on the fly would encrypt submissions with a key
    nobody has. Error messages never include the value.
    """
    raw = value if value is not None else os.environ.get(KEY_ENV_VAR, "")
    raw = raw.strip()
    if not raw:
        raise EncryptionError(f"{KEY_ENV_VAR} is not set")
    try:
        key = base64.b64decode(raw, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise EncryptionError(f"{KEY_ENV_VAR} is not valid base64") from None
    if len(key) != MASTER_KEY_SIZE:
        raise EncryptionError(f"{KEY_ENV_VAR} must decode to {MASTER_KEY_SIZE} bytes")
    return key


class SubmissionCipher:
    def __init__(self, master_key: bytes):
        if len(master_key) != MASTER_KEY_SIZE:
            raise EncryptionError("invalid master key size")
        self._master_key = master_key

    def _derive(self, purpose: str, student_id: str) -> bytes:
        info = f"hw-grader/v3/{purpose}/{student_id}".encode("utf-8")
        return HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=info
        ).derive(self._master_key)

    @staticmethod
    def _associated_data(student_id: str) -> bytes:
        return f"hw-grader:{student_id}".encode("utf-8")

    def encrypt(self, plaintext: bytes, student_id: str) -> bytes:
        nonce_key = self._derive("nonce", student_id)
        nonce = hmac.new(nonce_key, plaintext, hashlib.sha256).digest()[:NONCE_SIZE]
        aead = AESGCM(self._derive("enc", student_id))
        ciphertext = aead.encrypt(nonce, plaintext, self._associated_data(student_id))
        return MAGIC + nonce + ciphertext

    def decrypt(self, payload: bytes, student_id: str) -> bytes:
        header = len(MAGIC) + NONCE_SIZE
        if not payload.startswith(MAGIC) or len(payload) <= header:
            raise EncryptionError("unsupported or truncated ciphertext")
        nonce = payload[len(MAGIC):header]
        aead = AESGCM(self._derive("enc", student_id))
        try:
            return aead.decrypt(
                nonce, payload[header:], self._associated_data(student_id)
            )
        except InvalidTag:
            raise EncryptionError("decryption failed: wrong key or student") from None

    def decrypt_file(self, source: Path, destination: Path, student_id: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.decrypt(source.read_bytes(), student_id))
