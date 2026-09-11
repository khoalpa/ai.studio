# Workflow State Machine

The M3 kernel stores workflow, stage, transaction, generation-call and artifact state as closed enums. State changes pass through pure transition functions before a SQLite update.

Workflow transitions are `CREATED → RUNNING|FAILED`, `RUNNING → WAITING_INPUT|FAILED|COMPLETED`, and `WAITING_INPUT → RUNNING|FAILED`. Terminal states do not transition. Stage transitions are sequential from `PREFLIGHT → GENERATING → VALIDATING → PACKAGING → PASS`; each nonterminal state can instead transition to `FAIL` where defined. Invalid edges raise `RK001_INVALID_STATE_TRANSITION`.

An asset transaction is unique by `(stage_run_id, orientation, basename)`. Retry reuses that row and increments the generation-call attempt index. Progress is queried from committed transaction/binding state; it is not stored as a counter. Current gate evidence is included when gate history exists, so stale evidence cannot contribute to progress.

Artifact roles map to owner stages in `OWNER_STAGE_BY_ROLE`. Inherited or published artifacts have `READ_ONLY` mutation status. Owner mismatch fails before writing candidate bytes.

The public application surface is `WorkflowKernel`: create/transition workflow, start/transition stage, get/create transaction, begin/finish generation call, register/quarantine/commit artifact, record/stale gate, derive progress, lease workspace and inspect workflow. There is no web UI in M3.

## Stable state codes

| Code | Meaning |
| --- | --- |
| `RK001_INVALID_STATE_TRANSITION` | State edge is not allowed |
| `RK008_INVALID_CALL_FINISH` | A call was finished with a running state |
| `RK009_READ_ONLY_MUTATION` | Attempted mutation of immutable bytes |
| `RK010_DIFFERENT_DOUBLE_COMMIT` | Transaction already committed another artifact |
| `RK011_ARTIFACT_DIGEST_MISMATCH` | Store bytes differ from DB digest |
| `RK012_LEASE_CONFLICT` | Another non-expired workspace owner exists |
| `RK013_NOT_FOUND` | Kernel entity does not exist |
| `RK014_OWNER_STAGE_MISMATCH` | Candidate owner differs from active stage |
| `RK015_ROLE_OWNER_MISMATCH` | Artifact role is owned by another stage |
| `RK016_GATE_NOT_CURRENT_PASS` | Existing gate history has no usable current PASS |
| `RK017_CANDIDATE_NOT_VALIDATED` | Candidate has not reached validated state |
| `RK018_TRANSACTION_NOT_CALLABLE` | Transaction is terminal or already has a running call |
| `RK019_ARTIFACT_TRANSACTION_MISMATCH` | Artifact was not produced for the target transaction |
