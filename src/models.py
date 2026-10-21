"""
Pydantic data models for the lead processing pipeline.

Three stages of a lead:
  IncomingLead  → raw form submission (messy)
  CleanedLead   → after normalization & validation
  ScoredLead    → after LLM tagging & reply drafting
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LeadTag(str, Enum):
    """Lead qualification category assigned by the LLM (or stub)."""
    HOT = "Hot"
    WARM = "Warm"
    COLD = "Cold"


class DuplicateType(str, Enum):
    """How a duplicate was detected."""
    EXACT_EMAIL = "exact_email"
    EMAIL_ALIAS = "email_alias"
    FUZZY = "fuzzy"
    BATCH = "batch"


class ProcessingStatus(str, Enum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Lead models (pipeline stages)
# ---------------------------------------------------------------------------

class IncomingLead(BaseModel):
    """Raw lead exactly as received from the contact form / webhook."""
    id: str
    received_at: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    message: Optional[str] = None


class CleanedLead(BaseModel):
    """Lead after cleaning & normalisation.  Ready for dedup + scoring."""
    id: str
    received_at: datetime
    name: str
    email: Optional[str] = None          # None when missing / invalid
    email_normalized: Optional[str] = None  # lowercase, stripped, for storage
    email_for_dedup: Optional[str] = None   # also strips +alias, for matching
    email_valid: bool = True
    company: str
    message: str
    source: str = "website"
    validation_warnings: list[str] = Field(default_factory=list)


class ScoredLead(BaseModel):
    """Lead after LLM scoring — ready to persist."""
    lead_id: str                           # generated L-XXXX
    name: str
    email: Optional[str] = None
    email_valid: bool = True
    company: str
    source: str = "website"
    tag: LeadTag
    draft_reply: str
    message: str
    llm_reasoning: str
    received_at: datetime
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_id: str                         # original submission ID (S-XX)
    validation_warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

class DuplicateRecord(BaseModel):
    source_id: str
    matched_lead_id: Optional[str] = None
    matched_source_id: Optional[str] = None  # for batch dedup
    match_type: DuplicateType
    match_reason: str
    raw_data: str


class ErrorRecord(BaseModel):
    source_id: str
    stage: str                             # validation | dedup | scoring
    error_type: str
    error_detail: str
    raw_data: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProcessingResult(BaseModel):
    source_id: str
    status: ProcessingStatus
    lead_id: Optional[str] = None
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    duplicate_of: Optional[str] = None


class BatchResult(BaseModel):
    total: int = 0
    created: int = 0
    duplicates: int = 0
    errors: int = 0
    results: list[ProcessingResult] = Field(default_factory=list)
