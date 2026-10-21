"""
End-to-end integration tests for the full LeadPipeline.
"""

import json
from pathlib import Path

from src.database import Database
from src.models import IncomingLead, ProcessingStatus
from src.notifier import ConsoleNotifier
from src.pipeline import LeadPipeline
from src.scorer import StubScorer


class MockNotifier:
    def __init__(self):
        self.notified_leads = []

    def notify(self, lead) -> bool:
        self.notified_leads.append(lead)
        return True


def test_full_pipeline_run(tmp_path: Path):
    db_file = tmp_path / "test_leads.db"
    db = Database(str(db_file))
    mock_notifier = MockNotifier()
    pipeline = LeadPipeline(db=db, scorer=StubScorer(), notifier=mock_notifier)

    # 1. Load baseline existing leads
    root_dir = Path(__file__).resolve().parent.parent
    existing_csv = root_dir / "existing_leads.csv"
    imported = db.load_existing_csv(str(existing_csv))
    assert imported == 12
    pipeline.sync_deduplicator()

    # 2. Load the 15 incoming test leads
    incoming_json = root_dir / "incoming_leads.json"
    with open(incoming_json, "r", encoding="utf-8") as f:
        items = json.load(f)
    incoming_leads = [IncomingLead(**item) for item in items]
    assert len(incoming_leads) == 15

    # 3. Process batch
    batch_res = pipeline.process_batch(incoming_leads)

    assert batch_res.total == 15
    assert batch_res.duplicates == 4  # S-02, S-03, S-14, S-15
    assert batch_res.created == 11
    assert batch_res.errors == 0

    # 4. Verify duplicate details in DB
    duplicates = db.get_all_duplicates()
    assert len(duplicates) == 4
    dup_sources = {d["source_id"] for d in duplicates}
    assert dup_sources == {"S-02", "S-03", "S-14", "S-15"}

    # 5. Verify Hot lead notifications
    # S-01 (Peak Roast) and S-09 (Zoë Müller) are Hot
    assert len(mock_notifier.notified_leads) >= 2
    hot_names = {lead.name for lead in mock_notifier.notified_leads}
    assert "Hannah Brooks" in hot_names
    assert "Zoë Müller" in hot_names

    # 6. Verify prompt injection lead (S-10) was saved as Cold
    leads = db.get_all_leads()
    s10 = next((l for l in leads if l["source_id"] == "S-10"), None)
    assert s10 is not None
    assert s10["tag"] == "Cold"
    assert "injection" in s10["llm_reasoning"].lower()

    # 7. Verify CSV Export
    export_csv = tmp_path / "exported.csv"
    db.export_csv(str(export_csv))
    assert export_csv.exists()
    content = export_csv.read_text(encoding="utf-8")
    assert "Hannah Brooks" in content
    assert "L-1001" in content
    assert "draft_reply" in content

    db.close()
