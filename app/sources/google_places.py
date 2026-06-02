import asyncio
import logging
from typing import Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAIL_URL = "https://places.googleapis.com/v1/places/{place_id}"

# Pro-tier fields only — never request atmosphere/reviews (Enterprise tier).
# nextPageToken MUST be in the mask or the API never returns it (Bug 1).
# addressComponents + internationalPhoneNumber give clean city/emirate/E.164 (Bug 3).
_SEARCH_FIELD_MASK = (
    "nextPageToken,"
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.addressComponents,"
    "places.nationalPhoneNumber,"
    "places.internationalPhoneNumber,"
    "places.websiteUri,"
    "places.location,"
    "places.rating,"
    "places.userRatingCount,"
    "places.types,"
    "places.googleMapsUri"
)

# Text Search returns at most 20 results per page, up to 3 pages (60 total).
PLACES_PAGE_SIZE = 20

# Niche category we target — mapped from Google place `types`.
_NICHE_TYPES = {"real_estate_agency", "real_estate_developer"}

_DETAIL_FIELD_MASK = (
    "id,"
    "displayName,"
    "formattedAddress,"
    "nationalPhoneNumber,"
    "websiteUri,"
    "location,"
    "rating,"
    "userRatingCount,"
    "types,"
    "googleMapsUri"
)

# Max 5 concurrent requests to stay within 10 QPS quota
_semaphore = asyncio.Semaphore(5)

DUBAI_NEIGHBORHOODS = [
    "Deira", "Bur Dubai", "Al Barsha", "Jumeirah", "Downtown Dubai",
    "Business Bay", "Dubai Marina", "JBR", "Palm Jumeirah", "Al Quoz",
    "Al Nahda Dubai", "Al Qusais", "Karama", "Satwa", "Oud Metha",
    "Festival City", "Silicon Oasis", "International City", "Al Warqa",
    "Mirdif", "Arabian Ranches", "DIFC", "JLT", "Motor City",
    "Sports City", "Discovery Gardens", "Al Furjan", "Dubai Hills Estate",
    "Town Square", "Arjan",
]

ABU_DHABI_AREAS = [
    "Abu Dhabi Island", "Al Reem Island", "Khalifa City", "Al Raha Beach",
    "Yas Island", "Saadiyat Island", "Mussafah", "Al Shamkha",
    "Mohammed Bin Zayed City", "Al Ain City", "Al Mushrif",
    "Corniche Abu Dhabi", "Al Zahiyah", "Al Bateen", "Zayed City",
]

OTHER_EMIRATES_AREAS = [
    "Sharjah City", "Al Majaz Sharjah", "Al Nahda Sharjah",
    "Ajman City", "Al Nuaimiya Ajman",
    "Ras Al Khaimah City", "Al Hamra RAK",
    "Fujairah City",
    "Umm Al Quwain City",
]


# Search phrase prefix for the target niche.
NICHE_QUERY = "real estate agency"


def build_discovery_query(area: str, emirate: str) -> str:
    """Single source of truth for the discovery text query (Bug 4).

    Both the API trigger and the worker must produce identical strings so
    pagination tokens and dedup behave consistently.
    """
    return f"{NICHE_QUERY} {area} {emirate}"


async def search_places(
    query: str,
    settings: Settings,
    client: httpx.AsyncClient,
    page_token: Optional[str] = None,
) -> tuple[list[dict], Optional[str]]:
    payload: dict = {
        "textQuery": query,
        "languageCode": "en",
        "pageSize": PLACES_PAGE_SIZE,  # Bug 1: enable full 20-per-page results
    }
    if page_token:
        payload["pageToken"] = page_token

    async with _semaphore:
        resp = await client.post(
            PLACES_SEARCH_URL,
            json=payload,
            headers={
                "X-Goog-Api-Key": settings.google_maps_api_key,
                "X-Goog-FieldMask": _SEARCH_FIELD_MASK,
            },
            timeout=20,
        )

    if resp.status_code != 200:
        logger.error("Places search error %s: %s", resp.status_code, resp.text[:200])
        resp.raise_for_status()

    data = resp.json()
    return data.get("places", []), data.get("nextPageToken")


async def get_place_details(
    place_id: str,
    settings: Settings,
    client: httpx.AsyncClient,
) -> dict:
    async with _semaphore:
        resp = await client.get(
            PLACES_DETAIL_URL.format(place_id=place_id),
            headers={
                "X-Goog-Api-Key": settings.google_maps_api_key,
                "X-Goog-FieldMask": _DETAIL_FIELD_MASK,
            },
            timeout=20,
        )
    resp.raise_for_status()
    return resp.json()


async def lookup_place_by_name_phone(
    name: str,
    phone: Optional[str],
    emirate: str,
    settings: Settings,
    client: httpx.AsyncClient,
) -> Optional[dict]:
    query = f"{name} real estate {emirate} UAE"
    places, _ = await search_places(query, settings, client)
    return places[0] if places else None


_LATIN_LANGS = {"en", "en-US", "en-GB", "ar-Latn"}


def _parse_address_components(place: dict) -> dict:
    """Extract city / emirate / country from Google addressComponents (Bug 3).

    Prefers English (or romanized) component names; ignores pure-Arabic entries.
    """
    city = emirate = country = None
    for comp in place.get("addressComponents", []):
        types = comp.get("types", [])
        if comp.get("languageCode") not in _LATIN_LANGS:
            continue
        name = comp.get("longText")
        if "administrative_area_level_1" in types:
            emirate = name
        elif "locality" in types and not city:
            city = name
        elif "sublocality_level_1" in types and not city:
            city = name  # fallback when no locality present
        if "country" in types:
            country = comp.get("shortText")  # ISO-2, e.g. "AE"
    return {"city": city, "emirate": emirate, "country": country}


def _industry_from_types(place: dict) -> Optional[str]:
    for t in place.get("types", []):
        if t in _NICHE_TYPES:
            return t
    return None


def place_to_company_dict(place: dict) -> dict:
    loc = place.get("location", {})
    name_obj = place.get("displayName", {})
    addr = _parse_address_components(place)
    return {
        "place_id": place.get("id"),
        "company_name": name_obj.get("text", ""),
        "address": place.get("formattedAddress"),
        "phone": place.get("nationalPhoneNumber"),
        # International (E.164) number straight from Google — normalize_company
        # will still validate, but this is the authoritative source.
        "phone_e164": place.get("internationalPhoneNumber"),
        "website": place.get("websiteUri"),
        "city": addr["city"],
        "emirate": addr["emirate"],
        "country": addr["country"],
        "industry": _industry_from_types(place),
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "google_rating": place.get("rating"),
        "rating_count": place.get("userRatingCount"),
        "source": "google",
        "source_url": place.get("googleMapsUri"),
        "raw_payload": place,
    }
