"""Seed media 16:9 (832x480) normalizer and Dubai 256x256 aerial preset service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import uuid

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.models.schemas import (
    DUBAI_SOURCE_DATASET,
    CameraMode,
    EcosystemType,
    PresetCatalogResponse,
    PresetTileItem,
)

ORBIS_SEED_WIDTH = 832
ORBIS_SEED_HEIGHT = 480
DUBAI_TILE_SIZE = 256
DUBAI_CROP_HEIGHT_16X9 = 144  # Exact 16:9 crop height for 256px width (256 * 9 / 16 = 144)

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".webm"}
SUPPORTED_SEED_EXTENSIONS = SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS

SUPPORTED_MIME_PREFIXES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "video/mp4",
    "video/webm",
    "application/octet-stream",  # Allowed only when filename extension is explicitly valid
}

MAX_SEED_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB

HF_DUBAI_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=ayoubkirouane/Dubai_dataset-Aerial_Imagery_256x256"
    "&config=default&split=train"
)
HF_DUBAI_PARQUET_URL = (
    "https://huggingface.co/datasets/ayoubkirouane/Dubai_dataset-Aerial_Imagery_256x256"
    "/resolve/main/data/train-00000-of-00001-b05739c2cec48638.parquet"
)


class SeedValidationError(ValueError):
    """Raised when uploaded seed media fails format, MIME, or integrity checks."""


@dataclass(frozen=True)
class CuratedDubaiPresetSpec:
    preset_id: str
    row_index: int
    title: str
    ecosystem_type: EcosystemType
    recommended_camera_mode: CameraMode
    suggested_prompt: str


CURATED_DUBAI_PRESETS: tuple[CuratedDubaiPresetSpec, ...] = (
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-00",
        row_index=0,
        title="Dubai Marina Coastal Breakwater",
        ecosystem_type="coastal",
        recommended_camera_mode="forward_downward_oblique",
        suggested_prompt=(
            "Brisk onshore sea breeze drives whitecaps across turquoise marina channels "
            "and stone breakwaters under bright coastal sunlight"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-01",
        row_index=1,
        title="Al Qudra Desert Arterial Highway",
        ecosystem_type="arid_desert",
        recommended_camera_mode="forward_downward_oblique",
        suggested_prompt=(
            "Dry crosswinds sweep fine golden sand ribbons across desert highway lanes "
            "and ochre dune crests under crisp sunlight"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-02",
        row_index=2,
        title="Downtown Boulevard Urban Grid",
        ecosystem_type="urban_canyon",
        recommended_camera_mode="nadir_downward",
        suggested_prompt=(
            "Channelized urban canyon gusts ripple palm avenues and rooftop ventilation plumes "
            "between geometric commercial blocks"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-03",
        row_index=3,
        title="Creek Tidal Lagoon & Wetlands",
        ecosystem_type="wetlands",
        recommended_camera_mode="nadir_downward",
        suggested_prompt=(
            "Steady estuarine wind ripples shallow turquoise lagoon channels, sandbars, "
            "and coastal mangrove fringes"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-04",
        row_index=4,
        title="Jumeirah Shoreline & Pier Corridor",
        ecosystem_type="coastal",
        recommended_camera_mode="forward_downward_oblique",
        suggested_prompt=(
            "Moderate 12 m/s coastal crosswind pushes surf foam along sandy shoreline "
            "and waterfront promenade roads"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-05",
        row_index=5,
        title="Business Bay Canal & Tower Canyon",
        ecosystem_type="urban_canyon",
        recommended_camera_mode="forward_downward_oblique",
        suggested_prompt=(
            "Gusty thermal updrafts and crosswinds shimmer across the urban canal surface "
            "flanked by glass high-rise towers"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-06",
        row_index=6,
        title="Red Dune Ridge & Desert Track",
        ecosystem_type="arid_desert",
        recommended_camera_mode="forward_fpv",
        suggested_prompt=(
            "16 m/s desert crosswind lofts dust plumes along sculpted terracotta sand ridges "
            "and an unpaved utility corridor"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-07",
        row_index=7,
        title="Zabeel Irrigated Canopy & Interchange",
        ecosystem_type="temperate_forest",
        recommended_camera_mode="nadir_downward",
        suggested_prompt=(
            "Steady breeze sways dense green park canopies bordering curved highway ramps "
            "and clear open roadways"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-08",
        row_index=8,
        title="Palm Frond Waterfront Villas",
        ecosystem_type="coastal",
        recommended_camera_mode="nadir_downward",
        suggested_prompt=(
            "Onshore coastal gusts ripple narrow turquoise waterway channels lined with "
            "uniform waterfront rooftops and piers"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-09",
        row_index=9,
        title="Industrial Desert Logistics Grid",
        ecosystem_type="arid_desert",
        recommended_camera_mode="nadir_downward",
        suggested_prompt=(
            "Hot afternoon crosswinds carry light dust across wide paved yards, "
            "warehouse roofs, and arid perimeter roads"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-10",
        row_index=10,
        title="Hatta Foothill Rocky Escarpment",
        ecosystem_type="alpine",
        recommended_camera_mode="forward_downward_oblique",
        suggested_prompt=(
            "Ridge crosswinds sweep across dark craggy escarpments, wadi gravel beds, "
            "and winding mountain switchbacks"
        ),
    ),
    CuratedDubaiPresetSpec(
        preset_id="dubai-tile-11",
        row_index=11,
        title="Ras Al Khor Sanctuary Channels",
        ecosystem_type="wetlands",
        recommended_camera_mode="forward_downward_oblique",
        suggested_prompt=(
            "Light crosswinds shimmer across intertidal mudflats, braided creek channels, "
            "and green wetland islands"
        ),
    ),
)

PRESET_BY_ID: dict[str, CuratedDubaiPresetSpec] = {p.preset_id: p for p in CURATED_DUBAI_PRESETS}


def sanitize_filename(filename: str) -> str:
    base = Path(filename or "seed.jpg").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return cleaned or "seed.jpg"


def find_ffmpeg_binary() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    homebrew_path = Path("/opt/homebrew/bin/ffmpeg")
    if homebrew_path.is_file():
        return str(homebrew_path)
    usr_local = Path("/usr/local/bin/ffmpeg")
    if usr_local.is_file():
        return str(usr_local)
    return None


def center_crop_16x9_box(width: int, height: int) -> tuple[int, int, int, int]:
    """Compute exact centered 16:9 crop rectangle (left, top, right, bottom) without stretch."""
    if width <= 0 or height <= 0:
        raise SeedValidationError(f"Invalid image dimensions: {width}x{height}")
    target_aspect = 16.0 / 9.0
    current_aspect = width / height

    if abs(current_aspect - target_aspect) < 1e-3:
        return (0, 0, width, height)
    if current_aspect < target_aspect:
        # Taller/squarer than 16:9 (e.g. 256x256 -> 256x144)
        crop_w = width
        crop_h = max(1, int(round(width / target_aspect)))
        top = (height - crop_h) // 2
        return (0, top, crop_w, top + crop_h)
    else:
        # Wider than 16:9
        crop_h = height
        crop_w = max(1, int(round(height * target_aspect)))
        left = (width - crop_w) // 2
        return (left, 0, left + crop_w, crop_h)


def normalize_image_bytes_to_832x480(
    raw_bytes: bytes,
    *,
    sharpen_upscale: bool = False,
    output_format: str = "JPEG",
) -> bytes:
    """Center-crop arbitrary RGB image bytes to 16:9 and Lanczos-resize to 832x480."""
    if not raw_bytes:
        raise SeedValidationError("Uploaded seed image payload is empty.")
    try:
        with Image.open(BytesIO(raw_bytes)) as img:
            transposed = ImageOps.exif_transpose(img)
            rgb = transposed.convert("RGB")
            src_w, src_h = rgb.size
            crop_box = center_crop_16x9_box(src_w, src_h)
            cropped = rgb.crop(crop_box)
            was_upscaled = cropped.width < ORBIS_SEED_WIDTH or cropped.height < ORBIS_SEED_HEIGHT
            resized = cropped.resize(
                (ORBIS_SEED_WIDTH, ORBIS_SEED_HEIGHT),
                resample=Image.Resampling.LANCZOS,
            )
            if sharpen_upscale or was_upscaled:
                resized = resized.filter(
                    ImageFilter.UnsharpMask(radius=1.2, percent=95, threshold=2)
                )
    except SeedValidationError:
        raise
    except Exception as exc:
        raise SeedValidationError(f"Invalid or corrupted image file: {exc}") from exc

    buf = BytesIO()
    fmt = output_format.upper()
    if fmt == "PNG":
        resized.save(buf, format="PNG", optimize=True)
    else:
        resized.save(buf, format="JPEG", quality=92, subsampling=0)
    return buf.getvalue()


def extract_video_keyframe_bytes(raw_video_bytes: bytes, suffix: str = ".mp4") -> bytes:
    """Extract a representative RGB frame from an uploaded .mp4 or .webm seed video via ffmpeg."""
    if not raw_video_bytes:
        raise SeedValidationError("Uploaded seed video payload is empty.")
    ffmpeg_bin = find_ffmpeg_binary()
    if not ffmpeg_bin:
        raise SeedValidationError("ffmpeg is required to extract keyframes from video seeds.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        video_path = tmp_path / f"input{suffix}"
        frame_path = tmp_path / "keyframe.png"
        video_path.write_bytes(raw_video_bytes)

        proc = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                str(frame_path),
            ],
            capture_output=True,
            timeout=20,
        )
        if proc.returncode != 0 or not frame_path.is_file() or frame_path.stat().st_size == 0:
            stderr_msg = proc.stderr.decode("utf-8", errors="ignore")[:240]
            raise SeedValidationError(
                f"Unable to decode video keyframe via ffmpeg: {stderr_msg or 'invalid video container'}"
            )
        return frame_path.read_bytes()


def validate_and_normalize_seed_upload(
    *,
    filename: str,
    content_type: str | None,
    raw_bytes: bytes,
) -> tuple[bytes, str, LiteralMediaKind]:
    """Validate extension/MIME/size and return (normalized_832x480_jpeg_bytes, clean_filename, media_kind)."""
    if not raw_bytes:
        raise SeedValidationError("Seed media file must not be empty.")
    if len(raw_bytes) > MAX_SEED_UPLOAD_BYTES:
        raise SeedValidationError("Seed media exceeds maximum 100 MB upload limit.")

    clean_name = sanitize_filename(filename)
    ext = Path(clean_name).suffix.lower()
    if ext not in SUPPORTED_SEED_EXTENSIONS:
        raise SeedValidationError(
            f"Unsupported seed file extension {ext!r}. Allowed: {sorted(SUPPORTED_SEED_EXTENSIONS)}"
        )

    mime = (content_type or "").split(";")[0].strip().lower()
    if mime and mime not in SUPPORTED_MIME_PREFIXES:
        raise SeedValidationError(
            f"Unsupported seed MIME type {mime!r}. Allowed: .png, .jpg, .jpeg, .webp, .mp4, .webm."
        )

    if ext in SUPPORTED_VIDEO_EXTENSIONS:
        frame_bytes = extract_video_keyframe_bytes(raw_bytes, suffix=ext)
        normalized_jpeg = normalize_image_bytes_to_832x480(
            frame_bytes, sharpen_upscale=True, output_format="JPEG"
        )
        return normalized_jpeg, clean_name, "video"

    normalized_jpeg = normalize_image_bytes_to_832x480(
        raw_bytes, sharpen_upscale=True, output_format="JPEG"
    )
    return normalized_jpeg, clean_name, "image"


LiteralMediaKind = str  # "image" | "video"


def synthesize_deterministic_dubai_256_tile(spec: CuratedDubaiPresetSpec) -> bytes:
    """Generate a deterministic, realistic 256x256 RGB overhead aerial tile for offline/mock resilience."""
    img = Image.new("RGB", (DUBAI_TILE_SIZE, DUBAI_TILE_SIZE))
    draw = ImageDraw.Draw(img)
    seed_offset = (spec.row_index + 1) * 17

    eco = spec.ecosystem_type
    if eco == "coastal":
        # Sand shore + turquoise marina channel + stone breakwater + pier slips
        draw.rectangle([0, 0, 255, 255], fill=(218, 198, 162))
        draw.polygon([(0, 0), (255, 0), (255, 165), (0, 130)], fill=(22, 128, 152))
        draw.polygon([(0, 118), (255, 152), (255, 170), (0, 136)], fill=(238, 232, 214))
        # Breakwater & piers
        draw.line([(20, 75), (230, 95)], fill=(142, 138, 130), width=8)
        for x in range(40, 220, 28):
            draw.line([(x, 95), (x - 4, 130)], fill=(210, 212, 215), width=3)
        # Coastal road
        draw.line([(0, 205), (255, 215)], fill=(68, 72, 78), width=14)
        draw.line([(0, 205), (255, 215)], fill=(225, 215, 165), width=1)
    elif eco == "arid_desert":
        # Sculpted ochre sand dunes + multi-lane desert highway
        for y in range(256):
            wave = int(14 * math.sin((y + seed_offset) * 0.09))
            r = min(255, max(160, 214 + wave))
            g = min(255, max(120, 168 + wave // 2))
            b = min(255, max(80, 112 + wave // 3))
            draw.line([(0, y), (255, y)], fill=(r, g, b))
        draw.line([(0, 148), (255, 108)], fill=(62, 64, 68), width=20)
        draw.line([(0, 148), (255, 108)], fill=(235, 210, 120), width=2)
    elif eco == "urban_canyon":
        # Asphalt grid + urban blocks + canal + rooftops
        draw.rectangle([0, 0, 255, 255], fill=(58, 62, 68))
        for gx in range(18, 250, 56):
            for gy in range(18, 250, 52):
                shade = ((gx * 7 + gy * 13 + seed_offset) % 45) + 150
                draw.rectangle(
                    [gx, gy, min(250, gx + 40), min(250, gy + 36)],
                    fill=(shade, shade + 4, shade + 10),
                    outline=(90, 96, 105),
                )
        draw.rectangle([0, 116, 255, 140], fill=(28, 116, 148))
    elif eco == "wetlands":
        # Estuarine lagoon + vegetated marsh islands + sandbars
        draw.rectangle([0, 0, 255, 255], fill=(34, 118, 128))
        for idx in range(7):
            cx = (idx * 43 + seed_offset) % 210 + 20
            cy = (idx * 61 + seed_offset) % 190 + 30
            draw.ellipse([cx - 28, cy - 16, cx + 28, cy + 16], fill=(186, 174, 138))
            draw.ellipse([cx - 20, cy - 11, cx + 20, cy + 11], fill=(64, 118, 72))
    elif eco == "temperate_forest":
        # Irrigated green canopy + parkway roads
        draw.rectangle([0, 0, 255, 255], fill=(54, 104, 58))
        for idx in range(28):
            cx = (idx * 37 + seed_offset) % 240 + 8
            cy = (idx * 53 + seed_offset) % 240 + 8
            g_tone = 88 + (idx * 11) % 55
            draw.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=(42, g_tone, 48))
        draw.arc([-40, 60, 290, 220], start=185, end=355, fill=(74, 78, 84), width=12)
    else:
        # Alpine / rocky escarpment + switchback road
        draw.rectangle([0, 0, 255, 255], fill=(96, 92, 88))
        for idx in range(12):
            y0 = idx * 22
            shade = 72 + ((idx * 19 + seed_offset) % 52)
            draw.polygon(
                [(0, y0), (130, y0 + 14), (255, y0 - 6), (255, y0 + 22), (0, y0 + 22)],
                fill=(shade, shade - 2, shade - 5),
            )
        draw.line([(15, 235), (195, 155), (55, 95), (235, 35)], fill=(128, 126, 122), width=7)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class DubaiPresetService:
    """Manages curated 256x256 Dubai aerial tiles with optional HF fetch and deterministic offline cache."""

    def __init__(self, cache_dir: Path, *, allow_network_fetch: bool = False) -> None:
        self.cache_dir = cache_dir
        self.allow_network_fetch = allow_network_fetch
        self._tile_256_cache: dict[str, bytes] = {}
        self._preview_832x480_cache: dict[str, bytes] = {}

    def list_presets(self, *, limit: int = 12, offset: int = 0) -> PresetCatalogResponse:
        sliced = CURATED_DUBAI_PRESETS[offset : offset + limit]
        items = [
            PresetTileItem(
                preset_id=spec.preset_id,
                title=spec.title,
                source_dataset=DUBAI_SOURCE_DATASET,
                row_index=spec.row_index,
                ecosystem_type=spec.ecosystem_type,
                recommended_camera_mode=spec.recommended_camera_mode,
                suggested_prompt=spec.suggested_prompt,
                preview_url=f"/api/v1/media/seed/{spec.preset_id}/preview",
            )
            for spec in sliced
        ]
        return PresetCatalogResponse(
            dataset=DUBAI_SOURCE_DATASET,
            source_dataset=DUBAI_SOURCE_DATASET,
            presets=items,
        )

    def get_preset_spec(self, preset_id: str) -> CuratedDubaiPresetSpec | None:
        return PRESET_BY_ID.get(preset_id)

    async def get_raw_256_tile_bytes(self, spec: CuratedDubaiPresetSpec) -> bytes:
        """Return 256x256 RGB tile bytes from cache, HF datasets-server (when online), or deterministic bundle."""
        if spec.preset_id in self._tile_256_cache:
            return self._tile_256_cache[spec.preset_id]

        disk_tile = self.cache_dir / "dubai_tiles_256" / f"{spec.preset_id}.png"
        if disk_tile.is_file() and disk_tile.stat().st_size > 0:
            data = disk_tile.read_bytes()
            self._tile_256_cache[spec.preset_id] = data
            return data

        fetched: bytes | None = None
        if self.allow_network_fetch:
            fetched = await self._try_fetch_hf_tile(spec.row_index)

        raw_256 = fetched if fetched else synthesize_deterministic_dubai_256_tile(spec)
        try:
            disk_tile.parent.mkdir(parents=True, exist_ok=True)
            disk_tile.write_bytes(raw_256)
        except OSError:
            pass
        self._tile_256_cache[spec.preset_id] = raw_256
        return raw_256

    async def get_normalized_832x480_preset_bytes(self, spec: CuratedDubaiPresetSpec) -> bytes:
        """Transform 256x256 (1:1) Dubai tile -> 256x144 (16:9) center-crop -> 832x480 Lanczos + UnsharpMask."""
        if spec.preset_id in self._preview_832x480_cache:
            return self._preview_832x480_cache[spec.preset_id]

        raw_256 = await self.get_raw_256_tile_bytes(spec)
        normalized = normalize_image_bytes_to_832x480(
            raw_256,
            sharpen_upscale=True,
            output_format="JPEG",
        )
        self._preview_832x480_cache[spec.preset_id] = normalized
        return normalized

    async def _try_fetch_hf_tile(self, row_index: int) -> bytes | None:
        """Best-effort fetch from Hugging Face datasets-server with fast timeout."""
        url = f"{HF_DUBAI_ROWS_URL}&offset={row_index}&length=1"
        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None
                payload: dict[str, Any] = resp.json()
                rows = payload.get("rows") or []
                if not rows:
                    return None
                row_obj = rows[0].get("row") or {}
                image_entry = row_obj.get("image") or {}
                src_url = image_entry.get("src") if isinstance(image_entry, dict) else None
                if not src_url:
                    return None
                img_resp = await client.get(src_url)
                if img_resp.status_code == 200 and img_resp.content:
                    with Image.open(BytesIO(img_resp.content)) as im:
                        resized_256 = im.convert("RGB").resize(
                            (DUBAI_TILE_SIZE, DUBAI_TILE_SIZE),
                            Image.Resampling.LANCZOS,
                        )
                        out = BytesIO()
                        resized_256.save(out, format="PNG")
                        return out.getvalue()
        except Exception:
            return None
        return None


def make_seed_id(prefix: str = "seed") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
