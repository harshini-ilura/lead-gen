#!/usr/bin/env python3
"""
Non-destructive enrichment of the area seed CSV.

The feedback-loop discovery query "real estate agency {area} Dubai" sometimes
harvests sublocalities from agencies physically located in neighbouring emirates
(Ajman/Sharjah border Dubai). Rather than delete those rows — they are valuable
seeds for those OTHER emirates — we add a `verified_emirate` column flagging
each row, so nothing is lost.

Adds columns:
  verified_emirate  — Dubai | Ajman | Sharjah | Abu Dhabi | RAK | (blank = assumed Dubai)
  keep_for_dubai    — true/false (false = cross-emirate bleed, use elsewhere)

Input/output default to dubai_area_seeds.csv (enriched in place).
"""
import csv
import sys
from pathlib import Path

# Substring markers for areas that belong to a non-Dubai emirate.
# Conservative — only well-known cross-border names.
NON_DUBAI = {
    "Ajman": [
        "nuaimia", "nuaimiya", "mowaihat", "muwaihat", "muaihat", "mwaihat",
        "hamidiya", "rumailah", "al jerf", "ajman", "al bustan", "al nakhil",
        "al rawda", "al owan", "rashidiya 2", "rashidiya 3",
    ],
    "Sharjah": [
        "al majaz", "qasimia", "al khan", "al taawun", "al soor", "al layyah",
        "ghuwair", "mussalla", "abu shagara", "al nahda first", "al badee",
        "al nad", "al khalidiya district", "al jazeera al hamra", "al manakh",
        "muwaileh", "al ghuwair", "al mussalla",
    ],
    "Abu Dhabi": [
        "reem island", "khalifa city", "mussafah", "al raha", "yas island",
        "saadiyat", "al shamkha", "al bateen", "al mushrif", "al zahiyah",
    ],
    "Ras Al Khaimah": ["al hamra rak", "al nakheel rak"],
}


def classify(name: str) -> str:
    low = name.lower()
    for emirate, markers in NON_DUBAI.items():
        if any(m in low for m in markers):
            return emirate
    return "Dubai"


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "dubai_area_seeds.csv")
    rows = list(csv.DictReader(path.open()))

    counts = {}
    for r in rows:
        verified = classify(r["area_name"])
        r["verified_emirate"] = verified
        r["keep_for_dubai"] = "true" if verified == "Dubai" else "false"
        counts[verified] = counts.get(verified, 0) + 1

    fieldnames = ["area_name", "emirate", "verified_emirate", "keep_for_dubai",
                  "source", "times_seen_in_results"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    total = len(rows)
    dubai = counts.get("Dubai", 0)
    print(f"Enriched {total} rows in {path}")
    print(f"  Dubai (keep):        {dubai}")
    for em in ("Ajman", "Sharjah", "Abu Dhabi", "Ras Al Khaimah"):
        if counts.get(em):
            print(f"  {em} (bonus seeds):  {counts[em]}")


if __name__ == "__main__":
    main()
