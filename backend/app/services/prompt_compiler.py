"""UAV Forward & Downward Aerial System Prompt Compiler for Visko Orbis Stable."""

from __future__ import annotations

import os
import re
from typing import Any

from app.models.schemas import (
    CANONICAL_MODEL_ID,
    SUPPORTED_CAMERA_MODES,
    CameraMode,
    SystemPromptResponse,
    SystemPromptTemplates,
    validate_model_slug,
)

STEERING_ANCHOR_PREFIX = (
    "Maintaining continuous forward-and-downward UAV aerial flight along the same trajectory,"
)

CAMERA_MODE_TEMPLATES: dict[CameraMode, str] = {
    "forward_downward_oblique": (
        "Stabilized nose-mounted autonomous UAV perception camera pitched 35 degrees downward "
        "while cruising steadily forward above the terrain; the upper frame captures the forward "
        "flight corridor and horizon line while the lower two-thirds resolve downward ground-plane "
        "topography, roads, structures, vegetation, and wind-driven surface motion in crisp "
        "photorealistic detail, clean optical sensor view, single unbroken continuous aerial take."
    ),
    "nadir_downward": (
        "Stabilized belly-mounted nadir UAV mapping camera pointing straight downward (-90 degrees "
        "pitch) translating smoothly forward over the Earth's surface, resolving overhead terrain "
        "geometry, road networks, rooftops, coastlines, and wind-rippled water or dust plumes in "
        "sharp photorealistic detail, clean optical sensor view, single unbroken continuous aerial take."
    ),
    "forward_fpv": (
        "Stabilized forward-facing autonomous quadcopter navigation camera pitched 15 degrees "
        "downward flying steadily along a low-altitude aerial corridor, resolving obstacle depth, "
        "ridge contours, and crosswind drift in crisp photorealistic detail, single unbroken "
        "continuous aerial take."
    ),
}

_COMPACT_CAMERA_OPENERS: dict[CameraMode, str] = {
    "forward_downward_oblique": (
        "Stabilized nose-mounted autonomous UAV perception camera pitched 35 degrees downward "
        "cruising steadily forward"
    ),
    "nadir_downward": (
        "Stabilized belly-mounted nadir UAV mapping camera pointing straight downward (-90 degrees pitch) "
        "translating smoothly forward"
    ),
    "forward_fpv": (
        "Stabilized forward-facing autonomous quadcopter navigation camera pitched 15 degrees downward "
        "flying steadily along a low-altitude aerial corridor"
    ),
}

_ECOSYSTEM_VISUAL_DESCRIPTORS: dict[str, str] = {
    "alpine": (
        "an alpine mountain pass with granite ridges, pine slopes, and a winding glacial river; "
        "gusting crosswinds whip snow spray across dark rock faces"
    ),
    "coastal": (
        "a rugged coastal headland and marina shoreline with turquoise surf; "
        "brisk onshore winds drive whitecaps and sea spray across rocky cliffs"
    ),
    "urban_canyon": (
        "a dense metropolitan urban canyon of glass towers, arterial avenues, and intersections; "
        "channelized wind gusts rustle street trees and rooftop plumes"
    ),
    "temperate_forest": (
        "a rolling temperate forest canopy cut by winding fire roads and valley streams; "
        "steady crosswinds sway dense evergreen and deciduous treetops"
    ),
    "arid_desert": (
        "an arid desert highway corridor flanked by sculpted dunes and ochre mesas; "
        "dry crosswinds sweep fine golden sand ribbons across sunbaked terrain"
    ),
    "wetlands": (
        "braided river wetlands with marsh channels, reed islands, and shimmering floodplains; "
        "surface breezes ripple shallow water and bend tall marsh grass"
    ),
    "custom": (
        "varied real-world terrain with roads, natural topography, and vegetation; "
        "steady winds drive subtle surface motion across the ground plane"
    ),
}

