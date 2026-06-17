"""Phase 5 — email verification.

Tiered: a free tier (syntax + role/disposable + per-domain MX, Redis-cached) always
runs; a paid tier (MillionVerifier) runs only when enabled and under the monthly cap,
upgrading the free `mx_ok` ceiling to a real valid/invalid/risky verdict.
"""
import logging
import re
from typing import Optional

import dns.asyncresolver
import httpx
import redis.asyncio as aioredis

from app.config import Settings
from app.workers.contacts import _ROLE_LOCALPARTS

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_MILLIONVERIFIER_URL = "https://api.millionverifier.com/api/v3/"

# Common disposable / throwaway domains — addresses here are low-trust.
_DISPOSABLE = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "yopmail.com",
    "tempmail.com", "temp-mail.org", "throwawaymail.com", "getnada.com",
    "trashmail.com", "fakeinbox.com", "sharklasers.com", "dispostable.com",
    "maildrop.cc", "mailnesia.com", "mintemail.com", "mohmal.com",
    "spamgourmet.com", "tempinbox.com", "discard.email", "emailondeck.com",
})

# MillionVerifier result -> our verification_status.
_PAID_MAP = {
    "ok": "valid",
    "catch_all": "risky",
    "disposable": "risky",
    "invalid": "invalid",
    "unknown": "unknown",
}


def validate_syntax(email: str) -> bool:
    return bool(email and _EMAIL_RE.match(email.strip()))


def is_role(local_part: str) -> bool:
    return local_part.lower() in _ROLE_LOCALPARTS


def is_disposable(domain: str) -> bool:
    return domain.lower() in _DISPOSABLE


async def resolve_mx(domain: str, redis: aioredis.Redis, ttl_days: int) -> bool:
    """True if the domain has MX records. Cached (positive AND negative) in Redis."""
    key = f"mx:{domain.lower()}"
    cached = await redis.get(key)
    if cached is not None:
        return cached == b"1" or cached == "1"
    try:
        answers = await dns.asyncresolver.resolve(domain, "MX")
        has_mx = len(answers) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer,
            dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout, Exception):
        has_mx = False
    await redis.set(key, "1" if has_mx else "0", ex=ttl_days * 86400)
    return has_mx


async def _under_monthly_cap(redis: aioredis.Redis, cap: int) -> bool:
    """Reserve one paid call against the calendar-month counter. Returns False
    once the cap is reached."""
    from time import strftime

    key = f"verify:paid:usage:{strftime('%Y%m')}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 35 * 86400)
    return count <= cap


async def verify_paid(
    email: str, settings: Settings, redis: aioredis.Redis
) -> Optional[str]:
    """MillionVerifier single-email check. Returns a status or None (skip/error)."""
    if not await _under_monthly_cap(redis, settings.paid_verify_monthly_cap):
        logger.info("paid verify monthly cap reached — skipping %s", email)
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _MILLIONVERIFIER_URL,
                params={"api": settings.millionverifier_api_key, "email": email},
            )
        resp.raise_for_status()
        result = (resp.json() or {}).get("result", "unknown")
        return _PAID_MAP.get(result, "unknown")
    except Exception as exc:
        logger.warning("paid verify error for %s: %s", email, exc)
        return None


async def verify_email(
    email: str, settings: Settings, redis: aioredis.Redis
) -> str:
    """Run the verification ladder, returning a verification_status."""
    email = (email or "").strip().lower()
    if not validate_syntax(email):
        return "invalid"
    domain = email.split("@", 1)[1]
    if is_disposable(domain):
        return "risky"
    if not await resolve_mx(domain, redis, settings.mx_cache_ttl_days):
        return "invalid"

    # Free ceiling.
    status = "mx_ok"

    if settings.paid_verify_enabled and settings.millionverifier_api_key:
        paid = await verify_paid(email, settings, redis)
        if paid is not None:
            status = paid
    return status
