import base64
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List

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

    # Xfade chain -> [vmerge]
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
    # (populated later from Gemini -- we pass placeholders here; caller replaces)
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
