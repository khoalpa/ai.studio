from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

from .archive import PackageVerifier
from .config import project_root
from .errors import ConfigurationError

QUALITY_PRESETS = {
    "fast": {
        "label": "Nhanh", "parameters": {"temperature": 0.6},
        "retry_attempts": 1, "image_steps": 18,
        "image_candidates": {"character": 1, "cover": 1, "keyframe": 1, "scene": 1, "portrait": 1},
    },
    "balanced": {
        "label": "Cân bằng", "parameters": {"temperature": 0.7},
        "retry_attempts": 2, "image_steps": 28,
        "image_candidates": {"character": 2, "cover": 3, "keyframe": 3, "scene": 2, "portrait": 2},
    },
    "quality": {
        "label": "Chất lượng cao", "parameters": {"temperature": 0.65},
        "retry_attempts": 3, "image_steps": 40,
        "image_candidates": {"character": 3, "cover": 4, "keyframe": 4, "scene": 3, "portrait": 3},
    },
}


def apply_quality_preset(config: dict[str, Any], preset: str | None) -> dict[str, Any]:
    import copy
    selected = preset or "balanced"
    if selected not in QUALITY_PRESETS:
        raise ConfigurationError(f"Unsupported quality preset: {selected}")
    result = copy.deepcopy(config)
    values = QUALITY_PRESETS[selected]
    result["quality_preset"] = selected
    result["policy"]["retry_attempts"] = values["retry_attempts"]
    result["image_candidate_policy"] = dict(values["image_candidates"])
    for adapter in result["adapters"].values():
        if adapter.get("runtime") == "llama_cpp":
            adapter.setdefault("parameters", {}).update(values["parameters"])
        elif adapter.get("runtime") == "diffusers":
            adapter.setdefault("parameters", {})["steps"] = values["image_steps"]
    return result


def process_peak_memory_bytes() -> int | None:
    candidates: list[int] = []
    try:
        import resource
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        candidates.append(value if os.name == "nt" else value * 1024)
    except (ImportError, OSError, ValueError):
        pass
    try:
        import torch

        if torch.cuda.is_available():
            candidates.append(int(torch.cuda.max_memory_allocated()))
    except (ImportError, OSError, RuntimeError, ValueError):
        pass
    return max(candidates) if candidates else None


