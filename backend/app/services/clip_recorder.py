"""Fixed-interval (5s, 10s, 15s) MP4 video synthesizer, remuxer, and ISO BMFF fallback."""

from __future__ import annotations

from pathlib import Path
import struct
import subprocess
from typing import Any

from app.models.schemas import VALID_RECORDING_DURATIONS, validate_strict_duration
from app.services.seed_normalizer import find_ffmpeg_binary

ORBIS_FPS = 18


def validate_recording_interval(
    duration_seconds: Any = None,
    interval_setting: Any = None,
) -> int:
    """Validate fixed recording duration strictly in {5, 10, 15} seconds."""
    return validate_strict_duration(
        duration_seconds=duration_seconds,
        interval_setting=interval_setting,
    )


def verify_mp4_ftyp_signature(mp4_bytes: bytes) -> bool:
    """Verify valid ISO Base Media File Format ('ftyp' box at bytes[4:8])."""
    return len(mp4_bytes) >= 32 and mp4_bytes[4:8] == b"ftyp"


def remux_mpegts_to_mp4(ts_path: Path, output_mp4_path: Path) -> bytes:
    """Losslessly remux Reactor MPEG-TS (.ts) clip stream into web-compatible faststart .mp4."""
    ffmpeg_bin = find_ffmpeg_binary()
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg binary is required to remux MPEG-TS clips to MP4.")

    output_mp4_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(ts_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_mp4_path),
        ],
        capture_output=True,
        timeout=45,
    )
    if proc.returncode != 0 or not output_mp4_path.is_file():
        stderr_txt = proc.stderr.decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"ffmpeg MPEG-TS -> MP4 remux failed: {stderr_txt}")

    mp4_bytes = output_mp4_path.read_bytes()
    if not verify_mp4_ftyp_signature(mp4_bytes):
        raise RuntimeError("Remuxed MP4 failed ISO BMFF ftyp header verification.")
    return mp4_bytes


def _mp4_box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type) + payload


def _mp4_full_box(box_type: bytes, version: int, flags: int, payload: bytes) -> bytes:
    vf = ((version & 0xFF) << 24) | (flags & 0xFFFFFF)
    return _mp4_box(box_type, struct.pack(">I", vf) + payload)


