from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from uuid import uuid4

app = FastAPI(title="DB8 Intelligence Agent")

# Banco temporário em memória
properties = []

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

# Criar novo imóvel
@app.post("/properties")
def create_property(property: Property):
    new_property = {
        "id": str(uuid4()),
        "title": property.title,
        "description": property.description,
        "images": property.images,
        "status": "pending"
    }
    properties.append(new_property)
    return new_property

# Listar imóveis
@app.get("/properties")
def list_properties():
    return properties

# Atualizar status (approved / published)
@app.patch("/properties/{property_id}")
def update_property(property_id: str, status: str):
    for item in properties:
        if item["id"] == property_id:
            item["status"] = status
            return item
    raise HTTPException(status_code=404, detail="Property not found")
