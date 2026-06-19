"""Phase 7 — outreach handoff delivery.

Formats a qualified lead and delivers it to the configured outreach webhook
(CRM / email sequencer). This module owns the wire format + transport only;
selection, suppression, and tracking live in the worker.
"""
import logging

import httpx

logger = logging.getLogger(__name__)


def build_payload(lead: dict) -> dict:
    """Map an internal lead row to the outreach payload."""
    score = lead.get("lead_score") or 0.0
    tier = "hot" if score >= 0.70 else "warm" if score >= 0.45 else "cold"
    return {
        "company_name": lead.get("company_name"),
        "domain": lead.get("domain"),
        "full_name": lead.get("full_name"),
        "job_title": lead.get("job_title"),
        "seniority": lead.get("seniority"),
        "email": lead.get("email"),
        "email_status": lead.get("email_status"),
        "linkedin_url": lead.get("linkedin_url"),
        "lead_score": round(float(score), 2),
        "tier": tier,
    }


async def deliver(payload: dict, webhook_url: str) -> bool:
    """POST the lead to the outreach webhook. True on 2xx, False on any error."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(webhook_url, json=payload)
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("handoff delivery failed for %s: %s", payload.get("email"), exc)
        return False
