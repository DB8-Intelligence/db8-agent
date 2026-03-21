import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="DB8 Intelligence Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    return create_client(url, key)


def get_openai() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI not configured")
    return OpenAI(api_key=api_key)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "DB8 Agent Online 🚀"}


@app.get("/health")
def health():
    return {"status": "healthy"}


# ── Properties ───────────────────────────────────────────────────────────────

class PropertyCreate(BaseModel):
    title: str
    description: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    property_type: Optional[str] = None
    property_standard: Optional[str] = None
    built_area_m2: Optional[float] = None
    highlights: Optional[str] = None
    cover_url: Optional[str] = None
    workspace_id: Optional[str] = None
    source: Optional[str] = "manual"


@app.get("/properties")
def list_properties(workspace_id: Optional[str] = Query(None)):
    supabase = get_supabase()
    query = supabase.table("properties").select("*").order("created_at", desc=True)
    if workspace_id:
        query = query.eq("workspace_id", workspace_id)
    result = query.execute()
    return result.data


@app.post("/properties")
def create_property(payload: PropertyCreate):
    supabase = get_supabase()
    data = payload.model_dump(exclude_none=True)
    data.setdefault("status", "new")
    result = supabase.table("properties").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create property")
    return result.data[0]


@app.patch("/properties/{property_id}")
def update_property_status(
    property_id: str,
    status: Optional[str] = Query(None),
):
    supabase = get_supabase()
    if not status:
        raise HTTPException(status_code=400, detail="status query param is required")
    valid_statuses = {"new", "in_review", "approved", "rejected", "published"}
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    result = (
        supabase.table("properties")
        .update({"status": status})
        .eq("id", property_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Property not found")
    return result.data[0]


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
