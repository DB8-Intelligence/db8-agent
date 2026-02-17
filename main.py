from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from uuid import uuid4

app = FastAPI(title="DB8 Intelligence Agent")

# ============================
# BANCO TEMPORÁRIO EM MEMÓRIA
# ============================

properties_db = []
user_data = {
    "user_plan": "credits",  # "pro" ou "credits"
    "credits_remaining": 20
}

# ============================
# MODELOS
# ============================

class Property(BaseModel):
    property_type: str
    standard: str
    city: str
    neighborhood: str
    investment_value: str
    size_m2: str
    description: str
    images: List[str]

class UpdateCredits(BaseModel):
    credits_remaining: int


# ============================
# ROTAS BÁSICAS
# ============================

@app.get("/")
def root():
    return {"status": "DB8 Agent Online 🚀"}

@app.get("/health")
def health():
    return {"status": "healthy"}


# ============================
# PROPERTIES
# ============================

@app.post("/properties")
def create_property(property: Property):
    new_property = {
        "id": str(uuid4()),
        **property.dict(),
        "status": "pending"
    }
    properties_db.append(new_property)
    return new_property


@app.get("/properties")
def list_properties():
    return properties_db


@app.patch("/properties/{property_id}")
def update_property(
    property_id: str,
    status: Optional[str] = Query(None)
):
    for property in properties_db:
        if property["id"] == property_id:
            if status:
                property["status"] = status
            return property

    raise HTTPException(status_code=404, detail="Property not found")


@app.post("/properties/{property_id}/publish")
def publish_property(property_id: str):
    for property in properties_db:
        if property["id"] == property_id:

            # Se for plano credits, validar saldo
            if user_data["user_plan"] == "credits":
                if user_data["credits_remaining"] <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail="No credits remaining"
                    )
                user_data["credits_remaining"] -= 1

            property["status"] = "published"

            return {
                "message": "Property published successfully",
                "property": property,
                "credits_remaining": user_data["credits_remaining"]
            }

    raise HTTPException(status_code=404, detail="Property not found")


# ============================
# USER / PLAN / CREDITS
# ============================

@app.get("/me")
def get_user():
    return user_data


@app.patch("/me")
def update_user(data: UpdateCredits):
    user_data["credits_remaining"] = data.credits_remaining
    return user_data
