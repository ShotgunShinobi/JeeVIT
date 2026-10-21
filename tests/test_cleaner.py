"""
Unit tests for data cleaning and normalization.
"""

from src.cleaner import (
    clean_lead,
    company_dedup_key,
    email_dedup_key,
    normalize_company,
    normalize_email,
    normalize_name,
)
from src.models import IncomingLead


def test_normalize_email():
    assert normalize_email("  test@example.com  ") == ("test@example.com", True)
    assert normalize_email("Priya.Sharma@Brightloop.IO") == ("priya.sharma@brightloop.io", True)
    assert normalize_email("sara@@nordicform.se") == ("sara@@nordicform.se", False)
    assert normalize_email("ben.carter@gmail") == ("ben.carter@gmail", False)
    assert normalize_email("") == (None, False)
    assert normalize_email(None) == (None, False)


def test_email_dedup_key():
    assert email_dedup_key("tom+automation@acmelogistics.com") == "tom@acmelogistics.com"
    assert email_dedup_key("  User+Test1234@Domain.COM ") == "user@domain.com"
    assert email_dedup_key("normal@domain.com") == "normal@domain.com"
    assert email_dedup_key(None) is None


def test_normalize_name():
    assert normalize_name("  JAMES   o'CONNOR ") == "James O'Connor"
    assert normalize_name("Zoë Müller") == "Zoë Müller"
    assert normalize_name("jean-paul sartre") == "Jean-Paul Sartre"
    assert normalize_name("hannah brooks") == "Hannah Brooks"
    assert normalize_name("") == "Unknown"
    assert normalize_name(None) == "Unknown"


def test_normalize_company():
    assert normalize_company("  Peak Roast  ") == "Peak Roast"
    assert normalize_company("") == "Unknown"
    assert normalize_company(None) == "Unknown"
    assert company_dedup_key("Fern & Fox") == "fern and fox"
    assert company_dedup_key("Fern and Fox") == "fern and fox"


def test_clean_lead_with_warnings():
    raw_bad_email = IncomingLead(
        id="S-99",
        name="Test Lead",
        email="bad@@domain.com",
        company="",
        message="",
    )
    cleaned = clean_lead(raw_bad_email)
    assert not cleaned.email_valid
    assert len(cleaned.validation_warnings) >= 3
    assert any("Email format appears invalid" in w for w in cleaned.validation_warnings)
    assert any("Company is missing" in w for w in cleaned.validation_warnings)
    assert any("Message is empty" in w for w in cleaned.validation_warnings)
