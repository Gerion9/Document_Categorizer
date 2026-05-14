"""AWS configuration via Pydantic BaseSettings.

Required env vars: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET.
The app will refuse to start if any required variable is missing.
"""

from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings
from .env import ENV_PATH


class AdminSeedUser(BaseModel):
    email: str
    name: str


class RuntimeSettings(BaseSettings):
    APP_ENV: str = "development"
    RUN_STARTUP_SEEDERS: bool | None = None
    RUN_STARTUP_LEGACY_MIGRATIONS: bool | None = None
    ALLOW_PRODUCTION_ADMIN_SEED: bool = False
    ADMIN_SEED_USERS: tuple[AdminSeedUser, ...] = ()
    STARTUP_VALIDATION_MODE: str = "warn"
    VALIDATE_S3_ON_STARTUP: bool = False
    VALIDATE_QUESTIONNAIRE_ANSWERS_ON_STARTUP: bool = True
    VALIDATE_TEMPLATE_FILES_ON_STARTUP: bool = True
    ALLOW_ALEMBIC_STAMP_ON_EXISTING_SCHEMA: bool = False
    model_config = {"env_file": str(ENV_PATH), "env_file_encoding": "utf-8", "extra": "ignore"}

    def is_production(self) -> bool:
        return self.APP_ENV.strip().lower() in {"prod", "production"}

    def should_run_startup_seeders(self) -> bool:
        if self.RUN_STARTUP_SEEDERS is not None:
            return bool(self.RUN_STARTUP_SEEDERS)
        return not self.is_production()

    def should_run_legacy_migrations(self) -> bool:
        if self.RUN_STARTUP_LEGACY_MIGRATIONS is not None:
            return bool(self.RUN_STARTUP_LEGACY_MIGRATIONS)
        return not self.is_production()

    def startup_validation_mode(self) -> str:
        mode = self.STARTUP_VALIDATION_MODE.strip().lower()
        if mode in {"off", "warn", "strict"}:
            return mode
        return "warn"

    def startup_validation_is_strict(self) -> bool:
        return self.startup_validation_mode() == "strict"


class Settings(RuntimeSettings):
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str = "us-east-1"
    AWS_S3_BUCKET: str
    GOOGLE_DOCUMENT_AI_PROJECT_ID: str | None = None
    GOOGLE_DOCUMENT_AI_LOCATION: str | None = None
    GOOGLE_DOCUMENT_AI_PROCESSOR_ID: str | None = None
    GOOGLE_DOCUMENT_AI_PROCESSOR_VERSION: str | None = None


@lru_cache()
def get_settings() -> Settings:
    return Settings()


@lru_cache()
def get_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()