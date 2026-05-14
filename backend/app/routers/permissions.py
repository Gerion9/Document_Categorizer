"""Router – Permissions (read-only listing)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Permission
from ..schemas import PermissionOut

router = APIRouter(tags=["permissions"])


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(db: Session = Depends(get_db)):
    """Devuelve todos los permisos registrados en el sistema, ordenados por nombre."""
    return db.query(Permission).order_by(Permission.name).all()
