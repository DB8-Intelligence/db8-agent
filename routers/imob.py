import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from models.imob_models import CaptionRequest, PropertyCreate, WhatsAppProperty
from services.anthropic_ai import claude_chat
from services.supabase import _sb_delete, _sb_get, _sb_patch, _sb_post
from services.video import (
    _FORMAT_SIZES,
    _build_ffmpeg_cmd_with_text,
    _gemini_overlay,
)

router = APIRouter(prefix="", tags=["ImobCreator"])


# -- Properties ----------------------------------------------------------------

@router.get("/properties")
def list_properties(
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
):
    params: Dict[str, str] = {"select": "*", "order": "created_at.desc"}
    if status:       params["status"] = f"eq.{status}"
    if user_id:      params["user_id"] = f"eq.{user_id}"
    if workspace_id: params["workspace_id"] = f"eq.{workspace_id}"
    return _sb_get("properties", params)


@router.get("/properties/{property_id}")
def get_property(property_id: str):
    results = _sb_get("properties", {"select": "*", "id": f"eq.{property_id}"})
    if not results:
        raise HTTPException(status_code=404, detail="Property not found")
    return results[0]


@router.post("/properties")
def create_property(payload: PropertyCreate):
    data: Dict[str, Any] = {k: v for k, v in payload.model_dump().items() if v is not None and v != []}
    data.setdefault("status", "new")
    return _sb_post("properties", data)


@router.patch("/properties/{property_id}")
def update_property(property_id: str, status: Optional[str] = Query(None)):
    if not status:
        raise HTTPException(status_code=400, detail="status query param is required")
    return _sb_patch("properties", "id", property_id, {"status": status})


@router.delete("/properties/{property_id}")
def delete_property(property_id: str):
    result = _sb_delete("properties", "id", property_id)
    return {"deleted": True, "property": result}


# -- Generate Caption ----------------------------------------------------------

@router.post("/generate-caption")
async def generate_caption(payload: CaptionRequest):
    parts = []
    if payload.title:             parts.append(f"Título: {payload.title}")
    if payload.property_type:     parts.append(f"Tipo: {payload.property_type}")
    if payload.property_standard: parts.append(f"Padrão: {payload.property_standard}")
    if payload.city or payload.neighborhood:
        parts.append(f"Localização: {', '.join(filter(None, [payload.neighborhood, payload.city]))}")
    if payload.price or payload.investment_value:
        parts.append(f"Valor: {payload.price or payload.investment_value}")
    if payload.built_area_m2:     parts.append(f"Área: {payload.built_area_m2}m²")
    if payload.highlights:        parts.append(f"Destaques: {payload.highlights}")

    property_info = "\n".join(parts) if parts else "Imóvel disponível"
    post_label = {"feed": "post feed Instagram", "story": "story Instagram",
                  "carousel": "carrossel Instagram", "reels": "legenda para Reels"
                  }.get(payload.type or "feed", "post Instagram")

    user_prompt = f"Crie uma legenda para {post_label}:\n\n{property_info}"
    if payload.custom_prompt: user_prompt += f"\n\nInstruções: {payload.custom_prompt}"
    if payload.ai_prompt:     user_prompt += f"\n\nEstilo: {payload.ai_prompt}"
    if payload.cta:           user_prompt += f"\n\nCTA: {payload.cta}"

    caption = claude_chat(
        system="Você é especialista em marketing imobiliário brasileiro. Crie legendas envolventes com emojis e hashtags. Máximo 300 palavras.",
        user=user_prompt,
        max_tokens=500,
    )
    return {"caption": caption, "type": payload.type}


# -- WhatsApp / N8N webhook ----------------------------------------------------

@router.post("/webhook/whatsapp")
async def whatsapp_webhook(payload: WhatsAppProperty):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    data["status"] = "new"
    data["source"] = "whatsapp"
    result = _sb_post("properties", data)
    return {"success": True, "property_id": result.get("id")}


@router.post("/agent")
async def agent(payload: dict):
    return JSONResponse({"message": "DB8 Agent recebeu os dados", "data": payload})


# -- Video Generation ----------------------------------------------------------

@router.post("/generate-video")
async def generate_video(
    photos: List[UploadFile] = File(...),
    style: str = Form("cinematic"),
    format: str = Form("reels"),
    duration: str = Form("30"),
):
    if len(photos) < 2:
        raise HTTPException(status_code=400, detail="Mínimo 2 fotos necessárias.")

    w, h = _FORMAT_SIZES.get(format, _FORMAT_SIZES["reels"])
    dur = max(5, min(120, int(duration)))

    tmpdir = tempfile.mkdtemp(prefix="imob_video_")
    try:
        # Save uploads to disk
        photo_paths: List[str] = []
        for i, f in enumerate(photos):
            ext = Path(f.filename or "photo.jpg").suffix or ".jpg"
            dest = os.path.join(tmpdir, f"photo_{i:03d}{ext}")
            with open(dest, "wb") as fp:
                fp.write(await f.read())
            photo_paths.append(dest)

        # Gemini text analysis
        overlay = _gemini_overlay(photo_paths)

        # Build & run FFmpeg
        output_path = os.path.join(tmpdir, "output.mp4")
        cmd = _build_ffmpeg_cmd_with_text(
            photo_paths, output_path, w, h, dur, style,
            title=overlay["title"],
            subtitle=overlay["subtitle"],
            cta=overlay["cta"],
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            err_msg = (stderr_bytes or b"").decode(errors="replace")
            raise HTTPException(status_code=500, detail="FFmpeg error: " + err_msg)

        # Stream MP4 and clean up after
        def _stream():
            try:
                with open(output_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        yield chunk
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        return StreamingResponse(
            _stream(),
            media_type="video/mp4",
            headers={"Content-Disposition": "attachment; filename=video-imob.mp4"},
        )

    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc))
