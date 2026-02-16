# ==========================================================
# DB8 INTELLIGENCE AGENT
# Backend SaaS - Railway + Supabase
# ==========================================================

import os
import json
import re
import requests
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Body
from pydantic import BaseModel
from supabase import create_client, Client

# ==========================================================
# 🔧 CONFIGURAÇÕES
# ==========================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@db8.local")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing Supabase environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="DB8 Intelligence Agent SaaS")

# ==========================================================
# 🧠 MODELOS
# ==========================================================

class PropertyCreate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    images: List[str]

    property_type: str
    property_standard: str
    city: str
    neighborhood: str
    investment_value: str
    built_area_m2: float
    highlights: Optional[str] = ""

class PropertyPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    caption_final: Optional[str] = None
    status: Optional[str] = None
    property_type: Optional[str] = None
    property_standard: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    investment_value: Optional[str] = None
    built_area_m2: Optional[float] = None
    highlights: Optional[str] = None

# ==========================================================
# 👤 USUÁRIO (SaaS - MVP single user)
# ==========================================================

def get_or_create_user():
    res = supabase.table("users").select("*").eq("email", ADMIN_EMAIL).limit(1).execute()

    if res.data:
        return res.data[0]

    created = supabase.table("users").insert({
        "email": ADMIN_EMAIL,
        "user_plan": "credits",
        "credits_remaining": 20
    }).execute()

    return created.data[0]

def decrement_credit():
    user = get_or_create_user()

    if user["user_plan"] == "credits":
        if user["credits_remaining"] <= 0:
            raise HTTPException(status_code=403, detail="Sem créditos disponíveis")

        new_credits = user["credits_remaining"] - 1

        supabase.table("users").update({
            "credits_remaining": new_credits
        }).eq("id", user["id"]).execute()

        return new_credits

    return user["credits_remaining"]

# ==========================================================
# 🎯 SELEÇÃO INTELIGENTE DE PROMPT
# ==========================================================

def select_prompt(property_type: str, property_standard: str):

    pt = property_type.lower()
    ps = property_standard.lower()

    if pt == "apartamento":
        if ps == "luxo":
            return "APARTAMENTO_LUXO"
        elif ps == "medio":
            return "APARTAMENTO_MEDIO"
        else:
            return "APARTAMENTO_BAIXO"

    if pt == "casa":
        if ps == "luxo":
            return "CASA_LUXO"
        elif ps == "medio":
            return "CASA_MEDIO"
        else:
            return "CASA_BAIXO"

    if pt == "lancamento":
        return "LANCAMENTO"

    if pt == "terreno":
        return "TERRENO"

    if pt == "oportunidade":
        return "OPORTUNIDADE"

    return "PADRAO"

# ==========================================================
# ✍️ CONSTRUÇÃO DO PROMPT
# ==========================================================

def build_prompt(data: Dict[str, Any]):

    prompt_type = select_prompt(
        data["property_type"],
        data["property_standard"]
    )

    return f"""
Você é especialista em marketing imobiliário no Brasil.

Tipo de copy: {prompt_type}

Dados do imóvel:

Cidade: {data["city"]}
Bairro: {data["neighborhood"]}
Valor: {data["investment_value"]}
Área: {data["built_area_m2"]} m²
Diferenciais: {data.get("highlights","")}

Crie:

1) Título impactante
2) Texto envolvente
3) Lista de diferenciais
4) CTA forte
5) Hashtags locais

Retorne apenas JSON válido com:
title, caption, bullets, cta, hashtags
"""

# ==========================================================
# 🤖 CHAMADA OPENAI
# ==========================================================

def generate_ai_caption(data):

    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API Key missing")

    prompt = build_prompt(data)

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Você gera copy imobiliária em JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
    )

    if response.status_code >= 400:
        raise HTTPException(status_code=500, detail=response.text)

    content = response.json()["choices"][0]["message"]["content"]

    try:
        return json.loads(content)
    except:
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            return json.loads(match.group(0))
        raise HTTPException(status_code=500, detail="Invalid JSON from AI")

# ==========================================================
# 📦 ENDPOINTS
# ==========================================================

@app.get("/")
def root():
    return {"status": "DB8 Agent Online 🚀"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/me")
def get_me():
    return get_or_create_user()

@app.get("/properties")
def list_properties(status: Optional[str] = Query(None)):
    query = supabase.table("properties").select("*")

    if status:
        query = query.eq("status", status)

    result = query.execute()
    return result.data

@app.post("/properties")
def create_property(property: PropertyCreate):

    data = property.model_dump()

    ai_result = generate_ai_caption(data)

    insert_payload = {
        **data,
        "caption_ai": json.dumps(ai_result),
        "caption_final": ai_result.get("caption"),
        "status": "pending"
    }

    result = supabase.table("properties").insert(insert_payload).execute()

    return result.data[0]

@app.patch("/properties/{property_id}")
def update_property(property_id: str, body: PropertyPatch):

    payload = {k: v for k, v in body.model_dump().items() if v is not None}

    result = supabase.table("properties").update(payload).eq("id", property_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Property not found")

    return result.data[0]

@app.post("/properties/{property_id}/publish")
def publish_property(property_id: str):

    decrement_credit()

    result = supabase.table("properties").update({
        "status": "approved"
    }).eq("id", property_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Property not found")

    return {
        "status": "approved",
        "credits_remaining": get_or_create_user()["credits_remaining"]
    }
