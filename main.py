import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests as req
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

app = FastAPI(title="DB8 Agent", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Supabase REST helpers (no SDK needed) ────────────────────────────────────

SB_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SB_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY", "")
)

def _sb_headers() -> Dict[str, str]:
    return {
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def _sb_url(table: str) -> str:
    if not SB_URL:
        raise HTTPException(status_code=500, detail="SUPABASE_URL não configurado no Railway.")
    if not SB_KEY:
        raise HTTPException(status_code=500, detail="SUPABASE_SERVICE_ROLE não configurado no Railway.")
    return f"{SB_URL}/rest/v1/{table}"

def _sb_get(table: str, params: Dict[str, str]) -> list:
    r = req.get(_sb_url(table), headers=_sb_headers(), params=params, timeout=10)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Supabase error: {r.text[:300]}")
    return r.json()

def _sb_post(table: str, data: Dict) -> Dict:
    r = req.post(_sb_url(table), headers=_sb_headers(), json=data, timeout=10)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Supabase error: {r.text[:300]}")
    result = r.json()
    return result[0] if isinstance(result, list) else result

def _sb_patch(table: str, filter_col: str, filter_val: str, data: Dict) -> Dict:
    params = {filter_col: f"eq.{filter_val}"}
    r = req.patch(_sb_url(table), headers=_sb_headers(), params=params, json=data, timeout=10)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Supabase error: {r.text[:300]}")
    result = r.json()
    if not result:
        raise HTTPException(status_code=404, detail="Record not found")
    return result[0] if isinstance(result, list) else result

def _sb_delete(table: str, filter_col: str, filter_val: str) -> Dict:
    params = {filter_col: f"eq.{filter_val}"}
    r = req.delete(_sb_url(table), headers=_sb_headers(), params=params, timeout=10)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Supabase error: {r.text[:300]}")
    result = r.json()
    if not result:
        raise HTTPException(status_code=404, detail="Record not found")
    return result[0] if isinstance(result, list) else result

def _openai_chat(messages: list) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY não configurado no Railway.")
    r = req.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": "gpt-4o-mini", "messages": messages, "max_tokens": 500, "temperature": 0.8},
        timeout=30,
    )
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"].strip()


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "DB8 Agent Online 🚀", "version": "0.4.0"}

@app.get("/health")
def health():
    sb_ok = bool(SB_URL and SB_KEY)
    return {
        "status": "healthy" if sb_ok else "degraded",
        "supabase_configured": sb_ok,
        "supabase_url_present": bool(SB_URL),
        "supabase_key_present": bool(SB_KEY),
    }


# ── Models ────────────────────────────────────────────────────────────────────

class PropertyCreate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    property_type: Optional[str] = None
    property_standard: Optional[str] = None
    investment_value: Optional[float] = None
    built_area_m2: Optional[float] = None
    highlights: Optional[str] = None
    cover_url: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    source: Optional[str] = "manual"

class CaptionRequest(BaseModel):
    type: Optional[str] = "feed"
    property_type: Optional[str] = None
    property_standard: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    investment_value: Optional[str] = None
    built_area_m2: Optional[float] = None
    highlights: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    price: Optional[str] = None
    cta: Optional[str] = None
    ai_prompt: Optional[str] = None
    custom_prompt: Optional[str] = None

