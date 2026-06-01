from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SuppressionCreate, SuppressionRead
from app.db.models import SuppressionList
from app.db.session import get_db
from app.services.suppression import add_to_suppression, remove_from_suppression

router = APIRouter(tags=["suppression"])


@router.post("/suppression", response_model=SuppressionRead, status_code=201)
async def add_suppression(body: SuppressionCreate, db: AsyncSession = Depends(get_db)):
    await add_to_suppression(body.value, body.value_type, body.reason, db)
    row = (
        await db.execute(
            select(SuppressionList).where(
                SuppressionList.value_type == body.value_type,
                SuppressionList.value == body.value,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=500, detail="Insert failed")
    return row


@router.delete("/suppression")
async def delete_suppression(
    value: str = Query(...),
    value_type: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    removed = await remove_from_suppression(value, value_type, db)
    if not removed:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"removed": True}


@router.get("/suppression", response_model=list[SuppressionRead])
async def list_suppression(
    value_type: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    q = select(SuppressionList)
    if value_type:
        q = q.where(SuppressionList.value_type == value_type)
    q = q.order_by(SuppressionList.created_at.desc()).limit(limit).offset(offset)
    return (await db.execute(q)).scalars().all()
