from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SuppressionList


async def is_suppressed(
    value: str,
    value_type: str,
    session: AsyncSession,
) -> bool:
    row = (
        await session.execute(
            select(SuppressionList).where(
                SuppressionList.value_type == value_type,
                SuppressionList.value == value,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def add_to_suppression(
    value: str,
    value_type: str,
    reason: Optional[str],
    session: AsyncSession,
) -> None:
    stmt = (
        insert(SuppressionList)
        .values(value=value, value_type=value_type, reason=reason)
        .on_conflict_do_nothing(constraint="idx_suppression_value")
    )
    await session.execute(stmt)


async def remove_from_suppression(
    value: str,
    value_type: str,
    session: AsyncSession,
) -> bool:
    from sqlalchemy import delete

    result = await session.execute(
        delete(SuppressionList).where(
            SuppressionList.value_type == value_type,
            SuppressionList.value == value,
        )
    )
    return result.rowcount > 0
