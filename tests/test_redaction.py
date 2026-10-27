"""Redaction before any model call (ADR 0008): strip what a model doesn't need, keep the
job details it does. All values here are fake."""

import pytest

from brain_dock.core.agents.gateway import Redacted, redact

JOB = (
    "Role: Forward Deployed Engineer at Acme Analytics, remote, posted 2026-10-26, "
    "salary $120,000 to $140,000, 5+ years. https://jobs.example.com/fde/123"
)


def test_only_redact_makes_redacted_text():
    with pytest.raises(TypeError, match="only redact"):
        Redacted("a plain string pretending")

    assert isinstance(redact("text"), Redacted)


@pytest.mark.parametrize(
    ("text", "planted", "placeholder"),
    [
        ("Write to jane.doe+jobs@example.co.uk today", "jane.doe+jobs@example.co.uk", "[email]"),
        ("Call +44 20 7946 0958 after 5", "7946 0958", "[phone]"),
        ("Or (555) 010-4477 tomorrow", "010-4477", "Or [phone] tomorrow"),  # no stray "("
        (
            "Apply https://jobs.example.com/fde/1?token=SECRET-VALUE-42&utm=x now",
            "SECRET-VALUE-42",
            "https://jobs.example.com/fde/1?[query removed]",
        ),
        ("Thanks!\n-- \nJane Doe\nTalent Partner", "Talent Partner", "[signature removed]"),
        ("Hi Jane Doe, this one fits", "Jane Doe", "[redacted]"),
    ],
    ids=["email", "phone-international", "phone-local", "url-token", "signature", "extra-term"],
)
def test_redaction_rules(text, planted, placeholder):
    result = redact(text, extra_terms=["jane doe"]).text

    assert planted not in result
    assert placeholder in result


def test_job_details_survive():
    assert redact(JOB).text == JOB  # dates, salaries, years and the link path stay


# --- Known edge cases (pinned, so any change in behavior is a visible, reviewed diff) -----


def test_known_edge_a_seven_digit_local_number():
    # Handled in PR 3c (it used to slip past the 9-digit rule): local numbers are redacted.
    assert redact("Call 555-1234 or 555.9876 today").text == "Call [phone] or [phone] today"
    # Side effect, the safe direction: a 3-4 digit range looks like a local number.
    assert redact("Team of 100-1000 people").text == "Team of [phone] people"


def test_known_edge_a_salary_range_without_commas():
    # Over-redaction, the safe direction: a 12-digit range looks like a phone number. The
    # salary math reads the email before redaction (design section 3), so nothing is lost.
    assert redact("Salary 120000-150000 a year").text == "Salary [phone] a year"
    assert redact("Salary 120,000-150,000").text == "Salary 120,000-150,000"
