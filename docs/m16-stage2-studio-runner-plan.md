# M16 Stage 2 Studio Runner Plan

M16 connects the existing M7 Stage 2 ZONE pipeline to Audio Story Studio while
preserving all package, transaction, gate, and offline invariants.

## Scope

- Accept one authoritative Stage 1 `story.zip` inside the selected workspace.
- Build the deterministic Visual Plan and Visual Bible.
- Execute the ten-item landscape queue with one background worker.
- Support deterministic mock and explicitly configured loopback ComfyUI modes.
- Report committed count and next pending basename after every asset.
- Retry failed Stage 2 generation using the same workflow, stage, and logical
  transaction lineage.
- In mock mode, use explicit test-only semantic fixtures and publish the Stage 2
  checkpoint after aggregate PASS.
- In ComfyUI mode, stop at `WAITING_SEMANTIC_REVIEW` when semantic evidence is
  unavailable; never infer PASS from metadata.

## Definition of Done

- Mock Stage 2 runs from Stage 1 package to a reopened checkpoint with 10/10
  committed landscapes.
- ComfyUI configuration accepts only the existing loopback adapter contract.
- Progress is observable through the Studio job API and UI.
- Failed generation is retryable without replacing transaction lineage.
- Production mode cannot publish using test-only semantic evidence.
- Repository gates pass and canonical bytes remain unchanged.
