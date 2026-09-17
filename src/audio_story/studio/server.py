"""Loopback-only HTTP server for the Audio Story Studio UI and API."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import socket
import shutil
import subprocess
import threading
import time
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from contextlib import suppress
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from audio_story.adapters.image import ComfyUIConfig, ComfyUIImageAdapter, ImageRequest
from audio_story.adapters.image.comfyui_provenance import load_provenance
from audio_story.adapters.llm import LlamaCppAdapter, LlamaCppConfig
from audio_story.adapters.llm.models import GenerationKind, GenerationRequest, PromptCapsule
from audio_story.studio.commands import StudioCommandError, StudioCommandRunner
from audio_story.studio.instance_lock import StudioInstanceLock, StudioInstanceLockError
from audio_story.studio.snapshot import StudioSnapshotService
from audio_story.studio.vlm import LocalQwenVlmAssessor
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage1 import final_script_digest
from audio_story.workflows import WorkflowKernel
from audio_story.workflows.image_transaction import SemanticImageGateResult
from audio_story.workflows.stage1_characters import CharacterImageConfig
from audio_story.workflows.stage1_materialization import StoryQualityResult
from audio_story.workflows.story_quality_assessor import assess_story


class StudioServerError(RuntimeError):
    pass


class ExclusiveHTTPServer(HTTPServer):
    """Prevent multiple Windows processes from sharing the Studio port."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


def default_ui_directory() -> Path:
    return Path(__file__).resolve().parents[3] / "ui" / "dist"