# Ordered specific negation phrases -> positive physical states (longer phrases first)
_NEGATION_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(?:no|without|zero)\s+drone\s+(?:props|propellers|rotors|arms|frame)\b", re.I),
        "unobstructed wide-angle lens view",
    ),
    (
        re.compile(r"\b(?:no|without|zero)\s+(?:props|propellers|rotors|hud|text|overlays|watermarks?)\b", re.I),
        "unobstructed wide-angle lens view",
    ),
    (
        re.compile(r"\b(?:no|without|zero)\s+(?:people|pedestrians|crowds|humans|persons)\b", re.I),
        "empty open roadways",
    ),
    (
        re.compile(r"\b(?:no|without|zero)\s+(?:clouds|cloud\s+cover|overcast)\b|\bcloudless\b", re.I),
        "clear sunlit sky",
    ),
    (
        re.compile(r"\b(?:no|without|zero)\s+(?:trees|forests?|foliage|vegetation)\b|\btreeless\b", re.I),
        "barren rocky tundra",
    ),
    (
        re.compile(r"\b(?:no|without|zero)\s+(?:cars|vehicles|traffic|trucks)\b", re.I),
        "empty open roadways",
    ),
    (
        re.compile(r"\b(?:no|without|zero)\s+(?:buildings|structures|houses|cities)\b", re.I),
        "open natural terrain",
    ),
    (
        re.compile(r"\b(?:no|without|zero)\s+(?:fog|mist|haze|smoke)\b", re.I),
        "crisp high-visibility air",
    ),
    (
        re.compile(r"\b(?:no|without|zero)\s+(?:wind|gusts|breeze|turbulence)\b", re.I),
        "calm still air",
    ),
    (
        re.compile(r"\b(?:no|without|zero)\s+(?:rain|storms?|precipitation|snow)\b", re.I),
        "dry sunlit surface conditions",
    ),
)

_GENERIC_NEGATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:do\s+not|don'?t|never)\s+(?:show|include|render|add|place|have)\s+([a-z0-9_\-]+(?:\s+[a-z0-9_\-]+){0,2})",
            re.I,
        ),
        "clean unobstructed terrain",
    ),
    (
        re.compile(r"\b(?:no|without)\s+([a-z][a-z0-9_\-]*(?:\s+[a-z][a-z0-9_\-]*)?)\b", re.I),
        "clear open physical terrain",
    ),
)


def validate_camera_mode(camera_mode: str | None) -> CameraMode:
    """Validate camera_mode against the 3 canonical UAV gimbal modes."""
    if camera_mode is None:
        return "forward_downward_oblique"
    if camera_mode not in SUPPORTED_CAMERA_MODES:
        raise ValueError(
            f"Unsupported camera_mode {camera_mode!r}. Must be one of {list(SUPPORTED_CAMERA_MODES)}."
        )
    return camera_mode  # type: ignore[return-value]


def rewrite_negations(text: str) -> str:
    """Rewrite negative prompts ('no people', 'no clouds', 'no trees', etc.) into positive physical nouns."""
    if not text:
        return ""
    result = text.strip()
    for pattern, replacement in _NEGATION_REWRITES:
        result = pattern.sub(replacement, result)
    for pattern, replacement in _GENERIC_NEGATION_PATTERNS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"\s+", " ", result).strip(" ,;")
    return result


def _enforce_word_limit(prompt: str, max_words: int = 95) -> str:
    """Ensure compiled opening prompt stays strictly <= max_words while preserving closing optical clause."""
    words = prompt.split()
    if len(words) <= max_words:
        return prompt
    closing = "clean optical sensor view, single unbroken continuous aerial take."
    closing_words = closing.split()
    budget = max(20, max_words - len(closing_words))
    trimmed = " ".join(words[:budget]).rstrip(" ,;.")
    return f"{trimmed}, {closing}"


