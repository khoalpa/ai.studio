from __future__ import annotations

import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, ImageStat

from .archive import PackageVerifier
from .errors import WorkflowError
from .hashing import canonical_json_bytes, sha256_bytes
from .operations import PackageRepairSession
from .stage1.png import png_dimensions
from .stage2.config import basenames
from .stage2.planning import digest_with_null
from .stage2.validation import validate_stage2_documents
from .workspace import RunWorkspace


class GPTImageWebAssist:
    assist_id = "gpt-image-web-assist/1.0"

    def export(self, package: Path, output: Path, selected: list[str] | None = None) -> dict[str, Any]:
        verified = PackageVerifier().verify(package)
        if verified.package_stage != "STAGE2":
            raise WorkflowError("GPT Image Web Assist export currently requires a Stage 2 package")
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise WorkflowError(f"Assist output directory is not empty: {output}")
        selected = selected or basenames()
        unknown = sorted(set(selected) - set(basenames()))
        if unknown:
            raise WorkflowError(f"Unknown assist basenames: {unknown}")
        output.mkdir(parents=True, exist_ok=True)
        (output / "prompts").mkdir()
        (output / "references").mkdir()
        (output / "sources").mkdir()
        (output / "results").mkdir()
        with zipfile.ZipFile(package) as archive:
            plan = json.loads(archive.read("visual_plan.json"))
            bible = json.loads(archive.read("visual_bible.json"))
            locks = {item["character_id"]: item for item in bible["character_identity_locks"]}
            reference_paths = sorted({
                locks[character_id]["reference_image"]
                for asset in plan["assets"] if asset["basename"] in selected
                for character_id in asset["focal_character_ids"] if character_id in locks
            })
            for path in reference_paths:
                target = output / "references" / Path(path).name
                target.write_bytes(archive.read(path))
            assets = []
            for asset in plan["assets"]:
                if asset["basename"] not in selected:
                    continue
                basename = asset["basename"]
                source = f"landscape/{basename}"
                (output / "sources" / basename).write_bytes(archive.read(source))
                prompt = self._prompt(asset, bible, locks)
                prompt_path = output / "prompts" / f"{Path(basename).stem}.txt"
                prompt_path.write_text(prompt + "\n", encoding="utf-8")
                assets.append({
                    "basename": basename,
                    "prompt_path": prompt_path.relative_to(output).as_posix(),
                    "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                    "source_path": f"sources/{basename}",
                    "reference_paths": [
                        f"references/{Path(locks[item]['reference_image']).name}"
                        for item in asset["focal_character_ids"] if item in locks
                    ],
                    "result_path": f"results/{basename}",
                    "required_dimensions": [3840, 2160],
                })
        manifest = {
            "schema_version": "1.0",
            "assist_id": self.assist_id,
            "source_package_digest_sha256": verified.package_digest_sha256,
            "workflow": "MANUAL_OPTIONAL_NO_API",
            "instructions": [
                "Open GPT Image Web manually; do not provide API keys or session cookies to this tool.",
                "Upload the listed source and character references, then paste the matching prompt.",
                "Download one final PNG per asset into its declared result_path.",
                "Human-review identity, wardrobe, props, composition, and unwanted text before import.",
            ],
            "assets": assets,
            "assist_manifest_digest_sha256": None,
        }
        manifest["assist_manifest_digest_sha256"] = self._manifest_digest(manifest)
        (output / "assist_manifest.json").write_bytes(canonical_json_bytes(manifest))
        return {"output": str(output.resolve()), "asset_count": len(assets), "manifest": manifest}

    def apply(
        self, package: Path, assist_bundle: Path, workspace: RunWorkspace,
        *, human_reviewed: bool,
    ) -> dict[str, Any]:
        if not human_reviewed:
            raise WorkflowError("GPT Image Web results require explicit human-review confirmation")
        verified = PackageVerifier().verify(package)
        manifest_path = assist_bundle / "assist_manifest.json"
        if not manifest_path.is_file():
            raise WorkflowError("Assist bundle has no assist_manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("assist_id") != self.assist_id:
            raise WorkflowError("Assist manifest version is unsupported")
        if manifest.get("assist_manifest_digest_sha256") != self._manifest_digest(manifest):
            raise WorkflowError("Assist manifest digest is invalid")
        if manifest.get("source_package_digest_sha256") != verified.package_digest_sha256:
            raise WorkflowError("Assist bundle is bound to a different source package")
        replacements = {}
        seen = set()
        for item in manifest.get("assets", []):
            basename = str(item.get("basename", ""))
            result_path = PurePosixPath(str(item.get("result_path", "")))
            if (
                basename not in basenames() or basename in seen
                or result_path.is_absolute() or ".." in result_path.parts
                or result_path.parts != ("results", basename)
            ):
                raise WorkflowError("Assist manifest contains an unsafe or duplicate result path")
            seen.add(basename)
            path = assist_bundle.joinpath(*result_path.parts)
            if path.is_file():
                data = path.read_bytes()
                replacements[basename] = (data, self._technical_assessment(data, item))
        if not replacements:
            raise WorkflowError("Assist bundle contains no result images")

        def mutate(root: Path) -> None:
            plan_path = root / "visual_plan.json"
            bible_path = root / "visual_bible.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            bible = json.loads(bible_path.read_text(encoding="utf-8"))
            assets = {item["basename"]: item for item in plan["assets"]}
            manifest_assets = {item["basename"]: item for item in manifest["assets"]}
            for basename, (data, assessment) in replacements.items():
                target = root / "landscape" / basename
                target.write_bytes(data)
                digest = sha256_bytes(data)
                binding = assets[basename]["landscape_image"]
                binding.update({
                    "file_sha256": digest,
                    "dimensions": list(png_dimensions(data)),
                    "transaction_id": f"stage2:gpt-image-web-assist:{Path(basename).stem}",
                    "provider_id": self.assist_id,
                    "quality_assessment": {
                        **assessment,
                        "assist_provenance": {
                            "workflow": "MANUAL_OPTIONAL_NO_API",
                            "source_package_digest_sha256": verified.package_digest_sha256,
                            "prompt_sha256": manifest_assets[basename]["prompt_sha256"],
                            "result_sha256": digest,
                            "human_review_confirmed": True,
                        },
                        "structured_visual_qa": {
                            "status": "NOT_ASSESSED",
                            "required_element_count": len(assets[basename]["shot_spec"]["required_elements"]),
                            "forbidden_element_count": len(assets[basename]["shot_spec"]["forbidden_elements"]),
                            "checks": [],
                        },
                        "upscale_postprocess": {
                            "schema_version": "1.0", "mode": "GPT_IMAGE_WEB_EXTERNAL",
                            "model_id": None, "source_size": [3840, 2160],
                            "learned_size": None, "output_size": [3840, 2160],
                            "residual_resize": False, "postprocess": None,
                        },
                        "repair_history": [],
                    },
                    "validation_status": "PASS",
                })
                for state in bible["wardrobe_state_map"].get(basename, []):
                    state["landscape_pixel_sha256"] = digest
            plan["visual_plan_digest_sha256"] = digest_with_null(plan, "visual_plan_digest_sha256")
            bible["dependency_digest"] = digest_with_null(bible, "dependency_digest")
            plan_path.write_bytes(canonical_json_bytes(plan))
            bible_path.write_bytes(canonical_json_bytes(bible))
            validate_stage2_documents(plan, bible, root)

        repaired = PackageRepairSession().run(
            input_package=package, workspace=workspace, mutate=mutate
        )
        return {
            "changed_paths": repaired.changed_paths,
            "replacement_count": len(replacements),
            "package": repaired.package.to_dict(),
        }

    @staticmethod
    def _technical_assessment(data: bytes, item: dict[str, Any]) -> dict[str, Any]:
        try:
            import io

            image = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as exc:
            raise WorkflowError(f"Assist result is not a decodable image: {exc}") from exc
        expected = tuple(item["required_dimensions"])
        if image.size != expected or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise WorkflowError(
                f"Assist result {item['basename']} must be a {expected[0]}x{expected[1]} PNG"
            )
        stat = ImageStat.Stat(image.resize((256, 144)))
        variance = sum(value * value for value in stat.stddev) / 3
        mean_luma = sum(stat.mean) / 3
        if variance < 18**2 or not 20 <= mean_luma <= 235:
            raise WorkflowError(f"Assist result failed technical image QA: {item['basename']}")
        return {
            "status": "PASS",
            "method": "GPT_IMAGE_WEB_HUMAN_ASSIST_TECHNICAL",
            "mean_luma": round(mean_luma, 3),
            "variance": round(variance, 3),
            "qa_layers": [{
                "layer": "TECHNICAL", "status": "PASS",
                "checks": {"dimensions": list(image.size), "variance": round(variance, 3), "mean_luma": round(mean_luma, 3)},
            }, {
                "layer": "HUMAN_WEB_REVIEW", "status": "CONFIRMED",
                "checks": {"scope": ["identity", "wardrobe", "props", "composition", "unwanted_text"]},
            }],
        }

    @staticmethod
    def _prompt(asset: dict[str, Any], bible: dict[str, Any], locks: dict[str, Any]) -> str:
        shot = asset["shot_spec"]
        identities = [locks[item] for item in asset["focal_character_ids"] if item in locks]
        identity_text = "; ".join(
            f"{item['character_id']} ({item['name']}): {item['hair']}; {item['wardrobe']}; palette {', '.join(item['palette'])}"
            for item in identities
        ) or "no recurring character"
        return (
            "Create one final 16:9 story illustration at 3840x2160. Use uploaded images as strict "
            "identity and wardrobe references, without mixing faces. "
            f"Art direction: {bible['art_direction_id']}. Action: {shot['action']}. "
            f"Emotion: {shot['emotion']}. Location: {shot['location']}. Characters: {identity_text}. "
            f"Required elements: {', '.join(shot['required_elements'])}. "
            f"Forbidden: {', '.join(shot['forbidden_elements'])}. "
            f"Composition: {json.dumps(shot['subjects'], ensure_ascii=False)}; "
            f"props: {json.dumps(shot['prop_layout'], ensure_ascii=False)}. "
            "Preserve clear faces, coherent anatomy, and story-consistent lighting. Do not add typography."
        )

    @staticmethod
    def _manifest_digest(manifest: dict[str, Any]) -> str:
        projected = dict(manifest)
        projected["assist_manifest_digest_sha256"] = None
        return sha256_bytes(canonical_json_bytes(projected))
