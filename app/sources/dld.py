import logging
from typing import AsyncGenerator, Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_DATASET_ID = "dld_real_estate_licenses-open-api"


async def _get_access_token(settings: Settings, client: httpx.AsyncClient) -> Optional[str]:
    if not settings.dubai_pulse_api_key or not settings.dubai_pulse_api_secret:
        logger.warning(
            "DUBAI_PULSE_API_KEY / DUBAI_PULSE_API_SECRET not set — DLD source disabled"
        )
        return None
    try:
        resp = await client.post(
            f"{settings.dubai_pulse_token_url}?grant_type=client_credentials",
            data={
                "client_id": settings.dubai_pulse_api_key,
                "client_secret": settings.dubai_pulse_api_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as exc:
        logger.error("Dubai Pulse OAuth failed: %s", exc)
        return None


async def fetch_licensed_agencies(
    settings: Settings,
    client: httpx.AsyncClient,
    token: str,
    offset: int = 0,
    limit: int = 1000,
) -> list[dict]:
    resp = await client.get(
        f"{settings.dubai_pulse_api_url}/data/{_DATASET_ID}",
        headers={"Authorization": f"Bearer {token}"},
        params={"offset": offset, "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("result", {}).get("records", [])


async def fetch_all_licensed_agencies(
    settings: Settings,
    client: httpx.AsyncClient,
) -> AsyncGenerator[dict, None]:
    token = await _get_access_token(settings, client)
    if not token:
        return

    offset, limit = 0, 1000
    while True:
        records = await fetch_licensed_agencies(settings, client, token, offset, limit)
        if not records:
            break
        for record in records:
            yield record
        if len(records) < limit:
            break
        offset += limit


def dld_record_to_company_dict(record: dict) -> dict:
    # DLD field names vary by API version — try common patterns
    name = (
        record.get("OFFICE_NAME_EN")
        or record.get("OFFICE_NAME")
        or record.get("CompanyName")
        or record.get("company_name")
        or record.get("name")
        or ""
    )
    phone = (
        record.get("MOBILE")
        or record.get("PHONE")
        or record.get("Phone")
        or record.get("mobile")
        or record.get("phone")
    )
    area = (
        record.get("AREA_NAME_EN")
        or record.get("AREA")
        or record.get("Area")
        or record.get("area")
        or record.get("LOCATION")
    )
    return {
        "company_name": name,
        "phone": phone,
        "city": area or "Dubai",
        "emirate": "Dubai",
        "country": "AE",
        "source": "dld",
        "source_url": (
            "https://dubailand.gov.ae/en/eservices/"
            "licensed-real-estate-brokers-offices/"
        ),
        "industry": "real_estate",
        "subcategory": "brokerage",
        "raw_payload": record,
    }
