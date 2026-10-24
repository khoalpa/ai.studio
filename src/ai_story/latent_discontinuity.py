from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class LatentDiscontinuityConfig:
    minimum_ratio: float = 1.2
    minimum_robust_z: float = 3.5
    minimum_absolute_growth: float = 1.05
    confirmation_floor: float = 0.95
    persistence_steps: int = 2
    index_tolerance: int = 2
    interior_margin_fraction: float = 0.02
    minimum_interior_margin: int = 2
    vae_precursor_minimum_ratio: float = 1.8
    vae_precursor_minimum_robust_z: float = 1.8


@dataclass(frozen=True)
class BoundaryObservation:
    step: int
    axis: str
    maximum: float
    median: float
    mad: float
    maximum_index: int
    profile_length: int = 64

    @property
    def ratio(self) -> float:
        return self.maximum / max(self.median, 1e-12)

    @property
    def robust_z(self) -> float:
        return (self.maximum - self.median) / max(1.4826 * self.mad, 1e-12)


@dataclass(frozen=True)
class LatentDiscontinuityDecision:
    blocked: bool
    status: str
    axis: str | None = None
    onset_step: int | None = None
    boundary_index: int | None = None
    ratio: float | None = None
    robust_z: float | None = None
    absolute_growth: float | None = None


@dataclass(frozen=True)
class PairedLatentDiscontinuityConfig:
    maximum_ratio_delta: float = 0.02
    maximum_robust_z_delta: float = 0.25
    onset_step_tolerance: int = 0
    boundary_index_tolerance: int = 0


@dataclass(frozen=True)
class PairedLatentDiscontinuityDecision:
    blocked: bool
    status: str
    baseline_blocked: bool
    active_blocked: bool
    ratio_delta: float | None = None
    robust_z_delta: float | None = None
    onset_step_delta: int | None = None
    boundary_index_delta: int | None = None


def observation_from_profile(
    *, step: int, axis: str, profile: Mapping[str, float | int]
) -> BoundaryObservation:
    return BoundaryObservation(
        step=step,
        axis=axis,
        maximum=float(profile["maximum"]),
        median=float(profile["median"]),
        mad=float(profile["mad"]),
        maximum_index=int(profile["maximum_index"]),
        profile_length=len(profile.get("values", [])) or 64,
    )


def evaluate_paired_latent_discontinuity(
    baseline: LatentDiscontinuityDecision,
    active: LatentDiscontinuityDecision,
    config: PairedLatentDiscontinuityConfig | None = None,
) -> PairedLatentDiscontinuityDecision:
    """Compare an active trajectory only against its same-seed baseline.

    The absolute critic remains authoritative for unpaired trajectories. A paired
    active blocker may be suppressed only when the baseline has the same blocker
    at the same location and its severity has not materially increased.
    """
    config = config or PairedLatentDiscontinuityConfig()
    if not active.blocked:
        return PairedLatentDiscontinuityDecision(
            blocked=False,
            status="ACTIVE_TRAJECTORY_ABSOLUTELY_CLEAN",
            baseline_blocked=baseline.blocked,
            active_blocked=False,
        )
    if not baseline.blocked:
        return PairedLatentDiscontinuityDecision(
            blocked=True,
            status="ACTIVE_ONLY_DISCONTINUITY",
            baseline_blocked=False,
            active_blocked=True,
        )

    comparable = all(
        value is not None
        for value in (
            baseline.ratio,
            active.ratio,
            baseline.robust_z,
            active.robust_z,
            baseline.onset_step,
            active.onset_step,
            baseline.boundary_index,
            active.boundary_index,
        )
    )
    if not comparable:
        return PairedLatentDiscontinuityDecision(
            blocked=True,
            status="INSUFFICIENT_PAIRED_EVIDENCE",
            baseline_blocked=True,
            active_blocked=True,
        )

    ratio_delta = abs(float(active.ratio) - float(baseline.ratio))
    robust_z_delta = abs(float(active.robust_z) - float(baseline.robust_z))
    onset_delta = abs(int(active.onset_step) - int(baseline.onset_step))
    boundary_delta = abs(int(active.boundary_index) - int(baseline.boundary_index))
    same_signature = (
        active.status == baseline.status
        and active.axis == baseline.axis
        and onset_delta <= config.onset_step_tolerance
        and boundary_delta <= config.boundary_index_tolerance
        and ratio_delta <= config.maximum_ratio_delta
        and robust_z_delta <= config.maximum_robust_z_delta
    )
    return PairedLatentDiscontinuityDecision(
        blocked=not same_signature,
        status=(
            "MATCHED_BASELINE_STATIC_FEATURE" if same_signature else "PAIRED_ACTIVE_DISCONTINUITY"
        ),
        baseline_blocked=True,
        active_blocked=True,
        ratio_delta=round(ratio_delta, 8),
        robust_z_delta=round(robust_z_delta, 8),
        onset_step_delta=onset_delta,
        boundary_index_delta=boundary_delta,
    )


