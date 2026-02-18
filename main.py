from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from uuid import UUID, uuid4
from supabase import create_client, Client
import os

# ==========================
# CONFIGURAÇÃO SUPABASE
# ==========================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)

# ==========================
# FASTAPI
# ==========================

app = FastAPI()

# ==========================
# MODEL
# ==========================

class PropertyCreate(BaseModel):
    user_id: UUID
    property_type: str
    standard: str
    city: str
    neighborhood: str
    investment_value: float
    size_m2: float
    description: str
    images: List[str]

# ==========================
# HEALTH CHECK
# ==========================

@app.get("/")
def read_root():
    return {"status": "DB8 Agent Online"}

# ==========================
# CREATE PROPERTY
# ==========================

@app.post("/properties")
def create_property(property: PropertyCreate):

    data = property.dict()

    # Gerar UUID compatível com banco
    data["id"] = str(uuid4())

    # Status padrão
    data["status"] = "pending"

    # Supabase aceita jsonb automaticamente
    response = supabase.table("properties").insert(data).execute()

    return response.data

# ==========================
# LIST PROPERTIES
# ==========================

@app.get("/properties")
def list_properties():
    response = supabase.table("properties").select("*").execute()
    return response.data
