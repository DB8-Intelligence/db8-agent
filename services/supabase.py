import os
from typing import Dict

import requests as req
from fastapi import HTTPException

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
