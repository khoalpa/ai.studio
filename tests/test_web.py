from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_story.errors import WorkflowError
from ai_story.web import AIStoryHTTPServer, JobRegistry, WebService


def wait_for_terminal(registry: JobRegistry, job_id: str, timeout: float = 5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = registry.get(job_id)
        if job and job.state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return job
        time.sleep(0.01)
    raise AssertionError("Job did not reach a terminal state")


class WebServiceTests(unittest.TestCase):
    def test_anonymous_ux_events_are_schema_limited_and_summarized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = WebService(Path(temporary), jobs=JobRegistry(max_workers=1))
            try:
                accepted = service.record_ux_event({
                    "event": "BLOCKER_OPENED", "stage": "STAGE1",
                    "severity": "PUBLISH_BLOCKER", "viewport": "wide", "elapsed_ms": 1200,
                })
                self.assertTrue(accepted["accepted"])
                service.record_ux_event({
                    "event": "BLOCKER_OPENED", "stage": "STAGE1",
                    "severity": "QUALITY_BLOCKER", "viewport": "compact", "elapsed_ms": 800,
                })
                summary = service.ux_event_summary()
                self.assertEqual(summary["event_count"], 2)
                self.assertEqual(summary["counts_by_event"]["BLOCKER_OPENED"], 2)
                self.assertEqual(summary["median_blocker_open_ms"], 1000)
                with self.assertRaises(WorkflowError):
                    service.record_ux_event({"event": "BLOCKER_OPENED", "run_id": "sensitive"})
                with self.assertRaises(WorkflowError):
                    service.record_ux_event({"event": "UNKNOWN"})
            finally:
                service.jobs.close()

    def test_project_settings_are_validated_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = WebService(root, jobs=JobRegistry(max_workers=1))
            try:
                self.assertEqual(service.project_settings()["language"], "vi")
                saved = service.update_project_settings({"language": "en", "profile": "ADULT_STANDARD"})
                self.assertEqual(saved["language"], "en")
                self.assertEqual(saved["provider_mode"], "deterministic")
                self.assertEqual(saved["duration_youth"], 10)
                self.assertEqual(saved["ui_font"], "system")
                self.assertEqual(WebService(root, jobs=service.jobs).project_settings()["profile"], "ADULT_STANDARD")
                self.assertEqual(len(service.settings_history()), 1)
                self.assertTrue(service.settings_health()["ready"])
                with self.assertRaises(WorkflowError):
                    service.update_project_settings({"language": "fr"})
                with self.assertRaises(WorkflowError):
                    service.update_project_settings({"duration_youth": 99})
                with self.assertRaises(WorkflowError):
                    service.update_project_settings({"ui_font": "comic-sans"})
            finally:
                service.jobs.close()

    @staticmethod
    def _brief_generator(
        profile: str, language: str, count: int, seed: int, excluded: list[str]
    ) -> list[str]:
        del excluded
        return [
            f"{profile} {language} nhân vật {index} theo seed {seed} tìm một vật bị mất "
            "trong thành phố ven biển, nhưng thời gian và một lời hứa cũ buộc họ lựa chọn."
            for index in range(count)
        ]

    def test_random_brief_matches_profile_and_language(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = WebService(
                Path(temporary),
                jobs=JobRegistry(max_workers=1),
                brief_generator=self._brief_generator,
            )
            try:
                result = service.random_brief("SERIAL_DETECTIVE", "en")
                self.assertEqual(result["profile"], "SERIAL_DETECTIVE")
                self.assertEqual(result["language"], "en")
                self.assertGreater(len(result["brief"].split()), 15)
                choices = service.random_brief("YOUTH_SAFE", "vi", 3)
                self.assertEqual(len(choices["suggestions"]), 3)
                self.assertEqual(len(set(choices["suggestions"])), 3)
                self.assertEqual(choices["brief"], choices["suggestions"][0])
                first_ids = {item["id"] for item in choices["suggestion_items"]}
                next_choices = service.random_brief("YOUTH_SAFE", "vi", 3, first_ids)
                next_ids = {item["id"] for item in next_choices["suggestion_items"]}
                self.assertTrue(first_ids.isdisjoint(next_ids))
                self.assertEqual(choices["generator"], "story_model")
                self.assertIsInstance(choices["seed"], int)
                self.assertEqual(choices["seed"], choices["seeds"][0])
                with self.assertRaises(WorkflowError):
                    service.random_brief("UNKNOWN", "vi")
                with self.assertRaises(WorkflowError):
                    service.random_brief("YOUTH_SAFE", "fr")
                with self.assertRaises(WorkflowError):
                    service.random_brief("YOUTH_SAFE", "vi", 6)
            finally:
                service.jobs.close()

    def test_duration_options_cover_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = WebService(Path(temporary), jobs=JobRegistry(max_workers=1))
            try:
                values = service.duration_options()
                profiles = {item["profile"] for item in values}
                self.assertEqual(
                    profiles,
                    {"YOUTH_SAFE", "ADULT_STANDARD", "SERIAL_DETECTIVE"},
                )
                serial_modes = {
                    item["episode_mode"]
                    for item in values
                    if item["profile"] == "SERIAL_DETECTIVE"
                }
                self.assertEqual(
                    serial_modes,
                    {"START_SERIES", "CONTINUE_SERIES", "FINALIZE_SERIES"},
                )
                minimums = {
                    (item["profile"], item["episode_mode"]): item["length_min"]
                    for item in values
                }
                self.assertEqual(minimums[("YOUTH_SAFE", None)], 5)
                self.assertEqual(minimums[("ADULT_STANDARD", None)], 10)
                self.assertEqual(minimums[("SERIAL_DETECTIVE", "START_SERIES")], 15)
                self.assertEqual(minimums[("SERIAL_DETECTIVE", "CONTINUE_SERIES")], 12)
                self.assertEqual(minimums[("SERIAL_DETECTIVE", "FINALIZE_SERIES")], 18)
            finally:
                service.jobs.close()

    def test_stage1_job_and_run_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = WebService(Path(temporary), jobs=JobRegistry(max_workers=1))
            try:
                job = service.submit_stage1(
                    {
                        "profile": "YOUTH_SAFE",
                        "brief": "Một lời hứa sau mưa",
                        "language": "vi",
                        "minutes": 15,
                    }
                )
                deadline = time.monotonic() + 60
                current = service.jobs.get(job.job_id)
                while current and current.state not in {"SUCCEEDED", "FAILED"}:
                    if time.monotonic() >= deadline:
                        self.fail("Stage 1 web job timed out")
                    time.sleep(0.05)
                    current = service.jobs.get(job.job_id)
                self.assertIsNotNone(current)
                self.assertEqual(current.state, "SUCCEEDED", current.error)
                self.assertIsNotNone(current.run_id)
                detail = service.get_run(current.run_id or "")
                self.assertEqual(detail["stage"], "STAGE1")
                self.assertEqual(detail["status"], "SUCCEEDED")
                self.assertTrue(detail["output_package"])
                self.assertEqual(detail["package"]["provider_mode"], "deterministic")
                self.assertEqual(detail["package"]["execution_status"], "SUCCEEDED")
                self.assertEqual(detail["package"]["integrity_status"], "PASS")
                self.assertEqual(detail["package"]["content_quality_status"], "NOT_ASSESSED")
                self.assertEqual(detail["package"]["artifact_class"], "TEST_FIXTURE")
                self.assertEqual(detail["package"]["allowed_next_stage"], "STAGE2")
                self.assertEqual(detail["quality_decision"]["technical_status"], "PASS")
                self.assertEqual(detail["quality_decision"]["safety_status"], "PASS")
                self.assertEqual(detail["quality_decision"]["editorial_status"], "NOT_ASSESSED")
                self.assertEqual(detail["quality_decision"]["advancement_status"], "ALLOWED")
                self.assertEqual(detail["telemetry_reconciliation"]["status"], "PASS")
                self.assertLessEqual(
                    detail["telemetry_reconciliation"]["deviation_percent"],
                    detail["telemetry_reconciliation"]["maximum_deviation_percent"],
                )
                self.assertEqual(
                    {item["role"] for item in detail["package"]["providers"]},
                    {"story", "character_image", "safety"},
                )
                self.assertGreater(len(detail["artifacts"]), 2)
                self.assertGreater(len(detail["validation"]["records"]), 2)
                self.assertEqual(detail["validation"]["blocking_count"], 0)
                self.assertEqual(detail["validation"]["recommendations"], [])
                inspected = service.inspect_package(Path(detail["output_package"]).read_bytes())
                self.assertTrue(inspected["valid"])
                self.assertEqual(inspected["manifest"]["package_stage"], "STAGE1")
                self.assertEqual(inspected["quality_decision"]["release_status"], "BLOCKED")
                self.assertEqual(
                    inspected["manifest"]["validation"]["content_quality_status"],
                    "NOT_ASSESSED",
                )

                stage2 = service.submit_next_stage({"input_run_id": current.run_id}, 2)
                deadline = time.monotonic() + 60
                stage2_current = service.jobs.get(stage2.job_id)
                while stage2_current and stage2_current.state not in {"SUCCEEDED", "FAILED"}:
                    if time.monotonic() >= deadline:
                        self.fail("Stage 2 web job timed out")
                    time.sleep(0.05)
                    stage2_current = service.jobs.get(stage2.job_id)
                self.assertIsNotNone(stage2_current)
                self.assertEqual(stage2_current.state, "SUCCEEDED", stage2_current.error)
            finally:
                service.jobs.close()

    def test_artifact_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = WebService(Path(temporary), jobs=JobRegistry(max_workers=1))
            try:
                with self.assertRaises(WorkflowError):
                    service.artifact("run-test-0001", "../secret.txt")
            finally:
                service.jobs.close()

    def test_stage1_open_error_repair_reuses_original_generation_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = WebService(Path(temporary), jobs=JobRegistry(max_workers=1))
            try:
                original_payload = {
                    "profile": "YOUTH_SAFE", "brief": "Một lời hứa sau mưa",
                    "language": "vi", "minutes": 15, "provider_mode": "deterministic",
                    "idempotency_key": "original",
                }
                source = service.jobs.submit(
                    "STAGE1_CREATE", lambda _: {"ok": True},
                    request_payload=original_payload,
                )
                service.jobs.set_run_id(source.job_id, "run-warning")
                service.get_run = lambda _: {
                    "stage": "STAGE1", "validation": {"blocking_count": 2},
                }
                captured = {}

                def capture(payload):
                    captured.update(payload)
                    return source

                service.submit_stage1 = capture
                returned = service.submit_stage1_repair("run-warning")
                self.assertEqual(returned.job_id, source.job_id)
                self.assertEqual(captured["brief"], original_payload["brief"])
                self.assertEqual(captured["repair_source_run_id"], "run-warning")
                self.assertNotEqual(captured["idempotency_key"], "original")
            finally:
                service.jobs.close()

    def test_stage1_repair_loads_current_story_instead_of_regenerating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_work = root / "run-source" / "work"
            source_work.mkdir(parents=True)
            source_story = {"meta": {"title": "Current repaired draft"}, "script": []}
            source_contract = {"schema_version": "1.0", "requirements": []}
            (source_work / "story.json").write_text(json.dumps(source_story), encoding="utf-8")
            (source_work / "story_contract.json").write_text(
                json.dumps(source_contract), encoding="utf-8"
            )
            captured = {}

            class FakePipeline:
                def __init__(self, **_):
                    pass

                def run(self, request, workspace, **kwargs):
                    captured.update(kwargs)
                    return SimpleNamespace(to_dict=lambda: {
                        "run_id": workspace.run_id,
                        "package": {},
                    })

            service = WebService(root, jobs=JobRegistry(max_workers=1))
            try:
                with patch("ai_story.web.Stage1Pipeline", FakePipeline):
                    job = service.submit_stage1({
                        "profile": "YOUTH_SAFE",
                        "brief": "Một lời hứa sau mưa",
                        "language": "vi",
                        "minutes": 15,
                        "provider_mode": "deterministic",
                        "repair_source_run_id": "run-source",
                    })
                    current = wait_for_terminal(service.jobs, job.job_id)
                self.assertEqual(current.state, "SUCCEEDED", current.error)
                self.assertEqual(captured["initial_story"], source_story)
                self.assertEqual(captured["initial_story_contract"], source_contract)
            finally:
                service.jobs.close()

    def test_deterministic_stage1_discards_stale_model_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_path = root / "safety.gguf"
            model_path.write_bytes(b"model")
            captured = {}

            class FakePipeline:
                def __init__(self, **kwargs):
                    captured.update(kwargs)

                def run(self, _request, workspace, **_kwargs):
                    return SimpleNamespace(to_dict=lambda: {
                        "run_id": workspace.run_id,
                        "package": {},
                    })

            service = WebService(root, jobs=JobRegistry(max_workers=1))
            try:
                service.models.register({
                    "id": "safety-model",
                    "name": "Safety model",
                    "kind": "text",
                    "path": str(model_path),
                })
                with patch("ai_story.web.Stage1Pipeline", FakePipeline):
                    job = service.submit_stage1({
                        "profile": "YOUTH_SAFE",
                        "brief": "Một lời hứa sau mưa",
                        "language": "vi",
                        "minutes": 15,
                        "provider_mode": "deterministic",
                        "model_selection": {"safety": "safety-model"},
                    })
                    current = wait_for_terminal(service.jobs, job.job_id)
                self.assertEqual(current.state, "SUCCEEDED", current.error)
                self.assertEqual(captured["model_overrides"], {})
                self.assertEqual(current.request_payload["model_selection"], {})
            finally:
                service.jobs.close()

    def test_stage1_repair_rejects_package_without_open_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = WebService(Path(temporary), jobs=JobRegistry(max_workers=1))
            try:
                service.get_run = lambda _: {
                    "stage": "STAGE1", "validation": {"blocking_count": 0},
                }
                with self.assertRaisesRegex(WorkflowError, "không còn lỗi mở"):
                    service.submit_stage1_repair("run-clean")
            finally:
                service.jobs.close()

    def test_validation_summary_includes_prioritized_repair_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "story_validation.json").write_text(
                json.dumps({
                    "gates": [{
                        "gate_id": "DIALOGUE_STRUCTURE_GATE",
                        "severity": "QUALITY_BLOCKER",
                        "status": "FAIL",
                        "detector_method": "DETERMINISTIC",
                        "failure_reason": [{
                            "locator": "script",
                            "error": "DIALOGUE_TURN_COUNT_TOO_LOW",
                        }],
                    }, {
                        "gate_id": "STORY_CONTRACT_GATE",
                        "severity": "QUALITY_BLOCKER",
                        "status": "FAIL",
                        "detector_method": "DETERMINISTIC",
                        "metrics": {
                            "requirement_evidence": {"secure_home": ["script[2].text"]},
                            "outline_requirement_bindings": [{
                                "requirement_id": "secure_home", "status": "UNBOUND", "zones": [],
                            }],
                        },
                        "findings": [{
                            "locator": "outline",
                            "error": "OUTLINE_REQUIREMENT_UNBOUND",
                            "requirement_id": "secure_home",
                        }],
                    }],
                    "refinement": {
                        "refinement_status": "INCOMPLETE",
                        "initial_defect_count": 10,
                        "closed_defect_count": 10,
                        "open_defect_count": 0,
                        "refinement_round_count": 0,
                    },
                }),
                encoding="utf-8",
            )
            (root / "story_contract.json").write_text(
                json.dumps({
                    "requirements": [{"requirement_id": "secure_home", "kind": "ACTION"}],
                }),
                encoding="utf-8",
            )
            summary = WebService._validation_summary(root)
            self.assertEqual(summary["blocking_count"], 2)
            self.assertTrue(summary["recommendations"])
            self.assertIn("hội thoại", summary["recommendations"][0])
            self.assertEqual(
                summary["records"][0]["recommendations"][0],
                summary["recommendations"][0],
            )
            self.assertEqual(summary["requirement_coverage"]["total_count"], 1)
            self.assertEqual(summary["requirement_coverage"]["satisfied_count"], 0)
            self.assertEqual(summary["refinement"]["refinement_status"], "REPAIRED")
            self.assertEqual(
                summary["requirement_coverage"]["items"][0]["status"],
                "OUTLINE_UNBOUND",
            )

    def test_delete_run_removes_entire_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "run-delete-0001"
            workspace.mkdir()
            (workspace / "run.json").write_text(
                json.dumps({"run_id": "run-delete-0001"}), encoding="utf-8"
            )
            (workspace / "artifact.txt").write_text("temporary", encoding="utf-8")
            jobs = JobRegistry(max_workers=1, storage_root=root / ".jobs")
            service = WebService(root, jobs=jobs)
            try:
                related = jobs.submit("TEST", lambda _: {"ok": True})
                related = wait_for_terminal(jobs, related.job_id)
                jobs.set_run_id(related.job_id, "run-delete-0001")
                unrelated = jobs.submit("TEST", lambda _: {"ok": True})
                unrelated = wait_for_terminal(jobs, unrelated.job_id)
                jobs.set_run_id(unrelated.job_id, "run-keep-0001")
                self.assertEqual(
                    service.delete_run("run-delete-0001"),
                    {"deleted": "run-delete-0001", "deleted_jobs": 1},
                )
                self.assertFalse(workspace.exists())
                self.assertIsNone(jobs.get(related.job_id))
                self.assertFalse((root / ".jobs" / f"{related.job_id}.json").exists())
                self.assertIsNotNone(jobs.get(unrelated.job_id))
                with self.assertRaises(FileNotFoundError):
                    service.delete_run("run-delete-0001")
            finally:
                service.jobs.close()

    def test_legacy_invalid_package_is_reported_without_crashing_run_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "run-legacy-0001"
            (workspace / "output").mkdir(parents=True)
            (workspace / "work").mkdir()
            (workspace / "logs").mkdir()
            (workspace / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-legacy-0001",
                        "profile": "YOUTH_SAFE",
                        "created_at": "2026-09-24T00:00:00+00:00",
                        "status": "INITIALIZED",
                    }
                ),
                encoding="utf-8",
            )
            (workspace / "logs" / "events.ndjson").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-09-24T00:01:00+00:00",
                        "run_id": "run-legacy-0001",
                        "event": "STAGE1_COMPLETED",
                        "payload": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with zipfile.ZipFile(workspace / "output" / "story.zip", "w") as archive:
                archive.writestr("workflow_manifest.json", "{}")

            service = WebService(root, jobs=JobRegistry(max_workers=1))
            try:
                runs = service.list_runs()
                self.assertEqual(runs[0]["status"], "NEEDS_ATTENTION")
                self.assertIn("Manifest root fields", runs[0]["package_error"])
                detail = service.get_run("run-legacy-0001")
                integrity = detail["validation"]["records"][0]
                self.assertEqual(integrity["id"], "PACKAGE_INTEGRITY")
                self.assertEqual(integrity["status"], "FAIL")
            finally:
                service.jobs.close()


