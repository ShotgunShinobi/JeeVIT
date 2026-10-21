"""
CLI runner for the JeeVIT Lead Automation Pipeline.

Usage:
    python run.py [--db-path DB_PATH] [--reset]

Loads existing_leads.csv, processes incoming_leads.json,
prints an executive summary, and exports output/final_leads.csv.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure UTF-8 output encoding on Windows terminals
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from src.database import Database
from src.models import IncomingLead, ProcessingStatus
from src.notifier import ConsoleNotifier
from src.pipeline import LeadPipeline
from src.scorer import StubScorer


def run_pipeline(db_path: str = "leads.db", reset_db: bool = False) -> None:
    print("=" * 72)
    print("  JeeVIT Lead Intake & Qualification Automation Pipeline")
    print("=" * 72)

    if reset_db and os.path.exists(db_path):
        os.remove(db_path)
        print(f"[RESET] Cleaned existing database '{db_path}' for a fresh run.")

    db = Database(db_path)
    scorer = StubScorer()
    notifier = ConsoleNotifier()
    pipeline = LeadPipeline(db=db, scorer=scorer, notifier=notifier)

    # 1. Load existing leads
    existing_csv = ROOT_DIR / "existing_leads.csv"
    if not existing_csv.exists():
        print(f"[ERROR] {existing_csv} not found!")
        sys.exit(1)

    imported_existing = db.load_existing_csv(str(existing_csv))
    print(f"[INIT] Loaded {imported_existing} baseline leads from {existing_csv.name}")
    pipeline.sync_deduplicator()

    # 2. Load incoming leads
    incoming_json = ROOT_DIR / "incoming_leads.json"
    if not incoming_json.exists():
        print(f"[ERROR] {incoming_json} not found!")
        sys.exit(1)

    with open(incoming_json, "r", encoding="utf-8") as f:
        raw_items = json.load(f)
    incoming_leads = [IncomingLead(**item) for item in raw_items]
    print(f"[QUEUE] Found {len(incoming_leads)} incoming lead submissions in {incoming_json.name}\n")

    print("-" * 72)
    print("  Processing Incoming Leads (cleaning, deduplicating, scoring)...")
    print("-" * 72)

    batch_result = pipeline.process_batch(incoming_leads)

    # 3. Export to CSV
    output_dir = ROOT_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_csv = output_dir / "final_leads.csv"
    exported_path = db.export_csv(str(final_csv))

    # 4. Print Summary
    print("\n" + "=" * 72)
    print("  BATCH EXECUTION SUMMARY")
    print("=" * 72)
    print(f"  * Total Incoming Leads:  {batch_result.total}")
    print(f"  * New Leads Created:     {batch_result.created}")
    print(f"  * Duplicates Detected:   {batch_result.duplicates}")
    print(f"  * Processing Errors:     {batch_result.errors}")

    # Duplicates breakdown
    duplicates = db.get_all_duplicates()
    if duplicates:
        print("\n[DUPLICATES DETECTED & ISOLATED]:")
        for d in duplicates:
            print(f"    - Sub {d['source_id']}: [{d['match_type']}] {d['match_reason']}")

    # Warnings breakdown
    leads = db.get_all_leads()
    new_leads_with_warnings = [
        l for l in leads if l.get("validation_warnings") and l["validation_warnings"] != "[]"
    ]
    if new_leads_with_warnings:
        print("\n[LEADS WITH DATA QUALITY ISSUES (Made Visible)]:")
        for l in new_leads_with_warnings:
            warnings_list = json.loads(l["validation_warnings"])
            print(f"    - {l['lead_id']} ({l['name']} @ {l['company']}): {', '.join(warnings_list)}")

    # Tags breakdown
    tag_counts: dict[str, int] = {}
    for l in leads:
        t = l.get("tag") or "Untagged"
        tag_counts[t] = tag_counts.get(t, 0) + 1

    print("\n[QUALIFIED LEADS STORE BREAKDOWN (Total in DB)]:")
    for t, c in sorted(tag_counts.items()):
        print(f"    - {t}: {c}")

    print("\n[DELIVERABLE ARTIFACTS]:")
    print(f"    * SQLite Database:  {os.path.abspath(db_path)}")
    print(f"    * Final Leads CSV:  {exported_path}")
    print("=" * 72)

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run JeeVIT Lead Automation Pipeline")
    parser.add_argument("--db-path", default="leads.db", help="Path to SQLite database")
    parser.add_argument("--reset", action="store_true", help="Reset database before running")
    args = parser.parse_args()

    run_pipeline(db_path=args.db_path, reset_db=args.reset)
