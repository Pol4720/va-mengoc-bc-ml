"""Keyed pseudonymisation (HMAC-SHA256) of direct identifiers.

Direct identifiers (name, address) are used only in memory to derive a
pseudonymous person key and are then discarded. The key is secret and lives
outside the repository, so pseudonyms cannot be reversed or recomputed by a
reader of the curated data (ENISA, *Pseudonymisation techniques and best
practices*, 2019 — keyed hash with secret key).

For synthetic data a fixed, public test key is used so that CI runs are
reproducible; the pipeline refuses to use that key on real data.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from pathlib import Path

from vamengoc.parsing.text import normalize_text

__all__ = [
    "SYNTHETIC_TEST_KEY",
    "PseudonymKeyError",
    "Pseudonymizer",
    "load_key",
]

# Public, documented key used ONLY for synthetic data (never for real records).
SYNTHETIC_TEST_KEY = hashlib.sha256(b"vamengoc-synthetic-data-public-test-key").digest()
_MIN_KEY_BYTES = 32


class PseudonymKeyError(RuntimeError):
    """Raised when no acceptable pseudonymisation key is available."""


def _decode_key(text: str) -> bytes:
    t = text.strip()
    for decoder in (bytes.fromhex, base64.b64decode):
        try:
            key = decoder(t)
        except (ValueError, binascii.Error):
            continue
        if len(key) >= _MIN_KEY_BYTES:
            return key
    msg = f"Pseudonymisation key must decode (hex or base64) to >= {_MIN_KEY_BYTES} bytes"
    raise PseudonymKeyError(msg)


def load_key(env_var: str, key_file: str, *, synthetic: bool) -> bytes:
    """Resolve the HMAC key: environment variable, then key file.

    Synthetic runs fall back to :data:`SYNTHETIC_TEST_KEY`; real runs fail
    without a key, and also fail if someone configured the public test key.
    """
    raw = os.environ.get(env_var)
    if raw:
        key = _decode_key(raw)
    else:
        path = Path(key_file).expanduser()
        if path.is_file():
            key = _decode_key(path.read_text(encoding="utf-8"))
        elif synthetic:
            return SYNTHETIC_TEST_KEY
        else:
            msg = (
                f"No pseudonymisation key found. Set {env_var} or create {path} "
                "(e.g. `vamengoc keygen`). Real data are never processed without a secret key."
            )
            raise PseudonymKeyError(msg)
    if not synthetic and hmac.compare_digest(key, SYNTHETIC_TEST_KEY):
        msg = "The public synthetic test key must not be used on real data."
        raise PseudonymKeyError(msg)
    return key


class Pseudonymizer:
    """Derive stable, non-reversible identifiers from identifying fields."""

    def __init__(self, key: bytes, *, length: int = 20) -> None:
        if len(key) < _MIN_KEY_BYTES:
            msg = "HMAC key too short"
            raise PseudonymKeyError(msg)
        self._key = key
        self._length = length

    def token(self, namespace: str, *parts: object) -> str:
        """HMAC-SHA256 over normalised parts, hex-truncated (80 bits by default)."""
        msg = "\x1f".join([namespace, *(normalize_text(p) for p in parts)]).encode("utf-8")
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()[: self._length]

    def person_id(self, full_name: object, birth_date: object, sex: object) -> str:
        """Pseudonymous person key from name + birth date + sex (normalised)."""
        return "P" + self.token("person", full_name, birth_date, sex)

    def record_id(self, source_sha256: str, row_number: int) -> str:
        """Stable record key tied to the immutable source file and row."""
        return "R" + self.token("record", source_sha256, row_number)

    def generic(self, namespace: str, value: object) -> str:
        """Pseudonym for quasi-identifiers kept for linkage (e.g. clinic code)."""
        return namespace[:1].upper() + self.token(namespace, value)[:12]
