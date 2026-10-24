from __future__ import annotations

NEGATIVE_PROMPT = [
    "invented events",
    "identity drift",
    "face drift",
    "age drift",
    "wardrobe reset",
    "extra characters",
    "duplicate characters",
    "extra limbs",
    "malformed hands",
    "unmotivated props",
    "text overlays",
    "logos",
    "watermarks",
    "camera jitter",
    "flicker",
    "frame interpolation artifacts",
    "extra dialogue",
]


def design_shot(zone: str, segment_index: int, segment_count: int) -> dict[str, str]:
    by_zone = {
        "GREETING": ("MEDIUM_WIDE", "EYE_LEVEL", "SLOW_PUSH"),
        "OPENING": ("WIDE", "EYE_LEVEL", "SLOW_PUSH"),
        "INTRODUCTION": ("MEDIUM", "EYE_LEVEL", "TRACK_RIGHT"),
        "DEVELOPMENT": ("MEDIUM", "OVER_SHOULDER", "SLOW_PUSH"),
        "CLIMAX": ("MEDIUM_CLOSE", "LOW_ANGLE", "SLOW_PUSH"),
        "FALLING": ("MEDIUM", "EYE_LEVEL", "SLOW_PULL"),
        "ENDING": ("MEDIUM_WIDE", "EYE_LEVEL", "SLOW_PULL"),
        "FAREWELL": ("WIDE", "EYE_LEVEL", "STATIC"),
    }
    shot_size, angle, movement = by_zone.get(zone, ("MEDIUM", "EYE_LEVEL", "STATIC"))
    if segment_count > 1 and segment_index > 1:
        movement = "STATIC"
    return {
        "shot_size": shot_size,
        "camera_angle": angle,
        "camera_movement": movement,
        "framing_rule": "KEEP_FOCAL_EYES_IN_SAFE_AREA",
        "cut_motivation": "SOURCE_UTTERANCE_OR_SCENE_BOUNDARY",
    }
