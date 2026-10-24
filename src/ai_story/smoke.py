from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from .archive import PackageVerifier
from .models import Profile
from .release import ReleaseBundleBuilder, ReleaseBundleVerifier, ReleaseEvaluator
from .stage1 import Stage1Pipeline, Stage1Request
from .stage1.config import confirm_duration
from .stage2 import Stage2Pipeline, Stage2Request
from .stage3 import Stage3Pipeline, Stage3Request
from .stage4 import Stage4Pipeline, Stage4Request
from .workspace import RunWorkspace


def run_deterministic_smoke(
    root: Path,
    profile: Profile = Profile.YOUTH_SAFE,
) -> dict[str, Any]:
    """Run the lightweight built-in provider through Stage 4 and release evaluation."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    scenarios = {
        Profile.YOUTH_SAFE: ("Hai người bạn tìm lại vật kỷ niệm sau cơn mưa", 15),
        Profile.ADULT_STANDARD: ("Một người trưởng thành trở về khu phố cũ và đối diện lời hứa chưa hoàn thành", 30),
        Profile.SERIAL_DETECTIVE: ("Một căn phòng khóa kín để lại manh mối dẫn đến bí mật của thị trấn", 42),
    }
    brief, minutes = scenarios[profile]

    stage1 = Stage1Pipeline(provider_mode="deterministic").run(
        Stage1Request(
            profile,
            brief,
            confirm_duration(profile, minutes, "START_SERIES" if profile is Profile.SERIAL_DETECTIVE else None),
            episode_mode="START_SERIES" if profile is Profile.SERIAL_DETECTIVE else None,
            series_title="Hồ Sơ Thị Trấn" if profile is Profile.SERIAL_DETECTIVE else None,
        ),
        RunWorkspace.create(root, profile),
    )
    stage2 = Stage2Pipeline(provider_mode="deterministic").run(
        Stage2Request(Path(stage1.package.archive_path)),
        RunWorkspace.create(root, profile),
    )
    stage3 = Stage3Pipeline(provider_mode="deterministic").run(
        Stage3Request(Path(stage2.package.archive_path)),
        RunWorkspace.create(root, profile),
    )
    stage4 = Stage4Pipeline().run(
        Stage4Request(
            Path(stage3.package.archive_path),
            confirm_large_plan=True,
        ),
        RunWorkspace.create(root, profile),
    )
    package_path = Path(stage4.package.archive_path)
    verified = PackageVerifier().verify(package_path)
    with zipfile.ZipFile(package_path) as archive:
        validation_ledger = json.loads(archive.read("validation_ledger.json"))
    release_report = ReleaseEvaluator().evaluate(package_path, channel="development")
    release_path = root / "release" / "ai-story-smoke-release.zip"
    release_bundle = ReleaseBundleBuilder().build(
        package_path, release_path, channel="development"
    )
    ReleaseBundleVerifier().verify(release_path)
    return {
        "status": "PASS",
        "provider_mode": "deterministic",
        "profile": profile.value,
        "completed_stages": ["STAGE1", "STAGE2", "STAGE3", "STAGE4"],
        "stage4_package": str(package_path.resolve()),
        "package_digest_sha256": verified.package_digest_sha256,
        "validation_ledger": {
            "current_stage": validation_ledger["current_stage"],
            "stage_history": validation_ledger["stage_history"],
            "summary": validation_ledger["summary"],
            "ledger_digest_sha256": validation_ledger["ledger_digest_sha256"],
        },
        "release_evaluation": {
            "readiness": release_report["readiness"],
            "blockers": release_report["blockers"],
            "report_digest_sha256": release_report["validation"]["report_digest_sha256"],
        },
        "release_bundle": release_bundle,
    }
