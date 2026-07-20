"""Pure-Python orchestration models for the experiments in docs §4.3.

This module does not model packets or a network.  Dispatch/combine durations
are inputs, normally CCT/P99 values measured by the packet-level ns-3 runs.
All durations are microseconds and all throughput values are tokens/second.
"""
from __future__ import annotations

import heapq
import math
import random
from collections import deque
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from typing import Sequence, TypeAlias


DurationSpec: TypeAlias = (
    Real | Sequence[Real] | Sequence[Sequence[Real]] | None
)


@dataclass(frozen=True)
class Sys1Config:
    """Configuration for serial Wide-EP (system experiment 1).

    A scalar duration is reused everywhere.  A flat sequence supplies one
    value per layer.  ``ta_us`` and ``te_us`` are independently sampled from
    the configured uniform distribution when omitted.
    """

    layers: int = 60
    batch_size: int = 16
    ta_us: DurationSpec = None
    te_us: DurationSpec = None
    dispatch_us: DurationSpec = 0.0
    combine_us: DurationSpec = 0.0
    seed: int = 0
    uniform_low_us: float = 75.0
    uniform_high_us: float = 90.0

    def __post_init__(self) -> None:
        _validate_common_config(
            self.layers,
            self.batch_size,
            self.uniform_low_us,
            self.uniform_high_us,
        )


@dataclass(frozen=True)
class Sys1LayerResult:
    layer: int
    start_us: float
    ta_us: float
    dispatch_us: float
    te_us: float
    combine_us: float
    end_us: float

    @property
    def duration_us(self) -> float:
        return self.end_us - self.start_us


@dataclass(frozen=True)
class Sys1Result:
    config: Sys1Config
    layer_results: tuple[Sys1LayerResult, ...]
    step_time_us: float
    per_device_throughput_tokens_s: float


@dataclass(frozen=True)
class Sys2Config:
    """Configuration for dual-resource Wide-EP TBO (experiment 2).

    Nested duration sequences have shape ``[layers][microbatches]``.  A flat
    per-layer sequence is broadcast over microbatches; a flat sequence of
    length ``layers * microbatches`` is interpreted in layer-major order.
    """

    layers: int = 60
    microbatches: int = 2
    batch_size: int = 16
    ta_us: DurationSpec = None
    te_us: DurationSpec = None
    dispatch_us: DurationSpec = 0.0
    combine_us: DurationSpec = 0.0
    seed: int = 0
    uniform_low_us: float = 75.0
    uniform_high_us: float = 90.0

    def __post_init__(self) -> None:
        _validate_common_config(
            self.layers,
            self.batch_size,
            self.uniform_low_us,
            self.uniform_high_us,
        )
        _require_positive_int("microbatches", self.microbatches)
        if self.batch_size % self.microbatches:
            raise ValueError("batch_size must be divisible by microbatches")


@dataclass(frozen=True)
class TBOEvent:
    """One scheduled operation on the compute or communication resource."""

    layer: int
    microbatch: int
    stage: str
    resource: str
    start_us: float
    end_us: float

    @property
    def duration_us(self) -> float:
        return self.end_us - self.start_us


@dataclass(frozen=True)
class Sys2Result:
    config: Sys2Config
    events: tuple[TBOEvent, ...]
    step_time_us: float
    per_device_throughput_tokens_s: float
    compute_busy_us: float
    communication_busy_us: float
    compute_utilization: float
    communication_utilization: float


class AFDTeProfile(str, Enum):
    """AFD FFN calibration profiles from §4.3.3.4."""

    HIDDEN = "hidden"
    BALANCE = "balance"
    EXPOSED = "exposed"


_AFD_TE_RATIOS = {
    AFDTeProfile.HIDDEN: 0.7,
    AFDTeProfile.BALANCE: 1.0,
    AFDTeProfile.EXPOSED: 1.3,
}


