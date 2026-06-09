import logging
import random
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Phrases found on genuine block / challenge interstitials — NOT incidental
# references like cdnjs.cloudflare.com or a reCAPTCHA widget on a contact form.
# Bare "cloudflare"/"captcha" were removed: they match legit CDN/script URLs and
# caused full content pages (200, 200KB+) to be falsely marked blocked.
_BLOCK_PHRASES = [
    "attention required!",                 # Cloudflare block page title
    "checking your browser before accessing",
    "cf-browser-verification",
    "access denied",
    "verify you are human",
    "are you human",
    "unusual traffic from your",
    "ddos protection by",
    "request unsuccessful",                # Imperva/Incapsula
]

# Real challenge pages are small interstitials. A large 200 response is genuine
# content even if it references cloudflare/captcha in an asset URL or form widget,
# so we only scan small bodies for the phrases above.
_CHALLENGE_MAX_BYTES = 15_000


def compute_company_confidence(company: dict) -> float:
    score = 0.0

    # +0.25: website present
    if company.get("website"):
        score += 0.25

    # +0.20: valid E.164 phone
    if company.get("phone_e164"):
        score += 0.20

    # +0.25: present in ≥2 independent sources
    src = company.get("source") or ""
    source_count = sum([
        1 if ("google" in src or company.get("place_id")) else 0,
        1 if ("dld" in src or "osm" in src) else 0,
    ])
    if source_count >= 2:
        score += 0.25

    # +0.15: Google rating with review count
    rating = company.get("google_rating")
    rating_count = company.get("rating_count")
    if rating is not None and rating_count and rating_count > 0:
        score += 0.15

    # +0.15: no missing critical fields
    name = company.get("company_name")
    city = company.get("city") or company.get("emirate")
    if name and city and (company.get("website") or company.get("phone_e164")):
        score += 0.15

    return round(min(score, 1.0), 2)


def detect_block(status_code: int, body: Optional[str]) -> bool:
    if status_code in (403, 429, 503):
        return True
    body_lower = (body or "").lower()
    # Honeypot / empty 200 response
    if len(body_lower) < 500 and status_code == 200:
        return True
    # Only scan small bodies for challenge phrases — large pages are real content.
    if len(body_lower) <= _CHALLENGE_MAX_BYTES:
        return any(phrase in body_lower for phrase in _BLOCK_PHRASES)
    return False


async def acquire_domain_slot(
    domain: str,
    redis_client: aioredis.Redis,
    min_delay: int,
    max_delay: int,
) -> None:
    key = f"crawl:cooldown:{domain}"
    delay = random.randint(min_delay, max_delay)
    # SET NX with TTL — only set if key doesn't exist
    acquired = await redis_client.set(key, "1", ex=delay, nx=True)
    if not acquired:
        ttl = await redis_client.ttl(key)
        raise CooldownError(f"Domain {domain} is on cooldown for {ttl}s")


async def check_rate_limit(
    service: str,
    max_calls: int,
    window_seconds: int,
    redis_client: aioredis.Redis,
) -> bool:
    import time
    bucket = int(time.time()) // window_seconds
    key = f"ratelimit:{service}:{bucket}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, window_seconds)
    return count <= max_calls


class CooldownError(Exception):
    pass
