import os
import re
import json
import requests
from uuid import uuid4
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Body, Query
from pydantic import BaseModel, Field
from supabase import create_client, Client


# -----------------------------
# Config
# -----------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@db8.local")

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()  # openai | gemini
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="DB8 Intelligence Agent (Supabase SaaS)")


# -----------------------------
# Data Models
# -----------------------------
class PropertyCreate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    images: List[str] = Field(default_factory=list)

    # Campos nacionais
    property_type: str  # apartamento | casa | lancamento | terreno | oportunidade
    property_standard: str  # baixo | medio | luxo
    city: str
    neighborhood: str
    investment_value: str
    built_area_m2: float
    highlights: Optional[str] = ""

    # origem
    source: Optional[str] = "manual"  # manual | whatsapp
    sender_phone: Optional[str] = None

    # template
    template_id: Optional[str] = None


class PropertyPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    caption_final: Optional[str] = None
    images: Optional[List[str]] = None
    status: Optional[str] = None
    template_id: Optional[str] = None

    # campos nacionais editáveis
    property_type: Optional[str] = None
    property_standard: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    investment_value: Optional[str] = None
    built_area_m2: Optional[float] = None
    highlights: Optional[str] = None


class TemplateCreate(BaseModel):
    name: str
    logo_url: Optional[str] = None
    frame_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    footer_text: Optional[str] = None
    logo_position: Optional[str] = "bottom-right"


class TemplatePatch(BaseModel):
    name: Optional[str] = None
    logo_url: Optional[str] = None
    frame_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    footer_text: Optional[str] = None
    logo_position: Optional[str] = None


# -----------------------------
# Helpers: User (single-admin MVP)
# -----------------------------
def get_or_create_user() -> Dict[str, Any]:
    res = supabase.table("users").select("*").eq("email", ADMIN_EMAIL).limit(1).execute()
    if res.data and len(res.data) > 0:
        return res.data[0]

    created = supabase.table("users").insert({
        "email": ADMIN_EMAIL,
        "user_plan": "credits",          # para testes
        "credits_remaining": 20
    }).execute()

    if not created.data:
        raise HTTPException(status_code=500, detail="Failed to create default user")

    return created.data[0]


def update_user_credits(new_credits: int) -> Dict[str, Any]:
    user = get_or_create_user()
    upd = supabase.table("users").update({
        "credits_remaining": new_credits
    }).eq("id", user["id"]).execute()
    return upd.data[0] if upd.data else user