@dataclass(frozen=True)
class Sys3Config:
    """Configuration for the ideal AFD pipeline (experiment 3).

    ``batch_size`` is the global batch resident on each Attention device.
    ``tc_us`` is a *single-direction* M2N/N2M CCT supplied by ns-3.
    """

    layers: int = 60
    microbatches: int = 2
    batch_size: int = 16
    attention_devices: int = 112
    ffn_devices: int = 16
    ta_us: float | None = None
    tc_us: float = 0.0
    te_profile: AFDTeProfile | str = AFDTeProfile.HIDDEN
    seed: int = 0
    uniform_low_us: float = 75.0
    uniform_high_us: float = 90.0

    def __post_init__(self) -> None:
        _validate_common_config(
            self.layers,
            self.batch_size,
            self.uniform_low_us,
            self.uniform_high_us,
        )
        _require_positive_int("microbatches", self.microbatches)
        _require_positive_int("attention_devices", self.attention_devices)
        _require_positive_int("ffn_devices", self.ffn_devices)
        if self.batch_size % self.microbatches:
            raise ValueError("batch_size must be divisible by microbatches")
        if self.ta_us is not None:
            _duration("ta_us", self.ta_us)
        _duration("tc_us", self.tc_us)
        _normalize_profile(self.te_profile)


@dataclass(frozen=True)
class AFDMaskingResult:
    """Boolean evaluations of the three masking conditions in §4.3.3.2."""

    ffn_not_exposed: bool
    single_direction_hidden: bool
    bidirectional_hidden: bool
    fully_hidden: bool


@dataclass(frozen=True)
class Sys3Result:
    config: Sys3Config
    te_profile: AFDTeProfile
    ta_us: float
    te_us: float
    tc_us: float
    tf_us: float
    startup_us: float
    steady_state_us: float
    step_time_us: float
    masking: AFDMaskingResult
    cluster_throughput_tokens_s: float
    per_device_throughput_tokens_s: float


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_common_config(
    layers: int,
    batch_size: int,
    uniform_low_us: float,
    uniform_high_us: float,
) -> None:
    _require_positive_int("layers", layers)
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 0:
        raise ValueError("batch_size must be a non-negative integer")
    low = _duration("uniform_low_us", uniform_low_us)
    high = _duration("uniform_high_us", uniform_high_us)
    if low > high:
        raise ValueError("uniform_low_us must not exceed uniform_high_us")


def _duration(name: str, value: Real) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must contain real-valued durations")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} durations must be finite and non-negative")
    return result


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _duration_matrix(
    spec: DurationSpec,
    layers: int,
    microbatches: int,
    name: str,
) -> tuple[tuple[float, ...], ...]:
    if spec is None:
        raise ValueError(f"{name} has no explicit duration")
    if isinstance(spec, Real) and not isinstance(spec, bool):
        value = _duration(name, spec)
        return tuple(tuple(value for _ in range(microbatches)) for _ in range(layers))
    if not _is_sequence(spec):
        raise TypeError(f"{name} must be a duration or duration sequence")

    values = list(spec)
    if len(values) == layers and any(_is_sequence(value) for value in values):
        rows: list[tuple[float, ...]] = []
        for layer, row in enumerate(values):
            if not _is_sequence(row):
                raise ValueError(f"{name}[{layer}] must be a sequence")
            row_values = list(row)
            if len(row_values) != microbatches:
                raise ValueError(
                    f"{name}[{layer}] must contain {microbatches} microbatch values"
                )
            rows.append(
                tuple(_duration(f"{name}[{layer}]", value) for value in row_values)
            )
        return tuple(rows)
    if any(_is_sequence(value) for value in values):
        raise ValueError(f"{name} nested input must have shape [{layers}][{microbatches}]")

    flat = tuple(_duration(name, value) for value in values)
    if len(flat) == layers:
        return tuple(tuple(flat[layer] for _ in range(microbatches)) for layer in range(layers))
    if len(flat) == layers * microbatches:
        return tuple(
            flat[layer * microbatches : (layer + 1) * microbatches]
            for layer in range(layers)
        )
    raise ValueError(
        f"{name} must contain {layers} per-layer or "
        f"{layers * microbatches} per-microbatch values"
    )


