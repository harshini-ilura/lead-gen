# LeadGen Documentation

LeadGen is a Celery-based pipeline that discovers real-estate companies, crawls
their sites, extracts contacts, generates & verifies emails, and hands qualified
leads to outreach. Each phase is an independent worker stage connected by Redis
queues and the Postgres data model.

## Pipeline phases (in order)

| # | Phase | Doc | What it does |
|---|---|---|---|
| 1 | Discovery | [discovery.md](discovery.md) | Google Places Text Search over a curated area list → `companies` |
| 2 | Crawl | [crawl.md](crawl.md) | Fetch each company website, cache HTML → `crawl_cache` |
| 3 | Contact extraction | [contacts.md](contacts.md) | LLM (gpt-4o-mini) pulls people from cached HTML → `contacts` |
| 4 | Email generation | [emails.md](emails.md) | Generate likely emails from name + domain patterns → `contact_emails` |
| 5 | Verification | [verify.md](verify.md) | MX (+ optional paid) checks; flag one primary email per contact |
| 6 | Lead scoring | [scoring.md](scoring.md) | Weighted score (email + seniority + company + completeness) → `confidence_score` |
| 7 | Outreach handoff | [handoff.md](handoff.md) | Qualify + suppression-gate + deliver leads to the outreach webhook |

## Data flow

```
discovery_areas → [1 discover] → companies → [2 crawl] → crawl_cache
   → [3 extract contacts] → contacts → [4 generate emails] → contact_emails
   → [5 verify] → verified emails (+ is_primary) → [6 score] → contacts.confidence_score
   → [7 handoff] → outreach webhook (qualified + suppression-cleared leads)
```

## Architecture diagrams

One per phase, in [`diagrams/`](diagrams/):

- [Phase 1 — Discovery](diagrams/phase1_architecture.png)
- [Phase 2 — Crawl](diagrams/phase2_architecture.png)
- [Phase 3 — Contact extraction](diagrams/phase3_architecture.png)
- [Phase 4 — Email generation](diagrams/phase4_architecture.png)
- [Phase 5 — Verification](diagrams/phase5_architecture.png)
- [Phase 6 — Lead scoring](diagrams/phase6_architecture.png)
- [Phase 7 — Outreach handoff](diagrams/phase7_architecture.png)

## Status

All 7 phases are implemented and verified. Real outreach delivery activates once
`OUTREACH_WEBHOOK_URL` is set. A reconciliation sweeper for stranded tasks (crawl
and contact stages) is the main remaining hardening item.

## Running

See each phase doc for its trigger endpoint and verification steps. Common setup:

```bash
docker compose up -d
docker compose exec api alembic upgrade head     # apply all migrations
# keys in .env: GOOGLE_MAPS_API_KEY (Phase 1), OPENAI_API_KEY (Phase 3),
#               MILLIONVERIFIER_API_KEY + PAID_VERIFY_ENABLED (Phase 5, optional),
#               OUTREACH_WEBHOOK_URL (Phase 7, optional)
```