class WhatsAppProperty(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    property_type: Optional[str] = None
    cover_url: Optional[str] = None
    workspace_id: Optional[str] = None
    phone: Optional[str] = None
    raw_message: Optional[str] = None


# ── Properties ────────────────────────────────────────────────────────────────

@app.get("/properties")
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

@app.get("/properties/{property_id}")
def get_property(property_id: str):
    results = _sb_get("properties", {"select": "*", "id": f"eq.{property_id}"})
    if not results:
        raise HTTPException(status_code=404, detail="Property not found")
    return results[0]

@app.post("/properties")
def create_property(payload: PropertyCreate):
    data: Dict[str, Any] = {k: v for k, v in payload.model_dump().items() if v is not None and v != []}
    data.setdefault("status", "new")
    return _sb_post("properties", data)

@app.patch("/properties/{property_id}")
def update_property(property_id: str, status: Optional[str] = Query(None)):
    if not status:
        raise HTTPException(status_code=400, detail="status query param is required")
    return _sb_patch("properties", "id", property_id, {"status": status})

@app.delete("/properties/{property_id}")
def delete_property(property_id: str):
    result = _sb_delete("properties", "id", property_id)
    return {"deleted": True, "property": result}


# ── Generate Caption ──────────────────────────────────────────────────────────

@app.post("/generate-caption")
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

    caption = _openai_chat([
        {"role": "system", "content": (
            "Você é especialista em marketing imobiliário brasileiro. "
            "Crie legendas envolventes com emojis e hashtags. Máximo 300 palavras."
        )},
        {"role": "user", "content": user_prompt},
    ])
    return {"caption": caption, "type": payload.type}


# ── WhatsApp / N8N webhook ────────────────────────────────────────────────────

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(payload: WhatsAppProperty):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    data["status"] = "new"
    data["source"] = "whatsapp"
    result = _sb_post("properties", data)
    return {"success": True, "property_id": result.get("id")}

@app.post("/agent")
async def agent(payload: dict):
    return JSONResponse({"message": "DB8 Agent recebeu os dados", "data": payload})


# ── Video Generation ──────────────────────────────────────────────────────────

_FORMAT_SIZES: Dict[str, tuple] = {
    "reels":   (1080, 1920),
    "feed":    (1080, 1080),
    "youtube": (1920, 1080),
}

_STYLE_EQ: Dict[str, str] = {
    "cinematic": "contrast=1.1:brightness=-0.05:saturation=0.75",
    "moderno":   "contrast=1.2:saturation=1.3:brightness=0.02",
    "luxury":    "contrast=1.0:brightness=0.08:saturation=0.65:gamma=1.15",
}

_FPS = 25


def _find_font() -> str:
    """Return path to a bold sans-serif font, or '' if none found."""
    try:
        r = subprocess.run(
            ["fc-match", "Sans:bold", "--format=%{file}"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return ""


def _esc(text: str) -> str:
    """Escape text for FFmpeg drawtext filter value."""
    return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def _gemini_overlay(photo_paths: List[str]) -> Dict[str, str]:
    """Analyze up to 3 photos with Gemini and return PT-BR title/subtitle/cta."""
    api_key = os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    default = {"title": "Imóvel Exclusivo", "subtitle": "Qualidade e sofisticação", "cta": "Entre em contato"}
    if not api_key:
        return default
    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        parts: list = []
        for path in photo_paths[:3]:
            ext = Path(path).suffix.lower().lstrip(".")
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
            with open(path, "rb") as f:
                parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(f.read()).decode()}})
        parts.append(
            "Analise as fotos deste imóvel e gere em português brasileiro:\n"
            "1. title: título impactante (máx 35 chars)\n"
            "2. subtitle: subtítulo descritivo (máx 55 chars)\n"
            "3. cta: chamada para ação curta (máx 22 chars)\n\n"
            'Responda APENAS com JSON: {"title": "...", "subtitle": "...", "cta": "..."}'
        )
        text = model.generate_content(parts).text.strip()
        m = re.search(r'\{[^}]+\}', text, re.DOTALL)
        if m:
            return {**default, **json.loads(m.group())}
    except Exception:
        pass
    return default


def _build_ffmpeg_cmd(
    photo_paths: List[str], output_path: str,
    w: int, h: int, dur: int, style: str,
) -> List[str]:
    n = len(photo_paths)
    spp = dur / n                        # seconds per photo
    fade = min(0.5, spp * 0.25)         # crossfade duration
    zoom_frames = int((spp + fade) * _FPS)
    eq = _STYLE_EQ.get(style, _STYLE_EQ["cinematic"])
    scale_crop = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"

    cmd = ["ffmpeg", "-y"]
    for p in photo_paths:
        cmd += ["-loop", "1", "-t", f"{spp + fade:.3f}", "-i", p]

    filters: List[str] = []

    # Per-photo: scale + Ken Burns zoompan
    for i in range(n):
        if i % 2 == 0:
            zoom = "'min(zoom+0.0015,1.3)'"
        else:
            zoom = "'if(lte(zoom,1.0),1.3,max(1.0,zoom-0.0015))'"
        cx = "'iw/2-(iw/zoom/2)'"
        cy = "'ih/2-(ih/zoom/2)'"
        filters.append(
            f"[{i}:v]{scale_crop},"
            f"zoompan=z={zoom}:d={zoom_frames}:x={cx}:y={cy}:s={w}x{h}:fps={_FPS},"
            f"setpts=PTS-STARTPTS[v{i}]"
        )

    # Xfade chain → [vmerge]
    if n == 1:
        filters.append("[v0]null[vmerge]")
    else:
        prev = "v0"
        for i in range(1, n):
            tag = f"xf{i}" if i < n - 1 else "vmerge"
            offset = i * (spp - fade)
            filters.append(f"[{prev}][v{i}]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}[{tag}]")
            prev = tag

    # Color grade
    filters.append(f"[vmerge]eq={eq}[vcolor]")

    # Text overlays
    font_path = _find_font()
    font_arg = f"fontfile='{font_path}'" if font_path else "font=Sans"
    # (populated later from Gemini — we pass placeholders here; caller replaces)
    filters.append(f"[vcolor]null[vout]")

    filter_str = ";".join(filters)
    cmd += [
        "-filter_complex", filter_str,
        "-map", "[vout]", "-an",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-t", str(dur), output_path,
    ]
    return cmd