def _compute_matrices(
    ta_spec: DurationSpec,
    te_spec: DurationSpec,
    layers: int,
    microbatches: int,
    seed: int,
    low_us: float,
    high_us: float,
) -> tuple[tuple[tuple[float, ...], ...], tuple[tuple[float, ...], ...]]:
    ta = None if ta_spec is None else _duration_matrix(ta_spec, layers, microbatches, "ta_us")
    te = None if te_spec is None else _duration_matrix(te_spec, layers, microbatches, "te_us")
    if ta is not None and te is not None:
        return ta, te

    rng = random.Random(seed)
    sampled_ta = [[0.0] * microbatches for _ in range(layers)]
    sampled_te = [[0.0] * microbatches for _ in range(layers)]
    for layer in range(layers):
        for microbatch in range(microbatches):
            sampled_ta[layer][microbatch] = (
                rng.uniform(low_us, high_us)
                if ta is None
                else ta[layer][microbatch]
            )
            sampled_te[layer][microbatch] = (
                rng.uniform(low_us, high_us)
                if te is None
                else te[layer][microbatch]
            )
    return (
        tuple(tuple(row) for row in sampled_ta),
        tuple(tuple(row) for row in sampled_te),
    )


def _throughput(tokens: float, step_time_us: float) -> float:
    if tokens == 0.0:
        return 0.0
    if step_time_us == 0.0:
        return math.inf
    return tokens * 1_000_000.0 / step_time_us


def simulate_sys1(config: Sys1Config) -> Sys1Result:
    """Run the strict ``Attn -> Dispatch -> FFN -> Combine`` serial model."""

    ta, te = _compute_matrices(
        config.ta_us,
        config.te_us,
        config.layers,
        1,
        config.seed,
        config.uniform_low_us,
        config.uniform_high_us,
    )
    dispatch = _duration_matrix(config.dispatch_us, config.layers, 1, "dispatch_us")
    combine = _duration_matrix(config.combine_us, config.layers, 1, "combine_us")

    now = 0.0
    layer_results: list[Sys1LayerResult] = []
    for layer in range(config.layers):
        start = now
        now += ta[layer][0] + dispatch[layer][0] + te[layer][0] + combine[layer][0]
        layer_results.append(
            Sys1LayerResult(
                layer=layer,
                start_us=start,
                ta_us=ta[layer][0],
                dispatch_us=dispatch[layer][0],
                te_us=te[layer][0],
                combine_us=combine[layer][0],
                end_us=now,
            )
        )
    return Sys1Result(
        config=config,
        layer_results=tuple(layer_results),
        step_time_us=now,
        per_device_throughput_tokens_s=_throughput(config.batch_size, now),
    )


_STAGES = ("attention", "dispatch", "expert", "combine")
_RESOURCES = ("compute", "communication", "compute", "communication")


