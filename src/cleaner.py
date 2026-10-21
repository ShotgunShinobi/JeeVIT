"""
Data cleaning and validation for incoming leads.

Handles:
  - Email normalisation  (strip, lowercase, validate format)
  - Email dedup key       (also strips + aliases)
  - Name normalisation    (smart title-case, collapse whitespace)
  - Timestamp parsing
  - Missing / empty field detection
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .models import CleanedLead, IncomingLead

# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

# Simple but solid regex — covers 99 % of real-world addresses.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)


def normalize_email(raw: Optional[str]) -> tuple[Optional[str], bool]:
    """Return (normalised_email | None, is_valid).

    • Strips whitespace
    • Lowercases
    • Validates against a practical regex
    """
    if raw is None:
        return None, False

    email = raw.strip().lower()
    if not email:
        return None, False

    if _EMAIL_RE.match(email):
        return email, True

    # Invalid but we still store whatever we got, for human review.
    return email, False


def email_dedup_key(email: Optional[str]) -> Optional[str]:
    """Produce a canonical key for duplicate matching.

    • Strips  +alias  part   (tom+auto@x.com → tom@x.com)
    • Lowercases, strips whitespace (already done, but defensive)
    """
    if email is None:
        return None

    email = email.strip().lower()
    if not email:
        return None

    # Strip +alias
    local, sep, domain = email.partition("@")
    if not sep:
        return email  # malformed, just return as-is
    local = local.split("+", 1)[0]
    return f"{local}@{domain}"


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------

# Particles that stay lowercase unless they start the name.
_LOWERCASE_PARTICLES = {"de", "van", "von", "di", "da", "le", "la", "du"}


def normalize_name(raw: Optional[str]) -> str:
    """Smart title-case that handles:

    • Excess whitespace        ("  JAMES   o'CONNOR "  → "James O'Connor")
    • Apostrophe names         (o'connor → O'Connor)
    • Hyphenated names         (jean-paul → Jean-Paul)
    • Unicode characters       (Zoë Müller stays Zoë Müller)
    """
    if not raw or not raw.strip():
        return "Unknown"

    parts = raw.strip().split()          # collapse any whitespace
    result: list[str] = []

    for i, part in enumerate(parts):
        # Handle apostrophe names (O'Connor, D'Souza)
        if "'" in part:
            sub_parts = part.split("'")
            titled = "'".join(_title_word(sp) for sp in sub_parts)
            result.append(titled)
        # Handle hyphenated names (Jean-Paul)
        elif "-" in part:
            sub_parts = part.split("-")
            titled = "-".join(_title_word(sp) for sp in sub_parts)
            result.append(titled)
        else:
            word = part.lower()
            # Lowercase particles (de, van) stay lowercase unless first word.
            if word in _LOWERCASE_PARTICLES and i > 0:
                result.append(word)
            else:
                result.append(_title_word(part))

    return " ".join(result)


def _title_word(word: str) -> str:
    """Title-case a single word fragment."""
    if not word:
        return word
    return word[0].upper() + word[1:].lower()


# ---------------------------------------------------------------------------
# Company helpers
# ---------------------------------------------------------------------------

def normalize_company(raw: Optional[str]) -> str:
    """Basic company-name cleanup.  Preserves original casing."""
    if not raw or not raw.strip():
        return "Unknown"
    return raw.strip()


def company_dedup_key(company: str) -> str:
    """Canonical form for duplicate matching.

    "Fern & Fox"  and  "Fern and Fox"  should match.
    """
    key = company.lower().strip()
    key = key.replace("&", "and")
    key = re.sub(r"\s+", " ", key)
    return key


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

_TIMESTAMP_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
]


def parse_timestamp(raw: Optional[str]) -> datetime:
    """Try common formats; fall back to now()."""
    if not raw or not raw.strip():
        return datetime.now(timezone.utc)

    value = raw.strip()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    # Last resort
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Main cleaner
# ---------------------------------------------------------------------------

def clean_lead(raw: IncomingLead) -> CleanedLead:
    """Full cleaning pipeline for a single incoming lead.

    Never raises — problems are captured as validation_warnings.
    """
    warnings: list[str] = []

    # --- Name ---
    name = normalize_name(raw.name)
    if name == "Unknown":
        warnings.append("Name is missing or empty")

    # --- Email ---
    email_norm, email_valid = normalize_email(raw.email)
    email_dedup = email_dedup_key(raw.email)

    if raw.email is None:
        warnings.append("Email field is missing from submission")
    elif not raw.email.strip():
        warnings.append("Email is empty")
    elif not email_valid:
        warnings.append(f"Email format appears invalid: {raw.email.strip()}")

    # --- Company ---
    company = normalize_company(raw.company)
    if company == "Unknown":
        warnings.append("Company is missing or empty")

    # --- Message ---
    message = (raw.message or "").strip()
    if not message:
        warnings.append("Message is empty")

    # --- Timestamp ---
    received_at = parse_timestamp(raw.received_at)

    return CleanedLead(
        id=raw.id,
        received_at=received_at,
        name=name,
        email=email_norm,
        email_normalized=email_norm,
        email_for_dedup=email_dedup,
        email_valid=email_valid,
        company=company,
        message=message,
        source="website",
        validation_warnings=warnings,
    )