def build_handler(
    snapshot_service: StudioSnapshotService,
    command_runner: StudioCommandRunner,
    ui_directory: Path,
    delete_workspace: Callable[[], None] | None = None,
) -> type[BaseHTTPRequestHandler]:
    ui_root = ui_directory.resolve()

    class StudioRequestHandler(BaseHTTPRequestHandler):
        server_version = "AudioStoryStudio/1.0"

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/api/v1/studio":
                snapshot = snapshot_service.latest()
                snapshot["jobs"] = command_runner.list_jobs()
                self._json(HTTPStatus.OK, snapshot)
                return
            if path == "/api/v1/jobs":
                self._json(HTTPStatus.OK, {"jobs": command_runner.list_jobs()})
                return
            if path.startswith("/api/v1/jobs/"):
                job_id = path.removeprefix("/api/v1/jobs/")
                if job_id.endswith("/semantic-review"):
                    job_id = job_id.removesuffix("/semantic-review")
                    self._command_result(lambda: command_runner.semantic_review_assets(job_id))
                    return
                self._command_result(lambda: command_runner.get_job(job_id))
                return
            if path == "/api/v1/health":
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "PASS",
                        "offline": True,
                        "workspace": snapshot_service.workspace,
                    },
                )
                return
            if path == "/api/v1/release":
                self._json(HTTPStatus.OK, command_runner.release_readiness())
                return
            if path == "/api/v1/diagnostics":
                self._json(HTTPStatus.OK, command_runner.diagnostics())
                return
            if path == "/api/v1/contracts":
                self._json(
                    HTTPStatus.OK,
                    {
                        "api_version": "v1",
                        "offline": True,
                        "endpoints": {
                            "health": "GET /api/v1/health",
                            "studio": "GET /api/v1/studio",
                            "diagnostics": "GET /api/v1/diagnostics",
                            "release": "GET /api/v1/release",
                            "backup": "POST /api/v1/backup",
                            "delete_workspace": "POST /api/v1/workspace/delete",
                            "stage1": "POST /api/v1/workflows",
                            "stage2": "POST /api/v1/stage2",
                            "stage3": "POST /api/v1/stage3",
                            "stage4": "POST /api/v1/stage4",
                        },
                    },
                )
                return
            if path.startswith("/api/"):
                self._json(
                    HTTPStatus.NOT_FOUND,
                    {"status": "FAIL", "code": "UI001_API_NOT_FOUND"},
                )
                return
            self._static(path)

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/api/v1/story/delete":
                try:
                    payload = self._read_json()
                    workflow_id = payload.get("workflow_id")
                    if payload.get("confirm") is not True or not isinstance(workflow_id, str):
                        raise StudioCommandError(
                            "UI104_INVALID_REQUEST",
                            "story deletion requires workflow_id and confirm",
                        )
                except StudioCommandError as exc:
                    self._command_error(exc)
                    return
                self._command_result(lambda: command_runner.delete_story(workflow_id))
                return
            if path == "/api/v1/workspace/delete":
                try:
                    payload = self._read_json()
                    if payload != {"confirm": True}:
                        raise StudioCommandError(
                            "UI104_INVALID_REQUEST",
                            "workspace deletion requires {confirm: true}",
                        )
                    command_runner.ensure_workspace_can_be_deleted()
                    if delete_workspace is None:
                        raise StudioCommandError(
                            "UI116_DELETE_UNAVAILABLE", "delete is unavailable"
                        )
                except StudioCommandError as exc:
                    self._command_error(exc)
                    return
                self._json(HTTPStatus.OK, {"status": "PASS", "result": {"deleted": True}})
                threading.Thread(target=delete_workspace, daemon=True).start()
                return
            if path == "/api/v1/workflows":
                try:
                    payload = self._read_json()
                except StudioCommandError as exc:
                    self._command_error(exc)
                    return
                self._command_result(
                    lambda: command_runner.submit_stage1(payload), HTTPStatus.ACCEPTED
                )
                return
            if path == "/api/v1/stage2":
                try:
                    payload = self._read_json()
                except StudioCommandError as exc:
                    self._command_error(exc)
                    return
                self._command_result(
                    lambda: command_runner.submit_stage2(payload), HTTPStatus.ACCEPTED
                )
                return
            if path == "/api/v1/stories/import":
                try:
                    data = self._read_binary(536_870_912)
                except StudioCommandError as exc:
                    self._command_error(exc)
                    return
                filename = unquote(self.headers.get("X-Story-Filename", "story.zip"))
                self._command_result(
                    lambda: command_runner.import_story_package(data, filename),
                    HTTPStatus.CREATED,
                )
                return
            if path == "/api/v1/stage3":
                try:
                    payload = self._read_json()
                except StudioCommandError as exc:
                    self._command_error(exc)
                    return
                self._command_result(
                    lambda: command_runner.submit_stage3(payload), HTTPStatus.ACCEPTED
                )
                return
            if path == "/api/v1/stage4":
                try:
                    payload = self._read_json()
                except StudioCommandError as exc:
                    self._command_error(exc)
                    return
                self._command_result(
                    lambda: command_runner.submit_stage4(payload), HTTPStatus.ACCEPTED
                )
                return
            if path == "/api/v1/backup":
                try:
                    payload = self._read_json()
                except StudioCommandError as exc:
                    self._command_error(exc)
                    return
                self._command_result(
                    lambda: command_runner.create_workspace_backup(payload), HTTPStatus.ACCEPTED
                )
                return
            if path.startswith("/api/v1/jobs/") and path.endswith("/cancel"):
                job_id = path.removeprefix("/api/v1/jobs/").removesuffix("/cancel")
                self._command_result(lambda: command_runner.cancel_job(job_id))
                return
            if path.startswith("/api/v1/jobs/") and path.endswith("/retry"):
                job_id = path.removeprefix("/api/v1/jobs/").removesuffix("/retry")
                self._command_result(
                    lambda: command_runner.retry_stage2(job_id), HTTPStatus.ACCEPTED
                )
                return
            if path.startswith("/api/v1/jobs/") and path.endswith("/semantic-review"):
                job_id = path.removeprefix("/api/v1/jobs/").removesuffix("/semantic-review")
                try:
                    payload = self._read_json()
                except StudioCommandError as exc:
                    self._command_error(exc)
                    return
                self._command_result(lambda: command_runner.submit_semantic_review(job_id, payload))
                return
            if path.startswith("/api/v1/jobs/") and path.endswith("/vlm-review"):
                job_id = path.removeprefix("/api/v1/jobs/").removesuffix("/vlm-review")
                self._command_result(
                    lambda: command_runner.submit_vlm_review(job_id), HTTPStatus.ACCEPTED
                )
                return
            self._json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {
                    "status": "FAIL",
                    "code": "UI002_READ_ONLY_API",
                    "message": "Authority-changing actions require a workflow runner.",
                },
                headers={"Allow": "GET"},
            )

        def _command_result(
            self,
            action: Callable[[], dict[str, Any]],
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            try:
                result = action()
            except StudioCommandError as exc:
                self._command_error(exc)
                return
            self._json(status, {"status": "PASS", "result": result})

        def _command_error(self, exc: StudioCommandError) -> None:
            status = (
                HTTPStatus.NOT_FOUND
                if exc.code == "UI101_JOB_NOT_FOUND"
                else HTTPStatus.CONFLICT
                if exc.code
                in {
                    "UI102_JOB_NOT_CANCELLABLE",
                    "UI114_STAGE2_NOT_RETRYABLE",
                    "UI115_WORKSPACE_BUSY",
                }
                else HTTPStatus.BAD_REQUEST
            )
            self._json(status, {"status": "FAIL", "code": exc.code, "message": str(exc)})

        def _read_json(self) -> dict[str, Any]:
            value = self.headers.get("Content-Length")
            if value is None or not value.isdecimal():
                raise StudioCommandError("UI105_INVALID_JSON", "Content-Length is required")
            length = int(value)
            if not 1 <= length <= 16_384:
                raise StudioCommandError("UI106_REQUEST_TOO_LARGE", "request size is invalid")
            try:
                payload = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise StudioCommandError("UI105_INVALID_JSON", "request is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise StudioCommandError("UI104_INVALID_REQUEST", "request root must be an object")
            return payload

        def _read_binary(self, maximum: int) -> bytes:
            value = self.headers.get("Content-Length")
            if value is None or not value.isdecimal():
                raise StudioCommandError("UI105_INVALID_JSON", "Content-Length is required")
            length = int(value)
            if not 1 <= length <= maximum:
                raise StudioCommandError("UI106_REQUEST_TOO_LARGE", "story package size is invalid")
            if self.headers.get("Content-Type", "").split(";", 1)[0] not in {
                "application/zip",
                "application/octet-stream",
            }:
                raise StudioCommandError(
                    "UI125_INVALID_MEDIA_TYPE", "story import requires ZIP content"
                )
            return self.rfile.read(length)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _static(self, request_path: str) -> None:
            relative = request_path.lstrip("/") or "index.html"
            candidate = (ui_root / relative).resolve()
            if ui_root not in candidate.parents and candidate != ui_root:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"status": "FAIL", "code": "UI003_INVALID_PATH"},
                )
                return
            if not candidate.is_file():
                candidate = ui_root / "index.html"
            data = candidate.read_bytes()
            media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{media_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Audio-Story-API", "v1")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'",
            )
            self.end_headers()
            self.wfile.write(data)

        def _json(
            self,
            status: HTTPStatus,
            payload: dict[str, Any],
            *,
            headers: dict[str, str] | None = None,
        ) -> None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

    return StudioRequestHandler


