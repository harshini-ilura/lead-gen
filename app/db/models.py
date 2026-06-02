from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Double, Index, Integer, Numeric, Text,
    TIMESTAMP, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    company_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    place_id: Mapped[Optional[str]] = mapped_column(Text, unique=True, nullable=True)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[Optional[str]] = mapped_column(Text)
    website: Mapped[Optional[str]] = mapped_column(Text)
    domain: Mapped[Optional[str]] = mapped_column(Text)
    industry: Mapped[Optional[str]] = mapped_column(Text)
    subcategory: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(Text)
    emirate: Mapped[Optional[str]] = mapped_column(Text)
    country: Mapped[Optional[str]] = mapped_column(Text, server_default="AE")
    phone: Mapped[Optional[str]] = mapped_column(Text)
    phone_e164: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text)
    linkedin_url: Mapped[Optional[str]] = mapped_column(Text)
    instagram_url: Mapped[Optional[str]] = mapped_column(Text)
    address: Mapped[Optional[str]] = mapped_column(Text)
    latitude: Mapped[Optional[float]] = mapped_column(Double)
    longitude: Mapped[Optional[float]] = mapped_column(Double)
    google_rating: Mapped[Optional[float]] = mapped_column(Numeric(2, 1))
    rating_count: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[Optional[str]] = mapped_column(Text)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    crawl_status: Mapped[Optional[str]] = mapped_column(Text, server_default="discovered")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_companies_domain", "domain"),
        Index("idx_companies_phone", "phone_e164"),
        Index(
            "idx_companies_norm_name",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
    )


class Contact(Base):
    __tablename__ = "contacts"

    contact_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    full_name: Mapped[Optional[str]] = mapped_column(Text)
    first_name: Mapped[Optional[str]] = mapped_column(Text)
    last_name: Mapped[Optional[str]] = mapped_column(Text)
    job_title: Mapped[Optional[str]] = mapped_column(Text)
    seniority: Mapped[Optional[str]] = mapped_column(Text)
    linkedin_url: Mapped[Optional[str]] = mapped_column(Text)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class ContactEmail(Base):
    __tablename__ = "contact_emails"

    email_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contact_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    pattern: Mapped[Optional[str]] = mapped_column(Text)
    generation_confidence: Mapped[Optional[str]] = mapped_column(Text)
    verification_status: Mapped[Optional[str]] = mapped_column(Text, server_default="unknown")
    verification_source: Mapped[Optional[str]] = mapped_column(Text)
    is_role_email: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="false")
    verified_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class CrawlCache(Base):
    __tablename__ = "crawl_cache"

    url_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    domain: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(Text)
    raw_html: Mapped[Optional[str]] = mapped_column(Text)
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    next_recrawl_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))


class DiscoveryArea(Base):
    """Seed areas that Beat/API fan out into Places discovery queries.

    Populated from curated CSV exports (source='seed') and grown by the
    address-component feedback loop (source='loop').
    """
    __tablename__ = "discovery_areas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    area_name: Mapped[str] = mapped_column(Text, nullable=False)
    emirate: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(Text, server_default="seed")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Stats updated after each discovery run for prioritisation / saturation.
    times_seen: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    last_run_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    last_result_count: Mapped[Optional[int]] = mapped_column(Integer)
    is_saturated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("emirate", "area_name", name="idx_discovery_area_uniq"),
        Index("idx_discovery_areas_active", "emirate", "is_active"),
    )


class SuppressionList(Base):
    __tablename__ = "suppression_list"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("value_type", "value", name="idx_suppression_value"),
    )
