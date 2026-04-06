from typing import Dict, List, Optional

from pydantic import BaseModel


class ScriptRequest(BaseModel):
    topic: str
    niche: str           # ia_tech | financas | curiosidades | horror | motivacional
    language: str = "pt-BR"
    source_content: Optional[str] = None
    target_minutes: int = 8
    financial_data: Optional[Dict] = None


class VoiceRequest(BaseModel):
    script: str
    voice_id: str
    niche: str
    language: str = "pt-BR"


class VideoChannelRequest(BaseModel):
    audio_url: str
    niche: str
    template_style: str = "default"
    scene_descriptions: Optional[List[str]] = None


class ThumbnailRequest(BaseModel):
    thumbnail_prompt: str
    title: str
    niche: str
    style: str = "default"


class TrendingRequest(BaseModel):
    niche: str
    language: str = "pt-BR"
    limit: int = 10


class ShortsRequest(BaseModel):
    video_url: str
    script: str
    max_shorts: int = 3
