"""Google Cloud Storage & Deterministic Local Filesystem Object Storage Adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.models.schemas import AdapterMode


def clean_folder_path_for_gcs(folder_path: str) -> str:
    """Normalize slash-prefixed folder_path ('/', '/coastal-crosswinds/gusts') for GCS object keys."""
    stripped = (folder_path or "").strip().strip("/")
    return stripped if stripped else "root"


def build_seed_gcs_uri(
    *,
    bucket_name: str,
    seed_prefix: str,
    project_id: str,
    seed_id: str,
    safe_filename: str,
) -> str:
    prefix = seed_prefix.strip("/") or "seeds"
    return f"gs://{bucket_name}/{prefix}/{project_id}/{seed_id}_{safe_filename}"


def build_dataset_gcs_uri(
    *,
    bucket_name: str,
    dataset_prefix: str,
    project_id: str,
    folder_path: str,
    video_id: str,
) -> str:
    prefix = dataset_prefix.strip("/") or "datasets"
    clean_folder = clean_folder_path_for_gcs(folder_path)
    return f"gs://{bucket_name}/{prefix}/{project_id}/{clean_folder}/{video_id}.mp4"


def parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    """Parse 'gs://<bucket>/<object_key>' into (bucket_name, object_key)."""
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI {gcs_uri!r}; expected 'gs://<bucket>/<key>'.")
    without_scheme = gcs_uri[5:]
    slash_idx = without_scheme.find("/")
    if slash_idx <= 0 or slash_idx == len(without_scheme) - 1:
        raise ValueError(f"Invalid GCS URI {gcs_uri!r}; missing bucket or object key.")
    bucket = without_scheme[:slash_idx]
    object_key = without_scheme[slash_idx + 1 :]
    return bucket, object_key


class StorageBucketAdapter(ABC):
    """Abstract object storage interface supporting GCS and local filesystem mock mode."""

    mode: AdapterMode

    @abstractmethod
    def upload_bytes(
        self,
        gcs_uri: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> int:
        """Persist object bytes at canonical gcs_uri and return stored byte count."""

    @abstractmethod
    def download_bytes(self, gcs_uri: str) -> bytes:
        """Read full object bytes from canonical gcs_uri."""

    @abstractmethod
    def exists(self, gcs_uri: str) -> bool:
        """Check whether an object exists at canonical gcs_uri."""

    @abstractmethod
    def get_size_bytes(self, gcs_uri: str) -> int:
        """Return total byte length of stored object."""

    @abstractmethod
    def download_range(self, gcs_uri: str, start: int, end: int) -> bytes:
        """Read inclusive byte slice [start..end] from stored object."""

    @abstractmethod
    def generate_download_url(
        self,
        gcs_uri: str,
        *,
        filename: str,
        fallback_stream_url: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Return V4 Signed URL in live GCP mode, or reachable fallback URL when local/unsigned."""


class LocalStorageAdapter(StorageBucketAdapter):
    """Deterministic local filesystem storage mirroring gs://${GCS_BUCKET_NAME}/..."""

    mode: AdapterMode = "mock"

    def __init__(self, local_storage_dir: Path) -> None:
        self.local_storage_dir = local_storage_dir
        self.gcs_root = self.local_storage_dir / "gcs"
        self.gcs_root.mkdir(parents=True, exist_ok=True)

    def resolve_local_path(self, gcs_uri: str) -> Path:
        bucket, key = parse_gcs_uri(gcs_uri)
        safe_parts = [p for p in key.split("/") if p and p not in (".", "..")]
        if not safe_parts:
            raise ValueError(f"Unsafe or empty GCS object key in {gcs_uri!r}")
        return self.gcs_root.joinpath(bucket, *safe_parts)

    def upload_bytes(
        self,
        gcs_uri: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> int:
        target = self.resolve_local_path(gcs_uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return len(data)

    def download_bytes(self, gcs_uri: str) -> bytes:
        target = self.resolve_local_path(gcs_uri)
        if not target.is_file():
            raise FileNotFoundError(f"Local storage object not found for {gcs_uri}")
        return target.read_bytes()

    def exists(self, gcs_uri: str) -> bool:
        try:
            return self.resolve_local_path(gcs_uri).is_file()
        except ValueError:
            return False

    def get_size_bytes(self, gcs_uri: str) -> int:
        target = self.resolve_local_path(gcs_uri)
        if not target.is_file():
            raise FileNotFoundError(f"Local storage object not found for {gcs_uri}")
        return target.stat().st_size

    def download_range(self, gcs_uri: str, start: int, end: int) -> bytes:
        target = self.resolve_local_path(gcs_uri)
        if not target.is_file():
            raise FileNotFoundError(f"Local storage object not found for {gcs_uri}")
        with target.open("rb") as fh:
            fh.seek(max(0, start))
            length = max(0, end - start + 1)
            return fh.read(length)

    def generate_download_url(
        self,
        gcs_uri: str,
        *,
        filename: str,
        fallback_stream_url: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        return fallback_stream_url


class GCSStorageAdapter(StorageBucketAdapter):
    """Production Google Cloud Storage adapter with V4 Signed URLs and ADC fallback."""

    mode: AdapterMode = "live"

    def __init__(
        self,
        *,
        gcp_project_id: str,
        storage_client: Any = None,
    ) -> None:
        self.gcp_project_id = gcp_project_id
        if storage_client is not None:
            self._client = storage_client
        else:
            from google.cloud import storage

            self._client = storage.Client(project=gcp_project_id)

    def _get_blob(self, gcs_uri: str) -> Any:
        bucket_name, object_key = parse_gcs_uri(gcs_uri)
        bucket = self._client.bucket(bucket_name)
        return bucket.blob(object_key)

    def upload_bytes(
        self,
        gcs_uri: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> int:
        blob = self._get_blob(gcs_uri)
        blob.upload_from_string(data, content_type=content_type)
        return len(data)

    def download_bytes(self, gcs_uri: str) -> bytes:
        blob = self._get_blob(gcs_uri)
        if not blob.exists():
            raise FileNotFoundError(f"GCS object not found: {gcs_uri}")
        return bytes(blob.download_as_bytes())

    def exists(self, gcs_uri: str) -> bool:
        blob = self._get_blob(gcs_uri)
        return bool(blob.exists())

    def get_size_bytes(self, gcs_uri: str) -> int:
        blob = self._get_blob(gcs_uri)
        blob.reload()
        if blob.size is None:
            raise FileNotFoundError(f"GCS object size unavailable: {gcs_uri}")
        return int(blob.size)

    def download_range(self, gcs_uri: str, start: int, end: int) -> bytes:
        blob = self._get_blob(gcs_uri)
        return bytes(blob.download_as_bytes(start=start, end=end))

    def generate_download_url(
        self,
        gcs_uri: str,
        *,
        filename: str,
        fallback_stream_url: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        blob = self._get_blob(gcs_uri)
        try:
            return str(
                blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(seconds=int(expires_in_seconds)),
                    method="GET",
                    response_disposition=f'attachment; filename="{filename}"',
                    response_type="video/mp4",
                )
            )
        except Exception:
            # When running under workload identity / user ADC without private signing key,
            # fall back cleanly to the backend's direct byte-range stream URL.
            return fallback_stream_url
