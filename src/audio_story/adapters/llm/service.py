"""M1 capsule to M2 validation to M3 commit orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from threading import Event

from audio_story.adapters.llm.base import LLMAdapterError, LocalLLMAdapter
from audio_story.adapters.llm.models import GenerationKind, GenerationRequest, PromptCapsule
from audio_story.domain.state import CallStatus, DetectorClass, GateStatus
from audio_story.validation.errors import ValidationError
from audio_story.validation.schemas import validate_schema
from audio_story.validation.strict_json import parse_json_bytes, validate_field_order
from audio_story.workflows import WorkflowKernel


@dataclass(frozen=True, slots=True)
class AdapterPolicy:
    max_context_chars: int = 131_072
    max_output_tokens: int = 8_192
    max_attempts: int = 2
    adapter_version: str = "1.0"


class StructuredGenerationService:
    def __init__(
        self,
        kernel: WorkflowKernel,
        adapter: LocalLLMAdapter,
        policy: AdapterPolicy | None = None,
    ) -> None:
        self.kernel = kernel
        self.adapter = adapter
        self.policy = policy or AdapterPolicy()

    def generate_and_commit(
        self,
        transaction_id: str,
        stage_id: str,
        owner_stage: str,
        artifact_role: str,
        artifact_name: str,
        capsule: PromptCapsule,
        instruction: str,
        canonical_digest: str,
        profile: str,
        route: str,
        field_order: tuple[str, ...] | None = None,
        cancellation: Event | None = None,
        requested_output_tokens: int | None = None,
    ) -> str:
        token = cancellation or Event()
        self._verify_bindings(stage_id, owner_stage, capsule.digest, canonical_digest)
        if (
            len(capsule.canonical_bytes.decode("utf-8")) + len(instruction)
            > self.policy.max_context_chars
        ):
            raise LLMAdapterError("LLM002_CONTEXT_BUDGET", "request exceeds context budget")
        output_tokens = requested_output_tokens or self.policy.max_output_tokens
        if output_tokens <= 0 or output_tokens > self.policy.max_output_tokens:
            raise LLMAdapterError("LLM013_TOKEN_BUDGET", "request exceeds output token budget")
        last_error: LLMAdapterError | None = None
        for _ in range(self.policy.max_attempts):
            artifact_id: str | None = None
            request = GenerationRequest(
                capsule,
                instruction,
                kind=GenerationKind.STRUCTURED,
                max_output_tokens=output_tokens,
                schema_name=artifact_name,
                field_order=field_order,
            )
            request_digest = _request_digest(request, profile, route)
            call_id = self.kernel.begin_generation_call(
                transaction_id,
                request_digest,
                model_identity="PENDING_LOCAL",
                adapter_version=self.policy.adapter_version,
            )
            try:
                response = self.adapter.generate_structured(request, token)
                response_digest = hashlib.sha256(response.content).hexdigest()
                artifact_id = self.kernel.register_candidate(
                    call_id,
                    response.content,
                    "application/json",
                    owner_stage,
                    artifact_role=artifact_role,
                    dependency_digest=capsule.digest,
                )
                parsed = parse_json_bytes(response.content, artifact_name, engine_generated=True)
                if field_order is not None:
                    validate_field_order(parsed.value, field_order, artifact_name)
                implementation = validate_schema(
                    parsed.value, artifact_name, "OUTPUT", artifact_name
                )
                if implementation != "IMPLEMENTED":
                    raise LLMAdapterError(
                        "LLM010_VALIDATION_NOT_VERIFIED",
                        f"schema {artifact_name} is {implementation}",
                    )
                self.kernel.record_gate(
                    stage_id,
                    artifact_id,
                    "M4_STRUCTURED_OUTPUT",
                    DetectorClass.DETERMINISTIC,
                    GateStatus.PASS,
                    {"schema": artifact_name, "response_sha256": response_digest},
                    canonical_digest,
                    capsule.digest,
                    "M4-1.0",
                    capsule.digest,
                )
                self.kernel.finish_generation_call(
                    call_id,
                    CallStatus.FINISHED,
                    response_digest,
                    model_identity=response.model_identity,
                    adapter_version=response.adapter_version,
                    duration_ms=response.duration_ms,
                    termination_reason=response.termination_reason,
                )
                return self.kernel.commit_artifact(transaction_id, artifact_id)
            except ValidationError as exc:
                last_error = LLMAdapterError("LLM009_VALIDATION_FAILED", exc.finding.code)
            except LLMAdapterError as exc:
                last_error = exc
            except Exception as exc:
                last_error = LLMAdapterError(
                    "LLM014_EXECUTION_FAILURE",
                    f"local generation execution failed: {type(exc).__name__}",
                )
            if artifact_id is not None:
                self.kernel.quarantine_artifact(artifact_id, stage_id)
            self.kernel.finish_generation_call(
                call_id,
                CallStatus.FAILED,
                failure_code=last_error.code,
                termination_reason=last_error.code,
            )
            if last_error.code == "LLM004_CANCELLED":
                raise last_error
        raise LLMAdapterError(
            "LLM005_RETRY_EXHAUSTED",
            f"structured generation exhausted after {self.policy.max_attempts} attempts: "
            f"{last_error.code if last_error else 'unknown'}",
        )

    def _verify_bindings(
        self, stage_id: str, owner_stage: str, capsule_digest: str, canonical_digest: str
    ) -> None:
        row = self.kernel.db.connection.execute(
            "SELECT s.stage,s.capsule_digest,w.canonical_prompt_sha256 "
            "FROM stage_runs s JOIN workflow_runs w ON w.id=s.workflow_id WHERE s.id=?",
            (stage_id,),
        ).fetchone()
        if row is None or (
            row["stage"] != owner_stage
            or row["capsule_digest"] != capsule_digest
            or row["canonical_prompt_sha256"] != canonical_digest
        ):
            raise LLMAdapterError(
                "LLM012_BINDING_MISMATCH",
                "stage, capsule or canonical binding does not match the workflow",
            )


def _request_digest(request: GenerationRequest, profile: str, route: str) -> str:
    digest = hashlib.sha256()
    digest.update(request.capsule.digest.encode())
    digest.update(request.instruction.encode("utf-8"))
    digest.update(str(request.max_output_tokens).encode())
    digest.update((request.schema_name or "").encode())
    digest.update(profile.encode())
    digest.update(route.encode())
    digest.update(str(request.seed).encode())
    return digest.hexdigest()