def simulate_sys2(config: Sys2Config) -> Sys2Result:
    """Run deterministic FIFO event scheduling on compute and comm resources.

    Dependencies are retained per microbatch and per layer.  Independent
    microbatches can overlap when they occupy different resources.
    """

    ta, te = _compute_matrices(
        config.ta_us,
        config.te_us,
        config.layers,
        config.microbatches,
        config.seed,
        config.uniform_low_us,
        config.uniform_high_us,
    )
    dispatch = _duration_matrix(
        config.dispatch_us, config.layers, config.microbatches, "dispatch_us"
    )
    combine = _duration_matrix(
        config.combine_us, config.layers, config.microbatches, "combine_us"
    )
    durations = (ta, dispatch, te, combine)

    # Queue entries are (layer, microbatch, stage_index).  FIFO order is the
    # deterministic TBO arbitration rule for each of the two resources.
    queues: dict[str, deque[tuple[int, int, int]]] = {
        "compute": deque((0, mb, 0) for mb in range(config.microbatches)),
        "communication": deque(),
    }
    busy = {"compute": False, "communication": False}
    completions: list[tuple[float, int, str, int, int, int, TBOEvent]] = []
    scheduled: list[tuple[int, TBOEvent]] = []
    sequence = 0

    def start_one(resource: str, now_us: float) -> None:
        nonlocal sequence
        if busy[resource] or not queues[resource]:
            return
        layer, microbatch, stage_index = queues[resource].popleft()
        duration_us = durations[stage_index][layer][microbatch]
        event = TBOEvent(
            layer=layer,
            microbatch=microbatch,
            stage=_STAGES[stage_index],
            resource=resource,
            start_us=now_us,
            end_us=now_us + duration_us,
        )
        event_sequence = sequence
        sequence += 1
        scheduled.append((event_sequence, event))
        busy[resource] = True
        heapq.heappush(
            completions,
            (
                event.end_us,
                event_sequence,
                resource,
                layer,
                microbatch,
                stage_index,
                event,
            ),
        )

    start_one("compute", 0.0)
    completed = 0
    expected = config.layers * config.microbatches * len(_STAGES)
    while completions:
        now = completions[0][0]
        same_time = []
        while completions and completions[0][0] == now:
            same_time.append(heapq.heappop(completions))

        for _, _, resource, layer, microbatch, stage_index, _ in same_time:
            busy[resource] = False
            completed += 1
            if stage_index < len(_STAGES) - 1:
                next_stage = stage_index + 1
                queues[_RESOURCES[next_stage]].append((layer, microbatch, next_stage))
            elif layer + 1 < config.layers:
                queues["compute"].append((layer + 1, microbatch, 0))

        start_one("compute", now)
        start_one("communication", now)

    if completed != expected:
        raise RuntimeError(f"TBO scheduler stalled after {completed}/{expected} operations")

    ordered_events = tuple(event for _, event in sorted(scheduled))
    step_time_us = max((event.end_us for event in ordered_events), default=0.0)
    compute_busy_us = sum(
        event.duration_us for event in ordered_events if event.resource == "compute"
    )
    communication_busy_us = sum(
        event.duration_us
        for event in ordered_events
        if event.resource == "communication"
    )
    if step_time_us:
        compute_utilization = compute_busy_us / step_time_us
        communication_utilization = communication_busy_us / step_time_us
    else:
        compute_utilization = 0.0
        communication_utilization = 0.0
    return Sys2Result(
        config=config,
        events=ordered_events,
        step_time_us=step_time_us,
        per_device_throughput_tokens_s=_throughput(config.batch_size, step_time_us),
        compute_busy_us=compute_busy_us,
        communication_busy_us=communication_busy_us,
        compute_utilization=compute_utilization,
        communication_utilization=communication_utilization,
    )


def _normalize_profile(profile: AFDTeProfile | str) -> AFDTeProfile:
    if isinstance(profile, AFDTeProfile):
        return profile
    if not isinstance(profile, str):
        raise TypeError("te_profile must be hidden, balance, or exposed")
    normalized = profile.strip().lower().replace("_ffn", "").replace("-ffn", "")
    try:
        return AFDTeProfile(normalized)
    except ValueError as exc:
        raise ValueError("te_profile must be hidden, balance, or exposed") from exc


def afd_ideal_step_time_us(
    ta_us: float,
    te_us: float,
    tc_us: float,
    layers: int,
    microbatches: int,
) -> float:
    """Return ``(Ta + Te + 2Tc) + max(Ta,Te) * (mL - 1)`` in µs."""

    ta = _duration("ta_us", ta_us)
    te = _duration("te_us", te_us)
    tc = _duration("tc_us", tc_us)
    _require_positive_int("layers", layers)
    _require_positive_int("microbatches", microbatches)
    return ta + te + 2.0 * tc + max(ta, te) * (microbatches * layers - 1)


