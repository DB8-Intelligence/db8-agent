import os
from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import List, Optional
from uuid import uuid4
from openai import OpenAI

app = FastAPI(title="DB8 Intelligence Agent")

# Cliente OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Banco temporário
items = []
user_data = {
    "user_plan": "credits",
    "credits_remaining": 20
}

cclass Property(BaseModel):
    property_type: str
    standard: str
    city: str
    neighborhood: str
    investment_value: str
    size_m2: str
    description: str
    images: List[str]

def generate_caption(property: Property):
    prompt = f"""
Você é especialista em marketing imobiliário brasileiro.

Crie um post para Instagram com:
Título chamativo
Descrição persuasiva
CTA
Hashtags

Dados:
Tipo: {property.property_type}
Padrão: {property.standard}
Cidade: {property.city}
Bairro: {property.neighborhood}
Valor: {property.investment_value}
Tamanho: {property.size_m2} m2
Descrição adicional: {property.description}

Formato:
TÍTULO:
DESCRIÇÃO:
CTA:
HASHTAGS:
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    return response.choices[0].message.content

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/properties")
def create_property(property: Property):
    caption = generate_caption(property)

    new_item = {
        "id": str(uuid4()),
        "property_type": property.property_type,
        "standard": property.standard,
        "city": property.city,
        "neighborhood": property.neighborhood,
        "investment_value": property.investment_value,
        "size_m2": property.size_m2,
        "images": property.images,
        "ai_caption": caption,
        "status": "pending"
    }

    items.append(new_item)
    return new_item

@app.get("/properties")
def list_properties():
    return items

@app.patch("/properties/{property_id}")
def update_property(property_id: str, status: str = Query(...)):
    for item in items:
        if item["id"] == property_id:
            item["status"] = status
            return item
    return {"error": "Not found"}

@app.get("/me")
def get_user():
    return user_data

@app.post("/properties/{property_id}/publish")
def publish_property(property_id: str):
    if user_data["user_plan"] == "credits":
        if user_data["credits_remaining"] <= 0:
            return {"error": "Sem créditos disponíveis"}

        user_data["credits_remaining"] -= 1

    for item in items:
        if item["id"] == property_id:
            item["status"] = "published"
            return {
                "message": "Publicado com sucesso",
                "credits_remaining": user_data["credits_remaining"]
            }

    return {"error": "Imóvel não encontrado"}
