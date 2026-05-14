from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ENV_PATH = REPO_ROOT / ".env"


def load_project_env(*, override: bool = False) -> Path:
    """Load the shared repo-level .env file if present."""
    load_dotenv(ENV_PATH, override=override)
    return ENV_PATH
