from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from supabase import create_client
import os
from uuid import uuid4

app = FastAPI(title="DB8 Intelligence Agent")

# -----------------------------
# SUPABASE CONFIG
# -----------------------------

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------------
# MODELS
# -----------------------------

class PropertyCreate(BaseModel):
    user_id: str
    property_type: str
    standard: str
    city: str
    neighborhood: str
    investment_value: str
    size_m2: float
    description: str
    images: List[str]

class UpdateStatus(BaseModel):
    status: str

# -----------------------------
# HEALTH
# -----------------------------

@app.get("/health")
def health():
    return {"status": "healthy"}

# -----------------------------
# GET USER
# -----------------------------

@app.get("/me/{user_id}")
def get_user(user_id: str):
    response = supabase.table("users").select("*").eq("id", user_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="User not found")
    return response.data[0]

# -----------------------------
# CREATE PROPERTY
# -----------------------------

@app.post("/properties")
def create_property(property: PropertyCreate):
    data = property.dict()
    data["id"] = str(uuid4())
    data["status"] = "pending"

    response = supabase.table("properties").insert(data).execute()
    return response.data

# -----------------------------
# LIST PROPERTIES BY USER
# -----------------------------

@app.get("/properties/{user_id}")
def list_properties(user_id: str):
    response = supabase.table("properties").select("*").eq("user_id", user_id).execute()
    return response.data

# -----------------------------
# UPDATE PROPERTY STATUS
# -----------------------------

@app.patch("/properties/{property_id}")
def update_property(property_id: str, body: UpdateStatus):
    response = supabase.table("properties") \
        .update({"status": body.status}) \
        .eq("id", property_id) \
        .execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Property not found")

    return response.data[0]

# -----------------------------
# PUBLISH PROPERTY (COM CRÉDITO)
# -----------------------------

@app.post("/properties/{property_id}/publish")
def publish_property(property_id: str):

    # Buscar imóvel
    property_response = supabase.table("properties").select("*").eq("id", property_id).execute()
    if not property_response.data:
        raise HTTPException(status_code=404, detail="Property not found")

    property_data = property_response.data[0]
    user_id = property_data["user_id"]

    # Buscar usuário
    user_response = supabase.table("users").select("*").eq("id", user_id).execute()
    if not user_response.data:
        raise HTTPException(status_code=404, detail="User not found")

    user = user_response.data[0]

    # Validar créditos
    if user["user_plan"] == "credits":
        if user["credits_remaining"] <= 0:
            raise HTTPException(status_code=403, detail="No credits remaining")

        supabase.table("users") \
            .update({"credits_remaining": user["credits_remaining"] - 1}) \
            .eq("id", user_id) \
            .execute()

    # Atualizar status
    supabase.table("properties") \
        .update({"status": "published"}) \
        .eq("id", property_id) \
        .execute()

    return {"message": "Property published successfully"}