class WebHTTPTests(unittest.TestCase):
    def test_random_brief_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = WebService(
                Path(temporary),
                jobs=JobRegistry(max_workers=1),
                brief_generator=WebServiceTests._brief_generator,
            )
            server = AIStoryHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                url = f"http://{host}:{port}/api/briefs/random?profile=YOUTH_SAFE&language=vi&count=3"
                with urllib.request.urlopen(url) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["profile"], "YOUTH_SAFE")
                self.assertEqual(payload["language"], "vi")
                self.assertTrue(payload["brief"])
                self.assertEqual(len(payload["suggestions"]), 3)
            finally:
                server.shutdown()
                server.server_close()
                service.jobs.close()
                thread.join(timeout=2)

    def test_delete_run_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "run-delete-http"
            workspace.mkdir()
            (workspace / "run.json").write_text(
                json.dumps({"run_id": "run-delete-http"}), encoding="utf-8"
            )
            service = WebService(root, jobs=JobRegistry(max_workers=1))
            server = AIStoryHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/runs/run-delete-http", method="DELETE"
                )
                with urllib.request.urlopen(request) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(
                    payload,
                    {"deleted": "run-delete-http", "deleted_jobs": 0},
                )
                self.assertFalse(workspace.exists())
            finally:
                server.shutdown()
                server.server_close()
                service.jobs.close()
                thread.join(timeout=2)

    def test_health_and_static_app(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = WebService(Path(temporary), jobs=JobRegistry(max_workers=1))
            server = AIStoryHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                with urllib.request.urlopen(f"http://{host}:{port}/api/health") as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    csp = response.headers.get("Content-Security-Policy")
                self.assertEqual(payload["status"], "ok")
                self.assertIn("frame-ancestors 'none'", csp or "")
                event_request = urllib.request.Request(
                    f"http://{host}:{port}/api/ux-events",
                    data=json.dumps({
                        "event": "VALIDATION_VIEWED", "stage": "STAGE1", "viewport": "wide",
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(event_request) as response:
                    self.assertEqual(response.status, HTTPStatus.ACCEPTED)
                with urllib.request.urlopen(f"http://{host}:{port}/api/ux-events/summary") as response:
                    ux_summary = json.loads(response.read().decode("utf-8"))
                self.assertEqual(ux_summary["counts_by_event"]["VALIDATION_VIEWED"], 1)
                with urllib.request.urlopen(f"http://{host}:{port}/") as response:
                    html = response.read().decode("utf-8")
                self.assertIn("AI Story", html)
                self.assertIn("/app.js", html)
                with urllib.request.urlopen(f"http://{host}:{port}/app.js") as response:
                    javascript = response.read().decode("utf-8")
                self.assertIn("Trung tâm kiểm định", javascript)
                self.assertIn("filter-stage", javascript)
                self.assertNotIn("Khởi chạy dù có cảnh báo", javascript)
                self.assertIn("Bị chặn bởi kiểm định", javascript)
                self.assertIn("Có thể chạy stage tiếp theo", javascript)
                self.assertIn("prioritizedRecords", javascript)
                self.assertIn("kiểm tra phù hợp bộ lọc", javascript)
                self.assertNotIn("Các stage sản xuất tiếp theo đã bị khóa", javascript)
                self.assertIn("Vấn đề cụ thể", javascript)
                self.assertIn("workflowGroups", javascript)
                self.assertIn("validationTitle", javascript)
                self.assertIn("Chi tiết kỹ thuật", javascript)
                self.assertIn("state.validationUi", javascript)
                self.assertIn("state.runTabs", javascript)
                self.assertIn("state.scrollPositions", javascript)
                self.assertIn("sessionStorage.setItem", javascript)
                self.assertIn("sessionStorage.getItem", javascript)
                self.assertIn("Việc cần xử lý", javascript)
                self.assertIn("status: 'open'", javascript)
                self.assertIn("/api/ux-events", javascript)
                self.assertIn("BLOCKER_OPENED", javascript)
                self.assertIn("BLOCKER_CTA_SELECTED", javascript)
                for friendly_gate_name in (
                    "Cấu trúc kịch bản hợp lệ",
                    "Bộ ảnh tham chiếu nhân vật đầy đủ",
                    "Lời thoại rõ người nói",
                    "Câu văn hoàn chỉnh và sạch lỗi",
                    "Hành động của trẻ có bối cảnh an toàn",
                    "Dung lượng các phần cân đối",
                ):
                    self.assertIn(friendly_gate_name, javascript)
                self.assertIn('role="tab"', javascript)
                self.assertIn("ArrowRight", javascript)
                self.assertIn("Chưa nên phát hành", javascript)
                self.assertIn("job-summary", javascript)
                self.assertIn("job-search", javascript)
                self.assertIn("Xóa bộ lọc", javascript)
                self.assertIn("jobs-pagination", javascript)
                self.assertIn("Tự động cập nhật", javascript)
                self.assertIn("Đóng và tiếp tục chạy", javascript)
                self.assertIn("Đọc toàn bộ truyện", javascript)
                self.assertIn("Tùy chọn nâng cao", javascript)
                self.assertIn("activateDialog", javascript)
                self.assertIn('aria-label="Tạo truyện mới"', html)
                self.assertNotIn('name="visual_review_approved" value="yes" required', javascript)
                self.assertIn("QA hình ảnh đa tầng", javascript)
                with urllib.request.urlopen(f"http://{host}:{port}/styles.css") as response:
                    stylesheet = response.read().decode("utf-8")
                self.assertIn("@media (max-width: 420px)", stylesheet)
                self.assertIn(".tab-bar { width: 100%; overflow-x: auto; }", stylesheet)
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    urllib.request.urlopen(f"http://{host}:{port}/api/not-found")
                self.assertEqual(missing.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                service.jobs.close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