def _build_ffmpeg_cmd_with_text(
    photo_paths: List[str], output_path: str,
    w: int, h: int, dur: int, style: str,
    title: str, subtitle: str, cta: str,
) -> List[str]:
    n = len(photo_paths)
    spp = dur / n
    fade = min(0.5, spp * 0.25)
    zoom_frames = int((spp + fade) * _FPS)
    eq = _STYLE_EQ.get(style, _STYLE_EQ["cinematic"])
    scale_crop = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    font_path = _find_font()
    font_arg = f"fontfile='{font_path}'" if font_path else "font=Sans"

    cmd = ["ffmpeg", "-y"]
    for p in photo_paths:
        cmd += ["-loop", "1", "-t", f"{spp + fade:.3f}", "-i", p]

    filters: List[str] = []

    for i in range(n):
        zoom = "'min(zoom+0.0015,1.3)'" if i % 2 == 0 else "'if(lte(zoom,1.0),1.3,max(1.0,zoom-0.0015))'"
        cx, cy = "'iw/2-(iw/zoom/2)'", "'ih/2-(ih/zoom/2)'"
        filters.append(
            f"[{i}:v]{scale_crop},"
            f"zoompan=z={zoom}:d={zoom_frames}:x={cx}:y={cy}:s={w}x{h}:fps={_FPS},"
            f"setpts=PTS-STARTPTS[v{i}]"
        )

    if n == 1:
        filters.append("[v0]null[vmerge]")
    else:
        prev = "v0"
        for i in range(1, n):
            tag = f"xf{i}" if i < n - 1 else "vmerge"
            offset = i * (spp - fade)
            filters.append(f"[{prev}][v{i}]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}[{tag}]")
            prev = tag

    filters.append(f"[vmerge]eq={eq}[vcolor]")

    title_end = dur * 0.45
    cta_start = dur * 0.70
    fs_title = min(72, max(40, w // 16))
    fs_sub   = min(44, max(24, w // 26))
    fs_cta   = min(52, max(28, w // 20))

    drawtext = (
        f"[vcolor]"
        f"drawtext={font_arg}:text='{_esc(title)}':fontcolor=white:fontsize={fs_title}:"
        f"x=(w-text_w)/2:y=h*0.10:shadowcolor=black@0.7:shadowx=3:shadowy=3:"
        f"enable='between(t,0,{title_end:.2f})',"
        f"drawtext={font_arg}:text='{_esc(subtitle)}':fontcolor=white@0.90:fontsize={fs_sub}:"
        f"x=(w-text_w)/2:y=h*0.19:shadowcolor=black@0.7:shadowx=2:shadowy=2:"
        f"enable='between(t,0,{title_end:.2f})',"
        f"drawtext={font_arg}:text='{_esc(cta)}':fontcolor=white:fontsize={fs_cta}:"
        f"x=(w-text_w)/2:y=h*0.82:box=1:boxcolor=black@0.45:boxborderw=18:"
        f"enable='between(t,{cta_start:.2f},{dur})'[vout]"
    )
    filters.append(drawtext)

    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-an",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-t", str(dur), output_path,
    ]
    return cmd


@app.post("/generate-video")
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
