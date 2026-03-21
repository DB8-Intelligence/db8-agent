import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="DB8 Agent", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

_supabase: Optional[Client] = (
    create_client(SUPABASE_URL, SUPABASE_KEY)
    if SUPABASE_URL and SUPABASE_KEY
    else None
)

TABLE_PROPERTIES = "properties"


def get_supabase() -> Client:
    if _supabase is None:
        raise HTTPException(
            status_code=500,
            detail="Supabase não configurado. Verifique SUPABASE_URL e SUPABASE_SERVICE_ROLE no Railway.",
        )
    return _supabase


def get_openai() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY não configurado no Railway.")
    return OpenAI(api_key=api_key)


def _sb_error(e: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=f"Supabase error: {str(e)}")


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "DB8 Agent Online 🚀", "version": "0.3.0"}


@app.get("/health")
def health():
    ok = _supabase is not None
    return {
        "status": "healthy" if ok else "degraded",
        "supabase_configured": ok,
        "supabase_url_present": bool(SUPABASE_URL),
        "supabase_key_present": bool(SUPABASE_KEY),
    }


# ── Properties ───────────────────────────────────────────────────────────────

class PropertyCreate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    property_type: Optional[str] = None
    property_standard: Optional[str] = None
    standard: Optional[str] = None
    investment_value: Optional[float] = None
    built_area_m2: Optional[float] = None
    size_m2: Optional[float] = None
    highlights: Optional[str] = None
    cover_url: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    source: Optional[str] = "manual"


class PropertyUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    property_type: Optional[str] = None
    standard: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    investment_value: Optional[float] = None
    size_m2: Optional[float] = None
    images: Optional[List[str]] = None
    status: Optional[str] = None


@app.get("/properties")
def list_properties(
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
):
    sb = get_supabase()
    try:
        q = sb.table(TABLE_PROPERTIES).select("*").order("created_at", desc=True)
        if status:
            q = q.eq("status", status)
        if user_id:
            q = q.eq("user_id", user_id)
        if workspace_id:
            q = q.eq("workspace_id", workspace_id)
        return q.execute().data or []
    except Exception as e:
        raise _sb_error(e)


@app.get("/properties/{property_id}")
def get_property(property_id: str):
    sb = get_supabase()
    try:
        res = sb.table(TABLE_PROPERTIES).select("*").eq("id", property_id).single().execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Property not found")
        return res.data
    except HTTPException:
        raise
    except Exception as e:
        raise _sb_error(e)


@app.post("/properties")
def create_property(payload: PropertyCreate):
    sb = get_supabase()
    try:
        data: Dict[str, Any] = {k: v for k, v in payload.model_dump().items() if v is not None and v != []}
        data.setdefault("status", "new")
        res = sb.table(TABLE_PROPERTIES).insert(data).execute()
        if not res.data:
            raise HTTPException(status_code=500, detail="Failed to create property")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise _sb_error(e)


@app.patch("/properties/{property_id}")
def update_property(
    property_id: str,
    status: Optional[str] = Query(None),
):
    """Update property status via query param: PATCH /properties/{id}?status=approved"""
    sb = get_supabase()
    if not status:
        raise HTTPException(status_code=400, detail="status query param is required")
    try:
        res = sb.table(TABLE_PROPERTIES).update({"status": status}).eq("id", property_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Property not found")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise _sb_error(e)


@app.delete("/properties/{property_id}")
def delete_property(property_id: str):
    sb = get_supabase()
    try:
        res = sb.table(TABLE_PROPERTIES).delete().eq("id", property_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Property not found")
        return {"deleted": True, "property": res.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise _sb_error(e)


# ── Generate Caption ──────────────────────────────────────────────────────────

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


@app.post("/generate-caption")
async def generate_caption(payload: CaptionRequest):
    client = get_openai()

    parts = []
    if payload.title:
        parts.append(f"Título: {payload.title}")
    if payload.property_type:
        parts.append(f"Tipo: {payload.property_type}")
    if payload.property_standard:
        parts.append(f"Padrão: {payload.property_standard}")
    if payload.city or payload.neighborhood:
        location = ", ".join(filter(None, [payload.neighborhood, payload.city]))
        parts.append(f"Localização: {location}")
    if payload.price or payload.investment_value:
        parts.append(f"Valor: {payload.price or payload.investment_value}")
    if payload.built_area_m2:
        parts.append(f"Área: {payload.built_area_m2}m²")
    if payload.highlights:
        parts.append(f"Destaques: {payload.highlights}")

    property_info = "\n".join(parts) if parts else "Imóvel disponível"

    post_type_label = {
        "feed": "post feed Instagram",
        "story": "story Instagram",
        "carousel": "carrossel Instagram",
        "reels": "legenda para Reels",
    }.get(payload.type or "feed", "post Instagram")

    system_prompt = (
        "Você é um especialista em marketing imobiliário brasileiro. "
        "Crie legendas envolventes, com emojis estratégicos e hashtags relevantes. "
        "Use linguagem profissional mas acessível. Máximo 300 palavras."
    )

    user_prompt = f"Crie uma legenda para {post_type_label} com base nestas informações:\n\n{property_info}"
    if payload.custom_prompt:
        user_prompt += f"\n\nInstruções adicionais:\n{payload.custom_prompt}"
    if payload.ai_prompt:
        user_prompt += f"\n\nEstilo solicitado: {payload.ai_prompt}"
    if payload.cta:
        user_prompt += f"\n\nInclua este CTA no final: {payload.cta}"

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
            temperature=0.8,
        )
        caption = response.choices[0].message.content.strip()
        return {"caption": caption, "type": payload.type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Caption generation failed: {str(e)}")


# ── WhatsApp / N8N webhook ────────────────────────────────────────────────────

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


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(payload: WhatsAppProperty):
    """Recebe dados de imóvel do N8N/WhatsApp e salva no Supabase."""
    supabase = get_supabase()
    data = payload.model_dump(exclude_none=True)
    data["status"] = "new"
    data["source"] = "whatsapp"
    result = supabase.table("properties").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to save property")
    return {"success": True, "property_id": result.data[0]["id"]}


@app.post("/agent")
async def agent(payload: dict):
    return JSONResponse({
        "message": "DB8 Agent recebeu os dados",
        "data": payload
    })
