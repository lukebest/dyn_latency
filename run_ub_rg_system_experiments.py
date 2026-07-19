#!/usr/bin/env python3
"""Packet-only runner for the system experiments in design document §4.3."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

from dynlat.system_model import (
    Sys1Config,
    Sys2Config,
    Sys3Config,
    simulate_sys1,
    simulate_sys2,
    simulate_sys3,
)


ROOT = Path(__file__).resolve().parent
NS3 = ROOT / "ns-3-ub"
RESULTS_ROOT = ROOT / "results" / "ub_rg_system_packet"
NETWORK_ROOT = RESULTS_ROOT / "network"
SCHEMES = ("packet_spray", "ub_rg")
SCENARIOS = (1, 2, 3)
FULL_EP = {1: 128, 2: 1024, 3: 1024}
REDUCED_EP = {1: 64, 2: 256, 3: 256}
TOPK = 8
SEED = 1
PACKET_TARGET = "ub_rg-packet-experiment"


def _number(value: float) -> str:
    return f"{value:g}"


@dataclass(frozen=True)
class NetworkKey:
    """All inputs that can change one packet-level network measurement."""

    scenario: int
    scheme: str
    mode: str
    batch: int
    zipf_s: float
    ep_size: int
    m_attn: int = 0
    n_ffn: int = 0
    placement: str = "role_packed"
    seed: int = SEED

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError("scenario must be 1, 2, or 3")
        if self.scheme not in SCHEMES:
            raise ValueError(f"scheme must be one of {SCHEMES}")
        if self.mode not in ("dispatch", "combine", "afd_m2n", "afd_n2m"):
            raise ValueError("unsupported packet mode")
        if self.batch <= 0 or self.ep_size <= 0:
            raise ValueError("batch and ep_size must be positive")
        if self.mode.startswith("afd_"):
            if self.m_attn <= 0 or self.n_ffn <= 0:
                raise ValueError("AFD keys require positive M and N")
            if self.m_attn + self.n_ffn != self.ep_size:
                raise ValueError("AFD M+N must equal ep_size")
        elif self.m_attn or self.n_ffn:
            raise ValueError("Wide-EP keys cannot set AFD M or N")

    @property
    def run_id(self) -> str:
        fields = [
            f"s{self.scenario}",
            self.scheme,
            self.mode,
            f"mb{self.batch}",
            f"z{_number(self.zipf_s)}",
            f"ep{self.ep_size}",
        ]
        if self.mode.startswith("afd_"):
            fields.extend(
                (f"M{self.m_attn}", f"N{self.n_ffn}", self.placement)
            )
        fields.append(f"sd{self.seed}")
        return "_".join(fields)

    @property
    def out_dir(self) -> Path:
        return NETWORK_ROOT / self.run_id

    @property
    def summary_path(self) -> Path:
        return self.out_dir / "summary.json"

    @property
    def case_path(self) -> Path:
        return (
            NS3
            / "scratch"
            / "ub_rg_cases"
            / f"s{self.scenario}_n{self.ep_size}"
        )

    def command(
        self, binary: str | os.PathLike[str], out_dir: Path | None = None
    ) -> list[str]:
        destination = self.out_dir if out_dir is None else out_dir
        return [
            str(binary),
            f"--scenario={self.scenario}",
            f"--scheme={self.scheme}",
            f"--mode={self.mode}",
            f"--batch={self.batch}",
            f"--zipf-s={_number(self.zipf_s)}",
            f"--topk={TOPK}",
            f"--ep-size={self.ep_size}",
            f"--seed={self.seed}",
            f"--out-dir={destination}",
            f"--case-path={self.case_path}",
            f"--m-attn={self.m_attn}",
            f"--n-ffn={self.n_ffn}",
            f"--placement={self.placement}",
        ]


@dataclass(frozen=True)
class SystemJob:
    """One system-model point backed exclusively by packet measurements."""

    exp: str
    tier: str
    scenario: int
    scheme: str
    batch: int
    zipf_s: float
    ep_size: int
    layers: int = 60
    microbatches: int = 1
    m_attn: int = 0
    n_ffn: int = 0
    te_profile: str = "hidden"
    placement: str = "role_packed"
    seed: int = SEED

    def __post_init__(self) -> None:
        if self.exp not in ("sys1", "sys2", "sys3"):
            raise ValueError("exp must be sys1, sys2, or sys3")
        if self.tier not in ("main", "controls"):
            raise ValueError("tier must be main or controls")
        if self.scenario not in SCENARIOS or self.scheme not in SCHEMES:
            raise ValueError("invalid scenario or scheme")
        if min(self.batch, self.ep_size, self.layers, self.microbatches) <= 0:
            raise ValueError("batch, ep_size, layers, and microbatches must be positive")
        if self.batch % self.microbatches:
            raise ValueError("batch must be divisible by microbatches")
        if self.exp == "sys1" and self.microbatches != 1:
            raise ValueError("sys1 has exactly one full-batch network transfer")
        if self.exp == "sys3":
            if self.m_attn <= 0 or self.n_ffn <= 0:
                raise ValueError("sys3 requires positive M and N")
            if self.m_attn + self.n_ffn != self.ep_size:
                raise ValueError("sys3 M+N must equal ep_size")
        elif self.m_attn or self.n_ffn:
            raise ValueError("sys1/sys2 cannot set AFD M or N")

    @property
    def mb_batch(self) -> int:
        """Actual per-NPU batch passed to each packet invocation."""

        return self.batch if self.exp == "sys1" else self.batch // self.microbatches

    @property
    def network_keys(self) -> tuple[NetworkKey, NetworkKey]:
        common = {
            "scenario": self.scenario,
            "scheme": self.scheme,
            "batch": self.mb_batch,
            "zipf_s": self.zipf_s,
            "ep_size": self.ep_size,
            "seed": self.seed,
        }
        if self.exp == "sys3":
            afd = {
                **common,
                "m_attn": self.m_attn,
                "n_ffn": self.n_ffn,
                "placement": self.placement,
            }
            return (
                NetworkKey(mode="afd_m2n", **afd),
                NetworkKey(mode="afd_n2m", **afd),
            )
        return (
            NetworkKey(mode="dispatch", **common),
            NetworkKey(mode="combine", **common),
        )

    @property
    def run_id(self) -> str:
        fields = [
            self.exp,
            f"s{self.scenario}",
            self.scheme,
            f"b{self.batch}",
            f"z{_number(self.zipf_s)}",
            f"ep{self.ep_size}",
            f"L{self.layers}",
            f"m{self.microbatches}",
        ]
        if self.exp == "sys3":
            fields.extend(
                (
                    f"M{self.m_attn}",
                    f"N{self.n_ffn}",
                    self.te_profile,
                    self.placement,
                )
            )
        fields.append(f"sd{self.seed}")
        return "_".join(fields)

    @property
    def out_dir(self) -> Path:
        return RESULTS_ROOT / self.exp / self.run_id

    @property
    def summary_path(self) -> Path:
        return self.out_dir / "summary.json"


def _wide_job(
    exp: str,
    tier: str,
    scenario: int,
    scheme: str,
    *,
    batch: int = 256,
    zipf_s: float = 0.5,
    ep_size: int | None = None,
    layers: int = 60,
    microbatches: int = 1,
) -> SystemJob:
    return SystemJob(
        exp=exp,
        tier=tier,
        scenario=scenario,
        scheme=scheme,
        batch=batch,
        zipf_s=zipf_s,
        ep_size=FULL_EP[scenario] if ep_size is None else ep_size,
        layers=layers,
        microbatches=microbatches,
    )


def build_sys1_jobs() -> list[SystemJob]:
    jobs: list[SystemJob] = []
    for scenario in SCENARIOS:
        for scheme in SCHEMES:
            for zipf_s in (0.0, 0.5, 0.9):
                jobs.append(
                    _wide_job("sys1", "main", scenario, scheme, zipf_s=zipf_s)
                )
            for batch in (16, 64):
                jobs.append(
                    _wide_job("sys1", "controls", scenario, scheme, batch=batch)
                )
            jobs.append(
                _wide_job(
                    "sys1",
                    "controls",
                    scenario,
                    scheme,
                    ep_size=REDUCED_EP[scenario],
                )
            )
            for layers in (32, 94):
                jobs.append(
                    _wide_job(
                        "sys1", "controls", scenario, scheme, layers=layers
                    )
                )
    return jobs


def build_sys2_jobs() -> list[SystemJob]:
    jobs: list[SystemJob] = []
    for scenario in SCENARIOS:
        for scheme in SCHEMES:
            for zipf_s in (0.0, 0.5, 0.9):
                jobs.append(
                    _wide_job(
                        "sys2",
                        "main",
                        scenario,
                        scheme,
                        zipf_s=zipf_s,
                        microbatches=2,
                    )
                )
            for microbatches in (1, 4):
                for zipf_s in (0.5, 0.9):
                    jobs.append(
                        _wide_job(
                            "sys2",
                            "controls",
                            scenario,
                            scheme,
                            zipf_s=zipf_s,
                            microbatches=microbatches,
                        )
                    )
    return jobs


def _afd_ratio(scenario: int, ratio: str) -> tuple[int, int]:
    if scenario == 1:
        return {
            "7:1": (112, 16),
            "1:1": (64, 64),
            "31:1": (124, 4),
        }[ratio]
    return {
        "7:1": (896, 128),
        "1:1": (512, 512),
        "31:1": (992, 32),
    }[ratio]


def _main_placement(scenario: int) -> str:
    return "plane_striped" if scenario == 3 else "role_packed"


def _afd_job(
    tier: str,
    scenario: int,
    scheme: str,
    *,
    ratio: str = "7:1",
    zipf_s: float = 0.5,
    microbatches: int = 2,
    te_profile: str = "hidden",
    placement: str | None = None,
) -> SystemJob:
    m_attn, n_ffn = _afd_ratio(scenario, ratio)
    return SystemJob(
        exp="sys3",
        tier=tier,
        scenario=scenario,
        scheme=scheme,
        batch=256,
        zipf_s=zipf_s,
        ep_size=m_attn + n_ffn,
        layers=60,
        microbatches=microbatches,
        m_attn=m_attn,
        n_ffn=n_ffn,
        te_profile=te_profile,
        placement=_main_placement(scenario) if placement is None else placement,
    )


def build_sys3_jobs() -> list[SystemJob]:
    jobs: list[SystemJob] = []
    for scenario in SCENARIOS:
        for scheme in SCHEMES:
            for zipf_s in (0.0, 0.5, 1.0):
                jobs.append(
                    _afd_job(
                        "main", scenario, scheme, ratio="7:1", zipf_s=zipf_s
                    )
                )
            jobs.append(
                _afd_job("controls", scenario, scheme, ratio="1:1")
            )
            jobs.append(
                _afd_job(
                    "controls",
                    scenario,
                    scheme,
                    ratio="31:1",
                    te_profile="exposed",
                )
            )
            for microbatches in (1, 4):
                jobs.append(
                    _afd_job(
                        "controls",
                        scenario,
                        scheme,
                        ratio="7:1",
                        microbatches=microbatches,
                    )
                )
            if scenario == 3:
                jobs.append(
                    _afd_job(
                        "controls",
                        scenario,
                        scheme,
                        ratio="7:1",
                        placement="role_packed",
                    )
                )
    return jobs


def build_plan(
    tier: str = "all",
    exp: str | None = None,
    scenario: int | None = None,
) -> list[SystemJob]:
    """Build the exact main/control matrix, then apply optional filters."""

    if tier not in ("main", "controls", "all"):
        raise ValueError("tier must be main, controls, or all")
    if exp not in (None, "sys1", "sys2", "sys3"):
        raise ValueError("exp must be sys1, sys2, or sys3")
    if scenario not in (None, 1, 2, 3):
        raise ValueError("scenario must be 1, 2, or 3")

    builders = {
        "sys1": build_sys1_jobs,
        "sys2": build_sys2_jobs,
        "sys3": build_sys3_jobs,
    }
    selected = builders if exp is None else {exp: builders[exp]}
    jobs = [job for builder in selected.values() for job in builder()]
    if tier != "all":
        jobs = [job for job in jobs if job.tier == tier]
    if scenario is not None:
        jobs = [job for job in jobs if job.scenario == scenario]
    return jobs


def network_plan(jobs: Iterable[SystemJob]) -> list[NetworkKey]:
    """Return stable, de-duplicated packet measurements for system jobs."""

    keys = {key for job in jobs for key in job.network_keys}
    return sorted(
        keys,
        key=lambda key: (
            key.scenario,
            key.scheme,
            key.mode,
            key.ep_size,
            key.batch,
            key.zipf_s,
            key.m_attn,
            key.n_ffn,
            key.placement,
            key.seed,
        ),
    )


def find_binary(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Find a release/debug/default/optimized packet binary or fail clearly."""

    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"packet binary does not exist: {candidate}")

    build = NS3 / "build" / "scratch"
    # ns-3 release builds use the unsuffixed name. Prefer optimized binaries
    # over debug/sanitizer artifacts left by diagnostics.
    suffixes = ("release", "optimized", "default", "debug")
    names = [f"ns3.44-{PACKET_TARGET}"] + [
        f"ns3.44-{PACKET_TARGET}-{suffix}" for suffix in suffixes
    ]
    for name in names:
        candidate = build / name
        if candidate.is_file():
            return candidate.resolve()

    # Also support another ns-3 version while keeping deterministic suffix order.
    if build.is_dir():
        for suffix in (*suffixes, ""):
            ending = f"-{suffix}" if suffix else ""
            matches = sorted(build.glob(f"ns3.*-{PACKET_TARGET}{ending}"))
            if matches:
                return matches[0].resolve()
    searched = ", ".join(str(build / name) for name in names)
    raise FileNotFoundError(
        "packet binary not found. Build it with "
        f"`cd {NS3} && ./ns3 build {PACKET_TARGET}`. Looked for: {searched}"
    )


