"""Router – SSO authentication bridge with BOS (Laravel).

Flow:
  1. BOS redirects user to the frontend with email + name + role + HMAC signature
  2. Frontend POSTs to /api/sso-login
  3. We verify the HMAC, create/update the user in our DB (Just-in-Time),
     assign the role, and return a local JWT with user_id + permissions
  4. Frontend uses GET /api/auth/me to fetch the user profile with roles/permissions
"""

import hashlib
import hmac
import os
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Role, UserRole, RolePermission, UserPermission
from ..schemas import SSOLoginRequest, SSOLoginResponse, UserOut

router = APIRouter(tags=["auth"])

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_permissions(db: Session, user: User) -> list[str]:
    """Collect all permission names for a user (via roles + direct assignments)."""
    role_perms = (
        db.query(RolePermission)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .filter(UserRole.user_id == user.id)
        .all()
    )
    perm_ids = {rp.permission_id for rp in role_perms}

    direct_perms = (
        db.query(UserPermission)
        .filter(UserPermission.user_id == user.id)
        .all()
    )
    perm_ids.update(dp.permission_id for dp in direct_perms)

    if not perm_ids:
        return []

    from ..models import Permission
    perms = db.query(Permission).filter(Permission.id.in_(perm_ids)).all()
    return sorted(p.name for p in perms)


def _get_user_roles(db: Session, user: User) -> list[str]:
    """Get all role names for a user."""
    user_roles = db.query(UserRole).filter(UserRole.user_id == user.id).all()
    if not user_roles:
        return []
    role_ids = [ur.role_id for ur in user_roles]
    roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
    return sorted(r.name for r in roles)


def _build_user_out(db: Session, user: User) -> UserOut:
    """Build a UserOut schema from a User model instance."""
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        roles=_get_user_roles(db, user),
        permissions=_get_user_permissions(db, user),
    )


# ---------------------------------------------------------------------------
# JWT dependency – used by other routers via Depends(get_current_user)
# ---------------------------------------------------------------------------

def get_current_user(authorization: str = Header(...)):
    """Decode the Bearer token and return the JWT payload."""
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


# ---------------------------------------------------------------------------
# POST /api/sso-login – Token exchange with JIT user provisioning
# ---------------------------------------------------------------------------

@router.post("/sso-login", response_model=SSOLoginResponse)
def sso_login(data: SSOLoginRequest, db: Session = Depends(get_db)):
    if not SSO_SECRET_KEY:
        raise HTTPException(status_code=500, detail="SSO not configured")

    expected_signature = hmac.new(
        SSO_SECRET_KEY.encode(),
        data.email.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, data.signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # --- Just-in-Time user provisioning (like Laravel's updateOrCreate) ---
    user = db.query(User).filter(User.email == data.email).first()

    if user:
        full_name = data.name or f"{data.first_name or ''} {data.last_name or ''}".strip()
        if full_name and user.name != full_name:
            user.name = full_name
            db.commit()
            db.refresh(user)
    else:
        full_name = data.name or f"{data.first_name or ''} {data.last_name or ''}".strip() or data.email
        user = User(name=full_name, email=data.email)
        db.add(user)
        db.flush()

        if data.role:
            role = db.query(Role).filter(Role.name == data.role).first()
            if not role:
                role = Role(name=data.role)
                db.add(role)
                db.flush()
            db.add(UserRole(user_id=user.id, role_id=role.id))

        db.commit()
        db.refresh(user)

    permissions = _get_user_permissions(db, user)

    token = jwt.encode(
        {
            "user_id": user.id,
            "email": user.email,
            "permissions": permissions,
            "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    user_out = _build_user_out(db, user)
    return SSOLoginResponse(token=token, user=user_out)


# ---------------------------------------------------------------------------
# GET /api/auth/me – Return the authenticated user with roles & permissions
# ---------------------------------------------------------------------------

@router.get("/auth/me", response_model=UserOut)
def auth_me(
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return _build_user_out(db, user)
