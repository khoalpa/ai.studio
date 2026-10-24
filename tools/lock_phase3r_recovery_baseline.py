from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from ai_story.model_operations import BenchmarkEvaluator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE3_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story/phase3"
LOCK_ROOT = PHASE3_ROOT / "phase3r-locked-recovery-baseline"
SOURCE_LOCKS = (
    "phase3f-locked-pilot",
    "phase3g-locked-batch1",
    "phase3i-locked-batch2",
    "phase3n-locked-batch3",
    "phase3q-locked-batch4",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify(record: dict[str, object]) -> str:
    expected = str(record["expected_decision"])
    accepted = bool(record["content_accepted"])
    advanced = bool(record["advancement_allowed"])
    blockers = int(record["blocker_count"])
    if accepted and advanced and blockers == 0:
        if expected not in {"PASS", "REJECT_OR_REPAIR"}:
            raise RuntimeError("A strict REJECT case cannot be production-ready")
        return "PRODUCTION_READY"
    if not accepted and not advanced and expected in {"REJECT", "REJECT_OR_REPAIR"}:
        return "EXPECTED_NEGATIVE_FIXTURE"
    raise RuntimeError(
        f"Invalid result for expected={expected}: accepted={accepted}, "
        f"advanced={advanced}, blockers={blockers}"
    )


def main() -> None:
    evaluator = BenchmarkEvaluator()
    cases = {str(case["id"]): case for case in evaluator.plan()["cases"]}
    sources: dict[str, tuple[str, Path, str]] = {}
    source_lock_evidence = []
    for lock_name in SOURCE_LOCKS:
        manifest_path = PHASE3_ROOT / lock_name / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("packages", [])
        if len(entries) != int(manifest.get("case_count", -1)):
            raise RuntimeError(f"Lock manifest count mismatch: {lock_name}")
        for entry in entries:
            case_id = str(entry["case_id"])
            if case_id in sources:
                raise RuntimeError(f"Duplicate locked case: {case_id}")
            package = Path(entry["locked_package"])
            actual_sha = sha256(package) if package.is_file() else ""
            if actual_sha != entry["file_sha256"]:
                raise RuntimeError(f"Locked package SHA mismatch: {lock_name}:{case_id}")
            sources[case_id] = (lock_name, package, actual_sha)
        source_lock_evidence.append({
            "lock_name": lock_name,
            "manifest": str(manifest_path.resolve()),
            "manifest_sha256": sha256(manifest_path),
            "case_count": len(entries),
        })

    missing = sorted(set(cases) - set(sources))
    extra = sorted(set(sources) - set(cases))
    if missing or extra:
        raise RuntimeError(f"Corpus coverage mismatch: missing={missing}, extra={extra}")

    validated = []
    records = []
    for case_id in sorted(cases):
        lock_name, package, source_sha = sources[case_id]
        record = evaluator.record_from_package(
            cases[case_id], package, seed=int(cases[case_id]["seed"])
        )
        if int(record["p0_defect_count"]):
            raise RuntimeError(f"Escaped P0 defect in locked package: {case_id}")
        if not bool(record["outcome_compliant"]):
            raise RuntimeError(f"Unexpected benchmark outcome: {case_id}")
        classification = classify(record)
        validated.append((case_id, lock_name, package, source_sha, record, classification))
        records.append(record)

    packages_dir = LOCK_ROOT / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    classes: Counter[str] = Counter()
    expected: Counter[str] = Counter()
    blocker_taxonomy: Counter[str] = Counter()
    for case_id, lock_name, source, source_sha, record, classification in validated:
        target = packages_dir / f"{case_id}.zip"
        shutil.copy2(source, target)
        target_sha = sha256(target)
        if target_sha != source_sha:
            raise RuntimeError(f"Copied package SHA mismatch: {case_id}")
        classes[classification] += 1
        expected[str(record["expected_decision"])] += 1
        blocker_taxonomy.update(str(item) for item in record["failed_gate_ids"])
        entries.append({
            "case_id": case_id,
            "profile": str(cases[case_id]["profile"]),
            "source_lock": lock_name,
            "source_package": str(source.resolve()),
            "locked_package": str(target.resolve()),
            "file_sha256": target_sha,
            "story_sha256": record["story_sha256"],
            "expected_decision": record["expected_decision"],
            "outcome_compliant": record["outcome_compliant"],
            "classification": classification,
            "advancement_allowed": record["advancement_allowed"],
            "blocker_count": record["blocker_count"],
            "failed_gate_ids": record["failed_gate_ids"],
            "p0_defect_count": record["p0_defect_count"],
        })

    metrics = evaluator.summarize(records)
    manifest = {
        "schema_version": "1.0",
        "report_kind": "PHASE3R_LOCKED_RECOVERY_BASELINE",
        "suite_id": evaluator.plan()["suite_id"],
        "corpus_digest_sha256": evaluator.canonical_corpus_digest(),
        "policy": {
            "immutable": True,
            "image_regeneration_allowed": False,
            "model_execution_used": False,
            "expected_rejection_is_success": True,
        },
        "case_count": len(entries),
        "coverage": {
            "expected_case_count": len(cases),
            "missing_case_ids": [],
            "extra_case_ids": [],
            "duplicate_case_ids": [],
        },
        "classification_counts": dict(sorted(classes.items())),
        "expected_decision_counts": dict(sorted(expected.items())),
        "blocker_taxonomy": dict(sorted(blocker_taxonomy.items())),
        "metrics": metrics,
        "source_locks": source_lock_evidence,
        "packages": entries,
    }
    LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = LOCK_ROOT / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({
        "status": "LOCKED",
        "case_count": len(entries),
        "classification_counts": manifest["classification_counts"],
        "expected_outcome_accuracy": metrics["expected_outcome_accuracy"],
        "p0_defect_rate": metrics["p0_defect_rate"],
        "manifest": str(manifest_path.resolve()),
    }))


if __name__ == "__main__":
    main()