# -----------------------------
# Helpers: Prompt Engine
# -----------------------------
def normalize(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


PROMPT_HEADER = """
Você é especialista em marketing imobiliário no Brasil e copywriter para Instagram.
Crie uma legenda persuasiva, clara e altamente convertível, sem inventar dados.

Regras gerais:
- Não invente número de quartos/suítes se não estiver nos diferenciais.
- Seja compatível com qualquer estado/cidade do Brasil.
- Use linguagem humana, objetiva e profissional.
- Inclua CTA forte e 5–10 hashtags (misture locais + imobiliárias).
- Saída sempre em JSON estrito com as chaves:
  title, caption, bullets, cta, hashtags
"""

def prompt_by_niche(property_type: str, property_standard: str) -> str:
    pt = normalize(property_type)
    st = normalize(property_standard)

    # padronização de termos
    if pt in ["lançamento", "lancamento"]:
        pt = "lancamento"

    if st in ["médio", "medio"]:
        st = "medio"

    base = PROMPT_HEADER.strip()

    if pt == "apartamento":
        niche = f"""
Nicho: APARTAMENTO
Padrão: {st}

Ajuste o tom conforme o padrão:
- baixo: custo-benefício, financiamento, oportunidade, praticidade.
- medio: conforto, localização, rotina, valorização equilibrada.
- luxo: exclusividade, sofisticação, alto padrão, diferenciais premium.
"""
    elif pt == "casa":
        niche = f"""
Nicho: CASA
Padrão: {st}

Ajuste o tom conforme o padrão:
- baixo: primeira moradia, espaço, quintal (se houver), viabilidade.
- medio: qualidade de vida, conforto, segurança, localização.
- luxo: arquitetura, privacidade, sofisticação e exclusividade.
"""
    elif pt == "lancamento":
        niche = """
Nicho: LANÇAMENTO
Foco: valorização futura, condições especiais, escassez, entrada facilitada (se mencionado),
benefícios do empreendimento e da localização.
"""
    elif pt == "terreno":
        niche = """
Nicho: TERRENO
Foco: potencial construtivo, localização, investimento, segurança jurídica (sem promessas),
possibilidades de projeto (sem exageros).
"""
    elif pt == "oportunidade":
        niche = """
Nicho: OPORTUNIDADE
Foco: urgência/escassez, preço atrativo, rapidez no contato.
Não inventar desconto; use apenas se estiver nos diferenciais.
"""
    else:
        niche = """
Nicho: IMÓVEL (genérico)
Foco: clareza, benefícios reais e CTA.
"""

    return (base + "\n" + niche).strip()


def build_prompt_payload(p: Dict[str, Any]) -> str:
    niche_prompt = prompt_by_niche(p.get("property_type", ""), p.get("property_standard", ""))

    details = {
        "tipo": p.get("property_type"),
        "padrao": p.get("property_standard"),
        "cidade": p.get("city"),
        "bairro": p.get("neighborhood"),
        "valor": p.get("investment_value"),
        "area_m2": p.get("built_area_m2"),
        "diferenciais": p.get("highlights") or "",
        "texto_original": p.get("caption_original") or p.get("description") or ""
    }

    return f"""{niche_prompt}

Dados do imóvel (use apenas isso):
{json.dumps(details, ensure_ascii=False)}

Requisitos de formatação:
- Retorne SOMENTE o JSON final (sem markdown, sem texto fora do JSON).
"""


# -----------------------------
# Helpers: AI Calls
# -----------------------------
def call_openai(prompt: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "Você gera copy imobiliária em JSON estrito."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }

    r = requests.post(url, headers=headers, json=payload, timeout=60)
    if r.status_code >= 400:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {r.status_code} - {r.text}")

    content = r.json()["choices"][0]["message"]["content"].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # fallback simples: tenta extrair JSON
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise HTTPException(status_code=500, detail="OpenAI returned invalid JSON")
        return json.loads(match.group(0))


def call_gemini(prompt: str) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7}
    }

    r = requests.post(url, json=payload, timeout=60)
    if r.status_code >= 400:
        raise HTTPException(status_code=500, detail=f"Gemini error: {r.status_code} - {r.text}")

    text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise HTTPException(status_code=500, detail="Gemini returned invalid JSON")
        return json.loads(match.group(0))


def generate_caption_json(p: Dict[str, Any]) -> Dict[str, Any]:
    prompt = build_prompt_payload(p)
    if AI_PROVIDER == "gemini":
        return call_gemini(prompt)
    return call_openai(prompt)


# -----------------------------
# API
# -----------------------------
@app.get("/")
def root():
    return {"status": "DB8 Agent Online 🚀"}

@app.get("/health")
def health():
    return {"status": "healthy"}


# -----------------------------
# /me (user plan & credits)
# -----------------------------
@app.get("/me")
def get_me():
    user = get_or_create_user()
    return {
        "id": user["id"],
        "email": user["email"],
        "user_plan": user["user_plan"],
        "credits_remaining": user["credits_remaining"],
    }

@app.patch("/me")
def patch_me(data: Dict[str, Any] = Body(default={})):
    # MVP: permite atualizar credits_remaining e/ou user_plan (se quiser liberar)
    user = get_or_create_user()
    upd_payload = {}

    if "credits_remaining" in data:
        upd_payload["credits_remaining"] = int(data["credits_remaining"])

    if "user_plan" in data:
        upd_payload["user_plan"] = str(data["user_plan"])

    if not upd_payload:
        return {
            "id": user["id"],
            "email": user["email"],
            "user_plan": user["user_plan"],
            "credits_remaining": user["credits_remaining"],
        }

    upd = supabase.table("users").update(upd_payload).eq("id", user["id"]).execute()
    if not upd.data:
        raise HTTPException(status_code=500, detail="Failed to update user")
    user = upd.data[0]
    return {
        "id": user["id"],
        "email": user["email"],
        "user_plan": user["user_plan"],
        "credits_remaining": user["credits_remaining"],
    }


# -----------------------------
# Templates CRUD
# -----------------------------
@app.get("/templates")
def list_templates():
    res = supabase.table("templates").select("*").order("created_at", desc=True).execute()
    return res.data or []

@app.post("/templates")
def create_template(t: TemplateCreate):
    res = supabase.table("templates").insert(t.model_dump()).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create template")
    return res.data[0]

