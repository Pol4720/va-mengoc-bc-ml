"""Optional encryption at rest of curated files (Fernet: AES-128-CBC + HMAC-SHA256).

Disk-level encryption of the analysis workstation is the primary control; this
module adds file-level protection for the curated layer when
``security.encrypt_curated`` is enabled.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
from cryptography.fernet import Fernet

__all__ = ["generate_key", "load_fernet", "read_parquet", "write_parquet"]

ENCRYPTED_SUFFIX = ".parquet.enc"


def generate_key() -> bytes:
    return Fernet.generate_key()


def load_fernet(env_var: str, key_file: str) -> Fernet:
    raw = os.environ.get(env_var)
    if not raw:
        path = Path(key_file).expanduser()
        if not path.is_file():
            msg = f"Encryption enabled but no key: set {env_var} or create {path}"
            raise RuntimeError(msg)
        raw = path.read_text(encoding="utf-8").strip()
    return Fernet(raw.encode("ascii"))


def write_parquet(df: pd.DataFrame, path: Path, fernet: Fernet | None) -> Path:
    """Write a DataFrame as parquet, encrypted when a Fernet key is given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if fernet is None:
        target = path.with_suffix(".parquet")
        df.to_parquet(target, index=False)
        return target
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    target = path.with_name(path.stem + ENCRYPTED_SUFFIX)
    target.write_bytes(fernet.encrypt(buf.getvalue()))
    return target


def read_parquet(path: Path, fernet: Fernet | None) -> pd.DataFrame:
    """Read a (possibly encrypted) parquet file written by :func:`write_parquet`."""
    plain = path.with_suffix(".parquet")
    enc = path.with_name(path.stem + ENCRYPTED_SUFFIX)
    if enc.is_file():
        if fernet is None:
            msg = f"{enc} is encrypted: provide the Fernet key"
            raise RuntimeError(msg)
        return pd.read_parquet(io.BytesIO(fernet.decrypt(enc.read_bytes())))
    return pd.read_parquet(plain)
