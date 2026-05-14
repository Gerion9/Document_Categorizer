"""Router – User & Role management (admin endpoints)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Role, Permission, UserRole, RolePermission, UserPermission
from ..schemas import (
    UserDetail,
    UserUpdate,
    RoleOut,
    PermissionOut,
    SyncRolesRequest,
    AddRoleRequest,
)

router = APIRouter(tags=["admin"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_user_detail(db: Session, user: User) -> dict:
    roles = (
        db.query(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user.id)
        .all()
    )

    role_perm_ids = {
        rp.permission_id
        for rp in db.query(RolePermission)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .filter(UserRole.user_id == user.id)
        .all()
    }
    direct_perm_ids = {
        up.permission_id
        for up in db.query(UserPermission)
        .filter(UserPermission.user_id == user.id)
        .all()
    }
    all_perm_ids = role_perm_ids | direct_perm_ids
    perm_names = sorted(
        p.name
        for p in db.query(Permission).filter(Permission.id.in_(all_perm_ids)).all()
    ) if all_perm_ids else []

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "roles": [{"id": r.id, "name": r.name} for r in roles],
        "permissions": perm_names,
        "created_at": user.created_at,
    }


# ---------------------------------------------------------------------------
# Users CRUD
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[UserDetail])
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.name).all()
    return [_build_user_detail(db, u) for u in users]


@router.get("/users/{user_id}", response_model=UserDetail)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return _build_user_detail(db, user)


@router.put("/users/{user_id}", response_model=UserDetail)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    if data.name is not None:
        user.name = data.name

    if data.email is not None:
        existing = (
            db.query(User)
            .filter(User.email == data.email, User.id != user_id)
            .first()
        )
        if existing:
            raise HTTPException(409, "Email already in use")
        user.email = data.email

    db.commit()
    db.refresh(user)
    return _build_user_detail(db, user)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# User ↔ Role assignments
# ---------------------------------------------------------------------------

@router.put("/users/{user_id}/roles", response_model=UserDetail)
def sync_user_roles(user_id: int, data: SyncRolesRequest, db: Session = Depends(get_db)):
    """Replace all roles for a user with the given list."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    db.query(UserRole).filter(UserRole.user_id == user_id).delete()

    for role_id in set(data.role_ids):
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            raise HTTPException(404, f"Role {role_id} not found")
        db.add(UserRole(user_id=user_id, role_id=role_id))

    db.commit()
    db.refresh(user)
    return _build_user_detail(db, user)


@router.post("/users/{user_id}/roles", response_model=UserDetail)
def add_user_role(user_id: int, data: AddRoleRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    role = db.query(Role).filter(Role.id == data.role_id).first()
    if not role:
        raise HTTPException(404, "Role not found")

    exists = (
        db.query(UserRole)
        .filter(UserRole.user_id == user_id, UserRole.role_id == data.role_id)
        .first()
    )
    if exists:
        raise HTTPException(409, "Role already assigned to this user")

    db.add(UserRole(user_id=user_id, role_id=data.role_id))
    db.commit()
    db.refresh(user)
    return _build_user_detail(db, user)


@router.delete("/users/{user_id}/roles/{role_id}", response_model=UserDetail)
def remove_user_role(user_id: int, role_id: int, db: Session = Depends(get_db)):
    link = (
        db.query(UserRole)
        .filter(UserRole.user_id == user_id, UserRole.role_id == role_id)
        .first()
    )
    if not link:
        raise HTTPException(404, "Role assignment not found")

    db.delete(link)
    db.commit()

    user = db.query(User).filter(User.id == user_id).first()
    return _build_user_detail(db, user)
