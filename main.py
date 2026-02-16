from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from uuid import uuid4

app = FastAPI(title="DB8 Intelligence Agent")

items = []

user_data = {
    "user_plan": "credits",  # altere aqui para testar
    "credits_remaining": 3
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

@app.get("/properties")
def list_properties():
    return items

@app.patch("/properties/{property_id}")
def update_property(property_id: str, status: str):
    for item in items:
        if item["id"] == property_id:
            item["status"] = status
            return item
    raise HTTPException(status_code=404, detail="Not found")

@app.post("/properties/{property_id}/publish")
def publish_property(property_id: str):
    global user_data

    if user_data["user_plan"] == "credits":
        if user_data["credits_remaining"] <= 0:
            raise HTTPException(status_code=403, detail="Sem créditos disponíveis")

        user_data["credits_remaining"] -= 1

    for item in items:
        if item["id"] == property_id:
            item["status"] = "published"
            return {
                "message": "Publicado com sucesso",
                "credits_remaining": user_data["credits_remaining"]
            }

    raise HTTPException(status_code=404, detail="Imóvel não encontrado")

@app.get("/me")
def get_user():
    return user_data
