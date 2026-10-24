# Local generator upgrade

## Presets

Image presets control inference steps and successful candidate targets. Failed candidates consume the
existing transaction attempt budget and are never ranked.

| Preset | Steps | Character | Cover | Keyframe | Scene | Portrait |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fast | 18 | 1 | 1 | 1 | 1 | 1 |
| balanced | 28 | 2 | 3 | 3 | 2 | 2 |
| quality | 40 | 3 | 4 | 4 | 3 | 3 |

Cover, climax and ending receive the larger budgets. The selected preset and candidate policy are
recorded in package provenance.

## Candidate selection

Each successful candidate records its attempt, deterministic seed, generated hash, QA assessment and
rank score. `BEST_OF_N_QA_V1` ranks only measured signals: technical status, semantic similarity,
minimum character identity similarity, required-element checks and landscape/portrait parity. Missing
signals do not receive a synthetic passing score. Ties select the earlier attempt.

Only the selected PNG is committed to the canonical asset path. Candidate evidence remains embedded
in `quality_assessment.candidate_selection`, so benchmark reports can audit the decision without
inflating package size with rejected images.

## Image inference

- SD 3.5 Medium uses `FlowMatchEulerDiscreteScheduler`, guidance 4.5 and currently does not declare
  reference-image conditioning. Identity references remain available to QA but are not passed to the
  generator.

Unsupported runtime parameters fail before model loading.

## Benchmark commands

Run the Stage 1 golden packages with the supported SD 3.5 mode:

```powershell
py -3.10 -m ai_story run-image-baseline-suite --source-packages stage1-packages --output artifacts/benchmarks/image-sd35-balanced --provider-mode local_sd35 --quality-preset balanced --resume
```

Both `local` and `local_sd35` use SD 3.5 Medium.
