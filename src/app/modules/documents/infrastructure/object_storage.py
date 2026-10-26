import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

T = TypeVar("T")


class MinioOriginalStorage:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        self.bucket = bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                s3={"addressing_style": "path"},
                connect_timeout=3,
                read_timeout=10,
                retries={"mode": "standard", "total_max_attempts": 2},
                max_pool_connections=2,
            ),
        )
        self._slots = asyncio.Semaphore(2)
        self._bucket_lock = asyncio.Lock()
        self._bucket_ready = False

    async def _run(self, operation: Callable[[], T]) -> T:
        async with self._slots:
            task = asyncio.create_task(asyncio.to_thread(operation))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def _ensure_bucket(self) -> None:
        async with self._bucket_lock:
            if self._bucket_ready:
                return

            def ensure() -> None:
                try:
                    self._client.head_bucket(Bucket=self.bucket)
                except ClientError as error:
                    if str(error.response["Error"]["Code"]) not in (
                        "404",
                        "NoSuchBucket",
                        "NotFound",
                    ):
                        raise
                    try:
                        self._client.create_bucket(Bucket=self.bucket)
                    except ClientError as create_error:
                        if create_error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                            raise

            await self._run(ensure)
            self._bucket_ready = True

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        await self._ensure_bucket()
        await self._run(
            lambda: self._client.put_object(
                Bucket=self.bucket, Key=key, Body=content, ContentType=content_type
            )
        )

    async def get(self, key: str, max_bytes: int) -> bytes:
        def read() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                content: bytes = body.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise ValueError("Stored artifact exceeds the read limit")
                return content
            finally:
                body.close()

        return await self._run(read)

    async def delete(self, key: str) -> None:
        await self._run(lambda: self._client.delete_object(Bucket=self.bucket, Key=key))

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)