def ensure_cases(keys: Sequence[NetworkKey]) -> list[list[str]]:
    """Generate every selected topology case that is currently missing."""

    generated: list[list[str]] = []
    generator = ROOT / "gen_ub_rg_topo.py"
    case_specs = sorted({(key.scenario, key.ep_size, key.case_path) for key in keys})
    for scenario, ep_size, case_path in case_specs:
        markers = (
            case_path / "node.csv",
            case_path / "topology.csv",
            case_path / "routing_table.csv",
            case_path / "network_attribute.txt",
        )
        if all(marker.is_file() for marker in markers):
            continue
        command = [
            sys.executable,
            str(generator),
            "--scenario",
            str(scenario),
            "--ep-size",
            str(ep_size),
            "--out",
            str(case_path),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        generated.append(command)
    return generated


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_packet_summary(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    if str(data.get("engine", "")).lower() != "packet":
        raise ValueError(f"{path} is not a packet-engine summary")
    return data


def _run_network_key(
    key: NetworkKey, binary: str, force: bool, timeout_s: int = 0
) -> dict[str, Any]:
    command = key.command(binary)
    record: dict[str, Any] = {
        "network_key": asdict(key),
        "run_id": key.run_id,
        "command": command,
        "elapsed_s": 0.0,
        "error": None,
        "summary": str(key.summary_path),
    }
    if key.summary_path.is_file() and not force:
        try:
            _load_packet_summary(key.summary_path)
            record["status"] = "skipped"
            return record
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    key.out_dir.mkdir(parents=True, exist_ok=True)
    timeout = timeout_s or (14_400 if key.scenario >= 2 else 3_600)
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            cwd=NS3,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        record["elapsed_s"] = time.monotonic() - started
        if process.returncode != 0:
            raise RuntimeError(
                f"packet command returned {process.returncode}: "
                f"{(process.stderr or '')[-2000:]}"
            )
        if not key.summary_path.is_file():
            raise RuntimeError("packet command did not produce summary.json")
        _load_packet_summary(key.summary_path)
        record["status"] = "completed"
    except subprocess.TimeoutExpired as exc:
        record["elapsed_s"] = time.monotonic() - started
        record["status"] = "failed"
        record["error"] = f"timeout after {timeout}s"
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        record["stdout_tail"] = stdout[-4000:]
        record["stderr_tail"] = stderr[-2000:]
    except Exception as exc:  # noqa: BLE001 - preserve each worker failure in ledger
        record["elapsed_s"] = time.monotonic() - started
        record["status"] = "failed"
        record["error"] = str(exc)
    return record


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(_jsonable(value), stream, indent=2, sort_keys=True)
        stream.write("\n")
    temporary.replace(path)


def _required_float(summary: dict[str, Any], name: str, source: Path) -> float:
    try:
        value = float(summary[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{source} has no numeric {name}") from exc
    if value < 0:
        raise ValueError(f"{source} has negative {name}")
    return value


def _p99(summary: dict[str, Any], source: Path) -> float:
    try:
        value = float(summary["latency_all"]["p99_us"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{source} has no numeric latency_all.p99_us") from exc
    if value < 0:
        raise ValueError(f"{source} has negative latency_all.p99_us")
    return value


def synthesize_system_job(job: SystemJob, force: bool = False) -> str:
    """Run the pure system model from cached packet summaries."""

    if job.summary_path.is_file() and not force:
        _load_json(job.summary_path)
        return "skipped"

    first_key, second_key = job.network_keys
    first = _load_packet_summary(first_key.summary_path)
    second = _load_packet_summary(second_key.summary_path)
    network_inputs: dict[str, Any]

    if job.exp == "sys1":
        dispatch_us = _required_float(first, "cct_us", first_key.summary_path)
        combine_us = _required_float(second, "cct_us", second_key.summary_path)
        result = simulate_sys1(
            Sys1Config(
                layers=job.layers,
                batch_size=job.batch,
                dispatch_us=dispatch_us,
                combine_us=combine_us,
                seed=job.seed,
            )
        )
        network_inputs = {
            "dispatch_cct_us": dispatch_us,
            "combine_cct_us": combine_us,
        }
    elif job.exp == "sys2":
        dispatch_us = _required_float(first, "cct_us", first_key.summary_path)
        combine_us = _required_float(second, "cct_us", second_key.summary_path)
        result = simulate_sys2(
            Sys2Config(
                layers=job.layers,
                microbatches=job.microbatches,
                batch_size=job.batch,
                dispatch_us=dispatch_us,
                combine_us=combine_us,
                seed=job.seed,
            )
        )
        network_inputs = {
            "dispatch_cct_us": dispatch_us,
            "combine_cct_us": combine_us,
        }
    else:
        m2n_p99_us = _p99(first, first_key.summary_path)
        n2m_p99_us = _p99(second, second_key.summary_path)
        tc_us = max(m2n_p99_us, n2m_p99_us)
        result = simulate_sys3(
            Sys3Config(
                layers=job.layers,
                microbatches=job.microbatches,
                batch_size=job.batch,
                attention_devices=job.m_attn,
                ffn_devices=job.n_ffn,
                tc_us=tc_us,
                te_profile=job.te_profile,
                seed=job.seed,
            )
        )
        network_inputs = {
            "m2n_p99_us": m2n_p99_us,
            "n2m_p99_us": n2m_p99_us,
            "tc_us": tc_us,
            "tc_definition": "max(m2n_p99_us,n2m_p99_us)",
        }

    model = _jsonable(result)
    summary = {
        "run_id": job.run_id,
        "experiment": job.exp,
        "tier": job.tier,
        "engine": "packet",
        "job": asdict(job),
        "network_inputs": network_inputs,
        "network_runs": [
            {
                "run_id": key.run_id,
                "summary": str(key.summary_path),
                "key": asdict(key),
            }
            for key in job.network_keys
        ],
        "step_time_us": model["step_time_us"],
        "per_device_throughput_tokens_s": model[
            "per_device_throughput_tokens_s"
        ],
        "model": model,
    }
    if job.exp == "sys3":
        summary["cluster_throughput_tokens_s"] = model[
            "cluster_throughput_tokens_s"
        ]
    _write_json(job.summary_path, summary)
    return "completed"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("main", "controls", "all"), default="all")
    parser.add_argument("--exp", choices=("sys1", "sys2", "sys3"), default=None)
    parser.add_argument("--scenario", type=int, choices=SCENARIOS, default=None)
    parser.add_argument("--workers", type=int, default=0, help="0 selects a safe default")
    parser.add_argument("--limit", type=int, default=0, help="limit system jobs after filtering")
    parser.add_argument("--force", action="store_true", help="rerun packet and system outputs")
    parser.add_argument("--binary", default=None, help="explicit packet binary path")
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=0,
        help="per-packet-run wall timeout; 0 uses scenario defaults",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the exact plan only")
    return parser


def _dry_run_payload(
    jobs: Sequence[SystemJob], keys: Sequence[NetworkKey], binary: Path
) -> dict[str, Any]:
    return {
        "system_jobs": len(jobs),
        "network_runs": len(keys),
        "jobs": [
            {
                "run_id": job.run_id,
                "job": asdict(job),
                "network_run_ids": [key.run_id for key in job.network_keys],
            }
            for job in jobs
        ],
        "commands": [
            {"run_id": key.run_id, "command": key.command(binary)} for key in keys
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.workers < 0:
        raise SystemExit("--workers must be non-negative")
    if args.limit < 0:
        raise SystemExit("--limit must be non-negative")
    if args.timeout_s < 0:
        raise SystemExit("--timeout-s must be non-negative")

    jobs = build_plan(args.tier, args.exp, args.scenario)
    if args.limit:
        jobs = jobs[: args.limit]
    keys = network_plan(jobs)
    try:
        binary = find_binary(args.binary)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(_dry_run_payload(jobs, keys, binary), indent=2))
        return 0

    try:
        generated = ensure_cases(keys)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"error: failed to generate packet topology case: {exc}", file=sys.stderr)
        return 1

    workers = args.workers or min(4, max(1, os.cpu_count() or 1))
    started = time.monotonic()
    records: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _run_network_key, key, str(binary), args.force, args.timeout_s
            ): key
            for key in keys
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                record = future.result()
            except Exception as exc:  # noqa: BLE001 - account for worker crashes
                record = {
                    "network_key": asdict(key),
                    "run_id": key.run_id,
                    "command": key.command(binary),
                    "elapsed_s": 0.0,
                    "error": str(exc),
                    "summary": str(key.summary_path),
                    "status": "failed",
                }
            records.append(record)
            print(
                f"[{record['status']}] {key.run_id} "
                f"{record['elapsed_s']:.2f}s"
            )

    records.sort(key=lambda record: record["run_id"])
    available = {
        record["run_id"]
        for record in records
        if record["status"] in ("completed", "skipped")
    }
    system_records: list[dict[str, Any]] = []
    for job in jobs:
        record = {
            "run_id": job.run_id,
            "experiment": job.exp,
            "summary": str(job.summary_path),
            "error": None,
        }
        missing = [key.run_id for key in job.network_keys if key.run_id not in available]
        if missing:
            record["status"] = "failed"
            record["error"] = f"network inputs failed: {', '.join(missing)}"
        else:
            try:
                record["status"] = synthesize_system_job(job, force=args.force)
            except Exception as exc:  # noqa: BLE001 - preserve model failure in ledger
                record["status"] = "failed"
                record["error"] = str(exc)
        system_records.append(record)

    counts = {
        state: sum(record["status"] == state for record in records)
        for state in ("completed", "failed", "skipped")
    }
    system_counts = {
        state: sum(record["status"] == state for record in system_records)
        for state in ("completed", "failed", "skipped")
    }
    ledger = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "packet_only": True,
        "filters": {
            "tier": args.tier,
            "exp": args.exp,
            "scenario": args.scenario,
            "limit": args.limit,
            "force": args.force,
            "timeout_s": args.timeout_s,
        },
        "binary": str(binary),
        "planned": len(keys),
        **counts,
        "system_planned": len(jobs),
        "system_completed": system_counts["completed"],
        "system_failed": system_counts["failed"],
        "system_skipped": system_counts["skipped"],
        "elapsed_s": time.monotonic() - started,
        "generated_case_commands": generated,
        "network_runs": records,
        "system_runs": system_records,
    }
    ledger_path = RESULTS_ROOT / "ledger.json"
    _write_json(ledger_path, ledger)
    print(
        f"network planned={len(keys)} completed={counts['completed']} "
        f"failed={counts['failed']} skipped={counts['skipped']}; "
        f"system completed={system_counts['completed']} "
        f"failed={system_counts['failed']} skipped={system_counts['skipped']}; "
        f"ledger={ledger_path}"
    )
    return 2 if counts["failed"] or system_counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
