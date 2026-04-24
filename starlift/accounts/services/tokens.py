"""One-shot tokens for invites and email verification.

Design:
- `make_token()` returns a raw URL-safe string (delivered via email).
- `hash_token()` computes SHA-256 of the raw token; only the hash is stored.
- `verify_token()` compares hashes in constant time.

We intentionally do NOT use `signing.TimestampSigner` here — we want
server-side revocation (via a DB row with `used_at`/`revoked_at`), which
signed tokens alone cannot express.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 48  # 64 chars URL-safe


def make_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw: str) -> str:
    if not isinstance(raw, str):
        raise TypeError("raw token must be str")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_token(raw: str, expected_hash: str) -> bool:
    if not raw or not expected_hash:
        return False
    return hmac.compare_digest(hash_token(raw), expected_hash)
