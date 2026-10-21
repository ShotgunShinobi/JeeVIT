"""
Lead processing pipeline orchestrator.

Coordinates all stages of lead processing:
  1. Cleaning & validation  (cleaner.py)
  2. Deduplication          (deduplicator.py)
  3. LLM Scoring / Drafting (scorer.py)
  4. Persistence            (database.py)
  5. Notifications          (notifier.py)
  6. Audit & error logging  (database.py)
"""

from __future__ import annotations

import json
from typing import Optional

from .cleaner import clean_lead, email_dedup_key
from .database import Database
from .deduplicator import Deduplicator, ExistingLeadInfo
from .models import (
    BatchResult,
    IncomingLead,
    LeadTag,
    ProcessingResult,
    ProcessingStatus,
)
from .notifier import ConsoleNotifier, Notifier
from .scorer import Scorer, StubScorer


class LeadPipeline:
    """End-to-end pipeline orchestrator for incoming contact form leads."""

    def __init__(
        self,
        db: Database,
        scorer: Optional[Scorer] = None,
        notifier: Optional[Notifier] = None,
        deduplicator: Optional[Deduplicator] = None,
    ) -> None:
        self.db = db
        self.scorer: Scorer = scorer or StubScorer()
        self.notifier: Notifier = notifier or ConsoleNotifier()
        self.deduplicator: Deduplicator = deduplicator or Deduplicator()
        self.sync_deduplicator()

    def sync_deduplicator(self) -> None:
        """Populate deduplicator index from existing leads currently in DB."""
        db_leads = self.db.get_existing_leads()
        lead_infos: list[ExistingLeadInfo] = []
        for r in db_leads:
            raw_email = r.get("email")
            norm_email = raw_email.strip().lower() if raw_email else None
            dedup_email = email_dedup_key(raw_email)
            lead_infos.append(
                ExistingLeadInfo(
                    lead_id=r["lead_id"],
                    email=norm_email,
                    email_dedup=dedup_email,
                    name=r.get("name") or "",
                    company=r.get("company") or "",
                )
            )
        self.deduplicator.load_existing(lead_infos)

    def process_lead(self, raw: IncomingLead) -> ProcessingResult:
        """Process a single incoming lead through all pipeline stages.

        Errors at any stage are caught, logged to the `errors` table,
        and surfaced in the returned ProcessingResult so that one bad lead
        never crashes the entire batch.
        """
        raw_json = raw.model_dump_json()

        # -------------------------------------------------------------------
        # 1. Cleaning & validation
        # -------------------------------------------------------------------
        try:
            cleaned = clean_lead(raw)
        except Exception as exc:
            self.db.log_error(
                source_id=raw.id,
                stage="validation",
                error_type=type(exc).__name__,
                error_detail=str(exc),
                raw_data=raw_json,
            )
            self.db.log_processing(
                source_id=raw.id,
                lead_id=None,
                action="error",
                details=f"Validation failed: {exc}",
            )
            return ProcessingResult(
                source_id=raw.id,
                status=ProcessingStatus.ERROR,
                error=f"Validation failed: {exc}",
            )

        # -------------------------------------------------------------------
        # 2. Duplicate detection
        # -------------------------------------------------------------------
        try:
            dedup_res = self.deduplicator.check(cleaned)
            if dedup_res.is_duplicate and dedup_res.record:
                self.db.log_duplicate(dedup_res.record)
                matched_ref = (
                    dedup_res.record.matched_lead_id
                    or dedup_res.record.matched_source_id
                    or "unknown"
                )
                self.db.log_processing(
                    source_id=raw.id,
                    lead_id=None,
                    action="duplicate",
                    details=dedup_res.record.match_reason,
                )
                return ProcessingResult(
                    source_id=raw.id,
                    status=ProcessingStatus.DUPLICATE,
                    duplicate_of=matched_ref,
                    warnings=cleaned.validation_warnings,
                )
        except Exception as exc:
            self.db.log_error(
                source_id=raw.id,
                stage="dedup",
                error_type=type(exc).__name__,
                error_detail=str(exc),
                raw_data=raw_json,
            )
            return ProcessingResult(
                source_id=raw.id,
                status=ProcessingStatus.ERROR,
                error=f"Deduplication failed: {exc}",
                warnings=cleaned.validation_warnings,
            )

        # -------------------------------------------------------------------
        # 3. LLM Scoring & Reply Drafting
        # -------------------------------------------------------------------
        try:
            lead_id = self.db.generate_lead_id()
            scored = self.scorer.score(cleaned, lead_id)
        except Exception as exc:
            self.db.log_error(
                source_id=raw.id,
                stage="scoring",
                error_type=type(exc).__name__,
                error_detail=str(exc),
                raw_data=raw_json,
            )
            self.db.log_processing(
                source_id=raw.id,
                lead_id=None,
                action="error",
                details=f"Scoring failed: {exc}",
            )
            return ProcessingResult(
                source_id=raw.id,
                status=ProcessingStatus.ERROR,
                error=f"Scoring failed: {exc}",
                warnings=cleaned.validation_warnings,
            )

        # -------------------------------------------------------------------
        # 4. Persistence to SQLite
        # -------------------------------------------------------------------
        try:
            self.db.insert_lead(scored)
        except Exception as exc:
            self.db.log_error(
                source_id=raw.id,
                stage="persistence",
                error_type=type(exc).__name__,
                error_detail=str(exc),
                raw_data=raw_json,
            )
            return ProcessingResult(
                source_id=raw.id,
                status=ProcessingStatus.ERROR,
                error=f"Database insert failed: {exc}",
                warnings=cleaned.validation_warnings,
            )

        # -------------------------------------------------------------------
        # 5. Hot Lead Notification
        # -------------------------------------------------------------------
        if scored.tag == LeadTag.HOT:
            try:
                self.notifier.notify(scored)
            except Exception as exc:
                # Notification failures do not invalidate the lead, but are logged
                self.db.log_error(
                    source_id=raw.id,
                    stage="notification",
                    error_type=type(exc).__name__,
                    error_detail=f"Notification failed: {exc}",
                    raw_data=raw_json,
                )

        # -------------------------------------------------------------------
        # 6. Audit logging
        # -------------------------------------------------------------------
        action_detail = f"Tagged as {scored.tag.value}"
        if cleaned.validation_warnings:
            action_detail += f" with {len(cleaned.validation_warnings)} warning(s)"

        self.db.log_processing(
            source_id=raw.id,
            lead_id=scored.lead_id,
            action="created",
            details=action_detail,
        )

        return ProcessingResult(
            source_id=raw.id,
            status=ProcessingStatus.CREATED,
            lead_id=scored.lead_id,
            warnings=cleaned.validation_warnings,
        )

    def process_batch(self, leads: list[IncomingLead]) -> BatchResult:
        """Process a collection of incoming leads with batch deduplication."""
        self.deduplicator.reset_batch()
        batch_res = BatchResult(total=len(leads))

        for raw_lead in leads:
            res = self.process_lead(raw_lead)
            batch_res.results.append(res)
            if res.status == ProcessingStatus.CREATED:
                batch_res.created += 1
            elif res.status == ProcessingStatus.DUPLICATE:
                batch_res.duplicates += 1
            elif res.status == ProcessingStatus.ERROR:
                batch_res.errors += 1

        return batch_res
