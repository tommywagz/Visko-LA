"""Layer 1A Unit Tests: Fixed Recording Interval Validator (5s, 10s, 15s)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
import pytest

from app.models.schemas import RecordClipRequest, validate_strict_duration
from app.services.clip_recorder import validate_recording_interval


@pytest.mark.parametrize("valid_sec", [5, 10, 15])
def test_valid_integer_recording_intervals_pass(valid_sec: int) -> None:
    assert validate_recording_interval(duration_seconds=valid_sec) == valid_sec
    assert validate_strict_duration(duration_seconds=valid_sec) == valid_sec
    req = RecordClipRequest(duration_seconds=valid_sec)
    assert req.duration_seconds == valid_sec
    assert req.interval_setting == f"{valid_sec}s"


@pytest.mark.parametrize(("valid_str", "expected_sec"), [("5s", 5), ("10s", 10), ("15s", 15)])
def test_valid_string_interval_settings_pass(valid_str: str, expected_sec: int) -> None:
    assert validate_recording_interval(interval_setting=valid_str) == expected_sec
    req = RecordClipRequest(interval_setting=valid_str)
    assert req.duration_seconds == expected_sec
    assert req.interval_setting == valid_str

    # Matching pair also succeeds
    req_both = RecordClipRequest(duration_seconds=expected_sec, interval_setting=valid_str)
    assert req_both.duration_seconds == expected_sec


@pytest.mark.parametrize(
    "invalid_duration",
    [
        0,
        -5,
        -1,
        1,
        3,
        4,
        6,
        7,
        8,
        9,
        11,
        14,
        16,
        20,
        30,
        60,
        5.0,
        7.5,
        10.0,
        True,
        False,
        "5",
        "7s",
        "20s",
        "",
        [],
        {},
    ],
)
def test_invalid_recording_durations_strictly_rejected(invalid_duration: Any) -> None:
    """T2-01: Reject all non-{5, 10, 15} ints, floats, booleans, and invalid strings."""
    with pytest.raises(ValueError):
        validate_recording_interval(duration_seconds=invalid_duration)

    with pytest.raises(ValidationError):
        RecordClipRequest(duration_seconds=invalid_duration)


@pytest.mark.parametrize("invalid_setting", ["0s", "3s", "7s", "8s", "20s", "30s", "60s", "5", 5, True, ""])
def test_invalid_interval_setting_strings_rejected(invalid_setting: Any) -> None:
    with pytest.raises(ValueError):
        validate_recording_interval(interval_setting=invalid_setting)

    with pytest.raises(ValidationError):
        RecordClipRequest(interval_setting=invalid_setting)


def test_missing_or_conflicting_interval_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        RecordClipRequest()

    with pytest.raises(ValidationError):
        RecordClipRequest(duration_seconds=5, interval_setting="15s")
