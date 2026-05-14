"""Router – Roles CRUD + permission sync."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Role, Permission, RolePermission, UserRole
from ..schemas import (
    RoleCreate,
    RoleUpdate,
    RoleDetailOut,
    PermissionOut,
    SyncPermissionsRequest,
)

router = APIRouter(tags=["roles"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_role_detail(db: Session, role: Role) -> dict:
    """Construye la respuesta de un rol con sus permisos asociados.

    Hace un JOIN entre RolePermission y Permission para obtener
    los permisos del rol en una sola query.
    """
    perms = (
        db.query(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id == role.id)
        .order_by(Permission.name)
        .all()
    )
    return {
        "id": role.id,
        "name": role.name,
        "permissions": [{"id": p.id, "name": p.name} for p in perms],
        "created_at": role.created_at,
    }


# ---------------------------------------------------------------------------
# Roles CRUD
# ---------------------------------------------------------------------------

@router.get("/roles", response_model=list[RoleDetailOut])
def list_roles(db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.name).all()
    return [_build_role_detail(db, r) for r in roles]


@router.post("/roles", response_model=RoleDetailOut, status_code=201)
def create_role(data: RoleCreate, db: Session = Depends(get_db)):
    existing = db.query(Role).filter(Role.name == data.name).first()
    if existing:
        raise HTTPException(409, "A role with this name already exists")

    role = Role(name=data.name)
    db.add(role)
    db.commit()
    db.refresh(role)
    return _build_role_detail(db, role)


@router.put("/roles/{role_id}", response_model=RoleDetailOut)
def update_role(role_id: int, data: RoleUpdate, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(404, "Role not found")

    duplicate = (
        db.query(Role)
        .filter(Role.name == data.name, Role.id != role_id)
        .first()
    )
    if duplicate:
        raise HTTPException(409, "Another role already has this name")

    role.name = data.name
    db.commit()
    db.refresh(role)
    return _build_role_detail(db, role)


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(404, "Role not found")

    assigned_count = db.query(UserRole).filter(UserRole.role_id == role_id).count()
    if assigned_count > 0:
        raise HTTPException(
            409,
            f"Cannot delete: role is assigned to {assigned_count} user(s). "
            "Remove the role from all users first.",
        )

    db.delete(role)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Role ↔ Permission sync
# ---------------------------------------------------------------------------

@router.put("/roles/{role_id}/permissions", response_model=RoleDetailOut)
def sync_role_permissions(
    role_id: int,
    data: SyncPermissionsRequest,
    db: Session = Depends(get_db),
):
    """Reemplaza todos los permisos del rol con la lista proporcionada.

    Funciona como un 'sync': borra los existentes y asigna los nuevos.
    Esto evita problemas de duplicados y simplifica la lógica del frontend.
    """
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(404, "Role not found")

    for pid in data.permission_ids:
        perm = db.query(Permission).filter(Permission.id == pid).first()
        if not perm:
            raise HTTPException(404, f"Permission {pid} not found")

    db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()

    for pid in set(data.permission_ids):
        db.add(RolePermission(role_id=role_id, permission_id=pid))

    db.commit()
    db.refresh(role)
    return _build_role_detail(db, role)
