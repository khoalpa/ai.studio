from __future__ import annotations

from typing import Any


def candidate_score(assessment: dict[str, Any]) -> float:
    """Return a stable 0..1 score using only signals actually measured."""
    weighted: list[tuple[float, float]] = []
    status = str(assessment.get("status", ""))
    weighted.append((1.0 if status in {"PASS", "ASSESSED_PASS"} else 0.0, 3.0))
    semantic = assessment.get("semantic_score")
    if isinstance(semantic, (int, float)):
        weighted.append((max(0.0, min(1.0, float(semantic))), 3.0))
    parity = assessment.get("parity_score")
    if isinstance(parity, (int, float)):
        weighted.append((max(0.0, min(1.0, float(parity))), 2.0))
    identities = [
        float(value) for value in assessment.get("identity_similarity_scores", [])
        if isinstance(value, (int, float))
    ]
    if identities:
        weighted.append((max(0.0, min(1.0, min(identities))), 3.0))
    # Reward clearance above hard gates so a barely passing candidate does not
    # outrank a more robust one merely because it was generated later.
    thresholds = assessment.get("applied_thresholds", {})
    semantic_threshold = thresholds.get("semantic_threshold")
    if isinstance(semantic, (int, float)) and isinstance(semantic_threshold, (int, float)):
        margin = max(-0.1, min(0.1, float(semantic) - float(semantic_threshold)))
        weighted.append(((margin + 0.1) / 0.2, 1.0))
    identity_threshold = None
    for layer in assessment.get("qa_layers", []):
        if layer.get("layer") == "IDENTITY":
            identity_threshold = layer.get("checks", {}).get("threshold")
            break
    if identities and isinstance(identity_threshold, (int, float)):
        margin = max(-0.1, min(0.1, min(identities) - float(identity_threshold)))
        weighted.append(((margin + 0.1) / 0.2, 1.0))
    fidelity = assessment.get("visual_fidelity", {})
    fidelity_checks = fidelity.get("checks", []) if isinstance(fidelity, dict) else []
    margins = []
    for check in fidelity_checks:
        expected = check.get("expected_score")
        forbidden = check.get("best_forbidden_score")
        tolerance = check.get("ambiguity_tolerance", 0.0)
        if isinstance(expected, (int, float)) and isinstance(forbidden, (int, float)):
            margins.append(float(expected) + float(tolerance) - float(forbidden))
    if margins:
        margin = max(-0.1, min(0.1, min(margins)))
        weighted.append(((margin + 0.1) / 0.2, 1.0))
    structured = assessment.get("structured_visual_qa", {})
    checks = structured.get("checks", []) if isinstance(structured, dict) else []
    measured = [item for item in checks if item.get("status") in {"PASS", "FAIL"}]
    if measured:
        weighted.append((sum(item["status"] == "PASS" for item in measured) / len(measured), 3.0))
    total_weight = sum(weight for _, weight in weighted)
    return round(sum(value * weight for value, weight in weighted) / total_weight, 6)


def select_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        raise ValueError("At least one successful image candidate is required")
    for candidate in candidates:
        candidate["rank_score"] = candidate_score(candidate["assessment"])
    selected = max(
        candidates,
        key=lambda item: (item["rank_score"], -int(item["attempt"])),
    )
    for candidate in candidates:
        candidate["selected"] = candidate is selected
    return selected


def candidate_count(config: dict[str, Any], asset_class: str) -> int:
    policy = config.get("image_candidate_policy", {})
    return max(1, int(policy.get(asset_class, 1)))
