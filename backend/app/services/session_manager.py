"""Runtime container, seed registry, and live Orbis + Telemetry session manager."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import uuid

from app.adapters.catalog import (
    BigQueryCatalogAdapter,
    CatalogNotFoundError,
    MetadataCatalogAdapter,
    SQLiteCatalogAdapter,
    slugify_identifier,
    utc_now_iso,
)
from app.adapters.orbis import (
    LiveReactorOrbisAdapter,
    MockReactorOrbisAdapter,
    ORBIS_CHUNK_DURATION_SECONDS,
    ORBIS_FPS,
    ORBIS_FRAMES_PER_CHUNK,
    OrbisDriverSession,
    ReactorOrbisAdapter,
)
from app.adapters.storage import (
    GCSStorageAdapter,
    LocalStorageAdapter,
    StorageBucketAdapter,
    build_dataset_gcs_uri,
    build_seed_gcs_uri,
)
from app.config import Settings, get_settings
from app.models.schemas import (
    CANONICAL_MODEL_ID,
    CameraMode,
    CreateSessionRequest,
    DatasetRecord,
    EcosystemType,
    PromptEntry,
    ReanchorSeedResponse,
    ResolutionOption,
    SeedMediaResponse,
    SessionStateResponse,
    SteerPromptResponse,
    TelemetryFrame,
    validate_strict_duration,
)
from app.services.clip_recorder import verify_mp4_ftyp_signature
from app.services.prompt_compiler import AerialSystemPromptCompiler, validate_camera_mode
from app.services.seed_normalizer import (
    DubaiPresetService,
    SeedValidationError,
    make_seed_id,
    validate_and_normalize_seed_upload,
)
from app.services.telemetry_engine import SessionTelemetryEngine


@dataclass
class StoredSeedEntry:
    response: SeedMediaResponse
    normalized_gcs_uri: str


@dataclass
class ManagedAerialSession:
    session_id: str
    reactor_session_id: str
    project_id: str
    folder_id: str
    camera_mode: CameraMode
    ecosystem_type: EcosystemType
    resolution: ResolutionOption
    compiled_system_prompt: str
    initial_prompt: str
    reactor_jwt: str
    expires_at: int
    created_at: str
    driver_session: OrbisDriverSession
    telemetry_engine: SessionTelemetryEngine
    initial_telemetry: TelemetryFrame
    prompt_history: list[PromptEntry] = field(default_factory=list)
    seed_id: str | None = None
    seed_media_gcs_uri: str | None = None
    preview_url: str | None = None
    ws_queues: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    closed: bool = False

    def broadcast_event(self, event: dict[str, Any]) -> None:
        for q in list(self.ws_queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass

    def build_orbis_state_event(self) -> dict[str, Any]:
        chunk_idx = self.driver_session.chunk_index
        status = "closed" if self.closed else self.driver_session.effective_status
        frames_emitted = 0 if chunk_idx == 0 else chunk_idx * ORBIS_FRAMES_PER_CHUNK
        return {
            "type": "orbis_state",
            "session_id": self.session_id,
            "status": status,
            "mode": self.driver_session.mode,
            "model_id": CANONICAL_MODEL_ID,
            "chunk_index": chunk_idx,
            "frames_emitted": frames_emitted,
            "fps": ORBIS_FPS,
            "chunk_duration_seconds": ORBIS_CHUNK_DURATION_SECONDS,
            "camera_mode": self.camera_mode,
            "ecosystem_type": self.telemetry_engine.ecosystem_type,
            "active_prompt": self.driver_session.active_prompt,
            "timestamp_ms": int(time.time() * 1000),
        }

    def to_response(self) -> SessionStateResponse:
        status = "closed" if self.closed else self.driver_session.effective_status
        latest = self.telemetry_engine.latest_frame
        return SessionStateResponse(
            session_id=self.session_id,
            reactor_session_id=self.reactor_session_id,
            project_id=self.project_id,
            folder_id=self.folder_id,
            model_id=CANONICAL_MODEL_ID,
            mode=self.driver_session.mode,
            status=status,
            chunk_index=self.driver_session.chunk_index,
            camera_mode=self.camera_mode,
            ecosystem_type=self.telemetry_engine.ecosystem_type,
            passthrough=True,
            compiled_system_prompt=self.compiled_system_prompt,
            reactor_jwt=self.reactor_jwt,
            expires_at=self.expires_at,
            reactor_jwt_expires_at=self.expires_at,
            ws_url=f"/ws/orbis/stream/{self.session_id}",
            seed_id=self.seed_id,
            seed_media_gcs_uri=self.seed_media_gcs_uri,
            preview_url=self.preview_url,
            initial_telemetry=self.initial_telemetry,
            latest_telemetry=latest,
            prompt_history=list(self.prompt_history),
            created_at=self.created_at,
        )


class BackendRuntime:
    """Centralized runtime wiring adapters, prompt compiler, seed store, and sessions."""

    def __init__(self) -> None:
        self._settings_key: tuple[Any, ...] | None = None
        self._custom_orbis: ReactorOrbisAdapter | None = None
        self._custom_storage: StorageBucketAdapter | None = None
        self._custom_catalog: MetadataCatalogAdapter | None = None

        self._orbis: ReactorOrbisAdapter | None = None
        self._storage: StorageBucketAdapter | None = None
        self._catalog: MetadataCatalogAdapter | None = None
        self._presets: DubaiPresetService | None = None

        self._seeds: dict[str, StoredSeedEntry] = {}
        self._sessions: dict[str, ManagedAerialSession] = {}

    def set_custom_adapters(
        self,
        *,
        orbis: ReactorOrbisAdapter | None = None,
        storage: StorageBucketAdapter | None = None,
        catalog: MetadataCatalogAdapter | None = None,
    ) -> None:
        """Allow unit/integration tests to inject explicit adapter mocks."""
        self._custom_orbis = orbis
        self._custom_storage = storage
        self._custom_catalog = catalog

    def _compute_env_key(self, s: Settings) -> tuple[Any, ...]:
        return (
            s.orbis_mock_mode,
            s.reactor_api_key,
            s.reactor_api_url,
            s.gcp_mock_mode,
            s.gcp_project_id,
            s.gcs_bucket_name,
            s.bq_dataset_id,
            str(s.local_storage_dir),
        )

    def ensure_initialized(self) -> Settings:
        settings = get_settings()
        env_key = self._compute_env_key(settings)
        if self._settings_key != env_key:
            if self._custom_orbis is None:
                if settings.orbis_mock_mode:
                    self._orbis = MockReactorOrbisAdapter()
                else:
                    self._orbis = LiveReactorOrbisAdapter(
                        api_key=settings.reactor_api_key,
                        api_url=settings.reactor_api_url,
                        model_slug=CANONICAL_MODEL_ID,
                    )
            if self._custom_storage is None:
                if settings.gcp_mock_mode:
                    self._storage = LocalStorageAdapter(settings.local_storage_dir)
                else:
                    self._storage = GCSStorageAdapter(gcp_project_id=settings.gcp_project_id)
            if self._custom_catalog is None:
                if settings.gcp_mock_mode:
                    db_path = settings.local_storage_dir / "bq_catalog.db"
                    self._catalog = SQLiteCatalogAdapter(db_path)
                else:
                    self._catalog = BigQueryCatalogAdapter(
                        gcp_project_id=settings.gcp_project_id,
                        bq_dataset_id=settings.bq_dataset_id,
                        bq_datasets_table_id=settings.bq_datasets_table_id,
                        bq_folders_table_id=settings.bq_folders_table_id,
                        gcp_region=settings.gcp_region,
                    )
            self._presets = DubaiPresetService(
                cache_dir=settings.local_storage_dir / "preset_cache",
                allow_network_fetch=not settings.orbis_mock_mode,
            )
            self._settings_key = env_key
        return settings

    @property
    def orbis(self) -> ReactorOrbisAdapter:
        self.ensure_initialized()
        return self._custom_orbis or self._orbis  # type: ignore[return-value]

    @property
    def storage(self) -> StorageBucketAdapter:
        self.ensure_initialized()
        return self._custom_storage or self._storage  # type: ignore[return-value]

    @property
    def catalog(self) -> MetadataCatalogAdapter:
        self.ensure_initialized()
        return self._custom_catalog or self._catalog  # type: ignore[return-value]

    @property
    def presets(self) -> DubaiPresetService:
        self.ensure_initialized()
        assert self._presets is not None
        return self._presets

    @property
    def prompt_compiler(self) -> AerialSystemPromptCompiler:
        settings = get_settings()
        return AerialSystemPromptCompiler(
            system_prompt_override=settings.orbis_aerial_system_prompt
        )

    def _seed_meta_dir(self, settings: Settings) -> Path:
        d = settings.local_storage_dir / "seeds_meta"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_seed_entry(self, settings: Settings, entry: StoredSeedEntry) -> None:
        self._seeds[entry.response.seed_id] = entry
        meta_file = self._seed_meta_dir(settings) / f"{entry.response.seed_id}.json"
        payload = {
            "response": entry.response.model_dump(),
            "normalized_gcs_uri": entry.normalized_gcs_uri,
        }
        try:
            meta_file.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass

    def get_seed_entry(self, seed_id: str) -> StoredSeedEntry | None:
        settings = self.ensure_initialized()
        if seed_id in self._seeds:
            return self._seeds[seed_id]
        meta_file = self._seed_meta_dir(settings) / f"{seed_id}.json"
        if meta_file.is_file():
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
                entry = StoredSeedEntry(
                    response=SeedMediaResponse(**raw["response"]),
                    normalized_gcs_uri=raw["normalized_gcs_uri"],
                )
                self._seeds[seed_id] = entry
                return entry
            except Exception:
                return None
        return None

    def find_seed_by_gcs_uri(self, gcs_uri: str) -> StoredSeedEntry | None:
        self.ensure_initialized()
        for entry in self._seeds.values():
            if (
                entry.response.seed_media_gcs_uri == gcs_uri
                or entry.normalized_gcs_uri == gcs_uri
            ):
                return entry
        return None

    async def create_seed_from_preset(
        self, *, preset_id: str, project_id: str
    ) -> SeedMediaResponse:
        settings = self.ensure_initialized()
        spec = self.presets.get_preset_spec(preset_id)
        if spec is None:
            raise CatalogNotFoundError(f"Unknown Dubai aerial preset_id {preset_id!r}.")

        normalized_bytes = await self.presets.get_normalized_832x480_preset_bytes(spec)
        seed_id = make_seed_id("seed")
        safe_filename = f"{spec.preset_id}_832x480.jpg"
        gcs_uri = build_seed_gcs_uri(
            bucket_name=settings.gcs_bucket_name,
            seed_prefix=settings.gcs_seed_prefix,
            project_id=project_id,
            seed_id=seed_id,
            safe_filename=safe_filename,
        )
        self.storage.upload_bytes(gcs_uri, normalized_bytes, content_type="image/jpeg")

        resp = SeedMediaResponse(
            seed_id=seed_id,
            project_id=project_id,
            preset_id=spec.preset_id,
            filename=safe_filename,
            mime_type="image/jpeg",
            media_kind="image",
            seed_media_gcs_uri=gcs_uri,
            gcs_uri=gcs_uri,
            preview_url=f"/api/v1/media/seed/{seed_id}/preview",
            width=832,
            height=480,
            aspect_ratio="16:9",
            ecosystem_type=spec.ecosystem_type,
            recommended_camera_mode=spec.recommended_camera_mode,
            suggested_prompt=spec.suggested_prompt,
            created_at=utc_now_iso(),
        )
        self._save_seed_entry(settings, StoredSeedEntry(response=resp, normalized_gcs_uri=gcs_uri))
        return resp

    def create_seed_from_upload(
        self,
        *,
        filename: str,
        content_type: str | None,
        raw_bytes: bytes,
        project_id: str,
    ) -> SeedMediaResponse:
        settings = self.ensure_initialized()
        normalized_jpeg, clean_name, media_kind = validate_and_normalize_seed_upload(
            filename=filename,
            content_type=content_type,
            raw_bytes=raw_bytes,
        )
        seed_id = make_seed_id("seed")

        # Archive raw uploaded seed file to GCS per backend.md §1B
        raw_mime = (content_type or "application/octet-stream").split(";")[0].strip()
        raw_gcs_uri = build_seed_gcs_uri(
            bucket_name=settings.gcs_bucket_name,
            seed_prefix=settings.gcs_seed_prefix,
            project_id=project_id,
            seed_id=seed_id,
            safe_filename=clean_name,
        )
        self.storage.upload_bytes(raw_gcs_uri, raw_bytes, content_type=raw_mime)

        # Also persist normalized 832x480 16:9 JPEG alongside raw seed for Orbis conditioning & preview
        stem = Path(clean_name).stem
        norm_name = f"{stem}_832x480.jpg"
        norm_gcs_uri = build_seed_gcs_uri(
            bucket_name=settings.gcs_bucket_name,
            seed_prefix=settings.gcs_seed_prefix,
            project_id=project_id,
            seed_id=seed_id,
            safe_filename=norm_name,
        )
        self.storage.upload_bytes(norm_gcs_uri, normalized_jpeg, content_type="image/jpeg")

        # If uploaded input was already an image, overwrite raw_gcs_uri with normalized 832x480 ONLY if same name,
        # otherwise expose raw_gcs_uri (or norm_gcs_uri for images) while keeping normalized_gcs_uri ready for I2V.
        primary_gcs_uri = norm_gcs_uri if media_kind == "image" else raw_gcs_uri
        out_mime = "image/jpeg" if media_kind == "image" else raw_mime

        resp = SeedMediaResponse(
            seed_id=seed_id,
            project_id=project_id,
            preset_id=None,
            filename=clean_name,
            mime_type=out_mime,
            media_kind=media_kind,  # type: ignore[arg-type]
            seed_media_gcs_uri=primary_gcs_uri,
            gcs_uri=primary_gcs_uri,
            preview_url=f"/api/v1/media/seed/{seed_id}/preview",
            width=832,
            height=480,
            aspect_ratio="16:9",
            ecosystem_type=None,
            recommended_camera_mode="forward_downward_oblique",
            suggested_prompt=None,
            created_at=utc_now_iso(),
        )
        self._save_seed_entry(
            settings, StoredSeedEntry(response=resp, normalized_gcs_uri=norm_gcs_uri)
        )
        return resp

    async def get_seed_preview_bytes(self, seed_or_preset_id: str) -> bytes:
        """Serve normalized 832x480 JPEG preview for either a seed_id or a Dubai preset_id."""
        self.ensure_initialized()
        preset_spec = self.presets.get_preset_spec(seed_or_preset_id)
        if preset_spec is not None:
            return await self.presets.get_normalized_832x480_preset_bytes(preset_spec)

        entry = self.get_seed_entry(seed_or_preset_id)
        if entry is None:
            raise CatalogNotFoundError(f"Seed preview {seed_or_preset_id!r} not found.")
        try:
            return self.storage.download_bytes(entry.normalized_gcs_uri)
        except FileNotFoundError as exc:
            raise CatalogNotFoundError(f"Seed preview blob missing for {seed_or_preset_id!r}.") from exc

    def _resolve_seed_bytes_and_meta(
        self,
        *,
        seed_id: str | None,
        seed_media_gcs_uri: str | None,
    ) -> tuple[bytes | None, str | None, str | None, str | None]:
        """Return (seed_bytes, resolved_seed_id, resolved_gcs_uri, preview_url)."""
        if seed_id:
            entry = self.get_seed_entry(seed_id)
            if entry is None:
                raise CatalogNotFoundError(f"Seed {seed_id!r} not found.")
            img_bytes = self.storage.download_bytes(entry.normalized_gcs_uri)
            return (
                img_bytes,
                entry.response.seed_id,
                entry.response.seed_media_gcs_uri,
                entry.response.preview_url,
            )

        if seed_media_gcs_uri:
            matched = self.find_seed_by_gcs_uri(seed_media_gcs_uri)
            if matched is not None:
                img_bytes = self.storage.download_bytes(matched.normalized_gcs_uri)
                return (
                    img_bytes,
                    matched.response.seed_id,
                    matched.response.seed_media_gcs_uri,
                    matched.response.preview_url,
                )
            if self.storage.exists(seed_media_gcs_uri):
                raw = self.storage.download_bytes(seed_media_gcs_uri)
                norm_bytes, _, _ = validate_and_normalize_seed_upload(
                    filename=Path(seed_media_gcs_uri).name,
                    content_type=None,
                    raw_bytes=raw,
                )
                return norm_bytes, None, seed_media_gcs_uri, None
            raise CatalogNotFoundError(f"Seed GCS URI {seed_media_gcs_uri!r} not found.")

        return None, None, None, None

    async def create_session(self, req: CreateSessionRequest) -> ManagedAerialSession:
        self.ensure_initialized()
        uri_candidate = req.seed_media_gcs_uri or req.seed_gcs_uri
        seed_bytes, resolved_seed_id, resolved_gcs_uri, preview_url = (
            self._resolve_seed_bytes_and_meta(
                seed_id=req.seed_id,
                seed_media_gcs_uri=uri_candidate,
            )
        )

        session_id = f"sess_{uuid.uuid4().hex[:10]}"
        seed_int = int(hashlib.sha256(session_id.encode()).hexdigest()[:8], 16)

        telemetry_engine = SessionTelemetryEngine(
            session_seed=seed_int,
            ecosystem_type=req.ecosystem_type,
            camera_mode=req.camera_mode,
            drone_altitude_agl_m=req.drone_altitude_agl_m,
            initial_prompt=req.initial_prompt,
        )
        initial_telemetry = telemetry_engine.sample(dt_seconds=0.0, chunk_index=0)

        compiled_prompt = self.prompt_compiler.compile_initial_prompt(
            req.initial_prompt,
            camera_mode=req.camera_mode,
            ecosystem_type=req.ecosystem_type,
            drone_altitude_agl_m=req.drone_altitude_agl_m,
            drone_airspeed_mps=initial_telemetry.drone_airspeed_mps,
            model_id=req.model_id,
        )

        driver_session = await self.orbis.start_session(
            compiled_initial_prompt=compiled_prompt,
            resolution=req.resolution,
            seed_image_bytes=seed_bytes,
            seed_filename=f"{resolved_seed_id or 'seed'}_832x480.jpg",
            model_id=req.model_id,
        )

        token_resp = await self.orbis.mint_jwt(
            session_id_to_bind=driver_session.reactor_session_id,
            max_sessions=5,
            expires_after=3600,
            model_id=req.model_id,
        )

        now_iso = utc_now_iso()
        opening_raw = (
            req.initial_prompt.strip()
            if req.initial_prompt and req.initial_prompt.strip()
            else f"Autonomous {req.ecosystem_type.replace('_', ' ')} UAV perception survey"
        )
        first_entry = PromptEntry(
            prompt_id=f"prm_{uuid.uuid4().hex[:8]}",
            prompt=opening_raw,
            compiled_prompt=compiled_prompt,
            passthrough=True,
            chunk_index=0,
            status="applied",
            created_at=now_iso,
        )

        managed = ManagedAerialSession(
            session_id=session_id,
            reactor_session_id=driver_session.reactor_session_id,
            project_id=req.project_id,
            folder_id=req.folder_id,
            camera_mode=req.camera_mode,
            ecosystem_type=req.ecosystem_type,
            resolution=req.resolution,
            compiled_system_prompt=compiled_prompt,
            initial_prompt=opening_raw,
            reactor_jwt=token_resp.jwt,
            expires_at=token_resp.expires_at,
            created_at=now_iso,
            driver_session=driver_session,
            telemetry_engine=telemetry_engine,
            initial_telemetry=initial_telemetry,
            prompt_history=[first_entry],
            seed_id=resolved_seed_id,
            seed_media_gcs_uri=resolved_gcs_uri,
            preview_url=preview_url,
        )
        self._sessions[session_id] = managed
        return managed

    def get_session(self, session_id: str) -> ManagedAerialSession:
        self.ensure_initialized()
        sess = self._sessions.get(session_id)
        if sess is None or sess.closed:
            raise CatalogNotFoundError(f"Session {session_id!r} not found.")
        return sess

    async def steer_session_prompt(
        self,
        session_id: str,
        *,
        raw_prompt: str,
        camera_mode: str | None = None,
    ) -> SteerPromptResponse:
        sess = self.get_session(session_id)
        if camera_mode is not None:
            validated_cam = validate_camera_mode(camera_mode)
            sess.camera_mode = validated_cam
            sess.telemetry_engine.adjust_flight(camera_mode=validated_cam)

        compiled = self.prompt_compiler.compile_steering_prompt(
            raw_prompt,
            camera_mode=sess.camera_mode,
        )
        await self.orbis.steer_prompt(sess.reactor_session_id, compiled)

        updated_targets = sess.telemetry_engine.apply_prompt_directives(raw_prompt, immediate=False)
        chunk_idx = sess.driver_session.chunk_index
        latest = sess.telemetry_engine.sample(dt_seconds=0.1, chunk_index=chunk_idx)

        entry = PromptEntry(
            prompt_id=f"prm_{uuid.uuid4().hex[:8]}",
            prompt=raw_prompt,
            compiled_prompt=compiled,
            passthrough=True,
            chunk_index=chunk_idx,
            status="applied",
            created_at=utc_now_iso(),
        )
        sess.prompt_history.append(entry)

        ack_event = {
            "type": "prompt_ack",
            "session_id": sess.session_id,
            "prompt_id": entry.prompt_id,
            "prompt": raw_prompt,
            "raw_prompt": raw_prompt,
            "compiled_prompt": compiled,
            "passthrough": True,
            "chunk_index": chunk_idx,
            "status": "applied",
            "updated_telemetry_targets": updated_targets,
            "timestamp_ms": int(time.time() * 1000),
        }
        sess.broadcast_event(ack_event)

        return SteerPromptResponse(
            session_id=sess.session_id,
            status="applied",
            chunk_index=chunk_idx,
            raw_prompt=raw_prompt,
            compiled_prompt=compiled,
            passthrough=True,
            prompt_entry=entry,
            prompt_history=list(sess.prompt_history),
            updated_telemetry_targets=updated_targets,
            latest_telemetry=latest,
        )

    async def reanchor_session_seed(
        self,
        session_id: str,
        *,
        seed_id: str | None = None,
        seed_media_gcs_uri: str | None = None,
        prompt: str | None = None,
    ) -> ReanchorSeedResponse:
        sess = self.get_session(session_id)
        seed_bytes, resolved_seed_id, resolved_gcs_uri, preview_url = (
            self._resolve_seed_bytes_and_meta(
                seed_id=seed_id,
                seed_media_gcs_uri=seed_media_gcs_uri,
            )
        )
        assert seed_bytes is not None and resolved_gcs_uri is not None

        prompt_source = prompt.strip() if prompt and prompt.strip() else sess.initial_prompt
        compiled = self.prompt_compiler.compile_initial_prompt(
            prompt_source,
            camera_mode=sess.camera_mode,
            ecosystem_type=sess.telemetry_engine.ecosystem_type,
            drone_altitude_agl_m=sess.telemetry_engine.drone_altitude_agl_m,
            drone_airspeed_mps=sess.telemetry_engine.drone_airspeed_mps,
        )

        sess.broadcast_event(
            {
                "type": "orbis_state",
                "session_id": sess.session_id,
                "status": "reanchoring",
                "mode": sess.driver_session.mode,
                "model_id": CANONICAL_MODEL_ID,
                "chunk_index": 0,
                "frames_emitted": 0,
                "fps": ORBIS_FPS,
                "chunk_duration_seconds": ORBIS_CHUNK_DURATION_SECONDS,
                "camera_mode": sess.camera_mode,
                "ecosystem_type": sess.telemetry_engine.ecosystem_type,
                "active_prompt": compiled,
                "timestamp_ms": int(time.time() * 1000),
            }
        )

        command_seq = await self.orbis.reanchor_seed(
            sess.reactor_session_id,
            seed_image_bytes=seed_bytes,
            compiled_prompt=compiled,
            seed_filename=f"{resolved_seed_id or 'seed'}_832x480.jpg",
        )
        sess.telemetry_engine.reset_chunk_clock()
        if prompt and prompt.strip():
            sess.telemetry_engine.apply_prompt_directives(prompt.strip(), immediate=True)

        sess.seed_id = resolved_seed_id
        sess.seed_media_gcs_uri = resolved_gcs_uri
        sess.preview_url = preview_url
        sess.compiled_system_prompt = compiled

        entry = PromptEntry(
            prompt_id=f"prm_{uuid.uuid4().hex[:8]}",
            prompt=f"[Seed Re-Anchor] {prompt_source}",
            compiled_prompt=compiled,
            passthrough=True,
            chunk_index=0,
            status="applied",
            created_at=utc_now_iso(),
        )
        sess.prompt_history.append(entry)
        sess.broadcast_event(sess.build_orbis_state_event())

        return ReanchorSeedResponse(
            session_id=sess.session_id,
            status="applied",
            seed_id=resolved_seed_id,
            seed_media_gcs_uri=resolved_gcs_uri,
            gcs_uri=resolved_gcs_uri,
            preview_url=preview_url,
            command_sequence=command_seq,
            compiled_prompt=compiled,
            passthrough=True,
            chunk_index=0,
        )

    async def record_session_clip(
        self,
        session_id: str,
        *,
        duration_seconds: int,
        project_id: str | None = None,
        folder_id: str | None = None,
        title: str | None = None,
    ) -> DatasetRecord:
        settings = self.ensure_initialized()
        validated_duration = validate_strict_duration(duration_seconds=duration_seconds)
        sess = self.get_session(session_id)

        target_project_id = (project_id or sess.project_id or "default-uav-project").strip()
        target_folder_id = (folder_id or sess.folder_id or "root").strip()

        if self.catalog.get_project(target_project_id) is None:
            raise CatalogNotFoundError(f"Project {target_project_id!r} not found.")
        target_folder = self.catalog.get_folder(target_project_id, target_folder_id)
        if target_folder is None:
            raise CatalogNotFoundError(
                f"Folder {target_folder_id!r} not found in project {target_project_id!r}."
            )

        video_id = f"vid_{uuid.uuid4().hex[:10]}"
        recording_id = f"rec_{uuid.uuid4().hex[:8]}"
        eco = sess.telemetry_engine.ecosystem_type

        sess.broadcast_event(
            {
                "type": "recording_progress",
                "session_id": sess.session_id,
                "recording_id": recording_id,
                "video_id": video_id,
                "duration_seconds": validated_duration,
                "elapsed_seconds": 0.0,
                "progress_pct": 20.0,
                "status": "capturing",
                "gcs_video_uri": None,
                "timestamp_ms": int(time.time() * 1000),
            }
        )

        mp4_bytes = await self.orbis.capture_clip_mp4(
            sess.reactor_session_id,
            validated_duration,
            ecosystem_type=eco,
        )
        if not verify_mp4_ftyp_signature(mp4_bytes):
            raise RuntimeError("Captured video failed ISO BMFF MP4 ftyp header check.")

        sess.broadcast_event(
            {
                "type": "recording_progress",
                "session_id": sess.session_id,
                "recording_id": recording_id,
                "video_id": video_id,
                "duration_seconds": validated_duration,
                "elapsed_seconds": float(validated_duration),
                "progress_pct": 70.0,
                "status": "uploading",
                "gcs_video_uri": None,
                "timestamp_ms": int(time.time() * 1000),
            }
        )

        gcs_video_uri = build_dataset_gcs_uri(
            bucket_name=settings.gcs_bucket_name,
            dataset_prefix=settings.gcs_dataset_prefix,
            project_id=target_project_id,
            folder_path=target_folder.folder_path,
            video_id=video_id,
        )
        file_size_bytes = self.storage.upload_bytes(
            gcs_video_uri, mp4_bytes, content_type="video/mp4"
        )

        agg = sess.telemetry_engine.aggregate_window(validated_duration)
        now_iso = utc_now_iso()
        resolved_title = (
            title.strip()
            if title and title.strip()
            else f"{eco.replace('_', '-')}-{validated_duration}s-{video_id[-6:]}"
        )
        prompt_history_json = json.dumps([p.model_dump() for p in sess.prompt_history])

        dataset = DatasetRecord(
            video_id=video_id,
            project_id=target_project_id,
            folder_id=target_folder.folder_id,
            folder_path=target_folder.folder_path,
            title=resolved_title,
            session_id=sess.session_id,
            model_id=CANONICAL_MODEL_ID,
            ecosystem_type=eco,
            duration_seconds=validated_duration,  # type: ignore[arg-type]
            resolution=sess.resolution,
            fps=ORBIS_FPS,
            gcs_video_uri=gcs_video_uri,
            seed_media_gcs_uri=sess.seed_media_gcs_uri,
            initial_prompt=sess.initial_prompt,
            prompt_history_json=prompt_history_json,
            avg_wind_speed_mps=agg["avg_wind_speed_mps"],
            max_wind_gust_mps=agg["max_wind_gust_mps"],
            wind_direction_deg=agg["wind_direction_deg"],
            avg_air_pressure_hpa=agg["avg_air_pressure_hpa"],
            avg_air_density_kgm3=agg["avg_air_density_kgm3"],
            ambient_temp_c=agg["ambient_temp_c"],
            avg_turbulence_edr=agg["avg_turbulence_edr"],
            max_turbulence_edr=agg["max_turbulence_edr"],
            drone_altitude_agl_m=agg["drone_altitude_agl_m"],
            telemetry_summary_json=agg["telemetry_summary_json"],
            file_size_bytes=file_size_bytes,
            created_at=now_iso,
            download_url=f"/api/v1/datasets/{video_id}/download",
            direct_stream_url=f"/api/v1/datasets/{video_id}/file",
        )
        stored = self.catalog.insert_dataset(dataset)

        sess.broadcast_event(
            {
                "type": "recording_progress",
                "session_id": sess.session_id,
                "recording_id": recording_id,
                "video_id": video_id,
                "duration_seconds": validated_duration,
                "elapsed_seconds": float(validated_duration),
                "progress_pct": 100.0,
                "status": "completed",
                "gcs_video_uri": gcs_video_uri,
                "timestamp_ms": int(time.time() * 1000),
            }
        )
        return stored

    def upload_manual_dataset(
        self,
        *,
        project_id: str,
        folder_id: str,
        filename: str,
        content_type: str | None,
        raw_mp4_bytes: bytes,
        title: str | None = None,
        ecosystem_type: EcosystemType | None = None,
        duration_seconds: int = 5,
        initial_prompt: str | None = None,
        telemetry_overrides: dict[str, float | None] | None = None,
    ) -> DatasetRecord:
        settings = self.ensure_initialized()
        validated_duration = validate_strict_duration(duration_seconds=duration_seconds)

        if not raw_mp4_bytes or len(raw_mp4_bytes) < 8:
            raise SeedValidationError("Uploaded dataset .mp4 file must be non-empty.")

        ext = Path(filename or "clip.mp4").suffix.lower()
        mime = (content_type or "").split(";")[0].strip().lower()
        if ext != ".mp4" and mime not in ("video/mp4",):
            raise SeedValidationError(
                f"Uploaded dataset file must be a .mp4 video (got filename={filename!r}, content_type={content_type!r})."
            )
        if mime and mime not in ("video/mp4", "application/octet-stream"):
            raise SeedValidationError(
                f"Unsupported dataset upload MIME type {mime!r}; expected video/mp4."
            )

        if self.catalog.get_project(project_id) is None:
            raise CatalogNotFoundError(f"Project {project_id!r} not found.")
        target_folder = self.catalog.get_folder(project_id, folder_id)
        if target_folder is None:
            raise CatalogNotFoundError(
                f"Folder {folder_id!r} not found in project {project_id!r}."
            )

        resolved_eco: EcosystemType = (
            ecosystem_type
            or (target_folder.ecosystem_default if target_folder.ecosystem_default else None)  # type: ignore[assignment]
            or "custom"
        )
        video_id = f"vid_{uuid.uuid4().hex[:10]}"
        gcs_video_uri = build_dataset_gcs_uri(
            bucket_name=settings.gcs_bucket_name,
            dataset_prefix=settings.gcs_dataset_prefix,
            project_id=project_id,
            folder_path=target_folder.folder_path,
            video_id=video_id,
        )
        file_size_bytes = self.storage.upload_bytes(
            gcs_video_uri, raw_mp4_bytes, content_type="video/mp4"
        )

        overrides = telemetry_overrides or {}
        alt_m = (
            float(overrides["drone_altitude_agl_m"])
            if overrides.get("drone_altitude_agl_m") is not None
            else 65.0
        )
        baseline_engine = SessionTelemetryEngine(
            session_seed=42,
            ecosystem_type=resolved_eco,
            drone_altitude_agl_m=alt_m,
            initial_prompt=initial_prompt,
        )
        agg = baseline_engine.aggregate_window(validated_duration)

        for key in (
            "avg_wind_speed_mps",
            "max_wind_gust_mps",
            "wind_direction_deg",
            "avg_air_pressure_hpa",
            "avg_air_density_kgm3",
            "ambient_temp_c",
            "avg_turbulence_edr",
            "max_turbulence_edr",
            "drone_altitude_agl_m",
        ):
            if overrides.get(key) is not None:
                agg[key] = float(overrides[key])  # type: ignore[arg-type]

        # Ensure max >= avg invariants if only one side was overridden
        if agg["max_wind_gust_mps"] < agg["avg_wind_speed_mps"]:
            agg["max_wind_gust_mps"] = round(agg["avg_wind_speed_mps"] * 1.25, 2)
        if agg["max_turbulence_edr"] < agg["avg_turbulence_edr"]:
            agg["max_turbulence_edr"] = agg["avg_turbulence_edr"]

        now_iso = utc_now_iso()
        stem = slugify_identifier(Path(filename or "clip").stem, fallback="uploaded-clip")
        resolved_title = title.strip() if title and title.strip() else stem
        resolved_prompt = (
            initial_prompt.strip()
            if initial_prompt and initial_prompt.strip()
            else f"Direct MP4 dataset upload ({resolved_title})"
        )
        compiled_prompt = self.prompt_compiler.compile_initial_prompt(
            resolved_prompt,
            ecosystem_type=resolved_eco,
            drone_altitude_agl_m=agg["drone_altitude_agl_m"],
        )
        prompt_entry = PromptEntry(
            prompt_id=f"prm_{uuid.uuid4().hex[:8]}",
            prompt=resolved_prompt,
            compiled_prompt=compiled_prompt,
            passthrough=True,
            chunk_index=0,
            status="applied",
            created_at=now_iso,
        )

        dataset = DatasetRecord(
            video_id=video_id,
            project_id=project_id,
            folder_id=target_folder.folder_id,
            folder_path=target_folder.folder_path,
            title=resolved_title,
            session_id="direct-upload",
            model_id=CANONICAL_MODEL_ID,
            ecosystem_type=resolved_eco,
            duration_seconds=validated_duration,  # type: ignore[arg-type]
            resolution="832x480",
            fps=ORBIS_FPS,
            gcs_video_uri=gcs_video_uri,
            seed_media_gcs_uri=None,
            initial_prompt=resolved_prompt,
            prompt_history_json=json.dumps([prompt_entry.model_dump()]),
            avg_wind_speed_mps=agg["avg_wind_speed_mps"],
            max_wind_gust_mps=agg["max_wind_gust_mps"],
            wind_direction_deg=agg["wind_direction_deg"],
            avg_air_pressure_hpa=agg["avg_air_pressure_hpa"],
            avg_air_density_kgm3=agg["avg_air_density_kgm3"],
            ambient_temp_c=agg["ambient_temp_c"],
            avg_turbulence_edr=agg["avg_turbulence_edr"],
            max_turbulence_edr=agg["max_turbulence_edr"],
            drone_altitude_agl_m=agg["drone_altitude_agl_m"],
            telemetry_summary_json=agg["telemetry_summary_json"],
            file_size_bytes=file_size_bytes,
            created_at=now_iso,
            download_url=f"/api/v1/datasets/{video_id}/download",
            direct_stream_url=f"/api/v1/datasets/{video_id}/file",
        )
        return self.catalog.insert_dataset(dataset)

    async def close_session(self, session_id: str) -> None:
        sess = self.get_session(session_id)
        sess.closed = True
        await self.orbis.close_session(sess.reactor_session_id)
        sess.broadcast_event(sess.build_orbis_state_event())


runtime = BackendRuntime()
