import logging
from typing import Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# UAE bounding box: lat_min, lon_min, lat_max, lon_max
_UAE_BBOX = "23.5,51.5,26.5,56.5"

_OVERPASS_QUERY = f"""
[out:json][timeout:90];
(
  node["office"="estate_agent"]({_UAE_BBOX});
  way["office"="estate_agent"]({_UAE_BBOX});
  relation["office"="estate_agent"]({_UAE_BBOX});
  node["shop"="real_estate"]({_UAE_BBOX});
  way["shop"="real_estate"]({_UAE_BBOX});
);
out body;
"""

_EMIRATE_MAP = {
    "dubai": "Dubai",
    "abu dhabi": "Abu Dhabi",
    "sharjah": "Sharjah",
    "ajman": "Ajman",
    "ras al khaimah": "Ras Al Khaimah",
    "fujairah": "Fujairah",
    "umm al quwain": "Umm Al Quwain",
}


async def fetch_osm_real_estate(
    settings: Settings,
    client: httpx.AsyncClient,
) -> list[dict]:
    resp = await client.post(
        settings.osm_overpass_url,
        data={"data": _OVERPASS_QUERY},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json().get("elements", [])


def osm_element_to_company_dict(element: dict) -> dict:
    tags = element.get("tags", {})
    name = tags.get("name:en") or tags.get("name") or ""
    center = element.get("center") or {}
    lat = element.get("lat") or center.get("lat")
    lon = element.get("lon") or center.get("lon")

    return {
        "company_name": name,
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "website": tags.get("website") or tags.get("contact:website"),
        "address": tags.get("addr:full") or _build_address(tags),
        "latitude": lat,
        "longitude": lon,
        "emirate": _detect_emirate(tags),
        "city": tags.get("addr:city"),
        "country": "AE",
        "source": "osm",
        "source_url": (
            f"https://www.openstreetmap.org/"
            f"{element.get('type')}/{element.get('id')}"
        ),
        "industry": "real_estate",
        "raw_payload": element,
    }


def _build_address(tags: dict) -> Optional[str]:
    parts = [
        p for p in [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:suburb"),
            tags.get("addr:city"),
        ] if p
    ]
    return ", ".join(parts) or None


def _detect_emirate(tags: dict) -> Optional[str]:
    city = (tags.get("addr:city") or "").lower()
    state = (tags.get("addr:state") or "").lower()
    for key, val in _EMIRATE_MAP.items():
        if key in city or key in state:
            return val
    return None
