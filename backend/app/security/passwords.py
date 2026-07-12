"""Argon2id password policy, hashing and verification helpers."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error


PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PASSWORD_ALGORITHM = "argon2id"
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)

# Used to equalize verification work when an account does not exist. It is not a
# credential and is intentionally created with the same current Argon2 policy.
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("argon2-timing-equalizer-not-a-real-password")


def validate_password_policy(password: str) -> list[str]:
    errors: list[str] = []
    length = len(password or "")
    if length < PASSWORD_MIN_LENGTH:
        errors.append("password_too_short")
    if length > PASSWORD_MAX_LENGTH:
        errors.append("password_too_long")
    return errors


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password_required")
    policy_errors = validate_password_policy(password)
    if policy_errors:
        raise ValueError(policy_errors[0])
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except Argon2Error:
        return False
    except Exception:
        return False


def password_hash_needs_rehash(password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return PASSWORD_HASHER.check_needs_rehash(password_hash)
    except Exception:
        return False
