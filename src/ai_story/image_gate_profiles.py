from typing import Any

PHOTOREALISTIC_INTERACTION_PROMPT = (
    "Photorealistic candid photo in a Hanoi bedroom. Vietnamese boy left and mother right, "
    "seated on the floor. One natural hand each touches an opposite edge of one tiny folded "
    "paper boat. Real skin, distinct fingers, connected wrists, soft daylight, shallow depth."
)

PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT = (
    "text, watermark, extra person, extra limb, malformed hand, fused fingers, detached wrist, "
    "oversized prop, paper bowl, floating boat, cartoon, illustration, line art, blur"
)


def photorealistic_hand_prop_gates(
    crop_box_pixels: list[int] | None = None,
    crop_box_normalized: list[float] | None = None,
    *,
    include_prop_shape_scale: bool = False,
) -> list[dict[str, Any]]:
    """Mandatory gates calibrated by the rejected Phase 4L-R2 climax fixture."""
    crop: dict[str, object] = {}
    if crop_box_pixels is not None:
        crop["crop_box_pixels"] = crop_box_pixels
    elif crop_box_normalized is not None:
        crop["crop_box_normalized"] = crop_box_normalized
    gates = [
        {
            "probe_id": "photorealism_fidelity_gate",
            "required": True,
            "expected": "a realistic documentary photograph taken with a camera",
            "forbidden": [
                "a hand-drawn illustration with black outlines and flat painted colors",
                "a flat vector cartoon",
            ],
            "minimum_expected_score": 0.20,
            "minimum_contrast_margin": 0.0,
        },
        {
            "probe_id": "hand_anatomy_gate",
            "required": True,
            "expected": (
                "two anatomically correct human hands with distinct natural fingers "
                "and realistic connected wrists"
            ),
            "forbidden": [
                "malformed fused hands with distorted fingers",
                "a missing hand or detached wrist",
            ],
            **crop,
            "minimum_expected_score": 0.30,
            "minimum_contrast_margin": 0.04,
        },
        {
            "probe_id": "hand_prop_contact_gate",
            "required": True,
            "expected": (
                "two separate human hands naturally touching opposite edges of one "
                "small folded paper boat"
            ),
            "forbidden": [
                "hands merged into a paper boat as one ambiguous shape",
                "a floating paper boat without clean hand contact",
            ],
            **crop,
            "minimum_expected_score": 0.30,
            "minimum_contrast_margin": 0.04,
        },
    ]
    if include_prop_shape_scale:
        gates.append({
            "probe_id": "paper_boat_shape_scale_gate",
            "required": True,
            "expected": "one tiny palm-sized folded paper boat with a crisp triangular origami silhouette",
            "forbidden": [
                "an oversized paper bowl on the floor",
                "a giant crumpled paper object larger than the hands",
                "a full-size ship",
            ],
            **crop,
            "minimum_expected_score": 0.28,
            "minimum_contrast_margin": 0.04,
        })
    return gates


def identity_cast_hand_count_gates(
    interaction_crop_normalized: list[float],
) -> list[dict[str, Any]]:
    """Reject cropped cast framing and ambiguous extra-hand interactions."""
    return [
        {
            "probe_id": "two_visible_faces_cast_gate",
            "required": True,
            "expected": "exactly two people, one boy and one adult mother, both faces fully visible",
            "forbidden": [
                "the adult mother face is cropped outside the frame",
                "three people or an extra person",
                "only one visible face",
            ],
            "minimum_expected_score": 0.24,
            "minimum_contrast_margin": 0.03,
        },
        {
            "probe_id": "exactly_two_interaction_hands_gate",
            "required": True,
            "expected": "exactly two human hands near one paper boat",
            "forbidden": [
                "three or more hands around a paper boat",
                "many extra hands",
                "malformed overlapping hands",
            ],
            "crop_box_normalized": interaction_crop_normalized,
            "minimum_expected_score": 0.24,
            "minimum_contrast_margin": 0.03,
        },
    ]


def neutral_identity_portrait_gates() -> list[dict[str, Any]]:
    """Mandatory negative-regression gates for the Phase 4L-R9 neutral canary."""
    return [
        {
            "probe_id": "localized_face_neck_anatomy_gate",
            "required": True,
            "expected": "one complete natural human face connected to one normal neck and two shoulders",
            "forbidden": [
                "a fragmented duplicated face with repeated eyes mouths and broken neck",
                "a severed floating face with stacked facial parts",
                "horizontal slices of a fragmented face floating above a deformed neck",
            ],
            "crop_box_normalized": [0.24, 0.0, 0.76, 0.43],
            "minimum_expected_score": 0.24,
            "minimum_contrast_margin": 0.0,
        },
        {
            "probe_id": "single_subject_gate",
            "required": True,
            "expected": "exactly one person alone centered in the image",
            "forbidden": [
                "multiple people or duplicated human bodies",
                "one central person flanked by two partial duplicate bodies",
            ],
            "minimum_expected_score": 0.20,
            "minimum_contrast_margin": -0.005,
        },
        {
            "probe_id": "head_shoulders_portrait_framing_gate",
            "required": True,
            "expected": "a centered head-and-shoulders portrait cropped below the shoulders",
            "forbidden": [
                "a full body person visible from head to legs",
                "a malformed wide composition with partial bodies at both sides",
            ],
            "minimum_expected_score": 0.235,
            "minimum_contrast_margin": 0.0,
        },
    ]
