"""Router – CRUD for supervision Teams."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Role, Team, TeamUser, User, UserRole
from ..schemas import (
    TeamCreate,
    TeamDetailOut,
    TeamMemberOut,
    TeamOut,
    TeamUpdate,
    SupervisorOut,
)
from .auth import require_any_role

router = APIRouter(prefix="/teams", tags=["teams"])

_teams_access = Depends(require_any_role("supervisor", "admin"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_admin(db: Session, user_id: int) -> bool:
    return (
        db.query(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .filter(
            UserRole.user_id == user_id,
            Role.name == "admin",
        )
        .first()
        is not None
    )


def _get_team_or_404(
    db: Session, team_uuid: str, user_id: int, can_access_all: bool
) -> Team:
    q = db.query(Team).filter(
        Team.uuid == team_uuid,
        Team.deleted_at.is_(None),
    )
    if not can_access_all:
        q = q.filter(Team.supervisor_id == user_id)
    team = q.first()
    if not team:
        raise HTTPException(404, "Team not found")
    return team


def _build_detail(db: Session, team: Team) -> dict:
    active_members = (
        db.query(TeamUser)
        .filter(TeamUser.team_id == team.id, TeamUser.deleted_at.is_(None))
        .all()
    )
    user_ids = [m.user_id for m in active_members]
    users_map = {}
    if user_ids:
        users_map = {
            u.id: u
            for u in db.query(User).filter(User.id.in_(user_ids)).all()
        }

    sup = db.query(User).filter(User.id == team.supervisor_id).first()

    return {
        "team_uuid": team.uuid,
        "team_name": team.name,
        "supervisor": {"id": sup.id, "name": sup.name} if sup else {"id": 0, "name": ""},
        "members": [
            {
                "uuid_team_user": m.uuid,
                "id": m.user_id,
                "name": users_map[m.user_id].name if m.user_id in users_map else "",
                "email": users_map[m.user_id].email if m.user_id in users_map else "",
                "is_primary": m.is_primary,
            }
            for m in active_members
        ],
    }


# ---------------------------------------------------------------------------
# GET /teams
# ---------------------------------------------------------------------------

@router.get("", response_model=list[TeamOut])
def list_teams(
    payload: dict = _teams_access,
    db: Session = Depends(get_db),
):
    user_id = payload["user_id"]
    can_access_all = _is_admin(db, user_id)
    q = db.query(Team).filter(Team.deleted_at.is_(None))
    if not can_access_all:
        q = q.filter(Team.supervisor_id == user_id)
    teams = q.order_by(Team.name).all()
    result = []
    for t in teams:
        count = (
            db.query(TeamUser)
            .filter(TeamUser.team_id == t.id, TeamUser.deleted_at.is_(None))
            .count()
        )
        result.append({"uuid": t.uuid, "name": t.name, "members_count": count})
    return result


# ---------------------------------------------------------------------------
# POST /teams
# ---------------------------------------------------------------------------

@router.post("", response_model=TeamDetailOut, status_code=201)
def create_team(
    body: TeamCreate,
    payload: dict = _teams_access,
    db: Session = Depends(get_db),
):
    user_id = payload["user_id"]

    team = Team(name=body.name, supervisor_id=user_id)
    db.add(team)
    db.flush()

    for member in body.users:
        if member.is_primary:
            db.query(TeamUser).filter(
                TeamUser.user_id == member.id,
                TeamUser.deleted_at.is_(None),
                TeamUser.is_primary.is_(True),
            ).update({"is_primary": False, "updated_at": _utcnow()})

        db.add(TeamUser(
            team_id=team.id,
            user_id=member.id,
            is_primary=member.is_primary,
        ))

    db.commit()
    db.refresh(team)
    return _build_detail(db, team)


# ---------------------------------------------------------------------------
# GET /teams/{team_uuid}/users
# ---------------------------------------------------------------------------

@router.get("/{team_uuid}/users", response_model=TeamDetailOut)
def get_team_users(
    team_uuid: str,
    payload: dict = _teams_access,
    db: Session = Depends(get_db),
):
    user_id = payload["user_id"]
    team = _get_team_or_404(db, team_uuid, user_id, _is_admin(db, user_id))
    return _build_detail(db, team)


# ---------------------------------------------------------------------------
# PUT /teams/{team_uuid}
# ---------------------------------------------------------------------------

@router.put("/{team_uuid}", response_model=TeamDetailOut)
def update_team(
    team_uuid: str,
    body: TeamUpdate,
    payload: dict = _teams_access,
    db: Session = Depends(get_db),
):
    user_id = payload["user_id"]
    team = _get_team_or_404(db, team_uuid, user_id, _is_admin(db, user_id))

    if body.name is not None:
        team.name = body.name

    current_members = (
        db.query(TeamUser)
        .filter(TeamUser.team_id == team.id, TeamUser.deleted_at.is_(None))
        .all()
    )
    current_by_uuid = {m.uuid: m for m in current_members}

    incoming_uuids = set()
    for member in body.users:
        if member.uuid_team_user and member.uuid_team_user in current_by_uuid:
            existing = current_by_uuid[member.uuid_team_user]
            existing.is_primary = member.is_primary
            existing.updated_at = _utcnow()
            incoming_uuids.add(member.uuid_team_user)

            if member.is_primary:
                db.query(TeamUser).filter(
                    TeamUser.user_id == member.id,
                    TeamUser.uuid != member.uuid_team_user,
                    TeamUser.deleted_at.is_(None),
                    TeamUser.is_primary.is_(True),
                ).update({"is_primary": False, "updated_at": _utcnow()})
        else:
            if member.is_primary:
                db.query(TeamUser).filter(
                    TeamUser.user_id == member.id,
                    TeamUser.deleted_at.is_(None),
                    TeamUser.is_primary.is_(True),
                ).update({"is_primary": False, "updated_at": _utcnow()})

            db.add(TeamUser(
                team_id=team.id,
                user_id=member.id,
                is_primary=member.is_primary,
            ))

    for m in current_members:
        if m.uuid not in incoming_uuids:
            m.deleted_at = _utcnow()

    db.commit()
    db.refresh(team)
    return _build_detail(db, team)


# ---------------------------------------------------------------------------
# DELETE /teams/{team_uuid}
# ---------------------------------------------------------------------------

@router.delete("/{team_uuid}", status_code=204)
def delete_team(
    team_uuid: str,
    payload: dict = _teams_access,
    db: Session = Depends(get_db),
):
    user_id = payload["user_id"]
    team = _get_team_or_404(db, team_uuid, user_id, _is_admin(db, user_id))
    now = _utcnow()
    team.deleted_at = now

    db.query(TeamUser).filter(
        TeamUser.team_id == team.id,
        TeamUser.deleted_at.is_(None),
    ).update({"deleted_at": now})

    db.commit()