class BenchmarkEvaluator:
    @staticmethod
    def _outcome_is_compliant(expected: str, content_accepted: bool) -> bool:
        if expected == "PASS":
            return content_accepted
        if expected == "REJECT":
            return not content_accepted
        if expected == "REJECT_OR_REPAIR":
            return True
        raise ConfigurationError(f"Unsupported expected benchmark decision: {expected}")

    @staticmethod
    def _required_elements_are_compliant(
        required: list[str], matched: list[str], gates: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        if len(matched) == len(required):
            return True, "LITERAL_MATCH"
        adherence_gate = next(
            (gate for gate in gates if gate.get("gate_id") == "BRIEF_ADHERENCE_GATE"),
            None,
        )
        if adherence_gate and adherence_gate.get("status") == "PASS":
            return True, "BRIEF_ADHERENCE_GATE"
        return False, "INSUFFICIENT_EVIDENCE"

    def case(self, case_id: str) -> dict[str, Any]:
        match = next(
            (case for case in self.plan()["cases"] if str(case["id"]) == case_id),
            None,
        )
        if match is None:
            raise ConfigurationError(f"Unknown benchmark case: {case_id}")
        return match

    @staticmethod
    def load_records(path: Path) -> list[dict[str, Any]]:
        sources = sorted(path.glob("*.json")) if path.is_dir() else [path]
        if not sources:
            raise ConfigurationError(f"No benchmark record JSON files found: {path}")
        records: list[dict[str, Any]] = []
        for source in sources:
            document = json.loads(source.read_text(encoding="utf-8"))
            if isinstance(document, list):
                records.extend(document)
            elif isinstance(document, dict) and isinstance(document.get("records"), list):
                records.extend(document["records"])
            elif isinstance(document, dict) and document.get("case_id"):
                records.append(document)
            else:
                raise ConfigurationError(f"Invalid benchmark record document: {source}")
        return records

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        """Return a deterministic linearly interpolated percentile."""
        ordered = sorted(float(value) for value in values)
        if not ordered:
            raise ConfigurationError("Cannot calculate a percentile for an empty result set")
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * percentile
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction

    @staticmethod
    def _wilson_interval(successes: int, total: int) -> dict[str, float]:
        if total <= 0:
            return {"lower": 0.0, "upper": 1.0}
        z = 1.959963984540054
        proportion = successes / total
        denominator = 1 + (z * z / total)
        centre = (proportion + z * z / (2 * total)) / denominator
        margin = z * (
            (proportion * (1 - proportion) / total + z * z / (4 * total * total)) ** 0.5
        ) / denominator
        return {
            "lower": round(max(0.0, centre - margin), 4),
            "upper": round(min(1.0, centre + margin), 4),
        }

    def plan(self) -> dict[str, Any]:
        plan = json.loads((project_root() / "spec" / "benchmark.json").read_text(encoding="utf-8"))
        cases = plan.get("cases", [])
        required = {"id", "profile", "language", "minutes", "brief", "labels"}
        if len(cases) < 20 or len({case.get("id") for case in cases}) != len(cases):
            raise ConfigurationError("Benchmark corpus must contain at least 20 uniquely identified cases")
        if any(not required.issubset(case) for case in cases):
            raise ConfigurationError("Benchmark corpus case is missing required fields")
        golden_ids = [str(value) for value in plan.get("golden_case_ids", [])]
        case_ids = {str(case.get("id")) for case in cases}
        if (
            not 8 <= len(golden_ids) <= 10
            or len(golden_ids) != len(set(golden_ids))
            or not set(golden_ids).issubset(case_ids)
        ):
            raise ConfigurationError("Benchmark golden set must contain 8 to 10 unique canonical cases")
        golden_annotations = plan.get("golden_annotations", {})
        annotation_fields = {
            "severity", "expected_decision", "required_events", "forbidden_events",
            "roles", "relationships", "state_transitions",
        }
        if not isinstance(golden_annotations, dict) or set(golden_annotations) != set(golden_ids):
            raise ConfigurationError("Every golden case must have exactly one machine annotation")
        for case_id, annotation in golden_annotations.items():
            if not isinstance(annotation, dict) or not annotation_fields.issubset(annotation):
                raise ConfigurationError(f"Golden annotation is incomplete: {case_id}")
            if annotation["severity"] not in {"P0", "P1", "P2"}:
                raise ConfigurationError(f"Golden annotation severity is invalid: {case_id}")
            if annotation["expected_decision"] not in {"PASS", "REJECT", "REJECT_OR_REPAIR"}:
                raise ConfigurationError(f"Golden annotation decision is invalid: {case_id}")
            for field in ("required_events", "forbidden_events", "roles", "relationships", "state_transitions"):
                if not isinstance(annotation[field], list):
                    raise ConfigurationError(f"Golden annotation field must be a list: {case_id}.{field}")
            if not annotation["required_events"] or not annotation["roles"] or not annotation["state_transitions"]:
                raise ConfigurationError(f"Golden annotation lacks core machine labels: {case_id}")
        stage1 = json.loads((project_root() / "spec" / "stage1.json").read_text(encoding="utf-8"))
        for case in cases:
            case.setdefault(
                "seed",
                int.from_bytes(hashlib.sha256(str(case["id"]).encode("utf-8")).digest()[:4], "big"),
            )
            labels = case.get("labels", {})
            if not {"scenario", "expected_outcome", "required_elements", "forbidden_outcomes"}.issubset(labels):
                raise ConfigurationError("Benchmark case labels are incomplete")
            duration_key = str(case["profile"])
            if duration_key == "SERIAL_DETECTIVE":
                duration_key = f"SERIAL_DETECTIVE_{case.get('episode_mode', 'START_SERIES')}"
            bounds = stage1["duration_defaults"].get(duration_key)
            if not bounds or not bounds["length_min"] <= int(case["minutes"]) <= bounds["length_max"]:
                raise ConfigurationError(f"Benchmark case duration is invalid: {case['id']}")
        plan["corpus_digest_sha256"] = self._corpus_digest(plan)
        return plan

    @staticmethod
    def _corpus_digest(plan: dict[str, Any]) -> str:
        projected = {
            "schema_version": plan.get("schema_version"),
            "suite_id": plan.get("suite_id"),
            "golden_case_ids": plan.get("golden_case_ids", []),
            "golden_annotations": plan.get("golden_annotations", {}),
            "metrics": plan.get("metrics", []),
            "promotion_policy": plan.get("promotion_policy", {}),
            "case_schema": plan.get("case_schema", {}),
            "cases": plan.get("cases", []),
        }
        return hashlib.sha256(
            json.dumps(
                projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

    def canonical_corpus_digest(self) -> str:
        return str(self.plan()["corpus_digest_sha256"])

    def evaluate_human_reviews(
        self, review_a: dict[str, Any], review_b: dict[str, Any]
    ) -> dict[str, Any]:
        """Compare two independent blocker reviews over the canonical golden set."""
        golden_ids = [str(value) for value in self.plan().get("golden_case_ids", [])]
        if not 8 <= len(golden_ids) <= 10 or len(golden_ids) != len(set(golden_ids)):
            raise ConfigurationError("Golden set must contain 8 to 10 unique cases")

        def normalized(
            document: dict[str, Any], label: str
        ) -> tuple[str, dict[str, str], dict[str, str]]:
            if document.get("schema_version") != "1.0":
                raise ConfigurationError(f"{label} human review schema is invalid")
            reviewer_id = str(document.get("reviewer_id", "")).strip()
            if not reviewer_id:
                raise ConfigurationError(f"{label} reviewer id is missing")
            reviews = document.get("reviews")
            if not isinstance(reviews, list):
                raise ConfigurationError(f"{label} reviews must be a list")
            decisions: dict[str, str] = {}
            package_digests: dict[str, str] = {}
            for item in reviews:
                case_id = str(item.get("case_id", "")) if isinstance(item, dict) else ""
                decision = str(item.get("blocker_decision", "")) if isinstance(item, dict) else ""
                if case_id in decisions:
                    raise ConfigurationError(f"{label} contains duplicate case: {case_id}")
                if decision not in {"PASS", "BLOCK"}:
                    raise ConfigurationError(f"{label} has invalid blocker decision: {case_id}")
                package_digest = str(item.get("package_digest_sha256", ""))
                if not re.fullmatch(r"[0-9a-f]{64}", package_digest):
                    raise ConfigurationError(f"{label} has invalid package digest: {case_id}")
                decisions[case_id] = decision
                package_digests[case_id] = package_digest
            if set(decisions) != set(golden_ids):
                raise ConfigurationError(f"{label} must review the complete canonical golden set")
            return reviewer_id, decisions, package_digests

        reviewer_a, decisions_a, digests_a = normalized(review_a, "first")
        reviewer_b, decisions_b, digests_b = normalized(review_b, "second")
        if reviewer_a == reviewer_b:
            raise ConfigurationError("Human reviews must come from two different reviewers")
        mismatched_packages = sorted(
            case_id for case_id in golden_ids
            if digests_a[case_id] != digests_b[case_id]
        )
        if mismatched_packages:
            raise ConfigurationError(
                f"Human reviewers did not review the same packages: {mismatched_packages}"
            )
        agreements = sum(decisions_a[case_id] == decisions_b[case_id] for case_id in golden_ids)
        observed = agreements / len(golden_ids)
        pass_a = sum(decisions_a[case_id] == "PASS" for case_id in golden_ids) / len(golden_ids)
        pass_b = sum(decisions_b[case_id] == "PASS" for case_id in golden_ids) / len(golden_ids)
        expected = pass_a * pass_b + (1 - pass_a) * (1 - pass_b)
        kappa = 1.0 if expected == 1.0 and observed == 1.0 else (
            0.0 if expected == 1.0 else (observed - expected) / (1 - expected)
        )
        disagreements = [
            {
                "case_id": case_id,
                "reviewer_a": decisions_a[case_id],
                "reviewer_b": decisions_b[case_id],
            }
            for case_id in golden_ids
            if decisions_a[case_id] != decisions_b[case_id]
        ]
        report = {
            "schema_version": "1.0",
            "suite_id": self.plan()["suite_id"],
            "corpus_digest_sha256": self.canonical_corpus_digest(),
            "reviewer_ids": [reviewer_a, reviewer_b],
            "reviewed_package_digests": {
                case_id: digests_a[case_id] for case_id in golden_ids
            },
            "case_count": len(golden_ids),
            "agreement_rate": round(observed, 4),
            "cohen_kappa": round(kappa, 4),
            "minimum_kappa": 0.7,
            "agreement_status": "PASS" if kappa >= 0.7 else "FAIL",
            "disagreements": disagreements,
            "report_digest_sha256": None,
        }
        report["report_digest_sha256"] = hashlib.sha256(
            json.dumps(
                report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return report

    def human_review_template(
        self, records: list[dict[str, Any]], reviewer_id: str
    ) -> dict[str, Any]:
        reviewer_id = reviewer_id.strip()
        if not reviewer_id:
            raise ConfigurationError("Reviewer id is required")
        self._validate_canonical_records(records)
        by_case = {str(record["case_id"]): record for record in records}
        golden_ids = self.plan()["golden_case_ids"]
        reviews = []
        for case_id in golden_ids:
            record = by_case[case_id]
            package_digest = str(record.get("package_digest_sha256", ""))
            if not re.fullmatch(r"[0-9a-f]{64}", package_digest):
                raise ConfigurationError(
                    f"Benchmark record is missing package digest: {case_id}"
                )
            reviews.append({
                "case_id": case_id,
                "package_digest_sha256": package_digest,
                "blocker_decision": "UNREVIEWED",
                "notes": "",
            })
        return {
            "schema_version": "1.0",
            "reviewer_id": reviewer_id,
            "suite_id": self.plan()["suite_id"],
            "corpus_digest_sha256": self.canonical_corpus_digest(),
            "reviews": reviews,
        }

    def write_human_review_template(
        self,
        records: list[dict[str, Any]],
        reviewer_id: str,
        output_path: Path,
    ) -> dict[str, Any]:
        template = self.human_review_template(records, reviewer_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(template, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return template

    def write_human_review_report(
        self,
        review_a: dict[str, Any],
        review_b: dict[str, Any],
        output_path: Path,
    ) -> dict[str, Any]:
        report = self.evaluate_human_reviews(review_a, review_b)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return report

    def summarize(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate per-case evidence into stable, promotion-ready metrics."""
        if not records:
            raise ConfigurationError("Benchmark result set is empty")
        required = {
            "case_id", "seed", "evidence_digest", "editorial_basis", "outcome_compliant",
            "advancement_allowed", "forbidden_outcome_count",
            "completed", "blocker_count", "p0_defect_count", "editorial_score",
            "consistency_score", "required_elements", "matched_required_elements",
            "retry_count", "asset_count", "duration_seconds", "peak_memory_bytes",
        }
        if any(not required.issubset(record) for record in records):
            raise ConfigurationError("Benchmark record is missing required evidence")
        case_ids = [str(record["case_id"]) for record in records]
        if len(case_ids) != len(set(case_ids)):
            raise ConfigurationError("Benchmark result set contains duplicate case ids")
        if any(not re.fullmatch(r"[0-9a-f]{64}", str(record["evidence_digest"])) for record in records):
            raise ConfigurationError("Benchmark record evidence digest is invalid")
        total_required = sum(max(0, int(record["required_elements"])) for record in records)
        total_matched = sum(max(0, int(record["matched_required_elements"])) for record in records)
        total_contract_requirements = sum(
            max(0, int(record.get("contract_requirement_count", 0))) for record in records
        )
        total_matched_contract_requirements = sum(
            max(0, int(record.get("matched_contract_requirements", 0))) for record in records
        )
        total_assets = sum(max(0, int(record["asset_count"])) for record in records)
        editorial_scores = [
            float(record["editorial_score"])
            for record in records
            if record["editorial_score"] is not None
            and record["editorial_basis"] in {
                "MODEL_CRITIC_CORROBORATED", "MODEL_CRITIC_ASSESSED", "HUMAN_REVIEWED",
            }
        ]
        durations = [float(record["duration_seconds"]) for record in records]
        defect_taxonomy: dict[str, int] = {}
        for record in records:
            codes = record.get("defect_codes", record.get("failed_gate_ids", []))
            for code in codes if isinstance(codes, list) else []:
                key = str(code)
                defect_taxonomy[key] = defect_taxonomy.get(key, 0) + 1
        case_set_digest = hashlib.sha256(
            json.dumps(sorted((record["case_id"], record["seed"]) for record in records), separators=(",", ":")).encode()
        ).hexdigest()
        case_count = len(records)
        completion_successes = sum(bool(record["completed"]) for record in records)
        outcome_successes = sum(bool(record["outcome_compliant"]) for record in records)
        assessed_successes = sum(
            record["editorial_basis"] in {
                "MODEL_CRITIC_CORROBORATED", "MODEL_CRITIC_ASSESSED", "HUMAN_REVIEWED",
            }
            for record in records
        )
        advancement_successes = sum(bool(record["advancement_allowed"]) for record in records)
        blocker_successes = sum(int(record["blocker_count"]) > 0 for record in records)
        return {
            "case_count": case_count,
            "case_set_digest": case_set_digest,
            "corpus_digest_sha256": self.canonical_corpus_digest(),
            "completion_rate": completion_successes / case_count,
            "expected_outcome_accuracy": outcome_successes / case_count,
            "forbidden_outcome_rate": sum(int(record["forbidden_outcome_count"]) for record in records) / len(records),
            "assessed_editorial_rate": assessed_successes / case_count,
            "advancement_rate": advancement_successes / case_count,
            "blocker_rate": blocker_successes / case_count,
            "p0_defect_rate": sum(int(record["p0_defect_count"]) for record in records) / len(records),
            "editorial_score": round(statistics.mean(editorial_scores), 4) if editorial_scores else None,
            "editorial_score_median": round(statistics.median(editorial_scores), 4) if editorial_scores else None,
            "editorial_score_p10": round(self._percentile(editorial_scores, 0.1), 4) if editorial_scores else None,
            "editorial_score_p90": round(self._percentile(editorial_scores, 0.9), 4) if editorial_scores else None,
            "consistency_score": round(statistics.mean(float(record["consistency_score"]) for record in records), 4),
            "required_element_recall": round(total_matched / total_required, 4) if total_required else 1.0,
            "contract_requirement_recall": round(
                total_matched_contract_requirements / total_contract_requirements, 4
            ) if total_contract_requirements else 1.0,
            "retries_per_asset": round(sum(int(record["retry_count"]) for record in records) / total_assets, 4) if total_assets else 0.0,
            "duration_seconds": round(sum(float(record["duration_seconds"]) for record in records), 4),
            "duration_seconds_median": round(statistics.median(durations), 4),
            "duration_seconds_p10": round(self._percentile(durations, 0.1), 4),
            "duration_seconds_p90": round(self._percentile(durations, 0.9), 4),
            "peak_memory_bytes": max(int(record["peak_memory_bytes"] or 0) for record in records),
            "defect_taxonomy": dict(sorted(defect_taxonomy.items())),
            "confidence_intervals_95": {
                "completion_rate": self._wilson_interval(completion_successes, case_count),
                "expected_outcome_accuracy": self._wilson_interval(outcome_successes, case_count),
                "assessed_editorial_rate": self._wilson_interval(assessed_successes, case_count),
                "advancement_rate": self._wilson_interval(advancement_successes, case_count),
                "blocker_rate": self._wilson_interval(blocker_successes, case_count),
                "required_element_recall": self._wilson_interval(total_matched, total_required),
                "contract_requirement_recall": self._wilson_interval(
                    total_matched_contract_requirements, total_contract_requirements
                ),
            },
        }

    def _validate_canonical_records(self, records: list[dict[str, Any]]) -> None:
        plan = self.plan()
        expected = {str(case["id"]): int(case["seed"]) for case in plan["cases"]}
        actual = {str(record.get("case_id")): record for record in records}
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing or extra or len(actual) != len(records):
            raise ConfigurationError(
                f"Canonical benchmark records are incomplete: missing={missing}, extra={extra}"
            )
        wrong_seeds = sorted(
            case_id for case_id, seed in expected.items()
            if int(actual[case_id].get("seed", -1)) != seed
        )
        if wrong_seeds:
            raise ConfigurationError(
                f"Canonical benchmark record seeds do not match: {wrong_seeds}"
            )
        corpus_digest = self.canonical_corpus_digest()
        wrong_corpus = sorted(
            case_id for case_id, record in actual.items()
            if record.get("corpus_digest_sha256") != corpus_digest
        )
        if wrong_corpus:
            raise ConfigurationError(
                f"Canonical benchmark record corpus digest does not match: {wrong_corpus}"
            )

    def validate_canonical_record(self, record: dict[str, Any]) -> None:
        """Validate one record before an interrupted canonical run reuses it."""
        case_id = str(record.get("case_id", ""))
        case = self.case(case_id)
        if int(record.get("seed", -1)) != int(case["seed"]):
            raise ConfigurationError(
                f"Canonical benchmark record seed does not match for {case_id}"
            )
        if record.get("corpus_digest_sha256") != self.canonical_corpus_digest():
            raise ConfigurationError(
                f"Canonical benchmark record corpus digest does not match for {case_id}"
            )
        self.summarize([record])

    def baseline_report(
        self, records: list[dict[str, Any]], *, require_canonical: bool = True
    ) -> dict[str, Any]:
        """Build a byte-stable baseline report bound to its per-case evidence."""
        if require_canonical:
            self._validate_canonical_records(records)
        metrics = self.summarize(records)
        report = {
            "schema_version": "1.0",
            "report_kind": "BENCHMARK_BASELINE",
            "suite_id": self.plan()["suite_id"],
            "case_set_digest": metrics["case_set_digest"],
            "corpus_digest_sha256": metrics["corpus_digest_sha256"],
            "canonical_complete": require_canonical,
            "evidence_digests": [
                {
                    "case_id": str(record["case_id"]),
                    "seed": int(record["seed"]),
                    "evidence_digest": str(record["evidence_digest"]),
                    "package_digest_sha256": record.get("package_digest_sha256"),
                }
                for record in sorted(records, key=lambda item: str(item["case_id"]))
            ],
            "metrics": metrics,
            "report_digest_sha256": None,
        }
        report["report_digest_sha256"] = hashlib.sha256(
            json.dumps(
                report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return report

    def write_baseline_report(
        self,
        records: list[dict[str, Any]],
        output_path: Path,
        *,
        require_canonical: bool = True,
    ) -> dict[str, Any]:
        """Persist a baseline exactly once so previous measurements stay immutable."""
        report = self.baseline_report(records, require_canonical=require_canonical)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return report

    def canonical_case_set_digest(self) -> str:
        plan = self.plan()
        return hashlib.sha256(
            json.dumps(
                sorted((case["id"], case["seed"]) for case in plan["cases"]),
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def evaluate(self, candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
        candidate = self._benchmark_metrics("candidate", candidate)
        baseline = self._benchmark_metrics("baseline", baseline)
        policy = self.plan().get("promotion_policy", {})
        editorial_policy = policy.get("editorial_score", {})
        duration_policy = policy.get("duration_seconds", {})
        memory_policy = policy.get("peak_memory_bytes", {})
        minimum_editorial_delta = float(
            editorial_policy.get("minimum_delta", 0.0)
            if isinstance(editorial_policy, dict) else 0.0
        )
        maximum_duration_ratio = float(
            duration_policy.get("maximum_ratio", 1.0)
            if isinstance(duration_policy, dict) else 1.0
        )
        maximum_memory_ratio = float(
            memory_policy.get("maximum_ratio", 1.0)
            if isinstance(memory_policy, dict) else 1.0
        )
        required = (
            "case_count", "case_set_digest", "expected_outcome_accuracy", "forbidden_outcome_rate", "assessed_editorial_rate",
            "completion_rate", "blocker_rate", "p0_defect_rate", "editorial_score",
            "consistency_score", "required_element_recall", "retries_per_asset",
            "duration_seconds", "peak_memory_bytes",
        )
        for name, value in (("candidate", candidate), ("baseline", baseline)):
            if not all(key in value for key in required):
                raise ConfigurationError(f"{name} benchmark metrics are incomplete")
        candidate_editorial = candidate.get("editorial_score")
        baseline_editorial = baseline.get("editorial_score")
        editorial_scores_comparable = (
            isinstance(candidate_editorial, (int, float))
            and not isinstance(candidate_editorial, bool)
            and isinstance(baseline_editorial, (int, float))
            and not isinstance(baseline_editorial, bool)
        )
        checks = {
            "same_case_set": candidate["case_set_digest"] == baseline["case_set_digest"] and candidate["case_count"] == baseline["case_count"],
            "same_corpus": (
                candidate.get("corpus_digest_sha256")
                == baseline.get("corpus_digest_sha256")
                == self.canonical_corpus_digest()
            ),
            "completion_is_total": candidate["completion_rate"] == 1.0,
            "expected_outcomes_are_all_correct": candidate["expected_outcome_accuracy"] == 1.0,
            "forbidden_outcomes_are_zero": candidate["forbidden_outcome_rate"] == 0,
            "editorial_assessment_is_independent": candidate["assessed_editorial_rate"] == 1.0,
            "blocker_rate_not_worse": candidate["blocker_rate"] <= baseline["blocker_rate"],
            "p0_defects_are_zero": candidate["p0_defect_rate"] == 0,
            "editorial_score_improved": (
                editorial_scores_comparable
                and (candidate_editorial - baseline_editorial) >= minimum_editorial_delta
            ),
            "consistency_score_not_worse": candidate["consistency_score"] >= baseline["consistency_score"],
            "required_element_recall_not_worse": candidate["required_element_recall"] >= baseline["required_element_recall"],
            "contract_requirements_are_complete": candidate.get(
                "contract_requirement_recall", 1.0
            ) == 1.0,
            "retry_rate_not_worse": candidate["retries_per_asset"] <= baseline["retries_per_asset"],
            "latency_within_budget": self._within_ratio_budget(
                candidate["duration_seconds"], baseline["duration_seconds"], maximum_duration_ratio
            ),
            "peak_memory_within_budget": self._within_ratio_budget(
                candidate["peak_memory_bytes"], baseline["peak_memory_bytes"], maximum_memory_ratio
            ),
        }
        result = {
            "schema_version": "1.0",
            "suite_id": self.plan()["suite_id"],
            "promotion_verdict": "PROMOTE" if all(checks.values()) else "HOLD",
            "checks": checks,
            "candidate": candidate,
            "baseline": baseline,
            "applied_policy": {
                "minimum_editorial_delta": minimum_editorial_delta,
                "maximum_duration_ratio": maximum_duration_ratio,
                "maximum_peak_memory_ratio": maximum_memory_ratio,
            },
            "evaluation_digest_sha256": None,
        }
        result["evaluation_digest_sha256"] = self.evaluation_digest(result)
        return result

    @staticmethod
    def _within_ratio_budget(candidate: float, baseline: float, maximum_ratio: float) -> bool:
        candidate_value = float(candidate)
        baseline_value = float(baseline)
        if baseline_value <= 0:
            return candidate_value <= baseline_value
        return candidate_value <= baseline_value * maximum_ratio

    def _benchmark_metrics(self, name: str, document: dict[str, Any]) -> dict[str, Any]:
        if document.get("report_kind") != "BENCHMARK_BASELINE":
            return document
        projected = dict(document)
        digest = projected.get("report_digest_sha256")
        projected["report_digest_sha256"] = None
        expected = hashlib.sha256(
            json.dumps(
                projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if digest != expected:
            raise ConfigurationError(f"{name} benchmark report digest is invalid")
        if document.get("suite_id") != self.plan()["suite_id"]:
            raise ConfigurationError(f"{name} benchmark report suite is invalid")
        metrics = document.get("metrics")
        if not isinstance(metrics, dict):
            raise ConfigurationError(f"{name} benchmark report metrics are missing")
        return metrics

    @staticmethod
    def evaluation_digest(evidence: dict[str, Any]) -> str:
        projected = dict(evidence)
        projected["evaluation_digest_sha256"] = None
        return hashlib.sha256(
            json.dumps(
                projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

    def validate_promotion_evidence(self, evidence: dict[str, Any]) -> list[str]:
        """Return fail-closed reasons for benchmark evidence used by release."""
        failures: list[str] = []
        plan = self.plan()
        candidate = evidence.get("candidate", {})
        checks = evidence.get("checks", {})
        if evidence.get("schema_version") != "1.0":
            failures.append("schema_version")
        if evidence.get("suite_id") != plan["suite_id"]:
            failures.append("suite_id")
        if evidence.get("evaluation_digest_sha256") != self.evaluation_digest(evidence):
            failures.append("evaluation_digest_sha256")
        if evidence.get("promotion_verdict") != "PROMOTE":
            failures.append("promotion_verdict")
        if not checks or not all(value is True for value in checks.values()):
            failures.append("promotion_checks")
        if candidate.get("case_count") != len(plan["cases"]):
            failures.append("case_count")
        if candidate.get("case_set_digest") != self.canonical_case_set_digest():
            failures.append("case_set_digest")
        if candidate.get("corpus_digest_sha256") != self.canonical_corpus_digest():
            failures.append("corpus_digest_sha256")
        hard_requirements = {
            "completion_rate": 1.0,
            "expected_outcome_accuracy": 1.0,
            "forbidden_outcome_rate": 0,
            "assessed_editorial_rate": 1.0,
            "p0_defect_rate": 0,
        }
        for key, expected in hard_requirements.items():
            if candidate.get(key) != expected:
                failures.append(key)
        if float(candidate.get("required_element_recall", 0)) < 1.0:
            failures.append("required_element_recall")
        if float(candidate.get("contract_requirement_recall", 0)) < 1.0:
            failures.append("contract_requirement_recall")
        return failures

    def record_from_package(
        self,
        case: dict[str, Any],
        package_path: Path,
        *,
        seed: int,
        duration_seconds: float | None = None,
        peak_memory_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Build auditable benchmark evidence from a reopened Stage 1 package."""
        verified = PackageVerifier().verify(package_path)
        if verified.package_stage != "STAGE1":
            raise ConfigurationError("Benchmark evidence requires a Stage 1 package")
        expected_seed = int(case.get("seed", -1))
        if seed != expected_seed:
            raise ConfigurationError(
                f"Benchmark seed does not match case {case.get('id')}: {seed} != {expected_seed}"
            )
        with zipfile.ZipFile(package_path) as archive:
            story = json.loads(archive.read("story.json"))
            report = json.loads(archive.read("story_validation.json"))
            manifest = json.loads(archive.read("workflow_manifest.json"))
            story_contract = json.loads(archive.read("story_contract.json"))
            outline_evidence = json.loads(archive.read("outline_evidence.json"))
            quality_decision = json.loads(archive.read("quality_decision.json"))
        if manifest.get("active_profile") != case.get("profile"):
            raise ConfigurationError(
                f"Benchmark package profile does not match case {case.get('id')}"
            )
        if str(story.get("meta", {}).get("language", "")).casefold() != str(
            case.get("language", "")
        ).casefold():
            raise ConfigurationError(
                f"Benchmark package language does not match case {case.get('id')}"
            )
        labels = case.get("labels", {})
        normalized_content = unicodedata.normalize(
            "NFC",
            " ".join(
                [str(story.get("meta", {}).get("title", ""))]
                + [str(item.get("name", "")) for item in story.get("characters", [])]
                + [str(item.get("text", "")) for item in story.get("script", [])]
            ),
        ).casefold()
        required_elements = [str(value) for value in labels.get("required_elements", [])]
        forbidden_outcomes = [str(value) for value in labels.get("forbidden_outcomes", [])]
        matched = [value for value in required_elements if unicodedata.normalize("NFC", value).casefold() in normalized_content]
        forbidden_hits = [value for value in forbidden_outcomes if unicodedata.normalize("NFC", value).casefold() in normalized_content]
        report_gates = report.get("gates", [])
        failed_gates = [gate for gate in report_gates if gate.get("status") != "PASS"]
        failed_ids = {str(gate.get("gate_id")) for gate in failed_gates}
        contract_gate = next(
            (gate for gate in report.get("gates", []) if gate.get("gate_id") == "STORY_CONTRACT_GATE"),
            {},
        )
        contract_metrics = contract_gate.get("metrics", {})
        requirement_evidence = contract_metrics.get("requirement_evidence", {})
        requirements = story_contract.get("requirements", [])
        matched_contract_requirements = sum(
            bool(requirement_evidence.get(str(item.get("requirement_id")), []))
            for item in requirements
        )
        bound_contract_requirements = sum(
            item.get("status") == "BOUND"
            for item in outline_evidence.get("requirement_bindings", [])
        )
        contract_forbidden_findings = [
            finding
            for finding in contract_gate.get("findings", [])
            if finding.get("error") == "FORBIDDEN_OUTCOME_PRESENT"
        ]
        contract_compliant = (
            contract_gate.get("status") == "PASS"
            and matched_contract_requirements == len(requirements)
            and bound_contract_requirements == len(requirements)
        )
        p0_gate_ids = {
            "BRIEF_POLICY_GATE",
            "SENTENCE_COMPLETENESS_GATE", "NARRATIVE_INVARIANT_GATE", "BRIEF_ADHERENCE_GATE",
            "STORY_CONTRACT_GATE", "INTRA_ZONE_REPETITION_GATE", "CHARACTER_REFERENCE_SET_GATE", "ZONE_BUDGET_GATE",
        }
        advancement_allowed = (
            manifest.get("allowed_next_stage") is not None
            and quality_decision.get("advancement_status") == "ALLOWED"
        )
        forbidden_evidence_count = len(forbidden_hits) + len(contract_forbidden_findings)
        escaped_p0 = len(failed_ids & p0_gate_ids) + forbidden_evidence_count if advancement_allowed else 0
        annotation = self.plan().get("golden_annotations", {}).get(str(case.get("id")), {})
        expected = str(annotation.get("expected_decision", labels.get("expected_outcome", "PASS")))
        required_elements_compliant, required_element_evidence_basis = (
            self._required_elements_are_compliant(
                required_elements, matched, report_gates,
            )
        )
        content_accepted = (
            not failed_gates
            and contract_compliant
            and required_elements_compliant
            and forbidden_evidence_count == 0
        )
        outcome_compliant = self._outcome_is_compliant(expected, content_accepted)
        quality = report.get("quality", {})
        quality_gate = next(
            (gate for gate in report.get("gates", []) if gate.get("gate_id") == "STORY_QUALITY_GATE"),
            {},
        )
        assessment_basis = quality_gate.get("metrics", {}).get("assessment_basis", "MISSING")
        evidence = {
            "case_id": case.get("id"), "seed": seed,
            "story_sha256": report.get("story_sha256"),
            "package_digest_sha256": manifest.get("package_digest_sha256"),
            "failed_gate_ids": sorted(failed_ids), "matched_required_elements": matched,
            "required_element_evidence_basis": required_element_evidence_basis,
            "forbidden_hits": forbidden_hits, "editorial_basis": assessment_basis,
            "advancement_allowed": advancement_allowed,
            "content_accepted": content_accepted,
            "expected_decision": expected,
            "story_contract_digest_sha256": outline_evidence.get("story_contract_digest_sha256"),
            "quality_decision_digest_sha256": quality_decision.get("decision_digest_sha256"),
            "contract_compliant": contract_compliant,
            "matched_contract_requirements": matched_contract_requirements,
            "bound_contract_requirements": bound_contract_requirements,
            "golden_annotation": annotation or None,
        }
        evidence_digest = hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        generation = manifest.get("generation", {})
        benchmark_context = generation.get("benchmark_context", {})
        expected_context = {
            "case_id": str(case.get("id")),
            "seed": expected_seed,
            "corpus_digest_sha256": self.canonical_corpus_digest(),
        }
        for key, expected_value in expected_context.items():
            if benchmark_context.get(key) != expected_value:
                raise ConfigurationError(
                    f"Benchmark package context does not match case {case.get('id')}: {key}"
                )
        runtime = generation.get("runtime_metrics", {})
        operational = generation.get("operational_metrics", {})
        defect_codes = sorted({
            str(finding.get("code", finding.get("error", gate.get("gate_id", "UNKNOWN"))))
            for gate in failed_gates
            for finding in gate.get("findings", []) or [{}]
        })
        return {
            "case_id": str(case.get("id")), "seed": seed, "evidence_digest": evidence_digest,
            "editorial_basis": assessment_basis, "outcome_compliant": outcome_compliant,
            "advancement_allowed": advancement_allowed, "forbidden_outcome_count": forbidden_evidence_count,
            "content_accepted": content_accepted, "expected_decision": expected,
            "completed": True,
            "blocker_count": len(failed_gates), "p0_defect_count": escaped_p0,
            "failed_gate_ids": sorted(failed_ids), "defect_codes": defect_codes,
            "editorial_score": (
                float(quality["final_story_quality_score"])
                if quality.get("final_story_quality_score") is not None else None
            ),
            "preflight_story_quality_score": float(
                quality.get("preflight_story_quality_score", 0)
            ),
            "consistency_score": 0.0 if "NARRATIVE_INVARIANT_GATE" in failed_ids else 1.0,
            "required_elements": len(required_elements), "matched_required_elements": len(matched),
            "required_element_evidence_basis": required_element_evidence_basis,
            "contract_requirement_count": len(requirements),
            "matched_contract_requirements": matched_contract_requirements,
            "outline_bound_requirements": bound_contract_requirements,
            "contract_compliant": contract_compliant,
            "story_contract_digest_sha256": outline_evidence.get(
                "story_contract_digest_sha256"
            ),
            "quality_decision_digest_sha256": quality_decision.get(
                "decision_digest_sha256"
            ),
            "corpus_digest_sha256": self.canonical_corpus_digest(),
            "story_sha256": report.get("story_sha256"),
            "package_digest_sha256": manifest.get("package_digest_sha256"),
            "retry_count": int(runtime.get("retry_count", 0)),
            "asset_count": len(story.get("characters", [])),
            "duration_seconds": float(
                operational.get("duration_seconds", 0.0)
                if duration_seconds is None else duration_seconds
            ),
            "peak_memory_bytes": (
                generation.get("peak_memory_bytes")
                if peak_memory_bytes is None else peak_memory_bytes
            ),
        }

    def write_case_record(
        self, case_id: str, package_path: Path, output_path: Path
    ) -> dict[str, Any]:
        """Create one immutable, case-bound benchmark evidence record."""
        case = self.case(case_id)
        record = self.record_from_package(
            case, package_path, seed=int(case["seed"])
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return record