class AerialSystemPromptCompiler:
    """Compiles opening world-stake and live mid-stream steering prompts for reactor/visko-orbis-stable."""

    DEFAULT_CAMERA_MODE: CameraMode = "forward_downward_oblique"
    MAX_INITIAL_WORDS: int = 95

    def __init__(self, system_prompt_override: str | None = None) -> None:
        self._explicit_override = (
            system_prompt_override.strip()
            if system_prompt_override and system_prompt_override.strip()
            else None
        )

    @property
    def active_override(self) -> str | None:
        if self._explicit_override is not None:
            return self._explicit_override
        env_val = os.environ.get("ORBIS_AERIAL_SYSTEM_PROMPT", "").strip()
        return env_val if env_val else None

    @property
    def custom_override_active(self) -> bool:
        return self.active_override is not None

    def get_template(self, camera_mode: str | None = None) -> str:
        mode = validate_camera_mode(camera_mode)
        if self.active_override:
            return self.active_override
        return CAMERA_MODE_TEMPLATES[mode]

    def get_system_prompt_metadata(
        self, camera_mode: str | None = None
    ) -> SystemPromptResponse:
        selected_mode = validate_camera_mode(camera_mode)
        override = self.active_override
        templates = SystemPromptTemplates(
            forward_downward_oblique=override or CAMERA_MODE_TEMPLATES["forward_downward_oblique"],
            nadir_downward=override or CAMERA_MODE_TEMPLATES["nadir_downward"],
            forward_fpv=override or CAMERA_MODE_TEMPLATES["forward_fpv"],
        )
        return SystemPromptResponse(
            model_id=CANONICAL_MODEL_ID,
            default_camera_mode=self.DEFAULT_CAMERA_MODE,
            selected_camera_mode=selected_mode,
            selected_template=getattr(templates, selected_mode),
            passthrough=True,
            supported_camera_modes=list(SUPPORTED_CAMERA_MODES),
            templates=templates,
            steering_anchor_prefix=STEERING_ANCHOR_PREFIX,
            custom_override_active=override is not None,
            active_override=override,
        )

    def compile_initial_prompt(
        self,
        user_prompt: str | None = None,
        camera_mode: str | None = "forward_downward_oblique",
        ecosystem_type: str = "alpine",
        drone_altitude_agl_m: float = 65.0,
        drone_airspeed_mps: float = 12.0,
        model_id: str = CANONICAL_MODEL_ID,
        **kwargs: Any,
    ) -> str:
        """Compile a 2-3 sentence, <= 95-word opening Drone-POV prompt with zero negations."""
        if user_prompt is None:
            user_prompt = kwargs.get("prompt") or kwargs.get("initial_prompt")
        if "altitude_agl_m" in kwargs and drone_altitude_agl_m == 65.0:
            drone_altitude_agl_m = float(kwargs["altitude_agl_m"])
        validate_model_slug(model_id)
        mode = validate_camera_mode(camera_mode)
        alt_int = max(1, int(round(drone_altitude_agl_m)))
        speed_val = round(float(drone_airspeed_mps), 1)

        override = self.active_override
        if override:
            camera_clause = rewrite_negations(override).rstrip(".")
            kinematics_clause = f"{camera_clause} at {alt_int} meters AGL and {speed_val} m/s."
        else:
            opener = _COMPACT_CAMERA_OPENERS[mode]
            if mode == "forward_downward_oblique":
                framing = (
                    "the upper frame captures the forward flight corridor and horizon while the "
                    "lower two-thirds resolve downward ground-plane topography and roads"
                )
            elif mode == "nadir_downward":
                framing = (
                    "resolving overhead terrain geometry, road networks, rooftops, and surface textures directly below"
                )
            else:
                framing = (
                    "resolving forward obstacle depth, ridge contours, and ground-plane crosswind drift below"
                )
            kinematics_clause = (
                f"{opener} {alt_int} meters above ground at {speed_val} m/s; {framing}."
            )

        eco_desc = _ECOSYSTEM_VISUAL_DESCRIPTORS.get(
            ecosystem_type, _ECOSYSTEM_VISUAL_DESCRIPTORS["custom"]
        )
        cleaned_user = rewrite_negations(user_prompt or "")
        if cleaned_user:
            cleaned_user = cleaned_user.rstrip(".!;")
            scene_sentence = (
                f"Below across {ecosystem_type.replace('_', ' ')} terrain, {cleaned_user}, "
                "clean optical sensor view, single unbroken continuous aerial take."
            )
        else:
            scene_sentence = (
                f"The flight traverses {eco_desc}, clean optical sensor view, "
                "single unbroken continuous aerial take."
            )

        compiled = f"{kinematics_clause} {scene_sentence}"
        return _enforce_word_limit(compiled, max_words=self.MAX_INITIAL_WORDS)

    def compile_steering_prompt(
        self,
        user_prompt: str,
        camera_mode: str | None = None,
        model_id: str = CANONICAL_MODEL_ID,
        **_kwargs: Any,
    ) -> str:
        """Compile incremental mid-stream steering delta with camera-lock anchor without restating world."""
        validate_model_slug(model_id)
        if camera_mode is not None:
            validate_camera_mode(camera_mode)
        if not user_prompt or not user_prompt.strip():
            raise ValueError("Steering prompt must not be empty.")

        positive_delta = rewrite_negations(user_prompt)
        if not positive_delta:
            positive_delta = "steady forward aerial conditions continue across the terrain"

        # Lowercase leading letter unless acronym like UAV/EDR/ISA
        if (
            len(positive_delta) > 1
            and positive_delta[0].isupper()
            and not positive_delta[:2].isupper()
        ):
            positive_delta = positive_delta[0].lower() + positive_delta[1:]

        positive_delta = positive_delta.rstrip(".!;")
        return f"{STEERING_ANCHOR_PREFIX} {positive_delta}."

    def build_set_prompt_payload(
        self, compiled_prompt: str
    ) -> dict[str, Any]:
        """Build wire command payload for reactor.send_command('set_prompt', ...)."""
        return {
            "prompt": compiled_prompt,
            "passthrough": True,
        }
