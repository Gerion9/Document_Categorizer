"""Router – SSO authentication bridge with BOS (Laravel)."""

import hashlib
import hmac
import os
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import APIRouter, HTTPException, Header

from ..schemas import SSOLoginRequest, SSOLoginResponse

router = APIRouter(tags=["auth"])

def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.replace("Bearer ", "")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def _load_env():
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        load_dotenv(env_path)
    except ImportError:
        pass

_load_env()

SSO_SECRET_KEY = os.getenv("SSO_SECRET_KEY", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")


@router.post("/sso-login", response_model=SSOLoginResponse)
def sso_login(data: SSOLoginRequest):
    if not SSO_SECRET_KEY:
        raise HTTPException(status_code=500, detail="SSO not configured")

    expected_signature = hmac.new(
        SSO_SECRET_KEY.encode(),
        data.email.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, data.signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    token = jwt.encode(
        {
            "email": data.email,
            "name": data.name,
            "first_name": data.first_name,
            "last_name": data.last_name,
            "role": data.role,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    return SSOLoginResponse(token=token, email=data.email)