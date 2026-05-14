"""Shared FastAPI dependencies."""

from functools import lru_cache

from .core.config import get_settings
from .services.storage_service import S3StorageService


@lru_cache()
def get_s3_service() -> S3StorageService:
    """Singleton S3 service – one boto3 client for the entire app."""
    return S3StorageService(get_settings())
