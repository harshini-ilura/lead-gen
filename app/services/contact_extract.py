"""Phase 3 — LLM contact extraction (OpenAI).

Turns crawled HTML into a compact text representation and asks gpt-4o-mini to
return structured people + emails via strict json_schema structured output.
OpenAI applies automatic prompt caching to the static system prefix.
"""
import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)

_LINKEDIN_RE = re.compile(r"linkedin\.com/(in|company)/", re.IGNORECASE)

_SENIORITY = ["c_level", "founder", "director", "manager", "senior", "staff", "unknown"]

SYSTEM_PROMPT = (
    "You extract real people who work at a real-estate company from the text of "
    "its own website pages (team, about, agents, contact, etc.).\n"
    "Rules:\n"
    "- Only include named individuals who are staff/agents/leadership of THIS company.\n"
    "- Ignore testimonials, client names, blog authors, placeholders, and navigation.\n"
    "- job_title: their role as shown (e.g. 'Senior Property Consultant'); null if unknown.\n"
    "- seniority: bucket into c_level, founder, director, manager, senior, staff, or unknown.\n"
    "- linkedin_url / email: only if clearly tied to that person; otherwise null.\n"
    "- generic_emails: company-wide / role addresses (info@, sales@, contact@) that "
    "belong to no specific person.\n"
    "Return an empty people list rather than guessing."
)

# Strict json_schema: every property must be required; optionals are nullable unions.
_SCHEMA = {
    "name": "record_contacts",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "people": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "full_name": {"type": "string"},
                        "job_title": {"type": ["string", "null"]},
                        "seniority": {"type": ["string", "null"], "enum": _SENIORITY + [None]},
                        "linkedin_url": {"type": ["string", "null"]},
                        "email": {"type": ["string", "null"]},
                    },
                    "required": ["full_name", "job_title", "seniority", "linkedin_url", "email"],
                },
            },
            "generic_emails": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["people", "generic_emails"],
    },
}


class Person(BaseModel):
    full_name: str
    job_title: Optional[str] = None
    seniority: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None


class ExtractResult(BaseModel):
    people: list[Person] = []
    generic_emails: list[str] = []


def html_to_llm_text(url: str, raw_html: str, max_chars: int) -> str:
    """Compact a stored page into visible text + a LINKS appendix of the
    mailto/linkedin hrefs (which would otherwise be lost in get_text)."""
    soup = BeautifulSoup(raw_html or "", "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:") or _LINKEDIN_RE.search(href):
            links.append(href)
    text = soup.get_text(" ", strip=True)[:max_chars]
    appendix = ("\nLINKS:\n" + "\n".join(dict.fromkeys(links))) if links else ""
    return f"--- PAGE: {url} ---\n{text}{appendix}"


async def extract_people(
    pages: list[tuple[str, str]], settings: Settings
) -> ExtractResult:
    """pages = [(url, raw_html), ...] for one company → structured people/emails."""
    if not pages:
        return ExtractResult()

    pages = pages[: settings.contact_extract_max_pages]
    content = "\n\n".join(
        html_to_llm_text(url, html, settings.contact_extract_max_chars_per_page)
        for url, html in pages
    )

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=settings.contact_extract_model,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_schema", "json_schema": _SCHEMA},
    )

    raw = resp.choices[0].message.content
    try:
        return ExtractResult.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("contact extraction parse/validate failed: %s", exc)
        return ExtractResult()
