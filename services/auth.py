import os
from typing import Optional

from fastapi import Header, HTTPException

SERVICE_KEYS = {
    "imob":    os.getenv("SERVICE_KEY_IMOB", ""),
    "nexo":    os.getenv("SERVICE_KEY_NEXO", ""),
    "channel": os.getenv("SERVICE_KEY_CHANNEL", ""),
    "book":    os.getenv("SERVICE_KEY_BOOK", ""),
}


def require_service_key(x_service_key: Optional[str] = Header(None)) -> str:
    """Dependência FastAPI -- valida X-Service-Key nos endpoints novos."""
    if not x_service_key:
        raise HTTPException(status_code=401, detail="X-Service-Key header obrigatório")

    service = next((k for k, v in SERVICE_KEYS.items() if v and v == x_service_key), None)
    if not service:
        raise HTTPException(status_code=403, detail="X-Service-Key inválida")

    return service
