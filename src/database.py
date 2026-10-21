"""
SQLite database layer for the lead processing pipeline.

Tables:
  leads           — all qualified leads (existing + new)
  duplicates      — every duplicate detection with reason
  errors          — processing failures with context
  processing_log  — audit trail for every action

Also handles:
  • Loading existing_leads.csv into the leads table
  • Generating sequential lead IDs  (L-1013, L-1014, …)
  • Exporting the leads table to CSV
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import (
    DuplicateRecord,
    ErrorRecord,
    LeadTag,
    ScoredLead,
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS leads (
    lead_id       TEXT    PRIMARY KEY,
    name          TEXT    NOT NULL,
    email         TEXT,
    email_valid   INTEGER DEFAULT 1,
    company       TEXT,
    source        TEXT    DEFAULT 'website',
    tag           TEXT    CHECK(tag IN ('Hot','Warm','Cold')),
    draft_reply   TEXT,
    message       TEXT,
    llm_reasoning TEXT,
    created_at    TEXT,
    processed_at  TEXT,
    source_id     TEXT,
    validation_warnings TEXT
);

CREATE TABLE IF NOT EXISTS duplicates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT    NOT NULL,
    matched_lead_id TEXT,
    matched_source_id TEXT,
    match_type      TEXT,
    match_reason    TEXT,
    raw_data        TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS errors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT,
    stage        TEXT,
    error_type   TEXT,
    error_detail TEXT,
    raw_data     TEXT,
    created_at   TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processing_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  TEXT,
    lead_id    TEXT,
    action     TEXT,
    details    TEXT,
    created_at TEXT    DEFAULT (datetime('now'))
);
"""


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------

class Database:
    """Thin wrapper around SQLite with domain-specific helpers."""

    def __init__(self, db_path: str = "leads.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._next_id: Optional[int] = None

    def _init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -------------------------------------------------------------------
    # Lead ID generation
    # -------------------------------------------------------------------

    def _get_next_lead_number(self) -> int:
        """Find the highest existing L-XXXX number and return next."""
        if self._next_id is not None:
            current = self._next_id
            self._next_id += 1
            return current

        row = self.conn.execute(
            "SELECT lead_id FROM leads ORDER BY lead_id DESC LIMIT 1"
        ).fetchone()

        if row and row["lead_id"].startswith("L-"):
            try:
                num = int(row["lead_id"].split("-", 1)[1])
                self._next_id = num + 2  # return num+1 now, cache num+2
                return num + 1
            except ValueError:
                pass

        self._next_id = 1002
        return 1001

    def generate_lead_id(self) -> str:
        num = self._get_next_lead_number()
        return f"L-{num}"

    # -------------------------------------------------------------------
    # Load existing leads from CSV
    # -------------------------------------------------------------------

    def load_existing_csv(self, csv_path: str) -> int:
        """Import existing_leads.csv into the leads table.

        Returns the number of rows imported.
        Skips rows that already exist (by lead_id).
        """
        count = 0
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lead_id = row.get("lead_id", "").strip()
                if not lead_id:
                    continue

                # Check if already loaded
                existing = self.conn.execute(
                    "SELECT 1 FROM leads WHERE lead_id = ?", (lead_id,)
                ).fetchone()
                if existing:
                    continue

                self.conn.execute(
                    """INSERT INTO leads
                       (lead_id, name, email, company, source, tag, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        lead_id,
                        row.get("name", "").strip(),
                        row.get("email", "").strip().lower(),
                        row.get("company", "").strip(),
                        row.get("source", "website").strip(),
                        row.get("tag", "").strip(),
                        row.get("created_at", "").strip(),
                    ),
                )
                count += 1

        self.conn.commit()
        return count

    # -------------------------------------------------------------------
    # Get existing leads (for deduplication)
    # -------------------------------------------------------------------

    def get_existing_leads(self) -> list[dict]:
        """Return all current leads as dicts (for dedup index)."""
        rows = self.conn.execute(
            "SELECT lead_id, name, email, company FROM leads"
        ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------
    # Insert new lead
    # -------------------------------------------------------------------

    def insert_lead(self, lead: ScoredLead) -> str:
        """Insert a scored lead.  Returns the lead_id."""
        self.conn.execute(
            """INSERT INTO leads
               (lead_id, name, email, email_valid, company, source,
                tag, draft_reply, message, llm_reasoning,
                created_at, processed_at, source_id, validation_warnings)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                lead.lead_id,
                lead.name,
                lead.email,
                1 if lead.email_valid else 0,
                lead.company,
                lead.source,
                lead.tag.value,
                lead.draft_reply,
                lead.message,
                lead.llm_reasoning,
                lead.received_at.isoformat(),
                lead.processed_at.isoformat(),
                lead.source_id,
                json.dumps(lead.validation_warnings),
            ),
        )
        self.conn.commit()
        return lead.lead_id

    # -------------------------------------------------------------------
    # Log duplicate
    # -------------------------------------------------------------------

    def log_duplicate(self, record: DuplicateRecord) -> None:
        self.conn.execute(
            """INSERT INTO duplicates
               (source_id, matched_lead_id, matched_source_id,
                match_type, match_reason, raw_data)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                record.source_id,
                record.matched_lead_id,
                record.matched_source_id,
                record.match_type.value,
                record.match_reason,
                record.raw_data,
            ),
        )
        self.conn.commit()

    # -------------------------------------------------------------------
    # Log error
    # -------------------------------------------------------------------

    def log_error(
        self,
        source_id: str,
        stage: str,
        error_type: str,
        error_detail: str,
        raw_data: str,
    ) -> None:
        self.conn.execute(
            """INSERT INTO errors
               (source_id, stage, error_type, error_detail, raw_data)
               VALUES (?, ?, ?, ?, ?)""",
            (source_id, stage, error_type, error_detail, raw_data),
        )
        self.conn.commit()

    # -------------------------------------------------------------------
    # Log processing action
    # -------------------------------------------------------------------

    def log_processing(
        self, source_id: str, lead_id: Optional[str], action: str, details: str = ""
    ) -> None:
        self.conn.execute(
            """INSERT INTO processing_log
               (source_id, lead_id, action, details)
               VALUES (?, ?, ?, ?)""",
            (source_id, lead_id, action, details),
        )
        self.conn.commit()

    # -------------------------------------------------------------------
    # Query helpers (for API endpoints)
    # -------------------------------------------------------------------

    def get_all_leads(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM leads ORDER BY lead_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_duplicates(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM duplicates ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_errors(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM errors ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_processing_log(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM processing_log ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------
    # CSV export
    # -------------------------------------------------------------------

    def export_csv(self, output_path: str) -> str:
        """Export the leads table to a CSV file.

        Returns the absolute path of the exported file.
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        rows = self.conn.execute(
            """SELECT lead_id, name, email, company, source, tag,
                      draft_reply, message, created_at, processed_at,
                      source_id, validation_warnings
               FROM leads ORDER BY lead_id"""
        ).fetchall()

        columns = [
            "lead_id", "name", "email", "company", "source", "tag",
            "draft_reply", "message", "created_at", "processed_at",
            "source_id", "validation_warnings",
        ]

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))

        return os.path.abspath(output_path)
