import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
from typing import List

import httpx
import requests as req
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from models.channel_models import (
    ScriptRequest,
    ShortsRequest,
    ThumbnailRequest,
    TrendingRequest,
    VideoChannelRequest,
    VoiceRequest,
)
from services.anthropic_ai import claude_chat
from services.auth import require_service_key
from services.video import _FORMAT_SIZES, _STYLE_EQ, _FPS, _build_ffmpeg_cmd_with_text, _find_font, _esc

router = APIRouter(prefix="/channel", tags=["ChannelOS"])


# -- System prompts per niche --------------------------------------------------

SYSTEM_PROMPTS = {
    "ia_tech": (
        "Você é um roteirista especializado em tecnologia e IA para YouTube brasileiro. "
        "Crie roteiros que gerem alta retenção (acima de 50%) e sejam otimizados para o algoritmo. "
        "Tom: confiante, direto, levemente irreverente. Sem enrolação. "
        "Hook nos primeiros 30s com promessa ESPECÍFICA. Dados e números concretos em cada ponto. "
        "Retorne APENAS JSON válido, sem markdown, sem texto fora do JSON."
    ),
    "financas": (
        "Você é um analista financeiro e educador especializado no mercado brasileiro. "
        "SEMPRE inclua disclaimer 'não é recomendação de investimento'. "
        "Use os dados financeiros injetados para cálculos reais (SELIC, CDI, IPCA). "
        "Compare sempre com a poupança como referência popular. "
        "Inclua exemplos com R$1.000, R$5.000 e R$10.000. "
        "Retorne APENAS JSON válido, sem markdown, sem texto fora do JSON."
    ),
    "curiosidades": (
        "Você é um roteirista de conteúdo viral de curiosidades e fatos surpreendentes. "
        "Abre com o fato MAIS surpreendente — nunca o mais óbvio. "
        "Frases curtas. Máximo 2 linhas por parágrafo. Ritmo acelerado. "
        "Use números absurdos > fatos abstratos. Termine com pergunta para comentários. "
        "Retorne APENAS JSON válido, sem markdown, sem texto fora do JSON."
    ),
    "horror": (
        "Você é um roteirista de true crime e horror para narração em áudio/vídeo. "
        "Tom documental, sério, levemente perturbador — nunca sensacionalista barato. "
        "Abre in medias res com a cena mais perturbadora. Detalhes sensoriais específicos. "
        "Não glorificar perpetradores. Foco nas vítimas e no mistério. "
        "Retorne APENAS JSON válido, sem markdown, sem texto fora do JSON."
    ),
    "motivacional": (
        "Você é um biógrafo e roteirista especializado em histórias de superação. "
        "Tom épico, inspirador, emocionalmente honesto — não superficial. "
        "A diferença entre motivacional raso e transformador é a ESPECIFICIDADE. "
        "Abre no momento mais dramático da história. Inclua diálogos reais ou reconstruídos. "
        "Retorne APENAS JSON válido, sem markdown, sem texto fora do JSON."
    ),
}

VOICE_STYLES = {
    "ia_tech":      {"stability": 0.50, "similarity_boost": 0.80, "style": 0.30, "use_speaker_boost": True},
    "financas":     {"stability": 0.75, "similarity_boost": 0.85, "style": 0.10, "use_speaker_boost": True},
    "curiosidades": {"stability": 0.40, "similarity_boost": 0.75, "style": 0.50, "use_speaker_boost": True},
    "horror":       {"stability": 0.80, "similarity_boost": 0.90, "style": 0.20, "use_speaker_boost": False},
    "motivacional": {"stability": 0.60, "similarity_boost": 0.80, "style": 0.60, "use_speaker_boost": True},
}


# -- Helpers -------------------------------------------------------------------

