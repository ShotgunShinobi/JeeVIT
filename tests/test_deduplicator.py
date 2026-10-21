"""
Unit tests for duplicate detection across exact email, alias, and batch layers.
"""

from src.cleaner import clean_lead
from src.deduplicator import Deduplicator, ExistingLeadInfo
from src.models import DuplicateType, IncomingLead


def test_deduplicator_existing_exact_email():
    dedup = Deduplicator()
    dedup.load_existing([
        ExistingLeadInfo(
            lead_id="L-1001",
            email="priya.sharma@brightloop.io",
            email_dedup="priya.sharma@brightloop.io",
            name="Priya Sharma",
            company="Brightloop",
        )
    ])

    # Incoming with different casing
    raw = IncomingLead(
        id="S-02",
        name="Priya Sharma",
        email="Priya.Sharma@Brightloop.IO",
        company="Brightloop",
        message="Following up.",
    )
    cleaned = clean_lead(raw)
    res = dedup.check(cleaned)

    assert res.is_duplicate is True
    assert res.record.matched_lead_id == "L-1001"
    assert res.record.match_type == DuplicateType.EXACT_EMAIL


def test_deduplicator_existing_alias_email():
    dedup = Deduplicator()
    dedup.load_existing([
        ExistingLeadInfo(
            lead_id="L-1008",
            email="tom@acmelogistics.com",
            email_dedup="tom@acmelogistics.com",
            name="Tom Walsh",
            company="Acme Logistics",
        )
    ])

    # Incoming with +alias
    raw = IncomingLead(
        id="S-15",
        name="Tom Walsh",
        email="tom+automation@acmelogistics.com",
        company="Acme Logistics",
        message="Ready to go ahead.",
    )
    cleaned = clean_lead(raw)
    res = dedup.check(cleaned)

    assert res.is_duplicate is True
    assert res.record.matched_lead_id == "L-1008"
    assert res.record.match_type == DuplicateType.EMAIL_ALIAS


def test_deduplicator_batch_duplicate():
    dedup = Deduplicator()

    # First submission in batch
    raw1 = IncomingLead(
        id="S-12",
        name="Chloe Martin",
        email="chloe@fernandfox.com",
        company="Fern & Fox",
        message="We need help connecting Shopify.",
    )
    cleaned1 = clean_lead(raw1)
    res1 = dedup.check(cleaned1)
    assert res1.is_duplicate is False

    # Second submission in same batch with whitespace/casing differences
    raw2 = IncomingLead(
        id="S-14",
        name="Chloe Martin",
        email="CHLOE@fernandfox.com ",
        company="Fern and Fox",
        message="sorry, think I sent that twice!",
    )
    cleaned2 = clean_lead(raw2)
    res2 = dedup.check(cleaned2)
    assert res2.is_duplicate is True
    assert res2.record.matched_source_id == "S-12"
    assert res2.record.match_type == DuplicateType.BATCH
