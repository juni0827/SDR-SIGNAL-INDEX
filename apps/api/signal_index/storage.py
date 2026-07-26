from __future__ import annotations

import io
from typing import IO

import boto3
from botocore.config import Config

from .config import Settings, get_settings


class ObjectStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = boto3.client(
            "s3",
            endpoint_url=self.settings.S3_ENDPOINT,
            region_name=self.settings.S3_REGION,
            aws_access_key_id=self.settings.S3_ACCESS_KEY,
            aws_secret_access_key=self.settings.S3_SECRET_KEY.get_secret_value(),
            use_ssl=self.settings.S3_SECURE,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.settings.S3_BUCKET)
        except self.client.exceptions.ClientError:
            self.client.create_bucket(Bucket=self.settings.S3_BUCKET)

    def upload(self, key: str, body: bytes | IO[bytes], mime_type: str) -> None:
        payload: IO[bytes] = io.BytesIO(body) if isinstance(body, bytes) else body
        self.client.upload_fileobj(
            payload,
            self.settings.S3_BUCKET,
            key,
            ExtraArgs={"ContentType": mime_type, "ServerSideEncryption": "AES256"},
        )

    def download(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.settings.S3_BUCKET, Key=key)
        return bytes(response["Body"].read())

    def signed_get_url(self, key: str, expires_sec: int = 600) -> str:
        if not 30 <= expires_sec <= 3600:
            raise ValueError("signed URL expiry must be between 30 and 3600 seconds")
        return str(
            self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.settings.S3_BUCKET, "Key": key},
                ExpiresIn=expires_sec,
            )
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.settings.S3_BUCKET, Key=key)

    def health(self) -> bool:
        self.client.head_bucket(Bucket=self.settings.S3_BUCKET)
        return True