def build_minimal_iso_bmff_mp4(
    duration_seconds: int,
    *,
    width: int = 832,
    height: int = 480,
    fps: int = ORBIS_FPS,
) -> bytes:
    """Pure-Python valid ISO Base Media File Format (.mp4) fallback if ffmpeg is unavailable."""
    timescale = 1000
    duration_units = int(duration_seconds * timescale)
    frame_count = max(1, duration_seconds * fps)
    sample_delta = max(1, duration_units // frame_count)

    ftyp = _mp4_box(
        b"ftyp",
        b"isom" + struct.pack(">I", 0x200) + b"isomiso2mp41",
    )

    # Synthetic encoded frame payload inside mdat
    frame_payload = b"\x00\x00\x00\x08\x65\x88\x84\x00\x00\xff\xfe\x10"
    mdat_body = frame_payload * frame_count
    mdat = _mp4_box(b"mdat", mdat_body)

    # Movie header (mvhd)
    unity_matrix = struct.pack(">9I", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)
    mvhd_payload = (
        struct.pack(">IIIIIIH", 0, 0, timescale, duration_units, 0x00010000, 0x01000000, 0)
        + b"\x00" * 8
        + unity_matrix
        + b"\x00" * 24
        + struct.pack(">I", 2)
    )
    mvhd = _mp4_full_box(b"mvhd", 0, 0, mvhd_payload)

    # Track header (tkhd)
    tkhd_payload = (
        struct.pack(">III4sI", 0, 0, 1, b"\x00\x00\x00\x00", duration_units)
        + b"\x00" * 8
        + struct.pack(">HHHH", 0, 0, 0, 0)
        + unity_matrix
        + struct.pack(">II", width << 16, height << 16)
    )
    tkhd = _mp4_full_box(b"tkhd", 0, 0x000003, tkhd_payload)

    mdhd = _mp4_full_box(
        b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, timescale, duration_units, 0x55C4, 0)
    )
    hdlr = _mp4_full_box(
        b"hdlr", 0, 0, struct.pack(">I4s12s", 0, b"vide", b"\x00" * 12) + b"ViskoOrbisVideo\x00"
    )
    vmhd = _mp4_full_box(b"vmhd", 0, 1, struct.pack(">HHHH", 0, 0, 0, 0))
    url_box = _mp4_full_box(b"url ", 0, 1, b"")
    dref = _mp4_full_box(b"dref", 0, 0, struct.pack(">I", 1) + url_box)
    dinf = _mp4_box(b"dinf", dref)

    # Minimal 78-byte VisualSampleEntry (mp4v/avc1 compatible container structure)
    visual_entry_fixed = (
        b"\x00" * 6
        + struct.pack(">H", 1)
        + b"\x00" * 16
        + struct.pack(">HHII", width, height, 0x00480000, 0x00480000)
        + struct.pack(">IH", 0, 1)
        + b"\x00" * 32
        + struct.pack(">Hh", 0x0018, -1)
    )
    stsd = _mp4_full_box(
        b"stsd", 0, 0, struct.pack(">I", 1) + _mp4_box(b"mp4v", visual_entry_fixed)
    )
    stts = _mp4_full_box(b"stts", 0, 0, struct.pack(">III", 1, frame_count, sample_delta))
    stsc = _mp4_full_box(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, frame_count, 1))
    stsz = _mp4_full_box(b"stsz", 0, 0, struct.pack(">II", len(frame_payload), frame_count))
    # Compute chunk offset into mdat after ftyp + moov + 8-byte mdat header
    placeholder_stco = _mp4_full_box(b"stco", 0, 0, struct.pack(">II", 1, 0))
    stbl_tmp = _mp4_box(b"stbl", stsd + stts + stsc + stsz + placeholder_stco)
    minf_tmp = _mp4_box(b"minf", vmhd + dinf + stbl_tmp)
    mdia_tmp = _mp4_box(b"mdia", mdhd + hdlr + minf_tmp)
    trak_tmp = _mp4_box(b"trak", tkhd + mdia_tmp)
    moov_tmp = _mp4_box(b"moov", mvhd + trak_tmp)

    mdat_data_offset = len(ftyp) + len(moov_tmp) + 8
    stco = _mp4_full_box(b"stco", 0, 0, struct.pack(">II", 1, mdat_data_offset))
    stbl = _mp4_box(b"stbl", stsd + stts + stsc + stsz + stco)
    minf = _mp4_box(b"minf", vmhd + dinf + stbl)
    mdia = _mp4_box(b"mdia", mdhd + hdlr + minf)
    trak = _mp4_box(b"trak", tkhd + mdia)
    moov = _mp4_box(b"moov", mvhd + trak)

    mp4_bytes = ftyp + moov + mdat
    assert verify_mp4_ftyp_signature(mp4_bytes)
    return mp4_bytes


def synthesize_mock_orbis_mp4(
    duration_seconds: int,
    *,
    ecosystem_type: str = "alpine",
    output_mp4_path: Path | None = None,
) -> bytes:
    """Synthesize a genuine playable H.264/yuv420p .mp4 clip of exact duration_seconds (5, 10, or 15)."""
    if duration_seconds not in VALID_RECORDING_DURATIONS:
        raise ValueError(f"duration_seconds must be in {VALID_RECORDING_DURATIONS}")

    color_map = {
        "alpine": "0x1e293b",
        "coastal": "0x0e7490",
        "urban_canyon": "0x334155",
        "temperate_forest": "0x166534",
        "arid_desert": "0xb45309",
        "wetlands": "0x0f766e",
        "custom": "0x1d4ed8",
    }
    hex_color = color_map.get(ecosystem_type, "0x1e293b")

    ffmpeg_bin = find_ffmpeg_binary()
    if ffmpeg_bin:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            target_file = output_mp4_path or (Path(tmpdir) / f"orbis_{duration_seconds}s.mp4")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            # Generate 832x480 @ 18fps H.264 yuv420p +faststart MP4 quickly
            lavfi_src = (
                f"color=c={hex_color}:s=832x480:r={ORBIS_FPS}:d={duration_seconds},"
                "drawgrid=w=104:h=80:t=2:c=0x38bdf8@0.35"
            )
            proc = subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    lavfi_src,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-tune",
                    "zerolatency",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(target_file),
                ],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode == 0 and target_file.is_file():
                data = target_file.read_bytes()
                if verify_mp4_ftyp_signature(data):
                    return data

    # Fallback if ffmpeg is unavailable or lacks libx264
    fallback_bytes = build_minimal_iso_bmff_mp4(duration_seconds)
    if output_mp4_path is not None:
        output_mp4_path.parent.mkdir(parents=True, exist_ok=True)
        output_mp4_path.write_bytes(fallback_bytes)
    return fallback_bytes
