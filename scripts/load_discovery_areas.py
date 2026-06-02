#!/usr/bin/env python3
"""
Load curated area seeds (e.g. dubai_area_seeds.csv) into the discovery_areas table.

Only rows flagged keep_for_dubai=true are loaded as Dubai seeds; cross-emirate
rows (keep_for_dubai=false) are loaded under THEIR verified_emirate, turning the
feedback-loop bleed into free seeds for those emirates.

Idempotent: re-running upserts on (emirate, area_name).

Usage (inside the api/worker container, where DB env is set):
    python scripts/load_discovery_areas.py dubai_area_seeds.csv
"""
import asyncio
import csv
import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from app.db.models import DiscoveryArea
from app.db.session import AsyncSessionLocal


def read_rows(path: Path) -> list[dict]:
    out = []
    with path.open() as f:
        for r in csv.DictReader(f):
            name = (r.get("area_name") or "").strip()
            if not name:
                continue
            # Place each row under the emirate it actually belongs to.
            verified = (r.get("verified_emirate") or r.get("emirate") or "Dubai").strip()
            out.append({
                "area_name": name,
                "emirate": verified,
                "source": (r.get("source") or "seed").strip(),
                "is_active": True,
            })
    return out


async def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python scripts/load_discovery_areas.py <csv_path>")
    path = Path(sys.argv[1]).expanduser()
    rows = read_rows(path)
    print(f"Loaded {len(rows)} rows from {path}")

    inserted = 0
    async with AsyncSessionLocal() as session:
        for row in rows:
            stmt = (
                insert(DiscoveryArea)
                .values(**row)
                .on_conflict_do_update(
                    constraint="idx_discovery_area_uniq",
                    set_={"source": row["source"], "is_active": row["is_active"]},
                )
            )
            await session.execute(stmt)
            inserted += 1
        await session.commit()

    # Report per-emirate counts
    from collections import Counter
    by_em = Counter(r["emirate"] for r in rows)
    print(f"Upserted {inserted} areas:")
    for em, c in by_em.most_common():
        print(f"  {em}: {c}")


if __name__ == "__main__":
    asyncio.run(main())
