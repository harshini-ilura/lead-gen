import asyncio
import logging
from typing import Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAIL_URL = "https://places.googleapis.com/v1/places/{place_id}"

# Pro-tier fields only — never request atmosphere/reviews (Enterprise tier)
_SEARCH_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.nationalPhoneNumber,"
    "places.websiteUri,"
    "places.location,"
    "places.rating,"
    "places.userRatingCount,"
    "places.types,"
    "places.googleMapsUri"
)

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


async def search_places(
    query: str,
    settings: Settings,
    client: httpx.AsyncClient,
    page_token: Optional[str] = None,
) -> tuple[list[dict], Optional[str]]:
    payload: dict = {"textQuery": query, "languageCode": "en"}
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


def place_to_company_dict(place: dict) -> dict:
    loc = place.get("location", {})
    name_obj = place.get("displayName", {})
    return {
        "place_id": place.get("id"),
        "company_name": name_obj.get("text", ""),
        "address": place.get("formattedAddress"),
        "phone": place.get("nationalPhoneNumber"),
        "website": place.get("websiteUri"),
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "google_rating": place.get("rating"),
        "rating_count": place.get("userRatingCount"),
        "source": "google",
        "source_url": place.get("googleMapsUri"),
        "raw_payload": place,
    }
