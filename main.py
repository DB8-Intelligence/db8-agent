import os
import requests as req
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="DB8 Agent", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Supabase REST helpers (no SDK needed) ────────────────────────────────────

SB_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SB_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY", "")
)

def _sb_headers() -> Dict[str, str]:
    return {
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def _sb_url(table: str) -> str:
    if not SB_URL:
        raise HTTPException(status_code=500, detail="SUPABASE_URL não configurado no Railway.")
    if not SB_KEY:
        raise HTTPException(status_code=500, detail="SUPABASE_SERVICE_ROLE não configurado no Railway.")
    return f"{SB_URL}/rest/v1/{table}"

def _sb_get(table: str, params: Dict[str, str]) -> list:
    r = req.get(_sb_url(table), headers=_sb_headers(), params=params, timeout=10)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Supabase error: {r.text[:300]}")
    return r.json()

def _sb_post(table: str, data: Dict) -> Dict:
    r = req.post(_sb_url(table), headers=_sb_headers(), json=data, timeout=10)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Supabase error: {r.text[:300]}")
    result = r.json()
    return result[0] if isinstance(result, list) else result

def _sb_patch(table: str, filter_col: str, filter_val: str, data: Dict) -> Dict:
    params = {filter_col: f"eq.{filter_val}"}
    r = req.patch(_sb_url(table), headers=_sb_headers(), params=params, json=data, timeout=10)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Supabase error: {r.text[:300]}")
    result = r.json()
    if not result:
        raise HTTPException(status_code=404, detail="Record not found")
    return result[0] if isinstance(result, list) else result

def _sb_delete(table: str, filter_col: str, filter_val: str) -> Dict:
    params = {filter_col: f"eq.{filter_val}"}
    r = req.delete(_sb_url(table), headers=_sb_headers(), params=params, timeout=10)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Supabase error: {r.text[:300]}")
    result = r.json()
    if not result:
        raise HTTPException(status_code=404, detail="Record not found")
    return result[0] if isinstance(result, list) else result

def _openai_chat(messages: list) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY não configurado no Railway.")
    r = req.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": "gpt-4o-mini", "messages": messages, "max_tokens": 500, "temperature": 0.8},
        timeout=30,
    )
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"].strip()


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "DB8 Agent Online 🚀", "version": "0.4.0"}

@app.get("/health")
def health():
    sb_ok = bool(SB_URL and SB_KEY)
    return {
        "status": "healthy" if sb_ok else "degraded",
        "supabase_configured": sb_ok,
        "supabase_url_present": bool(SB_URL),
        "supabase_key_present": bool(SB_KEY),
    }


# ── Models ────────────────────────────────────────────────────────────────────

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


# ── Properties ────────────────────────────────────────────────────────────────

@app.get("/properties")
def list_properties(
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
):
    params: Dict[str, str] = {"select": "*", "order": "created_at.desc"}
    if status:       params["status"] = f"eq.{status}"
    if user_id:      params["user_id"] = f"eq.{user_id}"
    if workspace_id: params["workspace_id"] = f"eq.{workspace_id}"
    return _sb_get("properties", params)

@app.get("/properties/{property_id}")
def get_property(property_id: str):
    results = _sb_get("properties", {"select": "*", "id": f"eq.{property_id}"})
    if not results:
        raise HTTPException(status_code=404, detail="Property not found")
    return results[0]

@app.post("/properties")
def create_property(payload: PropertyCreate):
    data: Dict[str, Any] = {k: v for k, v in payload.model_dump().items() if v is not None and v != []}
    data.setdefault("status", "new")
    return _sb_post("properties", data)

@app.patch("/properties/{property_id}")
def update_property(property_id: str, status: Optional[str] = Query(None)):
    if not status:
        raise HTTPException(status_code=400, detail="status query param is required")
    return _sb_patch("properties", "id", property_id, {"status": status})

@app.delete("/properties/{property_id}")
def delete_property(property_id: str):
    result = _sb_delete("properties", "id", property_id)
    return {"deleted": True, "property": result}


# ── Generate Caption ──────────────────────────────────────────────────────────

@app.post("/generate-caption")
async def generate_caption(payload: CaptionRequest):
    parts = []
    if payload.title:             parts.append(f"Título: {payload.title}")
    if payload.property_type:     parts.append(f"Tipo: {payload.property_type}")
    if payload.property_standard: parts.append(f"Padrão: {payload.property_standard}")
    if payload.city or payload.neighborhood:
        parts.append(f"Localização: {', '.join(filter(None, [payload.neighborhood, payload.city]))}")
    if payload.price or payload.investment_value:
        parts.append(f"Valor: {payload.price or payload.investment_value}")
    if payload.built_area_m2:     parts.append(f"Área: {payload.built_area_m2}m²")
    if payload.highlights:        parts.append(f"Destaques: {payload.highlights}")

    property_info = "\n".join(parts) if parts else "Imóvel disponível"
    post_label = {"feed": "post feed Instagram", "story": "story Instagram",
                  "carousel": "carrossel Instagram", "reels": "legenda para Reels"
                  }.get(payload.type or "feed", "post Instagram")

    user_prompt = f"Crie uma legenda para {post_label}:\n\n{property_info}"
    if payload.custom_prompt: user_prompt += f"\n\nInstruções: {payload.custom_prompt}"
    if payload.ai_prompt:     user_prompt += f"\n\nEstilo: {payload.ai_prompt}"
    if payload.cta:           user_prompt += f"\n\nCTA: {payload.cta}"

    caption = _openai_chat([
        {"role": "system", "content": (
            "Você é especialista em marketing imobiliário brasileiro. "
            "Crie legendas envolventes com emojis e hashtags. Máximo 300 palavras."
        )},
        {"role": "user", "content": user_prompt},
    ])
    return {"caption": caption, "type": payload.type}


# ── WhatsApp / N8N webhook ────────────────────────────────────────────────────

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(payload: WhatsAppProperty):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    data["status"] = "new"
    data["source"] = "whatsapp"
    result = _sb_post("properties", data)
    return {"success": True, "property_id": result.get("id")}

@app.post("/agent")
async def agent(payload: dict):
    return JSONResponse({"message": "DB8 Agent recebeu os dados", "data": payload})
