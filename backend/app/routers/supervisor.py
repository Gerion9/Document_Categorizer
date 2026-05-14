"""Router – Supervisor views: see cases from all assigned case managers."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from ..database import get_db
from ..models import Case, CaseUser, Team, TeamUser, User
from ..schemas import SupervisorCaseOut, CaseManagerInfo, TeamInfo
from .auth import require_role

router = APIRouter(prefix="/supervisor", tags=["supervisor"])

_supervisor = Depends(require_role("supervisor"))


def _supervisor_cases_query(db: Session, supervisor_id: int, team_uuid: str | None = None):
    """Build supervisor case list: team members + own assigned cases."""
    q = (
        db.query(Case, User, Team)
        .join(CaseUser, CaseUser.case_id == Case.id)
        .join(User, User.id == CaseUser.user_id)
        .outerjoin(
            TeamUser,
            and_(
                TeamUser.user_id == CaseUser.user_id,
                TeamUser.deleted_at.is_(None),
            ),
        )
        .outerjoin(
            Team,
            and_(
                Team.id == TeamUser.team_id,
                Team.deleted_at.is_(None),
            ),
        )
        .filter(
            CaseUser.deleted_at.is_(None),
            or_(
                Team.supervisor_id == supervisor_id,
                CaseUser.user_id == supervisor_id,
            ),
        )
    )

    if team_uuid:
        q = q.filter(
            or_(
                Team.uuid == team_uuid,
                CaseUser.user_id == supervisor_id,
            )
        )

    return q.distinct(Case.id).order_by(Case.id, Case.updated_at.desc()).all()


def _rows_to_response(rows) -> list[dict]:
    return [
        {
            "case_id": case.id,
            "case_uuid": case.id,
            "name": case.name,
            "description": case.description or "",
            "case_manager": {"id": user.id, "name": user.name},
            "team": {
                "uuid": team.uuid if team else "",
                "name": team.name if team else "Sin equipo",
            },
            "created_at": case.created_at,
            "updated_at": case.updated_at,
        }
        for case, user, team in rows
    ]


# ---------------------------------------------------------------------------
# GET /supervisor/cases
# ---------------------------------------------------------------------------

@router.get("/cases", response_model=list[SupervisorCaseOut])
def list_supervisor_cases(
    payload: dict = _supervisor,
    db: Session = Depends(get_db),
):
    rows = _supervisor_cases_query(db, payload["user_id"])
    return _rows_to_response(rows)


# ---------------------------------------------------------------------------
# GET /supervisor/teams/{team_uuid}/cases
# ---------------------------------------------------------------------------

@router.get("/teams/{team_uuid}/cases", response_model=list[SupervisorCaseOut])
def list_team_cases(
    team_uuid: str,
    payload: dict = _supervisor,
    db: Session = Depends(get_db),
):
    team = (
        db.query(Team)
        .filter(
            Team.uuid == team_uuid,
            Team.supervisor_id == payload["user_id"],
            Team.deleted_at.is_(None),
        )
        .first()
    )
    if not team:
        raise HTTPException(404, "Team not found")

    rows = _supervisor_cases_query(db, payload["user_id"], team_uuid=team_uuid)
    return _rows_to_response(rows)
