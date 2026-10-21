"""
FastAPI application for JeeVIT Lead Automation.

Provides webhook endpoints to receive leads in real time, batch process submissions,
and inspect leads, duplicates, and errors.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse

from .database import Database
from .models import BatchResult, IncomingLead, ProcessingResult
from .notifier import create_notifier
from .pipeline import LeadPipeline
from .scorer import StubScorer

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "leads.db"))
EXISTING_CSV = str(BASE_DIR / "existing_leads.csv")
INCOMING_JSON = str(BASE_DIR / "incoming_leads.json")
OUTPUT_CSV = str(BASE_DIR / "output" / "final_leads.csv")

db = Database(DB_PATH)
notifier = create_notifier(os.getenv("NOTIFIER", "console"))
scorer = StubScorer()
pipeline = LeadPipeline(db=db, scorer=scorer, notifier=notifier)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure existing leads are loaded if present
    if os.path.exists(EXISTING_CSV):
        imported = db.load_existing_csv(EXISTING_CSV)
        if imported > 0:
            pipeline.sync_deduplicator()
    yield
    db.close()


app = FastAPI(
    title="JeeVIT Lead Intake & Qualification API",
    description=(
        "Automated webhook pipeline for cleaning, deduplicating, scoring, "
        "and drafting initial responses for website leads."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", tags=["Health"])
async def root() -> dict[str, Any]:
    """Health check and summary counters."""
    leads = db.get_all_leads()
    duplicates = db.get_all_duplicates()
    errors = db.get_all_errors()
    return {
        "status": "online",
        "service": "JeeVIT Lead Automation",
        "counts": {
            "total_leads_in_store": len(leads),
            "duplicates_detected": len(duplicates),
            "errors_logged": len(errors),
        },
    }


@app.post("/webhook/lead", response_model=ProcessingResult, tags=["Webhook"])
async def receive_webhook_lead(lead: IncomingLead) -> ProcessingResult:
    """Webhook endpoint receiving a single lead submission from the website contact form."""
    return pipeline.process_lead(lead)


@app.post("/batch", response_model=BatchResult, tags=["Batch"])
async def process_batch_leads(
    custom_leads: Optional[list[IncomingLead]] = None,
) -> BatchResult:
    """Process a batch of leads. If none provided in body, loads incoming_leads.json."""
    if custom_leads:
        leads_to_process = custom_leads
    else:
        if not os.path.exists(INCOMING_JSON):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sample file {INCOMING_JSON} not found.",
            )
        with open(INCOMING_JSON, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            leads_to_process = [IncomingLead(**item) for item in raw_data]

    result = pipeline.process_batch(leads_to_process)
    db.export_csv(OUTPUT_CSV)
    return result


@app.get("/leads", tags=["Inspection"])
async def list_leads(tag: Optional[str] = Query(None, description="Filter by Hot, Warm, Cold")):
    """List all leads stored in the system, optionally filtered by tag."""
    all_leads = db.get_all_leads()
    if tag:
        all_leads = [l for l in all_leads if l.get("tag", "").lower() == tag.lower()]
    return all_leads


@app.get("/duplicates", tags=["Inspection"])
async def list_duplicates():
    """List all detected duplicates with match type and reasoning."""
    return db.get_all_duplicates()


@app.get("/errors", tags=["Inspection"])
async def list_errors():
    """List all logged errors across validation, dedup, and scoring stages."""
    return db.get_all_errors()


@app.get("/audit-log", tags=["Inspection"])
async def list_audit_log():
    """Audit log of all actions taken by the pipeline."""
    return db.get_processing_log()


@app.get("/export", tags=["Export"])
async def download_csv():
    """Export and download the final combined leads sheet as a CSV file."""
    csv_file = db.export_csv(OUTPUT_CSV)
    return FileResponse(
        path=csv_file,
        media_type="text/csv",
        filename="final_leads.csv",
    )
