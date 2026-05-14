"""S3 storage service – single boto3 client for the entire app lifecycle."""

import logging

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from ..core.config import Settings

log = logging.getLogger(__name__)


class S3StorageError(Exception):
    """Raised when an S3 operation fails."""


class S3StorageService:
    def __init__(self, settings: Settings):
        self._bucket = settings.AWS_S3_BUCKET
        try:
            self._client = boto3.client(
                "s3",
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
        except NoCredentialsError as exc:
            raise S3StorageError("AWS credentials are missing or invalid") from exc

    # ── Write ──────────────────────────────────────────────────────────────

    def upload_bytes(self, content: bytes, key: str, content_type: str) -> str:
        """Upload raw bytes to S3. Returns the key."""
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
            return key
        except ClientError as exc:
            raise S3StorageError(f"Failed to upload {key}: {exc}") from exc

    # ── Read ───────────────────────────────────────────────────────────────

    def download_bytes(self, key: str) -> bytes:
        """Download an object from S3 and return its full content as bytes."""
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            raise S3StorageError(f"Failed to download {key}: {exc}") from exc

    # ── Presigned URLs ─────────────────────────────────────────────────────

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a temporary URL for downloading an object."""
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except ClientError as exc:
            raise S3StorageError(f"Failed to generate URL for {key}: {exc}") from exc

    # ── Delete ─────────────────────────────────────────────────────────────

    def delete(self, key: str) -> None:
        """Delete an object from S3. No-op if the key doesn't exist."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            log.warning("Failed to delete %s: %s", key, exc)

    # ── Existence check ────────────────────────────────────────────────────

    def exists(self, key: str) -> bool:
        """Check whether an object exists in the bucket."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False
