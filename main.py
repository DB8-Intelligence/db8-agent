import os
import requests
from fastapi import HTTPException

IG_USER_ID = os.getenv("IG_USER_ID")
IG_TOKEN = os.getenv("IG_ACCESS_TOKEN")

@app.post("/properties/{property_id}/publish")
def publish_property(property_id: str):

    for item in items:
        if item["id"] == property_id:

            if user_data["user_plan"] == "credits":
                if user_data["credits_remaining"] <= 0:
                    raise HTTPException(status_code=403, detail="Sem créditos")
                user_data["credits_remaining"] -= 1

            image_url = item["images"][0]
            caption = item["description"]

            # 1️⃣ Criar container
            container = requests.post(
                f"https://graph.facebook.com/v18.0/{IG_USER_ID}/media",
                data={
                    "image_url": image_url,
                    "caption": caption,
                    "access_token": IG_TOKEN
                }
            ).json()

            if "id" not in container:
                raise HTTPException(status_code=400, detail="Erro ao criar container")

            # 2️⃣ Publicar
            publish = requests.post(
                f"https://graph.facebook.com/v18.0/{IG_USER_ID}/media_publish",
                data={
                    "creation_id": container["id"],
                    "access_token": IG_TOKEN
                }
            ).json()

            if "id" not in publish:
                raise HTTPException(status_code=400, detail="Erro ao publicar")

            item["status"] = "published"
            item["ig_post_id"] = publish["id"]

            return {
                "status": "published",
                "ig_post_id": publish["id"],
                "credits_remaining": user_data["credits_remaining"]
            }

    raise HTTPException(status_code=404, detail="Imóvel não encontrado")
