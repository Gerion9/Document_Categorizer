"""Shared database helpers to avoid repeated boilerplate across routers."""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import AuditLog

T = TypeVar("T")


def get_or_404(db: Session, model: type[T], entity_id: Any, *, label: str | None = None) -> T:
    """Query a model by primary key and raise 404 if not found."""
    entity = db.query(model).filter(model.id == entity_id).first()  # type: ignore[attr-defined]
    if not entity:
        name = label or model.__name__  # type: ignore[attr-defined]
        raise HTTPException(404, f"{name} not found")
    return entity


def reorder_entities(db: Session, model: type, items: list) -> dict[str, bool]:
    """Generic reorder: set .order for each item in the list."""
    for item in items:
        entity = db.query(model).filter(model.id == item.id).first()  # type: ignore[attr-defined]
        if entity:
            entity.order = item.order
    db.commit()
    return {"ok": True}


def audit_log(
    db: Session,
    *,
    case_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            case_id=case_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )
