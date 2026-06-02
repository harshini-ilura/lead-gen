import re
import unicodedata
from typing import Optional

import phonenumbers
import tldextract

_LEGAL_SUFFIXES = re.compile(
    r"\b(llc|l\.l\.c|fze|fzc|fzco|fz|ltd|limited|co|corp|corporation|inc|"
    r"pvt|pte|plc|gmbh|ag|sa|sas|bv|nv|pty|"
    r"real estate|realty|properties|property|homes|home|"
    r"brokers|broker|group|holding|holdings|investment|investments|"
    r"mgmt|management|services|solutions|consultancy|consultants)\b",
    re.IGNORECASE,
)


def extract_domain(website_url: Optional[str]) -> Optional[str]:
    if not website_url:
        return None
    extracted = tldextract.extract(website_url)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    return None


def normalize_phone_e164(
    raw_phone: Optional[str], default_region: str = "AE"
) -> Optional[str]:
    if not raw_phone:
        return None
    try:
        parsed = phonenumbers.parse(raw_phone, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
    except phonenumbers.NumberParseException:
        pass
    return None


def normalize_company_name(name: str) -> str:
    if not name:
        return ""
    # Remove diacritics
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_name.lower().strip()
    cleaned = _LEGAL_SUFFIXES.sub("", lowered)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_company(raw: dict) -> dict:
    website = raw.get("website")
    # Prefer Google's international number (already +country), fall back to the
    # national number. Both are validated/reformatted into strict E.164.
    phone_source = raw.get("phone_e164") or raw.get("phone")
    name = raw.get("company_name", "")
    return {
        **raw,
        "domain": extract_domain(website),
        "phone_e164": normalize_phone_e164(phone_source),
        "normalized_name": normalize_company_name(name),
    }