def _is_interior(observation: BoundaryObservation, config: LatentDiscontinuityConfig) -> bool:
    margin = max(
        config.minimum_interior_margin,
        round(observation.profile_length * config.interior_margin_fraction),
    )
    return margin <= observation.maximum_index < observation.profile_length - margin


def _static_axis_decision(
    observations: Sequence[BoundaryObservation],
    config: LatentDiscontinuityConfig,
) -> LatentDiscontinuityDecision | None:
    required = config.persistence_steps
    if len(observations) < required:
        return None
    window = observations[-required:]
    onset = window[0]
    if any(
        item.ratio < config.minimum_ratio
        or item.robust_z < config.minimum_robust_z
        or not _is_interior(item, config)
        for item in window
    ):
        return None
    if any(
        current.step != previous.step + 1
        or abs(current.maximum_index - previous.maximum_index) > config.index_tolerance
        for previous, current in zip(window, window[1:])
    ):
        return None
    return LatentDiscontinuityDecision(
        blocked=True,
        status="PERSISTENT_STATIC_INTERIOR_DISCONTINUITY",
        axis=onset.axis,
        onset_step=onset.step,
        boundary_index=onset.maximum_index,
        ratio=round(onset.ratio, 8),
        robust_z=round(onset.robust_z, 8),
        absolute_growth=None,
    )


def _vae_amplification_precursor_decision(
    observations: Sequence[BoundaryObservation],
    config: LatentDiscontinuityConfig,
) -> LatentDiscontinuityDecision | None:
    required = config.persistence_steps
    if len(observations) < required:
        return None
    window = observations[-required:]
    onset = window[0]
    if any(
        item.ratio < config.vae_precursor_minimum_ratio
        or item.robust_z < config.vae_precursor_minimum_robust_z
        or not _is_interior(item, config)
        for item in window
    ):
        return None
    if any(
        current.step != previous.step + 1
        or abs(current.maximum_index - previous.maximum_index) > config.index_tolerance
        for previous, current in zip(window, window[1:])
    ):
        return None
    return LatentDiscontinuityDecision(
        blocked=True,
        status="PERSISTENT_VAE_AMPLIFICATION_PRECURSOR",
        axis=onset.axis,
        onset_step=onset.step,
        boundary_index=onset.maximum_index,
        ratio=round(onset.ratio, 8),
        robust_z=round(onset.robust_z, 8),
        absolute_growth=None,
    )


def _axis_decision(
    observations: Sequence[BoundaryObservation],
    config: LatentDiscontinuityConfig,
) -> LatentDiscontinuityDecision | None:
    required = config.persistence_steps
    if required < 2:
        raise ValueError("persistence_steps must be at least 2")
    for index in range(1, len(observations) - required + 1):
        previous = observations[index - 1]
        onset = observations[index]
        growth = onset.maximum / max(previous.maximum, 1e-12)
        if (
            onset.ratio < config.minimum_ratio
            or onset.robust_z < config.minimum_robust_z
            or growth < config.minimum_absolute_growth
        ):
            continue
        confirmations = observations[index + 1 : index + required]
        if all(
            item.ratio >= config.minimum_ratio
            and item.robust_z >= config.minimum_robust_z
            and item.maximum >= onset.maximum * config.confirmation_floor
            and abs(item.maximum_index - onset.maximum_index) <= config.index_tolerance
            for item in confirmations
        ):
            return LatentDiscontinuityDecision(
                blocked=True,
                status="PERSISTENT_ABSOLUTE_DISCONTINUITY",
                axis=onset.axis,
                onset_step=onset.step,
                boundary_index=onset.maximum_index,
                ratio=round(onset.ratio, 8),
                robust_z=round(onset.robust_z, 8),
                absolute_growth=round(growth, 8),
            )
    return None


def evaluate_latent_discontinuity(
    observations: Iterable[BoundaryObservation],
    config: LatentDiscontinuityConfig | None = None,
) -> LatentDiscontinuityDecision:
    config = config or LatentDiscontinuityConfig()
    grouped: dict[str, list[BoundaryObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.axis, []).append(observation)
    if not grouped:
        return LatentDiscontinuityDecision(blocked=False, status="INSUFFICIENT_ABSOLUTE_EVIDENCE")
    for axis in sorted(grouped):
        ordered = sorted(grouped[axis], key=lambda item: item.step)
        decision = _axis_decision(ordered, config)
        if decision is not None:
            return decision
        decision = _static_axis_decision(ordered, config)
        if decision is not None:
            return decision
        decision = _vae_amplification_precursor_decision(ordered, config)
        if decision is not None:
            return decision
    return LatentDiscontinuityDecision(blocked=False, status="NO_PERSISTENT_ABSOLUTE_DISCONTINUITY")
