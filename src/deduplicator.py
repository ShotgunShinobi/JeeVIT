"""
Duplicate detection for incoming leads.

Three-layer strategy:
  1. Exact email match against existing leads (after normalisation)
  2. Email-alias match  (tom+x@acme.com  →  tom@acme.com  in existing)
  3. Within-batch dedup  (same email or same name + similar company)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .cleaner import company_dedup_key, email_dedup_key
from .models import CleanedLead, DuplicateRecord, DuplicateType


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DedupResult:
    is_duplicate: bool = False
    record: Optional[DuplicateRecord] = None


# ---------------------------------------------------------------------------
# Existing-lead index (built from the CSV / DB)
# ---------------------------------------------------------------------------

@dataclass
class ExistingLeadInfo:
    """Minimal info we need from existing leads for dedup matching."""
    lead_id: str
    email: Optional[str] = None
    email_dedup: Optional[str] = None
    name: str = ""
    company: str = ""
    company_key: str = ""


# ---------------------------------------------------------------------------
# Deduplicator
# ---------------------------------------------------------------------------

class Deduplicator:
    """Stateful deduplicator — tracks both existing leads and the current batch."""

    def __init__(self) -> None:
        # Index existing leads by normalised email and dedup-key email.
        self._email_index: dict[str, str] = {}       # email → lead_id
        self._dedup_email_index: dict[str, str] = {}  # dedup_key → lead_id
        self._company_index: dict[str, list[ExistingLeadInfo]] = {}

        # Within-batch tracking.
        self._batch_emails: dict[str, str] = {}       # email → first source_id
        self._batch_dedup_emails: dict[str, str] = {}  # dedup_key → first source_id

    # -----------------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------------

    def load_existing(self, leads: list[ExistingLeadInfo]) -> None:
        """Build lookup indices from existing leads (loaded from CSV / DB)."""
        for lead in leads:
            if lead.email:
                email_lower = lead.email.strip().lower()
                self._email_index[email_lower] = lead.lead_id
            if lead.email_dedup:
                self._dedup_email_index[lead.email_dedup] = lead.lead_id

            ckey = company_dedup_key(lead.company)
            self._company_index.setdefault(ckey, []).append(lead)

    def reset_batch(self) -> None:
        """Clear batch-level tracking (call before each new batch)."""
        self._batch_emails.clear()
        self._batch_dedup_emails.clear()

    # -----------------------------------------------------------------------
    # Main check
    # -----------------------------------------------------------------------

    def check(self, lead: CleanedLead) -> DedupResult:
        """Check a cleaned lead for duplicates across all three layers.

        Returns DedupResult with is_duplicate=True and a DuplicateRecord
        if a match is found.  Otherwise is_duplicate=False.
        """
        raw_json = lead.model_dump_json()

        # --- Layer 1: exact email match against existing leads ---
        if lead.email_normalized and lead.email_normalized in self._email_index:
            matched_id = self._email_index[lead.email_normalized]
            return DedupResult(
                is_duplicate=True,
                record=DuplicateRecord(
                    source_id=lead.id,
                    matched_lead_id=matched_id,
                    match_type=DuplicateType.EXACT_EMAIL,
                    match_reason=(
                        f"Email '{lead.email_normalized}' matches existing "
                        f"lead {matched_id}"
                    ),
                    raw_data=raw_json,
                ),
            )

        # --- Layer 2: email-alias match against existing leads ---
        if lead.email_for_dedup and lead.email_for_dedup in self._dedup_email_index:
            matched_id = self._dedup_email_index[lead.email_for_dedup]
            # Make sure it's not just the same exact email already caught above
            if lead.email_normalized != lead.email_for_dedup or matched_id not in self._email_index.values():
                return DedupResult(
                    is_duplicate=True,
                    record=DuplicateRecord(
                        source_id=lead.id,
                        matched_lead_id=matched_id,
                        match_type=DuplicateType.EMAIL_ALIAS,
                        match_reason=(
                            f"Email '{lead.email_normalized}' is an alias of "
                            f"'{lead.email_for_dedup}' which matches existing "
                            f"lead {matched_id}"
                        ),
                        raw_data=raw_json,
                    ),
                )

        # --- Layer 3: within-batch dedup (same email) ---
        if lead.email_normalized and lead.email_normalized in self._batch_emails:
            first_id = self._batch_emails[lead.email_normalized]
            return DedupResult(
                is_duplicate=True,
                record=DuplicateRecord(
                    source_id=lead.id,
                    matched_source_id=first_id,
                    match_type=DuplicateType.BATCH,
                    match_reason=(
                        f"Email '{lead.email_normalized}' already seen in "
                        f"this batch (first: {first_id})"
                    ),
                    raw_data=raw_json,
                ),
            )

        # Also check batch dedup key
        if lead.email_for_dedup and lead.email_for_dedup in self._batch_dedup_emails:
            first_id = self._batch_dedup_emails[lead.email_for_dedup]
            return DedupResult(
                is_duplicate=True,
                record=DuplicateRecord(
                    source_id=lead.id,
                    matched_source_id=first_id,
                    match_type=DuplicateType.BATCH,
                    match_reason=(
                        f"Email alias '{lead.email_for_dedup}' already seen "
                        f"in this batch (first: {first_id})"
                    ),
                    raw_data=raw_json,
                ),
            )

        # --- No duplicate found — register in batch index ---
        if lead.email_normalized:
            self._batch_emails[lead.email_normalized] = lead.id
        if lead.email_for_dedup:
            self._batch_dedup_emails[lead.email_for_dedup] = lead.id

        return DedupResult(is_duplicate=False)
