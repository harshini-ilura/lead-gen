import logging
from typing import Literal, Optional

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company

logger = logging.getLogger(__name__)

DedupResult = Literal["place_id", "domain", "phone", "trgm", "none"]
TRGM_THRESHOLD = 0.7


async def find_duplicate(
    session: AsyncSession,
    normalized: dict,
) -> tuple[DedupResult, Optional[int]]:
    # 1. place_id exact match
    if place_id := normalized.get("place_id"):
        row = (
            await session.execute(
                select(Company.company_id).where(Company.place_id == place_id)
            )
        ).scalar_one_or_none()
        if row:
            return "place_id", row

    # 2. domain exact match
    if domain := normalized.get("domain"):
        row = (
            await session.execute(
                select(Company.company_id).where(Company.domain == domain)
            )
        ).scalar_one_or_none()
        if row:
            return "domain", row

    # 3. phone_e164 exact match
    if phone := normalized.get("phone_e164"):
        row = (
            await session.execute(
                select(Company.company_id).where(Company.phone_e164 == phone)
            )
        ).scalar_one_or_none()
        if row:
            return "phone", row

    # 4. trgm similarity (flag only — not auto-merged)
    if norm_name := normalized.get("normalized_name"):
        emirate = normalized.get("emirate")
        row = (
            await session.execute(
                text(
                    "SELECT company_id FROM companies "
                    # Cast required: asyncpg can't infer the type of a bare bind
                    # parameter used only in `IS NULL` (AmbiguousParameterError).
                    "WHERE (CAST(:emirate AS text) IS NULL OR emirate = :emirate) "
                    "AND normalized_name IS NOT NULL "
                    "AND similarity(normalized_name, :name) > :threshold "
                    "ORDER BY similarity(normalized_name, :name) DESC LIMIT 1"
                ),
                {"name": norm_name, "emirate": emirate, "threshold": TRGM_THRESHOLD},
            )
        ).scalar_one_or_none()
        if row:
            logger.warning(
                "trgm near-duplicate flagged: '%s' ≈ company_id=%s (not auto-merged)",
                normalized.get("company_name"),
                row,
            )
            return "trgm", row

    return "none", None


async def upsert_company(session: AsyncSession, normalized: dict) -> int:
    cols = {
        k: v
        for k, v in normalized.items()
        if v is not None and k != "company_id"
    }

    dedup_type, existing_id = await find_duplicate(session, normalized)

    # Domain or phone match: merge into existing row
    if dedup_type in ("domain", "phone"):
        await session.execute(
            update(Company)
            .where(Company.company_id == existing_id)
            .values(**{k: v for k, v in cols.items() if v is not None})
        )
        return existing_id  # type: ignore[return-value]

    # place_id match or new record with place_id: atomic upsert
    if normalized.get("place_id"):
        stmt = (
            insert(Company)
            .values(**cols)
            .on_conflict_do_update(
                index_elements=["place_id"],
                set_={k: v for k, v in cols.items() if k != "place_id"},
            )
            .returning(Company.company_id)
        )
        return (await session.execute(stmt)).scalar_one()

    # No place_id (OSM / DLD before enrichment): plain insert
    # trgm near-duplicates are intentionally inserted as new rows for human review
    stmt = insert(Company).values(**cols).returning(Company.company_id)
    return (await session.execute(stmt)).scalar_one()
