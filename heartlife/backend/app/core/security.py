from __future__ import annotations

import hashlib
import hmac
import secrets
from collections import defaultdict
from datetime import datetime, timedelta
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.clock import Clock

_ph = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=2)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash or password_hash == "!":
        return False
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_csrf(expected_hash: str, provided_token: str | None) -> bool:
    if not provided_token or not expected_hash:
        return False
    candidate_hash = hash_token(provided_token)
    return hmac.compare_digest(expected_hash, candidate_hash)


class LoginRateLimiter:
    """In-memory sliding window rate limiter backed by injectable Clock."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 900) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, list[datetime]] = defaultdict(list)

    def _prune(self, key: str, now: datetime) -> list[datetime]:
        cutoff = now - timedelta(seconds=self.window_seconds)
        kept = [ts for ts in self._failures[key] if ts > cutoff]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def check_allowed(self, key: str, clock: Clock) -> bool:
        recent = self._prune(key, clock.now())
        return len(recent) < self.max_attempts

    def record_failure(self, key: str, clock: Clock) -> None:
        now = clock.now()
        self._prune(key, now)
        self._failures[key].append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
