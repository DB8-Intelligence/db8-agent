import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.channel import router as channel_router
from routers.imob import router as imob_router

load_dotenv()

app = FastAPI(
    title="DB8 Agent",
    version="1.0.0",
    description="Engine compartilhada dos SaaS DB8-Intelligence",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(imob_router)
app.include_router(channel_router)


@app.get("/")
def root():
    return {"status": "DB8 Agent Online \U0001f680", "version": "1.0.0"}


@app.get("/health")
def health():
    from services.supabase import SB_KEY, SB_URL

    sb_ok = bool(SB_URL and SB_KEY)
    return {
        "status": "healthy" if sb_ok else "degraded",
        "version": "1.0.0",
        "supabase_configured": sb_ok,
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "elevenlabs_configured": bool(os.getenv("ELEVENLABS_API_KEY")),
        "fal_configured": bool(os.getenv("FAL_KEY")),
    }
