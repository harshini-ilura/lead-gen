#!/usr/bin/env python3
"""
One-time script: build a comprehensive Dubai (or any emirate) area seed list for
Google Places discovery.

Strategy (three layers):
  1. SEED   — load a CSV of known areas (e.g. Bayut export). New-development coverage.
  2. LOOP   — query Places "real estate agency {area} {emirate}" for each seed,
              extract every sublocality_level_1 / neighborhood from the results'
              addressComponents. New areas feed back into the queue. Converges.
              This fills the old-Dubai gap Bayut structurally misses.
  3. OUTPUT — merged, deduplicated, normalized CSV with provenance for review.

The loop's discovered names are already Google-canonical (they come straight out
of the Places index), so a separate Geocoding normalization pass is unnecessary.

Usage:
    python scripts/build_area_seed_list.py \
        --input ~/Downloads/dubai_locations_full.csv \
        --emirate Dubai \
        --output dubai_area_seeds.csv \
        --max-queries 400

Reads GOOGLE_MAPS_API_KEY from .env (or env var). Costs ~$0.032 per query — the
--max-queries cap bounds spend (400 queries ≈ $12.80).
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import httpx

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
SEARCH_FIELD_MASK = "places.id,places.displayName,places.addressComponents"

# English-ish language codes Google returns. Pure-Arabic ("ar") is rejected by
# the script-check below even if it slips through here.
_LATIN_LANGS = {"en", "en-US", "en-GB", "ar-Latn"}

# Words that indicate a UI/category link rather than a real area name.
_NOISE = {
    "buy", "sell", "rent", "sale", "property", "properties", "apartment",
    "villa", "studio", "office", "shop", "commercial", "warehouse", "bedroom",
    "search", "more", "view", "all", "page", "next", "back",
}


def load_api_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if key:
        return key
    # Fall back to .env next to the project root
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("GOOGLE_MAPS_API_KEY="):
                return line.split("=", 1)[1].strip()
    sys.exit("ERROR: GOOGLE_MAPS_API_KEY not found in env or .env")


def is_latin(text: str) -> bool:
    """Reject names containing Arabic (or other non-Latin) script."""
    for ch in text:
        if ch.isalpha() and ord(ch) > 0x2AF:  # beyond Latin Extended-B
            return False
    return True


def normalize(name: str) -> str:
    """Canonical form for dedup: strip, collapse spaces, title-case, fix casing."""
    name = unicodedata.normalize("NFKC", name).strip()
    name = re.sub(r"\s+", " ", name)
    # Preserve existing all-caps acronyms in parentheses like (JVC), (DIP)
    return name


def dedup_key(name: str) -> str:
    """Loose key so 'Abu Hail' and 'Abu hail' collapse to one."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load_seeds(path: Path) -> list[str]:
    rows = []
    with path.open() as f:
        reader = csv.DictReader(f)
        # Accept either a "Location" column or first column
        field = "Location" if "Location" in (reader.fieldnames or []) else reader.fieldnames[0]
        for r in reader:
            val = (r.get(field) or "").strip()
            if val:
                rows.append(normalize(val))
    return rows


def query_places(client: httpx.Client, api_key: str, query: str) -> list[dict]:
    resp = client.post(
        PLACES_SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": SEARCH_FIELD_MASK,
        },
        json={"textQuery": query, "maxResultCount": 20, "languageCode": "en"},
        timeout=20,
    )
    if resp.status_code != 200:
        print(f"    ! API error {resp.status_code}: {resp.text[:120]}")
        return []
    return resp.json().get("places", [])


def extract_areas(place: dict) -> set[str]:
    """Pull Google-canonical sublocality / neighborhood names from one place."""
    found = set()
    for comp in place.get("addressComponents", []):
        types = comp.get("types", [])
        lang = comp.get("languageCode", "")
        name = comp.get("longText", "").strip()
        if not name or len(name) < 3 or len(name) > 60:
            continue
        if lang not in _LATIN_LANGS or not is_latin(name):
            continue
        if any(w == name.lower() for w in _NOISE):
            continue
        if "sublocality_level_1" in types or "neighborhood" in types:
            found.add(normalize(name))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="CSV of seed area names")
    ap.add_argument("--emirate", default="Dubai", help="Emirate to append to queries")
    ap.add_argument("--output", default="area_seeds.csv", help="Output CSV path")
    ap.add_argument("--max-queries", type=int, default=400,
                    help="Hard cap on API calls (cost guard; 400 ≈ $12.80)")
    ap.add_argument("--max-rounds", type=int, default=8,
                    help="Max convergence rounds")
    ap.add_argument("--qps-delay", type=float, default=0.12,
                    help="Delay between API calls (seconds) to respect quota")
    args = ap.parse_args()

    api_key = load_api_key()
    seeds = load_seeds(Path(args.input).expanduser())
    print(f"Loaded {len(seeds)} seed areas from {args.input}")

    # State: dedup_key -> {"name": canonical, "source": "bayut"|"loop", "seen": int}
    known: dict[str, dict] = {}
    for s in seeds:
        known[dedup_key(s)] = {"name": s, "source": "seed", "seen": 0, "emirate": args.emirate}

    queue = list(seeds)
    visited: set[str] = set()
    query_count = 0
    round_num = 0

    client = httpx.Client()
    try:
        while queue and query_count < args.max_queries and round_num < args.max_rounds:
            round_num += 1
            batch = queue[:]
            queue = []
            new_this_round = 0
            print(f"\n── Round {round_num}: {len(batch)} areas to query "
                  f"(spent {query_count}/{args.max_queries} queries) ──")

            for area in batch:
                if query_count >= args.max_queries:
                    print("    (query budget exhausted — stopping)")
                    break
                key = dedup_key(area)
                if key in visited:
                    continue
                visited.add(key)

                query = f"real estate agency {area} {args.emirate}"
                places = query_places(client, api_key, query)
                query_count += 1
                time.sleep(args.qps_delay)

                discovered = set()
                for p in places:
                    discovered |= extract_areas(p)

                for d in discovered:
                    dk = dedup_key(d)
                    if dk in known:
                        known[dk]["seen"] += 1
                    else:
                        known[dk] = {"name": d, "source": "loop", "seen": 1,
                                     "emirate": args.emirate}
                        queue.append(d)
                        new_this_round += 1

            print(f"    → {new_this_round} new areas discovered "
                  f"(total known: {len(known)})")
            if new_this_round == 0:
                print("    ✓ Converged — no new areas")
                break
    finally:
        client.close()

    # Write output sorted by source then name
    out_path = Path(args.output)
    rows = sorted(known.values(), key=lambda r: (r["source"] != "seed", r["name"].lower()))
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["area_name", "emirate", "source", "times_seen_in_results"])
        for r in rows:
            w.writerow([r["name"], r["emirate"], r["source"], r["seen"]])

    seed_count = sum(1 for r in rows if r["source"] == "seed")
    loop_count = sum(1 for r in rows if r["source"] == "loop")
    cost = query_count * 0.032
    print(f"\n{'='*55}")
    print(f"Done. {len(rows)} total areas → {out_path}")
    print(f"  from seed CSV: {seed_count}")
    print(f"  newly discovered by feedback loop: {loop_count}")
    print(f"  API queries used: {query_count}  (~${cost:.2f})")
    print(f"  converged in {round_num} rounds")


if __name__ == "__main__":
    main()
