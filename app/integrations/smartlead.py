"""Phase 8 — Smartlead outreach integration.

Pushes qualified leads into a Smartlead campaign and maps inbound webhook events
(reply / bounce / unsubscribe) back to our pipeline. Smartlead runs the actual
sending, warmup, inbox rotation, and follow-up sequences.

API: https://server.smartlead.ai/api/v1  (auth via ?api_key=...)
"""
import logging
from typing import Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_BATCH = 100  # Smartlead accepts up to 100 leads per add-leads call


def lead_to_smartlead(lead: dict) -> dict:
    """Map an internal lead row to Smartlead's lead schema."""
    return {
        "email": lead["email"],
        "first_name": lead.get("first_name"),
        "last_name": lead.get("last_name"),
        "company_name": lead.get("company_name"),
        "custom_fields": {
            "job_title": lead.get("job_title") or "",
            "seniority": lead.get("seniority") or "",
            "city": lead.get("city") or "",
            "lead_score": str(lead.get("lead_score") or ""),
            "linkedin_url": lead.get("linkedin_url") or "",
        },
    }


async def push_leads(leads: list[dict], settings: Settings) -> int:
    """Add leads to the configured Smartlead campaign (batched). Returns count pushed.

    Smartlead de-duplicates by email within a campaign, so re-pushing is safe.
    """
    url = f"{settings.smartlead_base_url}/campaigns/{settings.smartlead_campaign_id}/leads"
    pushed = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(0, len(leads), _BATCH):
            batch = leads[i : i + _BATCH]
            payload = {
                "lead_list": [lead_to_smartlead(x) for x in batch],
                "settings": {"ignore_global_block_list": False,
                             "ignore_unsubscribe_list": False},
            }
            resp = await client.post(
                url, params={"api_key": settings.smartlead_api_key}, json=payload
            )
            resp.raise_for_status()
            pushed += len(batch)
    return pushed


def parse_event(payload: dict) -> tuple[Optional[str], Optional[str]]:
    """Map a Smartlead webhook payload → (outreach_status, lead_email).

    Smartlead event names vary across versions; match defensively.
    """
    raw = (
        payload.get("event_type")
        or payload.get("webhook_event")
        or payload.get("event")
        or ""
    ).lower()
    email = (
        payload.get("to_email")
        or payload.get("lead_email")
        or payload.get("email")
        or (payload.get("lead") or {}).get("email")
        or ""
    ).lower().strip()

    if "reply" in raw:
        status = "replied"
    elif "bounce" in raw:
        status = "bounced"
    elif "unsub" in raw:
        status = "unsubscribed"
    else:
        status = None
    return status, (email or None)