@app.patch("/templates/{template_id}")
def patch_template(template_id: str, t: TemplatePatch):
    payload = {k: v for k, v in t.model_dump().items() if v is not None}
    if not payload:
        # no-op
        cur = supabase.table("templates").select("*").eq("id", template_id).limit(1).execute()
        if not cur.data:
            raise HTTPException(status_code=404, detail="Template not found")
        return cur.data[0]

    res = supabase.table("templates").update(payload).eq("id", template_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Template not found")
    return res.data[0]

@app.delete("/templates/{template_id}")
def delete_template(template_id: str):
    res = supabase.table("templates").delete().eq("id", template_id).execute()
    return {"ok": True}


# -----------------------------
# Properties
# -----------------------------
@app.get("/properties")
def list_properties(status: Optional[str] = Query(default=None)):
    q = supabase.table("properties").select("*").order("created_at", desc=True)
    if status:
        q = q.eq("status", status)
    res = q.execute()
    return res.data or []


@app.post("/properties")
def create_property(p: PropertyCreate):
    # Salva "caption_original" e gera "caption_ai" automaticamente
    payload = {
        "source": p.source or "manual",
        "sender_phone": p.sender_phone,
        "title": p.title,
        "caption_original": p.description or "",
        "images": p.images,
        "status": "pending",
        "template_id": p.template_id,

        # campos nacionais
        "property_type": p.property_type,
        "property_standard": p.property_standard,
        "city": p.city,
        "neighborhood": p.neighborhood,
        "investment_value": p.investment_value,
        "built_area_m2": p.built_area_m2,
        "highlights": p.highlights or "",
    }

    # IA gera caption_ai (JSON)
    try:
        ai_json = generate_caption_json(payload)
    except Exception as e:
        # não derruba o fluxo: salva com erro e caption_ai vazio
        ai_json = None

    if ai_json:
        payload["caption_ai"] = json.dumps(ai_json, ensure_ascii=False)
        # Preenche caption_final com uma versão “pronta” (caption + hashtags)
        caption = ai_json.get("caption", "")
        hashtags = ai_json.get("hashtags", [])
        if isinstance(hashtags, list):
            hashtags_text = " ".join(hashtags)
        else:
            hashtags_text = str(hashtags)
        payload["caption_final"] = (caption + "\n\n" + hashtags_text).strip()
        payload["title"] = payload["title"] or ai_json.get("title") or payload["title"]
    else:
        payload["caption_ai"] = None
        payload["caption_final"] = payload["caption_original"]
        payload["status"] = "error"

    res = supabase.table("properties").insert(payload).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create property")
    return res.data[0]


@app.patch("/properties/{property_id}")
def patch_property(
    property_id: str,
    status: Optional[str] = Query(default=None),  # compat: status via query (se precisar)
    body: PropertyPatch = Body(default=PropertyPatch())
):
    payload = {k: v for k, v in body.model_dump().items() if v is not None}

    # compatibilidade: se status veio em query, sobrescreve
    if status:
        payload["status"] = status

    # ajustes de campos do banco:
    if "description" in payload:
        payload["caption_original"] = payload.pop("description")

    if "caption_final" in payload:
        payload["caption_final"] = payload["caption_final"]

    if not payload:
        cur = supabase.table("properties").select("*").eq("id", property_id).limit(1).execute()
        if not cur.data:
            raise HTTPException(status_code=404, detail="Property not found")
        return cur.data[0]

    res = supabase.table("properties").update(payload).eq("id", property_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Property not found")
    return res.data[0]


@app.post("/properties/{property_id}/publish")
def publish_property(property_id: str):
    """
    Backend controla cobrança.
    - Se user_plan == 'credits': precisa ter credits_remaining > 0, decrementa 1.
    - Atualiza status do imóvel para 'approved' (ou 'published' se quiser).
    - (n8n/IG real entra depois)
    """
    user = get_or_create_user()

    if user["user_plan"] == "credits":
        if int(user["credits_remaining"]) <= 0:
            raise HTTPException(status_code=403, detail="Sem créditos disponíveis")
        # decrementa
        new_credits = int(user["credits_remaining"]) - 1
        user = update_user_credits(new_credits)

    # atualiza propriedade
    res = supabase.table("properties").update({
        "status": "approved"
    }).eq("id", property_id).execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Property not found")

    prop = res.data[0]

    return {
        "ok": True,
        "property": prop,
        "user": {
            "user_plan": user["user_plan"],
            "credits_remaining": user["credits_remaining"]
        }
    }
