import os
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client

# ============================
# APP
# ============================

app = FastAPI(title="DB8 Agent", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # depois a gente restringe
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================
# SUPABASE (SERVER-SIDE)
# ============================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    # Não quebra o deploy; mas deixa claro no /health
    supabase: Optional[Client] = None
else:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE_PROPERTIES = "properties"


# ============================
# MODELS (BATEM COM A TABELA DO SUPABASE)
# ============================

class PropertyCreate(BaseModel):
    user_id: UUID
    property_type: str
    standard: str
    city: str
    neighborhood: str
    investment_value: float
    size_m2: float
    description: str
    images: List[str] = Field(default_factory=list)  # jsonb no Supabase aceita array


class PropertyUpdate(BaseModel):
    # Tudo opcional para PATCH
    property_type: Optional[str] = None
    standard: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    investment_value: Optional[float] = None
    size_m2: Optional[float] = None
    description: Optional[str] = None
    images: Optional[List[str]] = None
    status: Optional[str] = None


# ============================
# HELPERS
# ============================

def _require_supabase() -> Client:
    if supabase is None:
        raise HTTPException(
            status_code=500,
            detail="Supabase não configurado. Verifique SUPABASE_URL e SUPABASE_SERVICE_ROLE/SUPABASE_KEY no Railway.",
        )
    return supabase


def _sb_error_to_http(e: Exception) -> HTTPException:
    # Evita “500 genérico” e mostra o erro real
    return HTTPException(status_code=500, detail=f"Supabase error: {str(e)}")


# ============================
# ROTAS BÁSICAS
# ============================

@app.get("/")
def read_root():
    return {"status": "DB8 Agent Online 🚀"}


@app.get("/health")
def health():
    ok = (supabase is not None)
    return {
        "status": "healthy" if ok else "degraded",
        "supabase_configured": ok,
        "supabase_url_present": bool(SUPABASE_URL),
        "supabase_key_present": bool(SUPABASE_KEY),
    }


# ============================
# PROPERTIES — CRUD COMPLETO
# ============================

@app.get("/properties")
def list_properties(status: Optional[str] = None, user_id: Optional[UUID] = None):
    sb = _require_supabase()
    try:
        q = sb.table(TABLE_PROPERTIES).select("*").order("created_at", desc=True)
        if status:
            q = q.eq("status", status)
        if user_id:
            q = q.eq("user_id", str(user_id))
        res = q.execute()
        return res.data or []
    except Exception as e:
        raise _sb_error_to_http(e)


@app.get("/properties/{property_id}")
def get_property(property_id: UUID):
    sb = _require_supabase()
    try:
        res = sb.table(TABLE_PROPERTIES).select("*").eq("id", str(property_id)).single().execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Property not found")
        return res.data
    except HTTPException:
        raise
    except Exception as e:
        raise _sb_error_to_http(e)


@app.post("/properties")
def create_property(payload: PropertyCreate):
    sb = _require_supabase()
    try:
        data: Dict[str, Any] = payload.model_dump()
        # status e created_at já existem no banco (default), mas garantimos status:
        data["status"] = "pending"
        res = sb.table(TABLE_PROPERTIES).insert(data).execute()
        return (res.data or [None])[0]
    except Exception as e:
        raise _sb_error_to_http(e)


@app.patch("/properties/{property_id}")
def update_property(property_id: UUID, payload: PropertyUpdate):
    sb = _require_supabase()
    try:
        patch = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not patch:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        res = sb.table(TABLE_PROPERTIES).update(patch).eq("id", str(property_id)).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Property not found")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise _sb_error_to_http(e)


@app.delete("/properties/{property_id}")
def delete_property(property_id: UUID):
    sb = _require_supabase()
    try:
        # retorna o item deletado (Supabase costuma retornar data)
        res = sb.table(TABLE_PROPERTIES).delete().eq("id", str(property_id)).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Property not found")
        return {"deleted": True, "property": res.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise _sb_error_to_http(e)
