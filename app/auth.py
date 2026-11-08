from __future__ import annotations
import hmac, secrets
import os
from pathlib import Path
from fastapi import Header, HTTPException, Query, Request
from dotenv import dotenv_values
from .config import settings, _env

def _expected_key() -> str:
    vals = {}
    try:
        vals = dotenv_values(_env)
    except Exception:
        vals = {}
    for k in ("API_KEY","FT_AI_API_KEY","FTAI_API_KEY","FREE_AI_API_KEY","GATEWAY_API_KEY"):
        v = vals.get(k) or os.getenv(k) or settings.api_key
        if v:
            return str(v).strip().strip("'\"")
    return ""

def _extract_token(request: Request, authorization: str | None, headers: dict[str, str], query: dict[str, str]) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if authorization and authorization.strip() and ' ' not in authorization.strip():
        # some clients send raw key
        pass
    for name in ['x-api-key', 'api-key', 'x-openai-api-key', 'x-goog-api-key', 'key']:
        v = headers.get(name)
        if v and v.strip():
            # x-goog-api-key may be different upstream key in some contexts; accept only if matches gateway key? handled by compare
            return v.strip()
    for name in ['key', 'api_key', 'apikey', 'access_token', 'token']:
        v = query.get(name)
        if v and v.strip():
            return v.strip()
    # JSON body fallback for rare clients
    return None

async def require_api_key_flexible(
    request: Request,
    authorization: str | None = Header(default=None),
):
    expected = _expected_key()
    if not expected:
        raise HTTPException(status_code=503, detail="Server misconfigured: API_KEY is not set in .env")
    headers = {k.lower(): v for k, v in request.headers.items()}
    query = {k.lower(): v for k, v in request.query_params.items()}
    token = _extract_token(request, authorization, headers, query)
    if token is None:
        # try body key fields without consuming stream? FastAPI already can; use cached body if any
        try:
            if request.method in ('POST','PUT','PATCH'):
                body = await request.json()
                if isinstance(body, dict):
                    for k in ['api_key','apikey','key','access_token','token']:
                        v = body.get(k)
                        if isinstance(v, str) and v.strip():
                            token = v.strip(); break
                    # also nested auth
                    auth = body.get('auth')
                    if token is None and isinstance(auth, dict):
                        v = auth.get('api_key') or auth.get('key')
                        if isinstance(v, str): token = v.strip()
        except Exception:
            pass
    # accept raw Authorization value as token if it matches (some CLIs)
    if token is None and authorization and authorization.strip():
        token = authorization.strip()
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail={"message": "Invalid or missing API key", "method": "Authorization: Bearer <API_KEY|FT_AI_API_KEY>"})
    return True

# backward compat
async def require_api_key(request: Request, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None), key: str | None = Query(default=None)):
    return await require_api_key_flexible(request, authorization)