async def fetch_broll_images(scene_descriptions: List[str], count_per_scene: int = 2) -> List[str]:
    """Busca imagens B-roll no Pexels para cada descrição de cena."""
    pexels_key = os.getenv("PEXELS_API_KEY", "")
    if not pexels_key or not scene_descriptions:
        return []

    urls: List[str] = []
    async with httpx.AsyncClient() as client:
        for desc in scene_descriptions[:5]:
            r = await client.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": pexels_key},
                params={"query": desc, "per_page": count_per_scene, "orientation": "landscape"},
                timeout=10.0,
            )
            if r.status_code == 200:
                for photo in r.json().get("photos", []):
                    urls.append(photo["src"]["large"])
    return urls


def _parse_json_response(text: str) -> dict:
    """Try to extract JSON from Claude's response."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        m = re.search(r'\{[\s\S]+\}', text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    raise HTTPException(status_code=500, detail=f"Claude não retornou JSON válido: {text[:300]}")


# -- Endpoints -----------------------------------------------------------------

@router.post("/generate-script")
async def generate_script(body: ScriptRequest, service: str = Depends(require_service_key)):
    system_prompt = SYSTEM_PROMPTS.get(body.niche)
    if not system_prompt:
        raise HTTPException(status_code=400, detail=f"Niche '{body.niche}' não suportado. Opções: {list(SYSTEM_PROMPTS.keys())}")

    user_prompt = (
        f"Crie um roteiro completo para YouTube sobre: {body.topic}\n"
        f"Idioma: {body.language}\n"
        f"Duração alvo: {body.target_minutes} minutos\n"
    )
    if body.source_content:
        user_prompt += f"\nConteúdo-fonte para se basear:\n{body.source_content}\n"
    if body.niche == "financas" and body.financial_data:
        user_prompt += f"\nDados financeiros atualizados:\n{json.dumps(body.financial_data, ensure_ascii=False)}\n"

    user_prompt += (
        '\nRetorne um JSON com estas chaves exatas:\n'
        '{"title": "string", "title_variants": ["v1","v2","v3"], "script": "roteiro completo", '
        '"hook": "frase de abertura", "cta": "chamada para ação final", '
        '"description": "descrição para YouTube", "tags": ["tag1","tag2",...], '
        '"thumbnail_prompt": "prompt para gerar thumbnail", '
        '"shorts_hooks": ["hook1","hook2","hook3"], '
        '"scene_descriptions": ["cena1","cena2",...]}'
    )

    raw = claude_chat(system=system_prompt, user=user_prompt, max_tokens=4000)
    result = _parse_json_response(raw)
    return result


@router.post("/generate-voice")
async def generate_voice(body: VoiceRequest, service: str = Depends(require_service_key)):
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY não configurado.")

    voice_settings = VOICE_STYLES.get(body.niche, VOICE_STYLES["ia_tech"])

    r = req.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{body.voice_id}",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "text": body.script,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": voice_settings,
        },
        timeout=120,
    )
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"ElevenLabs error: {r.text[:300]}")

    audio_bytes = r.content
    audio_b64 = base64.b64encode(audio_bytes).decode()
    duration_estimate = len(audio_bytes) // (24000 * 2)  # rough estimate for 24kHz 16-bit

    return {
        "status": "ok",
        "audio_b64": audio_b64,
        "audio_url": "",
        "duration_seconds": max(1, duration_estimate),
        "_pipeline_note": (
            "audio_url está vazio. O n8n deve: "
            "1) decodificar audio_b64, "
            "2) fazer upload para Supabase Storage bucket 'channel-audio', "
            "3) usar a URL pública resultante como audio_url no próximo step /channel/generate-video"
        ),
    }


@router.post("/generate-video")
async def generate_video(body: VideoChannelRequest, service: str = Depends(require_service_key)):
    tmpdir = tempfile.mkdtemp(prefix="channel_video_")
    try:
        # Download audio
        audio_r = req.get(body.audio_url, timeout=60)
        if not audio_r.ok:
            raise HTTPException(status_code=502, detail="Falha ao baixar áudio da audio_url.")
        audio_path = os.path.join(tmpdir, "audio.mp3")
        with open(audio_path, "wb") as f:
            f.write(audio_r.content)

        # Fetch B-roll images from Pexels
        scene_descs = body.scene_descriptions or ["cinematic landscape", "technology", "abstract background"]
        image_urls = await fetch_broll_images(scene_descs)

        if len(image_urls) < 2:
            raise HTTPException(status_code=400, detail="Não foi possível obter imagens B-roll suficientes do Pexels.")

        # Download images
        photo_paths: List[str] = []
        for i, url in enumerate(image_urls[:10]):
            img_r = req.get(url, timeout=15)
            if img_r.ok:
                dest = os.path.join(tmpdir, f"broll_{i:03d}.jpg")
                with open(dest, "wb") as f:
                    f.write(img_r.content)
                photo_paths.append(dest)

        if len(photo_paths) < 2:
            raise HTTPException(status_code=400, detail="Não foi possível baixar imagens B-roll suficientes.")

        # Get audio duration with ffprobe
        dur = 30
        try:
            probe = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(probe.communicate(), timeout=10)
            dur = max(5, min(600, int(float(stdout.decode().strip()))))
        except Exception:
            pass

        # Build video (16:9 for YouTube)
        w, h = 1920, 1080
        output_path = os.path.join(tmpdir, "output.mp4")
        video_no_audio = os.path.join(tmpdir, "video_no_audio.mp4")

        cmd = _build_ffmpeg_cmd_with_text(
            photo_paths, video_no_audio, w, h, dur, body.template_style,
            title="", subtitle="", cta="",
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail="FFmpeg video error: " + (stderr_bytes or b"").decode(errors="replace")[:500])

        # Merge audio + video
        merge_cmd = [
            "ffmpeg", "-y", "-i", video_no_audio, "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            "-movflags", "+faststart", output_path,
        ]
        proc2 = await asyncio.create_subprocess_exec(
            *merge_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        _, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=120)
        if proc2.returncode != 0:
            raise HTTPException(status_code=500, detail="FFmpeg merge error: " + (stderr2 or b"").decode(errors="replace")[:500])

        from fastapi.responses import StreamingResponse

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
            headers={"Content-Disposition": "attachment; filename=channel-video.mp4"},
        )

    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/generate-thumbnail")
async def generate_thumbnail(body: ThumbnailRequest, service: str = Depends(require_service_key)):
    fal_key = os.getenv("FAL_KEY")
    if not fal_key:
        raise HTTPException(status_code=500, detail="FAL_KEY não configurado.")

    niche_styles = {
        "ia_tech": "futuristic, neon blue accents, tech-inspired, high contrast",
        "financas": "professional, green and gold tones, financial charts background",
        "curiosidades": "vibrant, eye-catching, bold colors, surprising element",
        "horror": "dark, eerie atmosphere, muted desaturated colors, cinematic horror",
        "motivacional": "epic lighting, golden hour, inspirational, warm tones",
    }
    style_suffix = niche_styles.get(body.niche, "professional, high quality")
    enhanced_prompt = f"{body.thumbnail_prompt}. YouTube thumbnail style, {style_suffix}, bold text overlay area, 16:9 aspect ratio"

    r = req.post(
        "https://fal.run/fal-ai/flux-pro",
        headers={
            "Authorization": f"Key {fal_key}",
            "Content-Type": "application/json",
        },
        json={
            "prompt": enhanced_prompt,
            "image_size": "landscape_16_9",
            "num_images": 1,
        },
        timeout=60,
    )
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Fal.ai error: {r.text[:300]}")

    result = r.json()
    images = result.get("images", [])
    if not images:
        raise HTTPException(status_code=502, detail="Fal.ai não retornou imagens.")

    thumbnail_url = images[0].get("url", "")
    return {"status": "ok", "thumbnail_url": thumbnail_url}


@router.post("/fetch-trending")
async def fetch_trending(body: TrendingRequest, service: str = Depends(require_service_key)):
    topics: List[dict] = []

    try:
        if body.niche == "ia_tech":
            topics.extend(await _fetch_trending_ia_tech())
        elif body.niche == "financas":
            topics.extend(await _fetch_trending_financas())
        elif body.niche == "curiosidades":
            topics.extend(await _fetch_trending_curiosidades())
        elif body.niche == "horror":
            topics.extend(await _fetch_trending_horror())
        elif body.niche == "motivacional":
            topics.extend(await _fetch_trending_motivacional())
        else:
            raise HTTPException(status_code=400, detail=f"Niche '{body.niche}' não suportado.")
    except HTTPException:
        raise
    except Exception:
        pass

    # Deduplicate by title
    seen = set()
    unique: List[dict] = []
    for t in topics:
        key = t.get("title", "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(t)

    return {"status": "ok", "topics": unique[:body.limit]}


@router.post("/generate-shorts")
async def generate_shorts(body: ShortsRequest, service: str = Depends(require_service_key)):
    tmpdir = tempfile.mkdtemp(prefix="channel_shorts_")
    try:
        # Download video
        video_r = req.get(body.video_url, timeout=120)
        if not video_r.ok:
            raise HTTPException(status_code=502, detail="Falha ao baixar vídeo da video_url.")
        video_path = os.path.join(tmpdir, "source.mp4")
        with open(video_path, "wb") as f:
            f.write(video_r.content)

        # Get video duration
        dur = 60
        try:
            probe = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(probe.communicate(), timeout=10)
            dur = max(1, int(float(stdout.decode().strip())))
        except Exception:
            pass

        # Ask Claude to identify best moments
        prompt = (
            f"Analise este roteiro e identifique os {body.max_shorts} melhores momentos para Shorts (máx 60s cada).\n"
            f"Duração total do vídeo: {dur} segundos.\n\n"
            f"Roteiro:\n{body.script}\n\n"
            f"Retorne APENAS JSON: "
            f'{{"shorts": [{{"start_pct": 0.0, "end_pct": 0.1, "hook": "frase de gancho"}},...]}}'
        )
        raw = claude_chat(
            system="Você é editor de vídeo. Identifique os melhores trechos para YouTube Shorts. Retorne APENAS JSON válido.",
            user=prompt,
            max_tokens=1000,
        )
        parsed = _parse_json_response(raw)
        shorts_data = parsed.get("shorts", [])[:body.max_shorts]

        results: List[dict] = []
        for idx, s in enumerate(shorts_data):
            start_sec = int(s.get("start_pct", 0) * dur)
            end_sec = int(s.get("end_pct", 0.1) * dur)
            clip_dur = min(60, max(5, end_sec - start_sec))

            short_path = os.path.join(tmpdir, f"short_{idx}.mp4")
            crop_cmd = [
                "ffmpeg", "-y", "-ss", str(start_sec), "-i", video_path,
                "-t", str(clip_dur),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-movflags", "+faststart",
                short_path,
            ]
            proc = await asyncio.create_subprocess_exec(
                *crop_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode == 0 and os.path.exists(short_path):
                with open(short_path, "rb") as f:
                    video_b64 = base64.b64encode(f.read()).decode()
                results.append({
                    "index": idx,
                    "video_b64": video_b64,
                    "hook": s.get("hook", ""),
                })

        return {"status": "ok", "shorts": results}

    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


# -- Trending helpers ----------------------------------------------------------

async def _fetch_trending_ia_tech() -> List[dict]:
    topics: List[dict] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        # GitHub Trending (unofficial JSON endpoint)
        try:
            r = await client.get("https://api.github.com/search/repositories", params={
                "q": "topic:ai created:>2026-04-01",
                "sort": "stars", "order": "desc", "per_page": 5,
            })
            if r.status_code == 200:
                for item in r.json().get("items", [])[:5]:
                    topics.append({
                        "title": item.get("full_name", ""),
                        "summary": item.get("description", "")[:200],
                        "source": "github",
                        "score": item.get("stargazers_count", 0),
                    })
        except Exception:
            pass

        # ProductHunt (public)
        try:
            r = await client.get("https://www.producthunt.com/frontend/graphql", params={
                "query": "query { posts(order: RANKING) { edges { node { name tagline votesCount } } } }"
            })
            # ProductHunt GraphQL may need auth; fallback silently
        except Exception:
            pass

    return topics


async def _fetch_trending_financas() -> List[dict]:
    topics: List[dict] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        # BACEN API SGS
        series = {"SELIC": 432, "IPCA": 433, "CDI": 12}
        for name, code in series.items():
            try:
                r = await client.get(
                    f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados/ultimos/1?formato=json"
                )
                if r.status_code == 200:
                    data = r.json()
                    if data:
                        val = data[-1].get("valor", "")
                        topics.append({
                            "title": f"{name} atual: {val}%",
                            "summary": f"Último valor do {name} segundo o Banco Central do Brasil.",
                            "source": "bacen",
                            "score": 100,
                        })
            except Exception:
                pass

        # RSS Infomoney (simplified)
        try:
            r = await client.get("https://www.infomoney.com.br/feed/")
            if r.status_code == 200:
                import re
                titles = re.findall(r'<title><!\[CDATA\[(.+?)\]\]></title>', r.text)
                for t in titles[:3]:
                    topics.append({
                        "title": t,
                        "summary": "",
                        "source": "infomoney",
                        "score": 50,
                    })
        except Exception:
            pass

    return topics


async def _fetch_trending_curiosidades() -> List[dict]:
    topics: List[dict] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Wikipedia Featured Content
        try:
            from datetime import datetime
            today = datetime.now()
            r = await client.get(
                f"https://pt.wikipedia.org/api/rest_v1/feed/featured"
                f"/{today.year}/{today.month:02d}/{today.day:02d}"
            )
            if r.status_code == 200:
                tfa = r.json().get("tfa", {})
                if tfa:
                    topics.append({
                        "title": tfa.get("normalizedtitle", tfa.get("title", "")),
                        "summary": tfa.get("extract", "")[:200],
                        "source": "wikipedia",
                        "score": 80,
                    })
        except Exception:
            pass

        # Reddit r/todayilearned
        try:
            r = await client.get(
                "https://www.reddit.com/r/todayilearned/hot.json?limit=5",
                headers={"User-Agent": "DB8Agent/1.0"},
            )
            if r.status_code == 200:
                for post in r.json().get("data", {}).get("children", [])[:5]:
                    d = post.get("data", {})
                    topics.append({
                        "title": d.get("title", ""),
                        "summary": d.get("selftext", "")[:200],
                        "source": "reddit/todayilearned",
                        "score": d.get("score", 0),
                    })
        except Exception:
            pass

    return topics


async def _fetch_trending_horror() -> List[dict]:
    topics: List[dict] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for sub in ["nosleep", "UnresolvedMysteries"]:
            try:
                r = await client.get(
                    f"https://www.reddit.com/r/{sub}/hot.json?limit=5",
                    headers={"User-Agent": "DB8Agent/1.0"},
                )
                if r.status_code == 200:
                    for post in r.json().get("data", {}).get("children", [])[:5]:
                        d = post.get("data", {})
                        topics.append({
                            "title": d.get("title", ""),
                            "summary": d.get("selftext", "")[:200],
                            "source": f"reddit/{sub}",
                            "score": d.get("score", 0),
                        })
            except Exception:
                pass

    return topics


async def _fetch_trending_motivacional() -> List[dict]:
    topics: List[dict] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Reddit r/Entrepreneur
        try:
            r = await client.get(
                "https://www.reddit.com/r/Entrepreneur/hot.json?limit=5",
                headers={"User-Agent": "DB8Agent/1.0"},
            )
            if r.status_code == 200:
                for post in r.json().get("data", {}).get("children", [])[:5]:
                    d = post.get("data", {})
                    topics.append({
                        "title": d.get("title", ""),
                        "summary": d.get("selftext", "")[:200],
                        "source": "reddit/Entrepreneur",
                        "score": d.get("score", 0),
                    })
        except Exception:
            pass

        # Quotable API
        try:
            r = await client.get("https://quotable.io/quotes?limit=5&sortBy=dateAdded&order=desc")
            if r.status_code == 200:
                for q in r.json().get("results", [])[:5]:
                    topics.append({
                        "title": q.get("content", ""),
                        "summary": f"— {q.get('author', 'Desconhecido')}",
                        "source": "quotable",
                        "score": 30,
                    })
        except Exception:
            pass

    return topics
