# DB8-AGENT — PROJECT MEMORY & AGENT INSTRUCTIONS

## O QUE É ESTE SERVIÇO
FastAPI/Python rodando no Railway em https://api.db8intelligence.com.br
Engine compartilhada de todos os SaaS da DB8-Intelligence.

## REGRA CRÍTICA — NUNCA QUEBRAR PRODUÇÃO
Os endpoints abaixo estão em produção sendo consumidos por ImobCreator e NexoOmnix.
NUNCA alterar assinatura, comportamento ou formato de resposta deles:
- GET/POST/PATCH/DELETE /properties (e /properties/{id})
- POST /generate-caption
- POST /generate-video
- POST /webhook/whatsapp
- GET /health, GET /

## STACK
- Python 3.11 / FastAPI 0.110 / Uvicorn
- Deploy: Railway (auto-deploy do branch main)
- Procfile: `web: uvicorn main:app --host 0.0.0.0 --port $PORT`
- CORS: allow_origins=["*"] (interno — todos os frontends são próprios)

## ESTRUTURA DE ARQUIVOS
main.py                  # app init, CORS, include_routers, health
routers/imob.py          # ImobCreator (properties, caption, video, whatsapp)
routers/channel.py       # ChannelOS (/channel/* com X-Service-Key)
services/supabase.py     # helpers Supabase REST (_sb_get, _sb_post, etc)
services/anthropic_ai.py # claude_chat() — substitui _openai_chat
services/auth.py         # require_service_key (Depends FastAPI)
services/video.py        # FFmpeg helpers (_build_ffmpeg_cmd_with_text, _gemini_overlay)
models/imob_models.py    # PropertyCreate, CaptionRequest, WhatsAppProperty
models/channel_models.py # ScriptRequest, VoiceRequest, VideoChannelRequest, etc

## VARIÁVEIS DE AMBIENTE (Railway)
SUPABASE_URL              # URL do projeto Supabase
SUPABASE_SERVICE_ROLE     # service role key (também aceita SUPABASE_SERVICE_ROLE_KEY)
ANTHROPIC_API_KEY         # substituiu OPENAI_API_KEY — modelo: claude-sonnet-4-20250514
OPENAI_API_KEY            # manter por compatibilidade mas não usar em código novo
GOOGLE_AI_API_KEY         # Gemini Vision para análise de fotos no /generate-video
ELEVENLABS_API_KEY        # síntese de voz para /channel/generate-voice
FAL_KEY                   # Fal.ai Flux Pro para /channel/generate-thumbnail
PEXELS_API_KEY            # B-roll para /channel/generate-video
SERVICE_KEY_IMOB          # X-Service-Key do ImobCreator (endpoints /channel/* apenas)
SERVICE_KEY_NEXO          # X-Service-Key do NexoOmnix
SERVICE_KEY_CHANNEL       # X-Service-Key do ChannelOS
SERVICE_KEY_BOOK          # X-Service-Key do BookAgent (futuro)

## PRODUTOS QUE CONSOMEM ESTE SERVIÇO
ImobCreator Studio  → /properties/* + /generate-caption + /generate-video
NexoOmnix           → /generate-caption + /generate-video + (migrar para /channel/* Fase 8)
ChannelOS           → /channel/* (com X-Service-Key obrigatório)
BookAgent           → /book/* (implementar futuro)

## MODELO ANTHROPIC
Sempre usar: claude-sonnet-4-20250514
max_tokens: 1000 para legendas/captions
max_tokens: 4000 para roteiros completos (/channel/generate-script)

## ADICIONAR NOVOS ENDPOINTS
Para novo produto XYZ:
1. Criar routers/xyz.py com APIRouter(prefix="/xyz", tags=["XYZ"])
2. Criar models/xyz_models.py com os Pydantic models
3. Adicionar SERVICE_KEY_XYZ nas variáveis Railway
4. Registrar router em main.py: app.include_router(xyz_router)
5. NUNCA modificar routers existentes

## DEPLOY
Push para main → Railway faz deploy automático.
Verificar logs no Railway dashboard após cada push.
URL de health check: https://api.db8intelligence.com.br/health
