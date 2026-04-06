from typing import List, Optional

from pydantic import BaseModel, Field


class PropertyCreate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    property_type: Optional[str] = None
    property_standard: Optional[str] = None
    investment_value: Optional[float] = None
    built_area_m2: Optional[float] = None
    highlights: Optional[str] = None
    cover_url: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    source: Optional[str] = "manual"


class CaptionRequest(BaseModel):
    type: Optional[str] = "feed"
    property_type: Optional[str] = None
    property_standard: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    investment_value: Optional[str] = None
    built_area_m2: Optional[float] = None
    highlights: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    price: Optional[str] = None
    cta: Optional[str] = None
    ai_prompt: Optional[str] = None
    custom_prompt: Optional[str] = None


class WhatsAppProperty(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    property_type: Optional[str] = None
    cover_url: Optional[str] = None
    workspace_id: Optional[str] = None
    phone: Optional[str] = None
    raw_message: Optional[str] = None