def serve_studio(
    workspace: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 4173,
    ui_directory: Path | None = None,
    canonical_path: Path | None = None,
    comfyui_endpoint: str = "http://127.0.0.1:8188",
    comfyui_workflow_path: Path | None = None,
    qwen_model_path: Path | None = None,
    qwen_runner_path: Path | None = None,
    ffmpeg_path: Path | None = None,
    ffprobe_path: Path | None = None,
    llama_endpoint: str = "http://127.0.0.1:8080",
    llama_server_path: Path | None = None,
    llama_model_path: Path | None = None,
    comfy_python_path: Path | None = None,
    comfy_root_path: Path | None = None,
    comfy_model_config_path: Path | None = None,
) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise StudioServerError("UI004_NON_LOOPBACK_BIND")
    if not 1 <= port <= 65_535:
        raise StudioServerError("UI005_INVALID_PORT")
    ui_root = (ui_directory or default_ui_directory()).resolve()
    if not (ui_root / "index.html").is_file():
        raise StudioServerError(f"UI006_MISSING_UI: {ui_root}")
    try:
        instance_lock = StudioInstanceLock.acquire(workspace)
    except StudioInstanceLockError as exc:
        raise StudioServerError(str(exc)) from exc
    kernel = WorkflowKernel(workspace)
    canonical = (
        canonical_path
        or Path(__file__).resolve().parents[3] / "canonical" / "ChatGPT_prompt_v3.16.13.txt"
    )
    if not canonical.is_file():
        kernel.close()
        instance_lock.release()
        raise StudioServerError(f"UI007_MISSING_CANONICAL: {canonical}")
    comfy_workflow = comfyui_workflow_path or (
        Path(__file__).resolve().parents[3] / "comfy_workflows" / "sdxl_txt2img_api.json"
    )
    if qwen_model_path is None:
        config_path = Path(__file__).resolve().parents[3] / "docs" / "m7-vlm-assessor.json"
        if config_path.is_file():
            with suppress(KeyError, TypeError, json.JSONDecodeError):
                configured = json.loads(config_path.read_text(encoding="utf-8"))["model_path"]
                qwen_model_path = Path(configured)
    detected_ffmpeg = shutil.which("ffmpeg")
    detected_ffprobe = shutil.which("ffprobe")
    resolved_qwen_runner = qwen_runner_path or (
        Path(__file__).resolve().parents[3] / "scripts" / "run_m7_semantic_assessor.py"
    )
    llama_process: subprocess.Popen[bytes] | None = None
    if llama_server_path is not None or llama_model_path is not None:
        if llama_server_path is None or llama_model_path is None:
            kernel.close()
            instance_lock.release()
            raise StudioServerError("UI008_INCOMPLETE_LLAMA_CONFIG")
        if not llama_server_path.is_file() or not llama_model_path.is_file():
            kernel.close()
            instance_lock.release()
            raise StudioServerError("UI009_LLAMA_RUNTIME_MISSING")
        llama_process = subprocess.Popen(
            [
                str(llama_server_path),
                "-m",
                str(llama_model_path),
                "--host",
                "127.0.0.1",
                "--port",
                "8080",
                "-ngl",
                "99",
                "--ctx-size",
                "16384",
                "--parallel",
                "1",
                "--sleep-idle-seconds",
                "1",
                "--no-webui",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(llama_endpoint + "/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            llama_process.terminate()
            kernel.close()
            instance_lock.release()
            raise StudioServerError("UI010_LLAMA_START_TIMEOUT")
    comfy_process: subprocess.Popen[bytes] | None = None
    if comfy_python_path is not None or comfy_root_path is not None:
        if comfy_python_path is None or comfy_root_path is None or comfy_model_config_path is None:
            kernel.close()
            instance_lock.release()
            raise StudioServerError("UI011_INCOMPLETE_COMFYUI_CONFIG")
        entrypoint = comfy_root_path / "main.py"
        if (
            not comfy_python_path.is_file()
            or not entrypoint.is_file()
            or not comfy_model_config_path.is_file()
        ):
            kernel.close()
            instance_lock.release()
            raise StudioServerError("UI012_COMFYUI_RUNTIME_MISSING")
        comfy_process = subprocess.Popen(
            [
                str(comfy_python_path),
                str(entrypoint),
                "--listen",
                "127.0.0.1",
                "--port",
                "8188",
                "--extra-model-paths-config",
                str(comfy_model_config_path),
                "--disable-all-custom-nodes",
                "--disable-api-nodes",
                "--disable-manager-ui",
                "--disable-auto-launch",
                "--deterministic",
            ],
            cwd=comfy_root_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    comfyui_endpoint + "/system_stats", timeout=2
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            comfy_process.terminate()
            if llama_process is not None:
                llama_process.terminate()
            kernel.close()
            instance_lock.release()
            raise StudioServerError("UI013_COMFYUI_START_TIMEOUT")

    llm_adapter = LlamaCppAdapter(LlamaCppConfig(endpoint=llama_endpoint, timeout_seconds=180))
    character_config = None
    story_assessor = None
    provenance_path = Path(__file__).resolve().parents[3] / "docs" / "m6-comfyui-evidence.json"
    if qwen_model_path is not None and resolved_qwen_runner.is_file() and provenance_path.is_file():
        provenance = load_provenance(provenance_path)

        def assess_character(data: bytes, request: ImageRequest) -> SemanticImageGateResult:
            urllib.request.urlopen(
                urllib.request.Request(
                    comfyui_endpoint + "/free",
                    data=b'{"unload_models":true,"free_memory":true}',
                    method="POST",
                    headers={"Content-Type": "application/json"},
                ),
                timeout=30,
            ).read()
            result = LocalQwenVlmAssessor(qwen_model_path, resolved_qwen_runner).assess(
                data,
                request.basename,
                {
                    "asset_role": "single character identity reference",
                    "required": [
                        "exactly one visible person",
                        "full body visible from head through feet",
                        "plain background",
                        "no text or watermark",
                    ],
                },
                threading.Event(),
            )
            return SemanticImageGateResult(
                result.status,
                {
                    "image_sha256": hashlib.sha256(data).hexdigest(),
                    "observable_findings": list(result.observable_findings),
                    "evidence_digest_sha256": result.evidence_digest_sha256,
                },
                "Qwen2.5-VL-7B-Instruct",
                "offline-local-1.0",
            )

        character_config = CharacterImageConfig(
            ComfyUIImageAdapter(
                ComfyUIConfig(comfyui_endpoint, 300.0, workflow_path=provenance.workflow_path)
            ),
            provenance.workflow_sha256,
            provenance.model_sha256,
            300.0,
            assess_character,
        )

        def story_assessor(
            story_bytes: bytes, assets: OrderedDict[str, bytes]
        ) -> StoryQualityResult:
            story = json.loads(story_bytes)
            return assess_story(
                llm_adapter,
                story_bytes,
                script_digest=final_script_digest(story["script"]),
                asset_set_digest=sha256_bytes(
                    canonical_json_bytes(
                        [[path, sha256_bytes(data)] for path, data in assets.items()]
                    )
                ),
            )

    def assess_video_prompts(prompts_bytes: bytes) -> None:
        schema = {
            "type": "object",
            "required": ["status", "observations"],
            "properties": {
                "status": {"type": "string", "enum": ["PASS", "FAIL"]},
                "observations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 12,
                },
            },
            "additionalProperties": False,
        }
        response = llm_adapter.generate_structured(
            GenerationRequest(
                capsule=PromptCapsule(prompts_bytes, sha256_bytes(prompts_bytes)),
                instruction=(
                    "Return JSON only. Review every video prompt for source fidelity, "
                    "continuity, identity consistency, and usable generation instructions."
                ),
                kind=GenerationKind.SEMANTIC_ASSESSMENT,
                max_output_tokens=512,
                json_schema=schema,
                temperature=0.0,
                top_p=1.0,
            ),
            threading.Event(),
        )
        assessment = json.loads(response.content)
        if assessment.get("status") != "PASS":
            raise StudioCommandError(
                "UI119_STAGE4_MODEL_REVIEW_FAILED",
                "local model rejected the Stage 4 video prompt package",
            )

    runner = StudioCommandRunner(
        workspace,
        canonical,
        comfyui_endpoint=comfyui_endpoint,
        comfyui_workflow_path=comfy_workflow,
        qwen_model_path=qwen_model_path,
        qwen_runner_path=resolved_qwen_runner,
        ffmpeg_path=ffmpeg_path or (Path(detected_ffmpeg) if detected_ffmpeg else None),
        ffprobe_path=ffprobe_path or (Path(detected_ffprobe) if detected_ffprobe else None),
        stage1_adapter=llm_adapter,
        stage1_test_mode=False,
        stage1_character_image_config=character_config,
        stage1_story_quality_assessor=story_assessor,
        stage4_prompt_assessor=assess_video_prompts,
    )
    server: HTTPServer

    def delete_workspace() -> None:
        runner.close()
        kernel.close()
        shutil.rmtree(workspace.resolve(), ignore_errors=False)
        server.shutdown()

    try:
        server = ExclusiveHTTPServer(
            (host, port),
            build_handler(StudioSnapshotService(kernel), runner, ui_root, delete_workspace),
        )
    except OSError as exc:
        runner.close()
        kernel.close()
        instance_lock.release()
        if llama_process is not None:
            llama_process.terminate()
        if comfy_process is not None:
            comfy_process.terminate()
        raise StudioServerError(f"UI017_STUDIO_PORT_IN_USE: {host}:{port}") from exc
    try:
        with suppress(KeyboardInterrupt):
            server.serve_forever()
    finally:
        server.server_close()
        runner.close()
        kernel.close()
        if llama_process is not None:
            llama_process.terminate()
            with suppress(subprocess.TimeoutExpired):
                llama_process.wait(timeout=10)
            if llama_process.poll() is None:
                llama_process.kill()
                llama_process.wait(timeout=10)
        if comfy_process is not None:
            comfy_process.terminate()
            with suppress(subprocess.TimeoutExpired):
                comfy_process.wait(timeout=10)
            if comfy_process.poll() is None:
                comfy_process.kill()
                comfy_process.wait(timeout=10)
        instance_lock.release()
