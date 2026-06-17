"""Phase 6 — lead scoring.

Turns a contact + its primary (verified) email + company quality into a single
0–1 lead score for outreach prioritization. Verification answers "can we reach
them"; this answers "is it worth it, and who first".

Weights (sum to 1.0):
  email deliverability  0.40   — the verified primary email
  seniority             0.30   — decision-makers outrank junior staff
  company quality       0.20   — discovery's confidence_score
  completeness          0.10   — has title / linkedin
"""
from typing import Optional

_SENIORITY_WEIGHT = {
    "c_level": 1.0,
    "founder": 1.0,
    "director": 0.8,
    "manager": 0.6,
    "senior": 0.45,
    "staff": 0.30,
    "unknown": 0.15,
}

_EMAIL_STATUS_WEIGHT = {
    "valid": 1.0,    # paid-confirmed deliverable
    "mx_ok": 0.55,   # domain accepts mail, mailbox unconfirmed
    "risky": 0.25,   # catch-all / accept-all
    "unknown": 0.15,
    "invalid": 0.0,
}

# Tier labels for the human-readable export.
def tier(score: float) -> str:
    if score >= 0.70:
        return "hot"
    if score >= 0.45:
        return "warm"
    return "cold"


def score_lead(
    *,
    seniority: Optional[str],
    email_status: Optional[str],
    email_source: Optional[str],
    is_role_email: bool,
    has_title: bool,
    has_linkedin: bool,
    company_confidence: Optional[float],
) -> float:
    """Return a 0.00–1.00 lead score."""
    # Email component: deliverability, with a bonus for real (crawled) addresses
    # and a penalty for role inboxes (less personal).
    email = _EMAIL_STATUS_WEIGHT.get(email_status or "unknown", 0.0)
    if email_source == "crawled":
        email = min(1.0, email + 0.15)
    if is_role_email:
        email *= 0.7

    seniority_w = _SENIORITY_WEIGHT.get(seniority or "unknown", 0.15)
    company_w = float(company_confidence or 0.0)
    completeness = (0.5 if has_title else 0.0) + (0.5 if has_linkedin else 0.0)

    score = (
        0.40 * email
        + 0.30 * seniority_w
        + 0.20 * company_w
        + 0.10 * completeness
    )
    return round(min(score, 1.0), 2)
