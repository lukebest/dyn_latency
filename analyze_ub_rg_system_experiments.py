#!/usr/bin/env python3
"""Analyze packet-backed UB_RG system experiments without pandas or scipy.

The analyzer treats the packet simulator summaries as evidence and never
substitutes behavioral results.  Missing cells remain visible in the report
and in placeholder figures.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS = ROOT / "results" / "ub_rg_system_packet"
DEFAULT_REPORT_MD = ROOT / "docs" / "UB_RG系统实验0719报告.md"
DEFAULT_FIGURES = ROOT / "docs" / "ub_rg_system_figures"

EXPERIMENTS = ("sys1", "sys2", "sys3")
CANONICAL_COLUMNS = (
    "experiment",
    "run_id",
    "summary_path",
    "engine",
    "network_engine",
    "status",
    "tier",
    "scenario",
    "scheme",
    "batch_size",
    "zipf_s",
    "ep_size",
    "layers",
    "microbatches",
    "attention_devices",
    "ffn_devices",
    "m_to_n",
    "placement",
    "te_profile",
    "step_time_us",
    "throughput_tokens_s",
    "baseline_step_time_us",
    "speedup",
    "tc_us",
    "dispatch_us",
    "combine_us",
    "mask_value",
    "mask_label",
)


@dataclass(frozen=True)
class Issue:
    kind: str
    run_id: str
    experiment: str
    message: str
    source: str


@dataclass(frozen=True)
class AnalysisOutputs:
    report_md: Path
    report_html: Path
    figures_dir: Path
    csv_path: Path
    summary_count: int
    issue_count: int


def _nested_get(data: Mapping[str, Any], dotted: str) -> Any:
    value: Any = data
    for component in dotted.split("."):
        if not isinstance(value, Mapping) or component not in value:
            return None
        value = value[component]
    return value


def _recursive_values(data: Any, names: set[str]) -> list[Any]:
    values: list[Any] = []
    if isinstance(data, Mapping):
        for key, value in data.items():
            if str(key).lower() in names:
                values.append(value)
            values.extend(_recursive_values(value, names))
    elif isinstance(data, list):
        for value in data:
            values.extend(_recursive_values(value, names))
    return values


def _pick(data: Mapping[str, Any], paths: Sequence[str], aliases: Sequence[str] = ()) -> Any:
    for path in paths:
        value = _nested_get(data, path)
        if value is not None:
            return value
    if aliases:
        for value in _recursive_values(data, {alias.lower() for alias in aliases}):
            if value is not None:
                return value
    return None


def _number(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    if result.is_integer():
        return int(result)
    return result


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "pass", "passed", "hidden", "success"}:
            return True
        if normalized in {"false", "no", "fail", "failed", "exposed"}:
            return False
    return None


def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(data, Mapping):
        for key, value in data.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            flat.update(_flatten(value, child))
    elif isinstance(data, list):
        # Event timelines can contain tens of thousands of objects.  Keep the
        # row-oriented CSV compact; canonical metrics and evidence paths are
        # extracted separately.
        if any(isinstance(value, (Mapping, list)) for value in data):
            flat[f"{prefix}._count"] = len(data)
        else:
            flat[prefix] = json.dumps(data, ensure_ascii=False, sort_keys=True)
    else:
        flat[prefix] = data
    return flat


def _display(value: Any, digits: int = 3) -> str:
    if value is None or value == "":
        return "缺失"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _engine_markers(data: Any) -> list[tuple[str, str]]:
    markers: list[tuple[str, str]] = []

    def walk(value: Any, prefix: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                if str(key).lower() in {"engine", "network_engine"}:
                    markers.append((path, str(child).strip().lower()))
                walk(child, path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{prefix}[{index}]")

    walk(data)
    return markers


def _require_packet(data: Any, source: Path, allow_packet_only: bool = False) -> None:
    markers = _engine_markers(data)
    if not markers:
        if (
            allow_packet_only
            and isinstance(data, Mapping)
            and data.get("packet_only") is True
        ):
            return
        raise ValueError(
            f"{source}: missing engine/network_engine marker; packet evidence is required"
        )
    invalid = [(path, value) for path, value in markers if value != "packet"]
    if invalid:
        details = ", ".join(f"{path}={value!r}" for path, value in invalid)
        raise ValueError(f"{source}: non-packet input rejected ({details})")


def _experiment_from_path(path: Path, results_root: Path) -> str:
    try:
        first = path.relative_to(results_root).parts[0].lower()
    except (ValueError, IndexError):
        first = ""
    return first if first in EXPERIMENTS else "unknown"


def _canonical_row(
    data: Mapping[str, Any], path: Path, results_root: Path
) -> dict[str, Any]:
    experiment = _experiment_from_path(path, results_root)
    declared = _pick(
        data,
        ("experiment", "system_experiment", "config.experiment", "metadata.experiment"),
        ("system_experiment",),
    )
    if isinstance(declared, str) and declared.lower() in EXPERIMENTS:
        experiment = declared.lower()

    try:
        relative_parent = path.parent.relative_to(results_root / experiment)
        run_id = relative_parent.as_posix()
    except ValueError:
        run_id = path.parent.name
    if not run_id or run_id == ".":
        run_id = path.parent.name

    engine = _pick(data, ("engine", "metadata.engine"))
    network_engine = _pick(
        data, ("network_engine", "metadata.network_engine", "network.engine")
    )
    status = _pick(data, ("status", "result.status", "metadata.status"))

    row: dict[str, Any] = {
        "experiment": experiment,
        "run_id": run_id,
        "summary_path": path.relative_to(results_root).as_posix(),
        "engine": engine,
        "network_engine": network_engine,
        "status": status or "ok",
        "tier": _pick(data, ("tier", "job.tier", "config.tier"), ("tier",)),
        "scenario": _number(
            _pick(
                data,
                ("scenario", "job.scenario", "config.scenario", "params.scenario"),
                ("scenario",),
            )
        ),
        "scheme": _pick(
            data,
            ("scheme", "job.scheme", "config.scheme", "params.scheme", "network.scheme"),
            ("scheme",),
        ),
        "batch_size": _number(
            _pick(
                data,
                (
                    "batch_size",
                    "batch",
                    "job.batch",
                    "config.batch_size",
                    "params.batch_size",
                ),
                ("batch_size", "batch"),
            )
        ),
        "zipf_s": _number(
            _pick(
                data,
                ("zipf_s", "job.zipf_s", "config.zipf_s", "params.zipf_s"),
                ("zipf_s",),
            )
        ),
        "ep_size": _number(
            _pick(
                data,
                ("ep_size", "job.ep_size", "config.ep_size", "params.ep_size"),
                ("ep_size",),
            )
        ),
        "layers": _number(
            _pick(
                data,
                ("layers", "job.layers", "config.layers", "params.layers"),
                ("layers",),
            )
        ),
        "microbatches": _number(
            _pick(
                data,
                (
                    "microbatches",
                    "job.microbatches",
                    "config.microbatches",
                    "params.microbatches",
                    "config.m",
                ),
                ("microbatches",),
            )
        ),
        "attention_devices": _number(
            _pick(
                data,
                (
                    "attention_devices",
                    "m_attn",
                    "job.m_attn",
                    "config.attention_devices",
                    "config.m_attn",
                    "params.m_attn",
                ),
                ("attention_devices", "m_attn"),
            )
        ),
        "ffn_devices": _number(
            _pick(
                data,
                (
                    "ffn_devices",
                    "n_ffn",
                    "job.n_ffn",
                    "config.ffn_devices",
                    "config.n_ffn",
                    "params.n_ffn",
                ),
                ("ffn_devices", "n_ffn"),
            )
        ),
        "placement": _pick(
            data,
            ("placement", "job.placement", "config.placement", "params.placement"),
            ("placement",),
        ),
        "te_profile": _pick(
            data,
            ("te_profile", "job.te_profile", "config.te_profile", "params.te_profile"),
            ("te_profile",),
        ),
        "step_time_us": _number(
            _pick(
                data,
                (
                    "step_time_us",
                    "step_us",
                    "result.step_time_us",
                    "system_result.step_time_us",
                    "metrics.step_time_us",
                ),
                ("step_time_us", "step_us"),
            )
        ),
        "throughput_tokens_s": _number(
            _pick(
                data,
                (
                    "per_device_throughput_tokens_s",
                    "throughput_tokens_s",
                    "result.per_device_throughput_tokens_s",
                    "system_result.per_device_throughput_tokens_s",
                    "metrics.per_device_throughput_tokens_s",
                ),
                ("per_device_throughput_tokens_s", "throughput_tokens_s"),
            )
        ),
        "baseline_step_time_us": _number(
            _pick(
                data,
                (
                    "baseline_step_time_us",
                    "serial_step_time_us",
                    "result.baseline_step_time_us",
                    "comparison.sys1_step_time_us",
                ),
                ("baseline_step_time_us", "serial_step_time_us"),
            )
        ),
        "speedup": _number(
            _pick(
                data,
                ("speedup", "result.speedup", "metrics.speedup", "speedup_vs_serial"),
                ("speedup", "speedup_vs_serial"),
            )
        ),
        "tc_us": _number(
            _pick(
                data,
                (
                    "tc_us",
                    "result.tc_us",
                    "system_result.tc_us",
                    "network.tc_us",
                    "network_cct_p99_us",
                ),
                ("tc_us", "network_cct_p99_us"),
            )
        ),
        "dispatch_us": _number(
            _pick(
                data,
                (
                    "dispatch_us",
                    "result.dispatch_us",
                    "network.dispatch_us",
                    "network_inputs.dispatch_cct_us",
                    "dispatch_cct_p99_us",
                ),
                ("dispatch_us", "dispatch_cct_us", "dispatch_cct_p99_us"),
            )
        ),
        "combine_us": _number(
            _pick(
                data,
                (
                    "combine_us",
                    "result.combine_us",
                    "network.combine_us",
                    "network_inputs.combine_cct_us",
                    "combine_cct_p99_us",
                ),
                ("combine_us", "combine_cct_us", "combine_cct_p99_us"),
            )
        ),
    }

    m_attn = row["attention_devices"]
    n_ffn = row["ffn_devices"]
    row["m_to_n"] = (
        float(m_attn) / float(n_ffn)
        if isinstance(m_attn, (int, float))
        and isinstance(n_ffn, (int, float))
        and n_ffn
        else None
    )

    mask_candidates = (
        "fully_hidden",
        "mask_success",
        "masking_success",
        "communication_hidden",
        "bidirectional_hidden",
        "masking_rate",
        "mask_ratio",
    )
    mask_raw = _pick(
        data,
        (
            "masking.fully_hidden",
            "model.masking.fully_hidden",
            "result.masking.fully_hidden",
            "system_result.masking.fully_hidden",
            "mask_success",
            "masking_rate",
        ),
        mask_candidates,
    )
    mask_bool = _boolean(mask_raw)
    row["mask_value"] = mask_bool if mask_bool is not None else _number(mask_raw)
    if row["mask_value"] is None and experiment == "sys2":
        row["mask_value"] = _tbo_mask_fraction(data)
        row["mask_definition"] = (
            "communication event time overlapped by compute events"
            if row["mask_value"] is not None
            else None
        )
        row["mask_label"] = (
            f"{100.0 * float(row['mask_value']):.1f}% 通讯重叠"
            if row["mask_value"] is not None
            else "缺失"
        )
    else:
        row["mask_label"] = (
            "通过"
            if mask_bool is True
            else "未通过"
            if mask_bool is False
            else _display(row["mask_value"])
        )

    evidence_paths = []
    network_runs = data.get("network_runs")
    if isinstance(network_runs, list):
        for network_run in network_runs:
            if isinstance(network_run, Mapping) and network_run.get("summary"):
                evidence_paths.append(str(network_run["summary"]))
    row["packet_evidence_paths"] = json.dumps(
        evidence_paths, ensure_ascii=False
    ) if evidence_paths else ""

    flat = _flatten(data)
    for key, value in flat.items():
        csv_key = f"raw.{key}"
        if csv_key not in row:
            row[csv_key] = value
    return row


def _tbo_mask_fraction(data: Mapping[str, Any]) -> float | None:
    """Return exact communication/compute overlap from serialized TBO events."""

    events = _pick(data, ("model.events", "result.events", "system_result.events"))
    if not isinstance(events, list):
        return None
    compute: list[tuple[float, float]] = []
    communication: list[tuple[float, float]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        start = _number(event.get("start_us"))
        end = _number(event.get("end_us"))
        if start is None or end is None or end < start:
            continue
        interval = (float(start), float(end))
        if event.get("resource") == "compute":
            compute.append(interval)
        elif event.get("resource") == "communication":
            communication.append(interval)
    communication_busy = sum(end - start for start, end in communication)
    if communication_busy <= 0.0:
        return None
    overlap = 0.0
    for comm_start, comm_end in communication:
        overlap += sum(
            max(0.0, min(comm_end, comp_end) - max(comm_start, comp_start))
            for comp_start, comp_end in compute
        )
    return min(1.0, max(0.0, overlap / communication_busy))


def _ledger_entries(data: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(data, list):
        yield from (entry for entry in data if isinstance(entry, Mapping))
        return
    if not isinstance(data, Mapping):
        return
    found = False
    for key in (
        "results",
        "runs",
        "entries",
        "records",
        "network_runs",
        "system_runs",
    ):
        entries = data.get(key)
        if isinstance(entries, list):
            found = True
            yield from (entry for entry in entries if isinstance(entry, Mapping))
    if found:
        return


def _ledger_issues(data: Any, path: Path, results_root: Path) -> list[Issue]:
    issues: list[Issue] = []
    experiment_hint = _experiment_from_path(path, results_root)
    for entry in _ledger_entries(data):
        status = str(entry.get("status", "")).strip().lower()
        error = entry.get("_error", entry.get("error"))
        skipped = entry.get("_skipped", entry.get("skipped", False))
        clipped = entry.get("clipped", entry.get("_clipped", False))
        if error or status in {"fail", "failed", "error", "timeout"}:
            kind = "失败"
        elif clipped or status in {"clipped", "pruned", "excluded"}:
            kind = "裁剪"
        elif skipped or status in {"skip", "skipped", "unsupported"}:
            kind = "跳过"
        else:
            continue
        run_id = str(entry.get("run_id", entry.get("_run_id", "未知运行")))
        experiment = str(
            entry.get("experiment", entry.get("exp", entry.get("_exp", experiment_hint)))
        )
        message = str(
            error
            or entry.get("reason")
            or entry.get("message")
            or entry.get("_stderr")
            or status
            or kind
        )
        issues.append(
            Issue(kind, run_id, experiment, message, path.relative_to(results_root).as_posix())
        )
    return issues


def load_inputs(results_root: Path) -> tuple[list[dict[str, Any]], list[Issue], list[Path]]:
    """Load all inputs and enforce the packet gate before returning any data."""

    rows: list[dict[str, Any]] = []
    issues: list[Issue] = []
    ledgers: list[Path] = []
    parsed: list[tuple[Path, Any, str]] = []

    for experiment in EXPERIMENTS:
        exp_root = results_root / experiment
        if not exp_root.exists():
            continue
        for path in sorted(exp_root.rglob("summary.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(
                    Issue(
                        "失败",
                        path.parent.name,
                        experiment,
                        f"summary.json 无法解析：{exc}",
                        path.relative_to(results_root).as_posix(),
                    )
                )
                continue
            parsed.append((path, data, "summary"))

    ledger_candidates = {path for path in results_root.rglob("ledger.json")}
    root_ledger = results_root / "ledger.json"
    if root_ledger.exists():
        ledger_candidates.add(root_ledger)
    for path in sorted(ledger_candidates):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(
                Issue(
                    "失败",
                    "ledger",
                    _experiment_from_path(path, results_root),
                    f"ledger.json 无法解析：{exc}",
                    path.relative_to(results_root).as_posix(),
                )
            )
            continue
        parsed.append((path, data, "ledger"))
        ledgers.append(path)

    # Validate every parseable input first, so behavioral data creates no output.
    for path, data, kind in parsed:
        _require_packet(data, path, allow_packet_only=(kind == "ledger"))

    for path, data, kind in parsed:
        if kind == "summary":
            if not isinstance(data, Mapping):
                issues.append(
                    Issue(
                        "失败",
                        path.parent.name,
                        _experiment_from_path(path, results_root),
                        "summary.json 顶层不是对象",
                        path.relative_to(results_root).as_posix(),
                    )
                )
                continue
            row = _canonical_row(data, path, results_root)
            rows.append(row)
            status = str(row.get("status", "")).lower()
            if status in {"failed", "fail", "error", "timeout", "skipped", "skip", "clipped"}:
                issue_kind = (
                    "失败"
                    if status in {"failed", "fail", "error", "timeout"}
                    else "裁剪"
                    if status == "clipped"
                    else "跳过"
                )
                issues.append(
                    Issue(
                        issue_kind,
                        str(row["run_id"]),
                        str(row["experiment"]),
                        str(_pick(data, ("error", "reason", "message")) or status),
                        str(row["summary_path"]),
                    )
                )
        else:
            issues.extend(_ledger_issues(data, path, results_root))
    return rows, issues, ledgers


def _group_mean(
    rows: Iterable[Mapping[str, Any]],
    x_key: str,
    y_key: str,
    group_keys: Sequence[str],
) -> dict[tuple[Any, ...], tuple[list[float], list[float]]]:
    samples: dict[tuple[Any, ...], dict[float, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        x = _number(row.get(x_key))
        y = _number(row.get(y_key))
        if x is None or y is None:
            continue
        group = tuple(row.get(key) for key in group_keys)
        samples[group][float(x)].append(float(y))
    grouped: dict[tuple[Any, ...], tuple[list[float], list[float]]] = {}
    for group, points in samples.items():
        xs = sorted(points)
        grouped[group] = (xs, [fmean(points[x]) for x in xs])
    return grouped


def _placeholder(ax: Any, message: str) -> None:
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])


def _finish_figure(fig: Any, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, format="svg", bbox_inches="tight")
    plt.close(fig)


def _label(group: tuple[Any, ...], names: Sequence[str]) -> str:
    parts = [
        f"{name}={_display(value)}"
        for name, value in zip(names, group)
        if value not in (None, "")
    ]
    return ", ".join(parts) or "全部样本"


def _derive_sys2_speedups(rows: list[dict[str, Any]]) -> None:
    sys1 = [row for row in rows if row["experiment"] == "sys1"]
    sys2 = [row for row in rows if row["experiment"] == "sys2"]
    match_keys = ("scenario", "scheme", "batch_size", "zipf_s", "ep_size", "layers")

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(row.get(name) for name in match_keys)

    sys1_steps: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    m1_steps: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in sys1:
        step = _number(row.get("step_time_us"))
        if step is not None:
            sys1_steps[key(row)].append(float(step))
    for row in sys2:
        step = _number(row.get("step_time_us"))
        if step is not None and _number(row.get("microbatches")) == 1:
            m1_steps[key(row)].append(float(step))

    for row in sys2:
        step = _number(row.get("step_time_us"))
        speedup = _number(row.get("speedup"))
        baseline = _number(row.get("baseline_step_time_us"))
        if baseline is None:
            candidates = m1_steps.get(key(row)) or sys1_steps.get(key(row))
            if candidates:
                baseline = fmean(candidates)
                row["baseline_step_time_us"] = baseline
        if speedup is None and baseline is not None and step not in (None, 0):
            row["speedup"] = float(baseline) / float(step)


def make_figures(rows: list[dict[str, Any]], figures_dir: Path) -> list[Path]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    # Sys1: required step/throughput view against Zipf.
    path = figures_dir / "sys1_step_throughput_vs_zipf.svg"
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    sys1 = [row for row in rows if row["experiment"] == "sys1"]
    group_names = ("scenario", "scheme", "batch_size")
    for ax, metric, ylabel in (
        (axes[0], "step_time_us", "Step time (µs)"),
        (axes[1], "throughput_tokens_s", "Per-device throughput (token/s)"),
    ):
        grouped = _group_mean(sys1, "zipf_s", metric, group_names)
        if not grouped:
            _placeholder(ax, "sys1 data missing")
        else:
            for group, (xs, ys) in sorted(grouped.items(), key=lambda item: str(item[0])):
                ax.plot(xs, ys, marker="o", label=_label(group, ("S", "scheme", "B")))
            ax.legend(fontsize=7)
            ax.grid(alpha=0.3)
        ax.set_xlabel("Zipf S")
        ax.set_ylabel(ylabel)
    fig.suptitle("Sys1: serial Wide-EP step and throughput")
    _finish_figure(fig, path)
    paths.append(path)

    # Sys2: speedup by microbatch count.
    path = figures_dir / "sys2_speedup_vs_m.svg"
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    sys2 = [row for row in rows if row["experiment"] == "sys2"]
    grouped = _group_mean(
        sys2, "microbatches", "speedup", ("scenario", "scheme", "batch_size", "zipf_s")
    )
    if not grouped:
        _placeholder(ax, "sys2 speedup / m data missing")
    else:
        for group, (xs, ys) in sorted(grouped.items(), key=lambda item: str(item[0])):
            ax.plot(xs, ys, marker="o", label=_label(group, ("S", "scheme", "B", "Zipf")))
        ax.axhline(1.0, color="#777", linestyle="--", linewidth=1)
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
    ax.set_xlabel("Microbatch count m")
    ax.set_ylabel("Speedup vs serial/m=1")
    ax.set_title("Sys2: TBO speedup")
    _finish_figure(fig, path)
    paths.append(path)

    # Sys3: packet Tc and resulting system throughput by M:N.
    path = figures_dir / "sys3_tc_throughput.svg"
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    sys3 = [row for row in rows if row["experiment"] == "sys3"]
    group_names3 = ("scenario", "scheme", "placement", "microbatches", "te_profile")
    for ax, metric, ylabel in (
        (axes[0], "tc_us", "One-way Tc (µs)"),
        (axes[1], "throughput_tokens_s", "Per-device throughput (token/s)"),
    ):
        grouped = _group_mean(sys3, "m_to_n", metric, group_names3)
        if not grouped:
            _placeholder(ax, "sys3 data missing")
        else:
            for group, (xs, ys) in sorted(grouped.items(), key=lambda item: str(item[0])):
                ax.plot(
                    xs,
                    ys,
                    marker="o",
                    label=_label(group, ("S", "scheme", "placement", "m", "Te")),
                )
            ax.legend(fontsize=6)
            ax.grid(alpha=0.3)
        ax.set_xlabel("M:N ratio")
        ax.set_ylabel(ylabel)
    fig.suptitle("Sys3: AFD packet Tc and system throughput")
    _finish_figure(fig, path)
    paths.append(path)

    # Cross-experiment anchor comparison, only from values actually present.
    path = figures_dir / "cross_experiment_compare.svg"
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    labels: list[str] = []
    values: list[float] = []
    for experiment in EXPERIMENTS:
        observed = [
            float(value)
            for row in rows
            if row["experiment"] == experiment
            for value in [_number(row.get("throughput_tokens_s"))]
            if value is not None
        ]
        if observed:
            labels.append(experiment)
            values.append(fmean(observed))
    if not values:
        _placeholder(ax, "cross-experiment data missing")
    else:
        ax.bar(labels, values, color=("#4c78a8", "#f58518", "#54a24b")[: len(values)])
        ax.set_ylabel("Observed mean throughput (token/s/device)")
        ax.grid(axis="y", alpha=0.3)
    ax.set_title("Cross-experiment observed anchor comparison")
    _finish_figure(fig, path)
    paths.append(path)
    return paths


def write_csv(rows: list[dict[str, Any]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    extra = sorted(
        {key for row in rows for key in row}
        - set(CANONICAL_COLUMNS)
    )
    columns = list(CANONICAL_COLUMNS) + extra
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _unique(rows: Sequence[Mapping[str, Any]], key: str) -> str:
    values = sorted(
        {row.get(key) for row in rows if row.get(key) not in (None, "")},
        key=lambda value: str(value),
    )
    return ", ".join(_display(value) for value in values) if values else "缺失"


def _markdown_table(headers: Sequence[str], body: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    if not body:
        lines.append("| " + " | ".join(["数据缺失"] + ["—"] * (len(headers) - 1)) + " |")
    else:
        for row in body:
            lines.append(
                "| "
                + " | ".join(
                    _display(value).replace("|", "\\|").replace("\n", " ")
                    for value in row
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def _evidence_values(row: Mapping[str, Any]) -> list[str]:
    values = [str(row["summary_path"])]
    encoded_paths = row.get("packet_evidence_paths")
    if isinstance(encoded_paths, str) and encoded_paths:
        try:
            paths = json.loads(encoded_paths)
        except json.JSONDecodeError:
            paths = []
        if isinstance(paths, list):
            values.extend(str(path) for path in paths if str(path) not in values)
    for key, value in row.items():
        lowered = key.lower()
        if not lowered.startswith("raw."):
            continue
        if not any(token in lowered for token in ("path", "source", "evidence")):
            continue
        if value in (None, "", []):
            continue
        rendered = str(value)
        if rendered not in values:
            values.append(rendered)
    return values


def build_report(
    rows: list[dict[str, Any]],
    issues: list[Issue],
    ledgers: list[Path],
    results_root: Path,
    figure_paths: list[Path],
    report_md: Path,
) -> str:
    ledger_payloads: list[Mapping[str, Any]] = []
    for ledger_path in ledgers:
        try:
            payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping):
            ledger_payloads.append(payload)
    network_records = [
        record
        for payload in ledger_payloads
        for record in payload.get("network_runs", [])
        if isinstance(record, Mapping)
    ]
    system_records = [
        record
        for payload in ledger_payloads
        for record in payload.get("system_runs", [])
        if isinstance(record, Mapping)
    ]
    network_completed = sum(record.get("status") == "completed" for record in network_records)
    network_failed = sum(record.get("status") == "failed" for record in network_records)
    system_completed = sum(record.get("status") == "completed" for record in system_records)
    system_failed = sum(record.get("status") == "failed" for record in system_records)

    by_exp = {
        experiment: [
            row
            for row in rows
            if row["experiment"] == experiment and row.get("report_included", True)
        ]
        for experiment in EXPERIMENTS
    }
    lines: list[str] = ["# UB_RG 系统实验 0719 报告\n"]
    lines.append(
        "> 本报告只汇总 `engine/network_engine=packet` 的逐包证据。"
        "数据缺失处明确标为“缺失”，不使用行为级结果补齐，也不插值。\n"
    )
    lines.append(
        "实验定义仅以精确文件 "
        "[`UB_RG实验设计0719.md`](./UB_RG实验设计0719.md) §4.3；"
        "不引用不含 `0719` 的同名设计文档。\n"
    )
    if network_records or system_records:
        lines.append(
            f"> **执行状态：部分完成。** 网络任务 {len(network_records)} 个，完成 "
            f"{network_completed}、失败 {network_failed}；系统配置 {len(system_records)} 个，"
            f"完成 {system_completed}、因网络输入失败 {system_failed}。成功结果均来自场景1，"
            "场景2/3 在本轮墙钟上限内未形成可分析 summary。\n"
        )

    lines.append("## 1. 方法与参数矩阵\n")
    lines.append(
        "方法：从每个逐包运行的 `summary.json` 读取网络 CCT/P99 证据与系统模型输出，"
        "以 `ledger.json` 核对失败、跳过和裁剪；重复点仅在绘图时取算术平均，"
        "[`UB_RG系统实验0719数据.csv`](./UB_RG系统实验0719数据.csv) 保留逐运行记录。\n"
    )
    matrix = []
    for experiment in EXPERIMENTS:
        subset = by_exp[experiment]
        matrix.append(
            (
                experiment,
                len(subset),
                _unique(subset, "tier"),
                _unique(subset, "scenario"),
                _unique(subset, "scheme"),
                _unique(subset, "batch_size"),
                _unique(subset, "zipf_s"),
                _unique(subset, "ep_size"),
                _unique(subset, "layers"),
                _unique(subset, "microbatches"),
            )
        )
    lines.append(
        _markdown_table(
            (
                "实验",
                "成功 summary",
                "tier",
                "场景",
                "网络方案",
                "B",
                "Zipf S",
                "EP",
                "L",
                "m",
            ),
            matrix,
        )
    )
    lines.append(
        "这是**实收参数矩阵**，不是对未运行配置的宣称；未出现的参数组合视为缺失或被裁剪。\n"
    )

    lines.append("## 2. 逐包证据来源与 packet 门禁\n")
    lines.append(
        f"- 输入根目录：`{results_root}`\n"
        f"- 已接受 summary：{len(rows)} 个；ledger：{len(ledgers)} 个\n"
        "- 门禁规则：每个可解析输入必须至少声明一个 `engine` 或 `network_engine`，"
        "且所有此类声明都必须严格等于 `packet`；runner 的 ledger 也可用"
        "`packet_only=true` 作等价声明。`behavioral` 会立即报错并停止写出。\n"
    )
    if rows:
        for row in rows:
            sources = "；".join(f"`{value}`" for value in _evidence_values(row))
            lines.append(
                f"- `{row['experiment']}/{row['run_id']}`：{sources}；"
                f"engine={_display(row.get('engine'))}，"
                f"network_engine={_display(row.get('network_engine'))}\n"
            )
    else:
        lines.append("- 数据缺失：没有可接受的逐包 summary，因而没有逐包数值证据可列。\n")

    lines.append("## 3. Sys1：step 与 throughput\n")
    sys1_table = [
        (
            row["run_id"],
            row["scenario"],
            row["scheme"],
            row["batch_size"],
            row["zipf_s"],
            row["step_time_us"],
            row["throughput_tokens_s"],
        )
        for row in by_exp["sys1"]
    ]
    lines.append(
        _markdown_table(
            ("run", "场景", "方案", "B", "Zipf S", "step (µs)", "token/s/device"),
            sys1_table,
        )
    )
    lines.append(
        f"![sys1 step/throughput]({_relative_link(report_md, figure_paths[0])})\n"
    )

    lines.append("## 4. Sys2：m、speedup 与掩盖\n")
    lines.append(
        "Speedup 优先采用 summary 明示值；否则仅在存在同锚点 m=1 或 Sys1 step 时计算"
        "`baseline_step / sys2_step`。没有锚点则保持缺失。掩盖列优先报告 summary "
        "明示的 mask/hidden；若只有序列化 TBO events，则精确计算“通讯事件时长中与"
        "计算事件重叠的比例”，不从 speedup 猜测。\n"
    )
    sys2_table = [
        (
            row["run_id"],
            row["microbatches"],
            row["step_time_us"],
            row["baseline_step_time_us"],
            row["speedup"],
            row["mask_label"],
            row["throughput_tokens_s"],
        )
        for row in by_exp["sys2"]
    ]
    lines.append(
        _markdown_table(
            ("run", "m", "step (µs)", "基线 step", "speedup", "mask", "token/s/device"),
            sys2_table,
        )
    )
    lines.append(f"![sys2 speedup]({_relative_link(report_md, figure_paths[1])})\n")

    lines.append("## 5. Sys3：M:N、placement、Tc、mask 与 throughput\n")
    sys3_table = [
        (
            row["run_id"],
            f"{_display(row['attention_devices'])}:{_display(row['ffn_devices'])}",
            row["m_to_n"],
            row["placement"],
            row["microbatches"],
            row["tc_us"],
            row["mask_label"],
            row["step_time_us"],
            row["throughput_tokens_s"],
        )
        for row in by_exp["sys3"]
    ]
    lines.append(
        _markdown_table(
            (
                "run",
                "M:N",
                "比值",
                "placement",
                "m",
                "Tc (µs)",
                "mask",
                "step (µs)",
                "token/s/device",
            ),
            sys3_table,
        )
    )
    lines.append(
        "Tc 口径为 `max(M2N cct_us, N2M cct_us)`。本轮每个网络键只有 seed=1，"
        "因此这是单 seed 的逐包方向 CCT，不是跨 seed 的 CCT-P99；若未来增加多 seed，"
        "应在方向 CCT 样本上再取 P99。本报告不会用逐 token latency P99、"
        "dispatch/combine 或均值替代 Tc。\n"
    )
    lines.append(f"![sys3 Tc/throughput]({_relative_link(report_md, figure_paths[2])})\n")

    lines.append("## 6. 跨实验锚点\n")
    lines.append(
        "可比锚点至少应对齐场景、网络方案、B、Zipf S 与 L；Sys2 还需说明 m，"
        "Sys3 还需说明 M:N/placement。下图仅展示各实验**已有样本均值**作数据可用性"
        "概览，不把未完全对齐的均值解释为方案优劣。\n"
    )
    anchor_rows = []
    for experiment in EXPERIMENTS:
        subset = by_exp[experiment]
        throughput = [
            float(value)
            for row in subset
            for value in [_number(row.get("throughput_tokens_s"))]
            if value is not None
        ]
        steps = [
            float(value)
            for row in subset
            for value in [_number(row.get("step_time_us"))]
            if value is not None
        ]
        anchor_rows.append(
            (
                experiment,
                len(subset),
                fmean(steps) if steps else None,
                fmean(throughput) if throughput else None,
            )
        )
    lines.append(
        _markdown_table(
            ("实验", "样本数", "实收 step 均值 (µs)", "实收吞吐均值"),
            anchor_rows,
        )
    )
    lines.append(f"![cross compare]({_relative_link(report_md, figure_paths[3])})\n")

    lines.append("## 7. 实验结论与证据边界\n")

    def anchor(
        experiment: str,
        scheme: str,
        zipf_s: float,
        microbatches: int,
        *,
        batch: int = 256,
        attention_devices: int | None = None,
        ffn_devices: int | None = None,
    ) -> Mapping[str, Any] | None:
        for row in by_exp[experiment]:
            if (
                row.get("scenario") == 1
                and row.get("scheme") == scheme
                and row.get("batch_size") == batch
                and row.get("zipf_s") == zipf_s
                and row.get("layers") == 60
                and row.get("microbatches") == microbatches
            ):
                if attention_devices is not None and row.get("attention_devices") != attention_devices:
                    continue
                if ffn_devices is not None and row.get("ffn_devices") != ffn_devices:
                    continue
                return row
        return None

    spray_serial = anchor("sys1", "packet_spray", 0.5, 1)
    rg_serial = anchor("sys1", "ub_rg", 0.5, 1)
    spray_tbo2 = anchor("sys2", "packet_spray", 0.5, 2)
    spray_tbo4 = anchor("sys2", "packet_spray", 0.5, 4)
    rg_tbo2 = anchor("sys2", "ub_rg", 0.5, 2)
    rg_tbo4 = anchor("sys2", "ub_rg", 0.5, 4)
    rg_afd_11 = anchor(
        "sys3",
        "ub_rg",
        0.5,
        2,
        attention_devices=64,
        ffn_devices=64,
    )
    rg_afd_rows = [
        row
        for row in by_exp["sys3"]
        if row.get("scheme") == "ub_rg" and _number(row.get("tc_us")) is not None
    ]
    rg_afd_min = min(rg_afd_rows, key=lambda row: float(row["tc_us"])) if rg_afd_rows else None

    if spray_serial and rg_serial:
        spray_step = float(spray_serial["step_time_us"])
        rg_step = float(rg_serial["step_time_us"])
        lines.append(
            f"- **实验1（串行 Wide-EP）**：场景1、B=256、S=0.5、L=60 下，"
            f"`ub_rg` step={rg_step:.1f} µs，Packet Spray={spray_step:.1f} µs，"
            f"逐包输入对应 **{spray_step / rg_step:.2f}×** step 加速；"
            f"per-device throughput 从 {float(spray_serial['throughput_tokens_s']):.1f} "
            f"提升到 {float(rg_serial['throughput_tokens_s']):.1f} token/s。\n"
        )
    if spray_tbo2 and spray_tbo4 and spray_serial:
        base = float(spray_serial["step_time_us"])
        lines.append(
            f"- **实验2（TBO）**：同一 Packet Spray 锚点，m=2/m=4 相对串行分别达到 "
            f"{base / float(spray_tbo2['step_time_us']):.2f}×/"
            f"{base / float(spray_tbo4['step_time_us']):.2f}×；"
            "这是切小 MB 后网络 CCT 变化与双 stream 重叠的共同净效应；当前矩阵未做"
            "因素消融，不能把全部加速单独归因于重叠。\n"
        )
    if rg_tbo2 and rg_tbo4 and rg_serial:
        base = float(rg_serial["step_time_us"])
        lines.append(
            f"- **TBO 并非必然获益**：`ub_rg` 的 S=0.5 锚点中，m=2/m=4 speedup 仅 "
            f"{base / float(rg_tbo2['step_time_us']):.2f}×/"
            f"{base / float(rg_tbo4['step_time_us']):.2f}×（小于 1 即退化）。"
            "这些样本只证明净效应为退化；未做消融，不能分别确定多次 CCT、"
            "启动/排空或固定每-MB计算标定的贡献。\n"
        )
    if rg_afd_11 and rg_afd_min:
        lines.append(
            f"- **实验3（AFD）**：已完成的 `ub_rg` 样本中，最小 Tc="
            f"{float(rg_afd_min['tc_us']):.3f} µs（M:N="
            f"{rg_afd_min['attention_devices']}:{rg_afd_min['ffn_devices']}、"
            f"m={rg_afd_min['microbatches']}、S={rg_afd_min['zipf_s']}）；"
            f"1:1、m=2、S=0.5 对照 Tc={float(rg_afd_11['tc_us']):.3f} µs。"
            "两者双向掩盖均未通过，7:1 的 S=0.5/S=1 主锚点未形成成对成功数据；"
            "逐包证据不支持“在本次记录的 fabric 配置上，m=2 可无条件隐藏 AFD "
            "双向通信”。\n"
        )
    completed_scenarios = {
        int(row["scenario"])
        for row in rows
        if row.get("scenario") is not None and row.get("report_included", True)
    }
    if 2 not in completed_scenarios or 3 not in completed_scenarios:
        scenario_network_counts = {
            scenario: sum(
                str(record.get("run_id", "")).startswith(f"s{scenario}_")
                for record in network_records
            )
            for scenario in (2, 3)
        }
        lines.append(
            f"- **规模边界**：场景2的 {scenario_network_counts[2]} 个、场景3的 "
            f"{scenario_network_counts[3]} 个逐包网络任务（含 EP=256 控制点和 "
            "EP=1024 主点）在统一 120 秒墙钟上限内均未产出 summary。这些点是 "
            "**inconclusive / simulator scalability failure**，不是网络性能为零，"
            "也不能从场景1外推定量结论。\n"
        )

    lines.append("## 8. 失败、跳过与裁剪可见性\n")
    counts = {kind: sum(issue.kind == kind for issue in issues) for kind in ("失败", "跳过", "裁剪")}
    lines.append(
        f"ledger/解析记录：原始网络失败 **{network_failed}**，由缺失网络输入连带阻塞的"
        f"系统配置 **{system_failed}**；合并展示记录 {counts['失败']} 条（两者存在因果"
        f"重复，不代表 {counts['失败']} 次独立仿真失败）。跳过 **{counts['跳过']}**，"
        f"裁剪 **{counts['裁剪']}**。若已有 summary 通过 packet 门禁，该 summary 仍按"
        "可复用证据纳入。\n"
    )
    lines.append(
        _markdown_table(
            ("类别", "实验", "run", "原因", "来源"),
            [
                (issue.kind, issue.experiment, issue.run_id, issue.message, issue.source)
                for issue in issues
            ],
        )
    )

    lines.append("## 9. 数据边界：B>=1024 未纳入\n")
    lines.append(
        "**B>=1024 未纳入本次系统报告统计与结论。** 这是运行矩阵的显式裁剪边界，"
        "不是“性能等同于 B<1024”的假设。即使目录中出现 B>=1024 的意外 summary，"
        "分析器也会保留原始 CSV 证据，但报告解释应单独复核，不能外推当前图表结论。\n"
    )

    lines.append("## 10. 复现命令\n")
    lines.append(
        "```bash\n"
        "cd /workspace\n"
        "# 将父仓库维护的 §4.3 overlay 安装到锁定的 ns-3-ub 子模块\n"
        "python3 prepare_ns3_system_overlay.py apply\n"
        "cd ns-3-ub\n"
        "CC=gcc CXX=g++ python3.12 ./ns3 configure --enable-modules=unified-bus \\\n"
        "  --disable-examples --disable-tests --disable-mpi --disable-mtp \\\n"
        "  --disable-werror -d release\n"
        "python3.12 ./ns3 build -j 3 ub_rg-packet-experiment\n"
        "cd ..\n"
        "# 生成 main + controls 的 packet summary/ledger；不使用 behavioral 输入\n"
        "python3 run_ub_rg_system_experiments.py --tier all --workers 3 "
        "--timeout-s 120 --force\n"
        "python3 analyze_ub_rg_system_experiments.py \\\n"
        "  --results results/ub_rg_system_packet\n"
        "python3 -m unittest tests.test_system_model tests.test_system_runner \\\n"
        "  tests.test_system_analyzer\n"
        "```\n"
    )
    lines.append(
        "输出：`results/ub_rg_system_packet/all_summaries.csv`、"
        "`docs/UB_RG系统实验0719数据.csv`、`docs/UB_RG系统实验0719报告.md`、"
        "同名 HTML 与 `docs/ub_rg_system_figures/*.svg`。\n"
    )
    return "\n".join(lines)


def _relative_link(origin: Path, target: Path) -> str:
    import os

    return Path(os.path.relpath(target, origin.parent)).as_posix()


def _embed_markdown_image(
    alt: str, src: str, report_md: Path | None
) -> str:
    """Prefer inlining local SVG so the HTML report is self-contained."""

    candidate: Path | None = None
    src_path = Path(src)
    if src_path.is_absolute() and src_path.exists():
        candidate = src_path
    elif report_md is not None:
        resolved = (report_md.parent / src_path).resolve()
        if resolved.exists():
            candidate = resolved
    if candidate is not None and candidate.suffix.lower() == ".svg":
        svg = candidate.read_text(encoding="utf-8")
        return (
            "<figure class='fig'>"
            f"<div class='svg-wrap'>{svg}</div>"
            f"<figcaption>{html.escape(alt)} "
            f"(<code>{html.escape(candidate.name)}</code>)</figcaption>"
            "</figure>"
        )
    return (
        f"<p><img alt='{html.escape(alt, quote=True)}' "
        f"src='{html.escape(src, quote=True)}'></p>"
    )


def markdown_to_html(
    markdown: str, title: str, report_md: Path | None = None
) -> str:
    """Small dependency-free converter sufficient for the generated report.

    When ``report_md`` is provided, local ``.svg`` image links are inlined so the
    HTML file can be opened without sibling figure files.
    """

    output = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(title)}</title>",
        "<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;"
        "padding:0 1rem;line-height:1.6;color:#202124}table{border-collapse:collapse;"
        "width:100%;font-size:.9rem}th,td{border:1px solid #ccc;padding:.35rem .5rem;"
        "text-align:left}th{background:#f4f6f8}img,.svg-wrap{max-width:100%;"
        "border:1px solid #ddd;background:#fff}.svg-wrap{overflow:auto;padding:.5rem}"
        ".svg-wrap svg{max-width:100%;height:auto;display:block}"
        "figure.fig{margin:1.25rem 0}figcaption{color:#555;font-size:.9rem;"
        "margin-top:.4rem}code,pre{font-family:ui-monospace,monospace}"
        "pre{background:#f6f8fa;padding:1rem;overflow:auto}blockquote{border-left:4px solid "
        "#999;padding-left:1rem;color:#555}</style></head><body>",
    ]
    in_code = False
    in_table = False
    in_list = False

    def close_blocks() -> None:
        nonlocal in_table, in_list
        if in_table:
            output.append("</tbody></table>")
            in_table = False
        if in_list:
            output.append("</ul>")
            in_list = False

    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            close_blocks()
            if in_code:
                output.append("</code></pre>")
            else:
                output.append("<pre><code>")
            in_code = not in_code
            index += 1
            continue
        if in_code:
            output.append(html.escape(line) + "\n")
            index += 1
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            separator = (
                index + 1 < len(lines)
                and bool(re.fullmatch(r"\|?[\s:|-]+\|?", lines[index + 1]))
            )
            if not in_table:
                close_blocks()
                output.append("<table><thead><tr>")
                output.extend(f"<th>{html.escape(cell)}</th>" for cell in cells)
                output.append("</tr></thead><tbody>")
                in_table = True
                if separator:
                    index += 2
                    continue
            elif all(set(cell) <= {"-", ":"} for cell in cells):
                index += 1
                continue
            else:
                output.append("<tr>")
                output.extend(f"<td>{html.escape(cell)}</td>" for cell in cells)
                output.append("</tr>")
            index += 1
            continue
        if not line.startswith("- "):
            close_blocks()
        image = re.fullmatch(r"!\[(.*?)\]\((.*?)\)", line.strip())
        if image:
            output.append(
                _embed_markdown_image(image.group(1), image.group(2), report_md)
            )
        elif line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 6)
            text = line[level:].strip()
            output.append(f"<h{level}>{html.escape(text)}</h{level}>")
        elif line.startswith("> "):
            output.append(f"<blockquote>{html.escape(line[2:])}</blockquote>")
        elif line.startswith("- "):
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{html.escape(line[2:])}</li>")
        elif line.strip():
            escaped = html.escape(line)
            escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
            output.append(f"<p>{escaped}</p>")
        index += 1
    close_blocks()
    if in_code:
        output.append("</code></pre>")
    output.append("</body></html>")
    return "\n".join(output) + "\n"


def analyze(
    results_root: Path,
    report_md: Path = DEFAULT_REPORT_MD,
    figures_dir: Path = DEFAULT_FIGURES,
) -> AnalysisOutputs:
    results_root = results_root.resolve()
    report_md = report_md.resolve()
    figures_dir = figures_dir.resolve()
    if not results_root.exists():
        raise FileNotFoundError(f"results directory does not exist: {results_root}")

    rows, issues, ledgers = load_inputs(results_root)
    _derive_sys2_speedups(rows)
    for row in rows:
        batch_size = _number(row.get("batch_size"))
        row["report_included"] = batch_size is None or batch_size < 1024
        if not row["report_included"]:
            issues.append(
                Issue(
                    "裁剪",
                    str(row["run_id"]),
                    str(row["experiment"]),
                    f"B={_display(batch_size)} 落在 B>=1024 报告裁剪边界",
                    str(row["summary_path"]),
                )
            )

    # All output creation follows packet validation in load_inputs().
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_rows = [row for row in rows if row["report_included"]]
    figure_paths = make_figures(report_rows, figures_dir)
    csv_path = results_root / "all_summaries.csv"
    write_csv(rows, csv_path)
    write_csv(rows, report_md.with_name("UB_RG系统实验0719数据.csv"))
    markdown = build_report(
        rows, issues, ledgers, results_root, figure_paths, report_md
    )
    report_md.write_text(markdown, encoding="utf-8")
    report_html = report_md.with_suffix(".html")
    report_html.write_text(
        markdown_to_html(
            markdown, "UB_RG 系统实验 0719 报告", report_md=report_md
        ),
        encoding="utf-8",
    )
    return AnalysisOutputs(
        report_md,
        report_html,
        figures_dir,
        csv_path,
        len(rows),
        len(issues),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES)
    args = parser.parse_args(argv)
    try:
        outputs = analyze(args.results, args.report, args.figures_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"Wrote {outputs.report_md}, {outputs.report_html}, {outputs.csv_path}; "
        f"summaries={outputs.summary_count}, issues={outputs.issue_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
