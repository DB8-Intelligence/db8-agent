from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from uuid import uuid4

app = FastAPI(title="DB8 Intelligence Agent")

# Banco temporário em memória
items = []

user_data = {
    "user_plan": "pro",
    "credits_remaining": 20
}

class Property(BaseModel):
    title: str
    description: str
    images: List[str]

@app.get("/")
def root():
    return {"status": "DB8 Agent Online 🚀"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# 🔹 CRIAR IMÓVEL
@app.post("/properties")
def create_property(property: Property):
    new_item = {
        "id": str(uuid4()),
        "title": property.title,
        "description": property.description,
        "images": property.images,
        "status": "pending"
    }
    items.append(new_item)
    return new_item

# 🔹 LISTAR IMÓVEIS
@app.get("/properties")
def list_properties():
    return items

# 🔹 ATUALIZAR STATUS DO IMÓVEL
@app.patch("/properties/{property_id}")
def update_property(property_id: str, status: str):
    for item in items:
        if item["id"] == property_id:
            item["status"] = status
            return item
    return {"error": "Not found"}

# 🔹 CONSULTAR USUÁRIO (CRÉDITOS)
@app.get("/me")
def get_user():
    return user_data

# 🔹 ATUALIZAR CRÉDITOS
@app.patch("/me")
def update_user(data: dict):
    if "credits_remaining" in data:
        user_data["credits_remaining"] = data["credits_remaining"]
    return user_data
