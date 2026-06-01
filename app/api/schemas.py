from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CompanyRead(BaseModel):
    company_id: int
    place_id: Optional[str] = None
    company_name: str
    normalized_name: Optional[str] = None
    website: Optional[str] = None
    domain: Optional[str] = None
    industry: Optional[str] = None
    subcategory: Optional[str] = None
    city: Optional[str] = None
    emirate: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    phone_e164: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    google_rating: Optional[float] = None
    rating_count: Optional[int] = None
    source: Optional[str] = None
    confidence_score: Optional[float] = None
    crawl_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiscoveryTriggerRequest(BaseModel):
    emirate: str = "Dubai"
    use_dld: bool = True
    areas: Optional[list[str]] = None


class DiscoveryTriggerResponse(BaseModel):
    enqueued: int
    message: str


class SuppressionCreate(BaseModel):
    value: str
    value_type: str  # email | domain | phone
    reason: Optional[str] = None


class SuppressionRead(BaseModel):
    id: int
    value: str
    value_type: str
    reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
