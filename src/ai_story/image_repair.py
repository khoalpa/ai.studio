from __future__ import annotations

from typing import Any

REPAIR_RULES = {
    "IMAGE_DECODE_FAILED": ("REGENERATE", "Generate a clean decodable PNG.", []),
    "DIMENSIONS_MISMATCH": ("REGENERATE", "Keep the requested aspect ratio and framing.", []),
    "LOW_VISUAL_VARIANCE": (
        "REGENERATE", "Increase subject detail, local contrast, and background separation.", []
    ),
    "LUMINANCE_OUT_OF_BAND": (
        "REGENERATE", "Use balanced exposure with visible faces and midtone detail.", []
    ),
    "UNWANTED_TEXT": (
        "REGENERATE", "Render no letters, captions, signs, logos, or watermark.",
        ["letters", "caption", "signage", "logo", "watermark"],
    ),
    "SEMANTIC_MISMATCH": (
        "REGENERATE", "Prioritize the declared action, location, characters, and required props.", []
    ),
    "PARITY_MISMATCH": (
        "RECOMPOSE", "Preserve the source scene, identity, wardrobe, props, palette, and lighting.", []
    ),
    "IDENTITY_MISMATCH": (
        "REGENERATE", "Match each role-bound face, hair, age, silhouette, outfit, and palette reference.",
        ["changed identity", "face swap", "mixed identity"],
    ),
    "REQUIRED_ELEMENT_MISSING": (
        "RECOMPOSE", "Make every required subject and prop clearly visible at its specified position.", []
    ),
    "ASSESSOR_UNAVAILABLE": ("ABORT", "", []),
}


def plan_image_repair(
    failure: dict[str, Any], *, attempt: int, asset_type: str
) -> dict[str, Any]:
    findings = failure.get("findings") or [{"error": "UNKNOWN_IMAGE_FAILURE"}]
    codes = list(dict.fromkeys(str(item.get("error", "UNKNOWN_IMAGE_FAILURE")) for item in findings))
    rules = [REPAIR_RULES.get(code, ("REGENERATE", "Regenerate while preserving the shot specification.", [])) for code in codes]
    missing_elements = list(dict.fromkeys(
        str(element).split(":", 1)[-1].replace("_", " ")
        for finding in findings if finding.get("error") == "REQUIRED_ELEMENT_MISSING"
        for element in finding.get("elements", [])
    ))
    corrections = [rule[1] for rule in rules if rule[1]]
    if missing_elements:
        corrections.insert(0, "Clearly show these missing required elements: " + ", ".join(missing_elements))
    retryable = all(rule[0] != "ABORT" for rule in rules)
    strength_override = None
    if "PARITY_MISMATCH" in codes:
        strength_override = 0.24
    elif "IDENTITY_MISMATCH" in codes:
        strength_override = 0.3
    guidance_override = None
    steps_override = None
    if "SEMANTIC_MISMATCH" in codes or "REQUIRED_ELEMENT_MISSING" in codes:
        guidance_override = min(8.0, 6.5 + 0.5 * attempt)
        steps_override = min(40, 28 + 4 * attempt)
    return {
        "schema_version": "1.0",
        "planner": "RULE_BASED_LAYERED_IMAGE_REPAIR_V2",
        "attempt": attempt,
        "asset_type": asset_type,
        "failure_codes": codes,
        "source_layers": list(dict.fromkeys(
            str(item.get("layer", "UNKNOWN")) for item in findings
        )),
        "disposition": "ABORT" if not retryable else (
            "RECOMPOSE" if any(rule[0] == "RECOMPOSE" for rule in rules) else "REGENERATE"
        ),
        "retryable": retryable,
        "prompt_corrections": corrections,
        "negative_prompt_additions": list(dict.fromkeys(
            value for rule in rules for value in rule[2]
        )),
        "parameter_adjustments": {
            "strength": strength_override,
            "guidance_scale": guidance_override,
            "steps": steps_override,
            "seed_policy": "NEXT_DETERMINISTIC_ATTEMPT",
        },
    }