def afd_masking_conditions(
    ta_us: float,
    te_us: float,
    tc_us: float,
    microbatches: int,
) -> AFDMaskingResult:
    """Evaluate FFN, one-way, and two-way masking conditions from §4.3.3."""

    ta = _duration("ta_us", ta_us)
    te = _duration("te_us", te_us)
    tc = _duration("tc_us", tc_us)
    _require_positive_int("microbatches", microbatches)
    tf = max(ta, te)
    ffn_not_exposed = te <= ta
    single_direction_hidden = tc < tf
    bidirectional_hidden = microbatches * tf >= 2.0 * (tf + tc)
    return AFDMaskingResult(
        ffn_not_exposed=ffn_not_exposed,
        single_direction_hidden=single_direction_hidden,
        bidirectional_hidden=bidirectional_hidden,
        fully_hidden=(
            ffn_not_exposed
            and single_direction_hidden
            and bidirectional_hidden
        ),
    )


def fastafd_per_device_throughput(
    batch_size: int,
    attention_devices: int,
    ffn_devices: int,
    step_time_us: float,
) -> float:
    """FastAFD throughput ``M*B / ((M+N)*Tstep)`` in tokens/s/device."""

    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 0:
        raise ValueError("batch_size must be a non-negative integer")
    _require_positive_int("attention_devices", attention_devices)
    _require_positive_int("ffn_devices", ffn_devices)
    step = _duration("step_time_us", step_time_us)
    tokens_per_device = attention_devices * batch_size / (
        attention_devices + ffn_devices
    )
    return _throughput(tokens_per_device, step)


def simulate_sys3(config: Sys3Config) -> Sys3Result:
    """Evaluate the ideal AFD formula, masking conditions, and throughput."""

    profile = _normalize_profile(config.te_profile)
    ta_us = (
        random.Random(config.seed).uniform(
            config.uniform_low_us, config.uniform_high_us
        )
        if config.ta_us is None
        else _duration("ta_us", config.ta_us)
    )
    tc_us = _duration("tc_us", config.tc_us)
    te_us = _AFD_TE_RATIOS[profile] * ta_us
    tf_us = max(ta_us, te_us)
    startup_us = ta_us + te_us + 2.0 * tc_us
    steady_state_us = tf_us * (config.microbatches * config.layers - 1)
    step_time_us = afd_ideal_step_time_us(
        ta_us, te_us, tc_us, config.layers, config.microbatches
    )
    masking = afd_masking_conditions(
        ta_us, te_us, tc_us, config.microbatches
    )
    cluster_throughput = _throughput(
        config.attention_devices * config.batch_size, step_time_us
    )
    per_device_throughput = fastafd_per_device_throughput(
        config.batch_size,
        config.attention_devices,
        config.ffn_devices,
        step_time_us,
    )
    return Sys3Result(
        config=config,
        te_profile=profile,
        ta_us=ta_us,
        te_us=te_us,
        tc_us=tc_us,
        tf_us=tf_us,
        startup_us=startup_us,
        steady_state_us=steady_state_us,
        step_time_us=step_time_us,
        masking=masking,
        cluster_throughput_tokens_s=cluster_throughput,
        per_device_throughput_tokens_s=per_device_throughput,
    )


# Semantic and short aliases keep call sites readable in analyses.
SerialConfig = Sys1Config
SerialResult = Sys1Result
TBOConfig = Sys2Config
TBOResult = Sys2Result
AFDConfig = Sys3Config
AFDResult = Sys3Result
simulate_serial = simulate_sys1
simulate_tbo = simulate_sys2
simulate_afd = simulate_sys3
run_sys1 = simulate_sys1
run_sys2 = simulate_sys2
run_sys3 = simulate_sys3


__all__ = [
    "AFDConfig",
    "AFDMaskingResult",
    "AFDResult",
    "AFDTeProfile",
    "SerialConfig",
    "SerialResult",
    "Sys1Config",
    "Sys1LayerResult",
    "Sys1Result",
    "Sys2Config",
    "Sys2Result",
    "Sys3Config",
    "Sys3Result",
    "TBOConfig",
    "TBOEvent",
    "TBOResult",
    "afd_ideal_step_time_us",
    "afd_masking_conditions",
    "fastafd_per_device_throughput",
    "run_sys1",
    "run_sys2",
    "run_sys3",
    "simulate_afd",
    "simulate_serial",
    "simulate_sys1",
    "simulate_sys2",
    "simulate_sys3",
    "simulate_tbo",
]
