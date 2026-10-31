"""Email normalization and hashing. This is the public lookup rule (design doc, section 5).

Every application that wants an avatar must apply exactly the same steps:
trim whitespace, lowercase, then SHA-256 as lowercase hex.
"""
import hashlib


def normalize_email(email):
    return (email or "").strip().lower()


def hash_email(email):
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()
