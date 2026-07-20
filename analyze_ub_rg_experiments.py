#!/usr/bin/env python3
"""Aggregate UB_RG experiment results, plot figures, write simulation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "docs" / "UB_RG仿真报告.md"
SCHEMES = ("ub_rg", "ub_rg_pop", "packet_spray")
SCHEME_LS = {"ub_rg": "-", "ub_rg_pop": "-.", "packet_spray": "--"}
SCHEME_COLOR = {"ub_rg": "C0", "ub_rg_pop": "C2", "packet_spray": "C1"}


def load_summaries(results: Path) -> pd.DataFrame:
    rows = []
    for exp_dir in sorted(results.glob("exp*")):
        if not exp_dir.is_dir():
            continue
        for run_dir in sorted(exp_dir.iterdir()):
            summary = run_dir / "summary.json"
            if not summary.exists():
                continue
            try:
                text = summary.read_text()
                if not text.strip():
                    continue
                d = json.loads(text)
            except (json.JSONDecodeError, OSError):
                # Race with an in-flight writer (partial summary.json).
                continue
            # Prefer summary.json; fall back to results root name so peer merges
            # still label engines correctly when the field is absent.
            eng = d.get("engine")
            if eng not in ("packet", "behavioral"):
                eng = "packet" if results.name == "ub_rg_packet" else "behavioral"
            row = {
                "exp": exp_dir.name,
                "run_id": run_dir.name,
                "engine": eng,
                "scenario": d.get("scenario"),
                "scheme": d.get("scheme"),
                "mode": d.get("mode"),
                "batch": d.get("batch"),
                "zipf_s": d.get("zipf_s"),
                "ep_size": d.get("ep_size"),
                "total_tokens": d.get("total_tokens"),
                "konig_us": d.get("konig_us"),
                "rtt_us": d.get("rtt_us"),
                "barrier_us": d.get("barrier_us"),
                "cct_us": d.get("cct_us"),
                "step_us": d.get("step_us"),
                "throughput_GBs": d.get("throughput_GBs"),
                "lat_mean": d.get("latency_all", {}).get("mean_us"),
                "lat_p50": d.get("latency_all", {}).get("p50_us"),
                "lat_p99": d.get("latency_all", {}).get("p99_us"),
                "hot_p99": d.get("latency_hot", {}).get("p99_us"),
                "cold_p99": d.get("latency_cold", {}).get("p99_us"),
                "hot_mean": d.get("latency_hot", {}).get("mean_us"),
                "cold_mean": d.get("latency_cold", {}).get("mean_us"),
                "roundtrip_step_us": d.get("roundtrip_step_us"),
            }
            hist = run_dir / "hist.csv"
            row["hist_path"] = str(hist) if hist.exists() else ""
            rows.append(row)
    return pd.DataFrame(rows)


def style_ax(ax, title, xlabel, ylabel):
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)


def plot_exp12(df: pd.DataFrame, exp: str, tag: str, figs_dir: Path):
    sub = df[df["exp"] == exp].copy()
    if sub.empty:
        return []
    figs = []
    for scenario in sorted(sub["scenario"].unique()):
        s = sub[sub["scenario"] == scenario]
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for scheme in SCHEMES:
            ls = SCHEME_LS[scheme]
            for batch in sorted(s["batch"].unique()):
                g = s[(s["scheme"] == scheme) & (s["batch"] == batch)].sort_values("zipf_s")
                if g.empty:
                    continue
                ax.plot(
                    g["zipf_s"],
                    g["throughput_GBs"],
                    ls,
                    color=SCHEME_COLOR[scheme],
                    marker="o",
                    label=f"{scheme} b={batch}",
                )
        style_ax(
            ax,
            f"{tag} scenario{scenario}: Throughput vs Zipf S",
            "Zipf S",
            "Throughput (GB/s)",
        )
        path = figs_dir / f"{exp}_s{scenario}_throughput_vs_s.png"
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        figs.append(path)

        batches = sorted(s["batch"].unique())
        batch_focus = 256 if 256 in batches else batches[len(batches) // 2]
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for scheme in SCHEMES:
            ls = SCHEME_LS[scheme]
            g = s[(s["scheme"] == scheme) & (s["batch"] == batch_focus)].sort_values("zipf_s")
            if g.empty:
                continue
            ax.plot(
                g["zipf_s"],
                g["hot_p99"],
                ls,
                color=SCHEME_COLOR[scheme],
                marker="o",
                label=f"{scheme} hot p99",
            )
            ax.plot(
                g["zipf_s"],
                g["cold_p99"],
                ls,
                color=SCHEME_COLOR[scheme],
                marker="x",
                label=f"{scheme} cold p99",
            )
        style_ax(
            ax,
            f"{tag} scenario{scenario}: hot/cold p99 (batch={batch_focus})",
            "Zipf S",
            "Latency p99 (us)",
        )
        path = figs_dir / f"{exp}_s{scenario}_hotcold_p99_vs_s.png"
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        figs.append(path)

        s_focus = 0.7 if 0.7 in set(s["zipf_s"]) else sorted(s["zipf_s"].unique())[-1]
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for scheme in SCHEMES:
            ls = SCHEME_LS[scheme]
            g = s[(s["scheme"] == scheme) & (np.isclose(s["zipf_s"], s_focus))].sort_values(
                "batch"
            )
            if g.empty:
                continue
            ax.plot(
                g["batch"],
                g["step_us"],
                ls,
                color=SCHEME_COLOR[scheme],
                marker="o",
                label=f"{scheme} step",
            )
            ax.plot(
                g["batch"],
                g["cct_us"],
                ls,
                color=SCHEME_COLOR[scheme],
                marker="x",
                label=f"{scheme} cct",
            )
        ax.set_xscale("log", base=2)
        style_ax(
            ax,
            f"{tag} scenario{scenario}: CCT/Step vs BatchSize (S={s_focus})",
            "BatchSize",
            "Time (us)",
        )
        path = figs_dir / f"{exp}_s{scenario}_step_vs_batch.png"
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        figs.append(path)
    return figs


def plot_exp3(df: pd.DataFrame, figs_dir: Path):
    """Roundtrip Step vs EP summary (per-token CDF/PDF figures are dropped;
    see plot_exp3_pdf for the system dispatch+combine CCT distributions)."""
    # Remove stale per-token CDF/PDF figures from earlier report versions.
    for stale in figs_dir.glob("exp3_s*_cdf_pdf.png"):
        stale.unlink()
    sub = df[df["exp"] == "exp3_roundtrip"].copy()
    if sub.empty:
        return []
    figs = []
    for scenario in sorted(sub["scenario"].unique()):
        s = sub[sub["scenario"] == scenario]
        # step_us vs ep_size
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for scheme in SCHEMES:
            ls = SCHEME_LS[scheme]
            for zipf_s in sorted(s["zipf_s"].unique()):
                g = s[(s["scheme"] == scheme) & np.isclose(s["zipf_s"], zipf_s)].sort_values(
                    "ep_size"
                )
                if g.empty:
                    continue
                step = g["roundtrip_step_us"].fillna(g["step_us"])
                ax.plot(
                    g["ep_size"],
                    step,
                    ls,
                    color=SCHEME_COLOR[scheme],
                    marker="o",
                    label=f"{scheme} S={zipf_s:g}",
                )
        style_ax(
            ax,
            f"Exp3 scenario{scenario}: Roundtrip Step vs EP",
            "EP size",
            "Step (us)",
        )
        path = figs_dir / f"exp3_s{scenario}_step_vs_ep.png"
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        figs.append(path)
    return figs


def _plot_density(ax, samples: np.ndarray, ls: str, color: str, label: str) -> None:
    """Plot a smooth density (KDE if available, else histogram) of CCT samples."""
    samples = np.asarray(samples, dtype=float)
    samples = samples[np.isfinite(samples)]
    lo, hi = float(samples.min()), float(samples.max())
    if hi <= lo:
        ax.axvline(lo, ls=ls, color=color, alpha=0.8, label=label)
        return
    span = max(hi - lo, 1e-9)
    try:
        from scipy.stats import gaussian_kde

        # Wider bandwidth → visually open PDF curves (still integrates to 1).
        bw = max(0.85, 1.4 * samples.size ** (-1.0 / 5.0))
        kde = gaussian_kde(samples, bw_method=bw)
        pad = max(4.5 * float(np.std(samples)), 0.6 * span, 2.0)
        xs = np.linspace(max(0.0, lo - pad), hi + pad, 640)
        ys = kde(xs)
        # Keep more of the tails so curves look open, not truncated spikes.
        thr = 0.005 * float(ys.max())
        mask = ys >= thr
        if mask.any():
            i0, i1 = int(np.argmax(mask)), int(len(mask) - 1 - np.argmax(mask[::-1]))
            xs, ys = xs[i0 : i1 + 1], ys[i0 : i1 + 1]
        ax.plot(xs, ys, ls, color=color, label=label)
    except Exception:
        bins = min(20, max(5, samples.size // 2))
        counts, edges = np.histogram(samples, bins=bins, density=True)
        centers = 0.5 * (edges[:-1] + edges[1:])
        ax.plot(centers, counts, ls, color=color, marker=".", label=label)


def plot_exp3_pdf(df: pd.DataFrame, figs_dir: Path):
    """PDF (no CDF) of system dispatch+combine CCT for exp3_pdf runs.

    - One figure per (scenario, batch, zipf_s): all EP sizes of that scenario.
    - One cross-scenario compare figure per (batch, zipf_s): s1-EP128 / s2-EP1024 /
      s3-EP1024 (the previous EP128-vs-EP1024 view, plus scenario 3).
    """
    sub = df[df["exp"] == "exp3_pdf"].copy()
    if sub.empty:
        return []
    sub = sub[sub["cct_us"].notna() & (sub["cct_us"] > 0)]
    sub = sub[sub["batch"] < 512]
    if sub.empty:
        return []

    scheme_ls = SCHEME_LS
    ep_color = {32: "C0", 64: "C1", 128: "C2", 256: "C4", 1024: "C3"}
    sc_color = {1: "C0", 2: "C3", 3: "C2"}
    figs = []

    # Per-scenario PDFs
    for scenario in sorted(sub["scenario"].unique()):
        sc = sub[sub["scenario"] == scenario]
        eps = sorted(sc["ep_size"].dropna().unique())
        for batch in sorted(sc["batch"].unique()):
            for zs in sorted(sc["zipf_s"].unique()):
                cell = sc[(sc["batch"] == batch) & np.isclose(sc["zipf_s"], zs)]
                if cell.empty:
                    continue
                fig, ax = plt.subplots(figsize=(7.5, 4.5))
                any_curve = False
                for ep in eps:
                    for scheme in SCHEMES:
                        g = cell[(cell["ep_size"] == ep) & (cell["scheme"] == scheme)]
                        samples = g["cct_us"].to_numpy(dtype=float)
                        samples = samples[np.isfinite(samples)]
                        if samples.size < 2:
                            continue
                        label = f"EP={int(ep)} {scheme} (n={samples.size})"
                        _plot_density(
                            ax,
                            samples,
                            scheme_ls[scheme],
                            ep_color.get(int(ep), "C0"),
                            label,
                        )
                        any_curve = True
                if not any_curve:
                    plt.close(fig)
                    continue
                style_ax(
                    ax,
                    f"Exp3 S{int(scenario)} System CCT PDF "
                    f"(batch={int(batch)}, S={zs:g})",
                    "System dispatch+combine CCT (µs)  "
                    "[attention→dispatch→GEMV→combine one iteration]",
                    "Density",
                )
                path = figs_dir / f"exp3_pdf_s{int(scenario)}_b{int(batch)}_s{zs:g}.png"
                fig.tight_layout()
                fig.savefig(path, dpi=140)
                plt.close(fig)
                figs.append(path)

    # Cross-scenario compare: representative EP of each topology
    compare = [
        (1, 128),
        (2, 1024),
        (3, 1024),
    ]
    for batch in sorted(sub["batch"].unique()):
        for zs in sorted(sub["zipf_s"].unique()):
            fig, ax = plt.subplots(figsize=(7.5, 4.5))
            any_curve = False
            for scenario, ep in compare:
                cell = sub[
                    (sub["scenario"] == scenario)
                    & (sub["ep_size"] == ep)
                    & (sub["batch"] == batch)
                    & np.isclose(sub["zipf_s"], zs)
                ]
                for scheme in SCHEMES:
                    g = cell[cell["scheme"] == scheme]
                    samples = g["cct_us"].to_numpy(dtype=float)
                    samples = samples[np.isfinite(samples)]
                    if samples.size < 2:
                        continue
                    label = f"S{scenario} EP={ep} {scheme} (n={samples.size})"
                    _plot_density(
                        ax,
                        samples,
                        scheme_ls[scheme],
                        sc_color[scenario],
                        label,
                    )
                    any_curve = True
            if not any_curve:
                plt.close(fig)
                continue
            style_ax(
                ax,
                f"Exp3 Cross-Scenario CCT PDF (batch={int(batch)}, S={zs:g})",
                "System dispatch+combine CCT (µs)  "
                "[attention→dispatch→GEMV→combine one iteration]",
                "Density",
            )
            path = figs_dir / f"exp3_pdf_compare_b{int(batch)}_s{zs:g}.png"
            fig.tight_layout()
            fig.savefig(path, dpi=140)
            plt.close(fig)
            figs.append(path)

    # Drop legacy names (exp3_pdf_b16_s0.3.png) that omitted the scenario tag.
    for stale in figs_dir.glob("exp3_pdf_b*_s*.png"):
        try:
            stale.unlink()
        except OSError:
            pass
    return figs



def _md_inline(text: str, html_lib, re) -> str:
    """Escape + light inline markdown: `code`, **bold**, [text](url)."""
    s = html_lib.escape(text)

    def _code(m):
        return f"<code>{m.group(1)}</code>"

    def _bold(m):
        return f"<strong>{m.group(1)}</strong>"

    def _link(m):
        return f"<a href='{m.group(2)}'>{m.group(1)}</a>"

    s = re.sub(r"`([^`]+)`", _code, s)
    s = re.sub(r"\*\*([^*]+)\*\*", _bold, s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, s)
    return s


def _write_html_report(md: str, html_path: Path, figs_dir: Path) -> None:
    """Minimal MD→HTML for the generated report (headings, lists, images, tables, code)."""
    import html as html_lib
    import re

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>UB_RG仿真报告</title>",
        "<style>body{font-family:system-ui,sans-serif;max-width:980px;margin:2rem auto;",
        "line-height:1.55;padding:0 1rem;color:#222}",
        "img{max-width:100%;height:auto;border:1px solid #ddd;margin:0.5rem 0}",
        "pre{background:#f6f8fa;padding:0.75rem;overflow:auto;border-radius:6px}",
        "code{font-family:ui-monospace,monospace;font-size:0.92em}",
        "table{border-collapse:collapse;width:100%;margin:0.75rem 0;font-size:0.92em}",
        "th,td{border:1px solid #ddd;padding:0.4rem 0.55rem;text-align:left;vertical-align:top}",
        "th{background:#f6f8fa}",
        "blockquote{margin:0.75rem 0;padding:0.5rem 0.9rem;border-left:3px solid #ccc;",
        "background:#fafafa;color:#444}",
        "ul{padding-left:1.25rem}</style></head><body>\n",
    ]
    in_code = False
    in_ul = False
    table_rows: list[list[str]] = []

    def flush_ul():
        nonlocal in_ul
        if in_ul:
            parts.append("</ul>\n")
            in_ul = False

    def flush_table():
        nonlocal table_rows
        if not table_rows:
            return
        parts.append("<table>\n<thead><tr>")
        for cell in table_rows[0]:
            parts.append(f"<th>{_md_inline(cell, html_lib, re)}</th>")
        parts.append("</tr></thead>\n<tbody>\n")
        for row in table_rows[1:]:
            parts.append("<tr>")
            for cell in row:
                parts.append(f"<td>{_md_inline(cell, html_lib, re)}</td>")
            parts.append("</tr>\n")
        parts.append("</tbody></table>\n")
        table_rows = []

    def is_table_sep(line: str) -> bool:
        s = line.strip()
        if not s.startswith("|"):
            return False
        body = s.strip("|").replace(" ", "")
        return bool(body) and all(c in "-|:" for c in body)

    def parse_row(line: str) -> list[str]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        return cells

    for line in md.splitlines():
        if line.strip().startswith("```"):
            flush_ul()
            flush_table()
            if not in_code:
                parts.append("<pre><code>")
                in_code = True
            else:
                parts.append("</code></pre>\n")
                in_code = False
            continue
        if in_code:
            parts.append(html_lib.escape(line) + "\n")
            continue

        # Markdown pipe tables
        if line.strip().startswith("|"):
            flush_ul()
            if is_table_sep(line):
                continue
            table_rows.append(parse_row(line))
            continue
        else:
            flush_table()

        if line.startswith("# "):
            flush_ul()
            parts.append(f"<h1>{_md_inline(line[2:], html_lib, re)}</h1>\n")
        elif line.startswith("## "):
            flush_ul()
            parts.append(f"<h2>{_md_inline(line[3:], html_lib, re)}</h2>\n")
        elif line.startswith("### "):
            flush_ul()
            parts.append(f"<h3>{_md_inline(line[4:], html_lib, re)}</h3>\n")
        elif line.startswith("#### "):
            flush_ul()
            parts.append(f"<h4>{_md_inline(line[5:], html_lib, re)}</h4>\n")
        elif line.startswith("!["):
            flush_ul()
            m = re.match(r"!\[(.*?)\]\((.*?)\)", line)
            if m:
                parts.append(
                    f"<p><img alt='{html_lib.escape(m.group(1))}' "
                    f"src='{html_lib.escape(m.group(2))}'></p>\n"
                )
            else:
                parts.append(f"<p>{_md_inline(line, html_lib, re)}</p>\n")
        elif line.startswith("> "):
            flush_ul()
            parts.append(f"<blockquote>{_md_inline(line[2:], html_lib, re)}</blockquote>\n")
        elif line.startswith("- "):
            if not in_ul:
                parts.append("<ul>\n")
                in_ul = True
            parts.append(f"<li>{_md_inline(line[2:], html_lib, re)}</li>\n")
        elif line.strip() == "":
            flush_ul()
            parts.append("<br/>\n")
        else:
            flush_ul()
            parts.append(f"<p>{_md_inline(line, html_lib, re)}</p>\n")
    flush_ul()
    flush_table()
    parts.append("</body></html>\n")
    html_path.write_text("".join(parts), encoding="utf-8")
    print(f"Wrote {html_path}")


def topology_and_scheme_md(engine: str) -> str:
    """组网差异 + 三方案实现差异（对齐 EXPERIMENT_REPORT_FULL_S123 结构，口径为本仓库实现）。"""
    eng_note = (
        "逐包引擎（`ub_rg-packet-experiment` + `UbRgExperimentApp`）"
        if engine == "packet"
        else "行为级引擎（`ub_rg-dispatch-experiment`）"
    )
    return f"""### 1.1 组网方案

对齐 [UB_RG实验设计.md](./UB_RG实验设计.md) 与参考报告 [EXPERIMENT_REPORT_FULL_S123.html](./EXPERIMENT_REPORT_FULL_S123.html) 的三场景拓扑；本报告由 {eng_note} 驱动。

| 场景 | 拓扑 | NPU | 交换 | 备注 |
|---|---|---:|---|---|
| 1 | 单层 Clos | 128 | 8 × SW128 | 每 NPU 8×400G 上联；路径 2 跳 |
| 2 | 两层 Clos | 1024 | 128 Leaf + 64 Spine | 16 组 × 64 NPU；路径 4 跳 |
| 3 | MpClos · 8 平面 | 1024 | 128 Leaf + 64 Spine | 与场景2同规模；按平面钉扎，平面间隔离 |

组网差异要点：

- **跳数 / RTT**：场景1 控制面 RTT_rg≈0.6µs；场景2/3≈1.1µs（两层更长）。
- **瓶颈位置**：场景1 主要是目的侧平面下行；场景2/3 另有 Leaf↔Spine 中段争用（Packet Spray 更敏感）。
- **平面**：三者均为 8 上联/平面；场景3 强调跨平面隔离，RG/POP 路径钉扎，Spray 按源序 RR 洒平面。

### 1.2 网络方案与实现差异

| 方案 | Scheme | 语义 |
|---|---|---|
| §2.1 | `packet_spray` | 自由注入 / Packet Spray 基线（参考报告中的 `ub_unscheduled`） |
| §2.2 | `ub_rg` | 标准 Request-Grant：目的侧按 1 grain/τ_g 授权 |
| §2.3 | `ub_rg_pop` | SHMEM-POP：Push 元数据 → ESC → PullGrant → 远端读 Pull |

主 KPI：CCT / step（µs）；辅 KPI：hot/cold p99、吞吐、CCT/König。机制对照如下（以本仓库仿真为准，POP 为近似模型，非完整 supernode `UbRgPopEsc` 模块）。

#### 角色关系

| 对象 | 形态 | 角色 |
|---|---|---|
| `ub_request_grant.md` / 设计 | 文档 | 交换机侧分布式 REQ/GNT：每 τ_g 每出口 ≤1、路径钉扎、cursor/SYNC |
| `ub_rg` | 仿真 scheme | 主协议的落地：目的侧授权节奏 + 源侧 FCFS；行为级折叠控制面为 RTT；逐包走真实 REQ/GNT/SYNC |
| `ub_rg_pop` | 仿真 scheme | [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md)：Push→Pull；**同 RG 稳态节拍**，多付一次单向启动 + PullCredit 窗口 |
| `packet_spray` | 仿真 scheme | 无授权准入；源上联自由注入；目的/中段 FIFO；分析阶段叠软件屏障 |

> **对齐的核心（设计 ↔ ub_rg）：** grain 量化、τ_g、每平面 ≤1 授权、Clos/MpClos 钉扎。
> **POP 相对 RG：** 稳态 König 渐近相同；startup = RTT_rg + oneWay（≈1.5×）；小 batch 略慢，大负载/高偏斜时 pop≈rg。
> **Spray 相对 RG：** 无目的侧节拍 → 热点队列放大，CCT/p99 与软件屏障更重。

#### 三方机制对照

| 维度 | `packet_spray` | `ub_rg` | `ub_rg_pop`（本仓库） |
|---|---|---|---|
| 调度 / 准入 | 无；源侧自由注入 | 目的侧 GNT 节奏（1/τ_g/egress） | 同 RG 目的侧节奏；Pull 前多一次 Push 单向 |
| 控制通道 | 无控制面握手 | REQ → GNT → DATA（逐包真实报文；行为级折叠为 RTT） | Push meta → PullGrant → Pull remote-read（行为级：`rtt_pop`；逐包：Kickoff 延时 + 更大 credit） |
| 注入准入 | 仅源端口串行 | GNT 到才发，无预支库存 | PullCredit 窗口 `C_pop=⌈rtt_pop/τ_g⌉+margin`，稳态可流水 |
| 冷启动 | 0（立即发） | 付一次 RTT_rg | 付 RTT_rg + oneWay（Push→Grant→Pull） |
| ESC / 节拍 | 无 | 每 τ_g 每 egress ≤1 grain | 同左（König 渐近对齐 RG） |
| 数据路径 | 源序 RR 洒平面；两层含 spine→leaf 队列 | RG 平面钉扎；近零队列（σ 抖动） | 同 RG 钉扎 |
| 屏障 | 软件屏障（更重） | BSP cursor 屏障（轻） | 同 `ub_rg` |
| 实现入口 | `UsePacketSpray=true` | `Scheme::UbRg` / RG scheduler active | `Scheme::UbRgPop`；逐包复用 RG transport + POP overlay |

#### 实验可读差异（期望趋势）

| 维度 | `ub_rg` | `ub_rg_pop` | `packet_spray` |
|---|---|---|---|
| 首包 / 小 batch | 付 RTT_rg | 略高于 RG（多 oneWay） | 常介于二者之间或更差（无节拍） |
| 大 batch / 高偏斜 | CCT 贴 König | pop/rg → 1（同节拍） | spray/rg ≫ 1，hot p99 放大 |
| 冷流隔离 | 好（按需授权） | 接近 RG | 差（热点占满下行） |
| 两层 Clos | 中段压力可控 | 偶发略差于 RG | 中段 FIFO 放大更明显 |

CLI：`--scheme=ub_rg|ub_rg_pop|packet_spray`。
"""

def md_img(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return f"![{path.name}](../{rel})"


def clean_table(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines())


def write_report(
    df: pd.DataFrame,
    fig_paths: list[Path],
    results: Path,
    figs_dir: Path,
    peer_df: pd.DataFrame | None = None,
):
    figs_dir.mkdir(parents=True, exist_ok=True)
    engine = str(df["engine"].iloc[0]) if "engine" in df.columns and len(df) else "unknown"
    rel_results = results.relative_to(ROOT).as_posix()
    lines = []
    lines.append("# UB_RG 网络仿真报告\n")
    lines.append("## 1. 实验概述\n")
    if engine == "packet":
        lines.append(
            "本报告对应 [UB_RG实验设计.md](./UB_RG实验设计.md) §4.2.1–§4.2.3，"
            "在 `ns-3-ub` **Unified Bus 协议栈**上用逐包仿真器 "
            "`scratch/ub_rg-packet-experiment.cc` 对比 **UB_RG**、"
            "**UB_RG_POP（SHMEM-POP）** 与 **Packet Spray（自由注入）**。"
            "结构对齐参考报告 [EXPERIMENT_REPORT_FULL_S123.html](./EXPERIMENT_REPORT_FULL_S123.html)：组网 → 方案差异 → 扫参结果。\n"
        )
    else:
        lines.append(
            "本报告对应 [UB_RG实验设计.md](./UB_RG实验设计.md) §4.2.1–§4.2.3，"
            "在 `ns-3-ub` 中用自包含行为级仿真器 "
            "`scratch/ub_rg-dispatch-experiment.cc` 对比 **UB_RG（request/grant）**、"
            "**UB_RG_POP（SHMEM-POP）** 与 **Packet Spray（自由注入）**。"
            "结构对齐参考报告 [EXPERIMENT_REPORT_FULL_S123.html](./EXPERIMENT_REPORT_FULL_S123.html)：组网 → 方案差异 → 扫参结果。\n"
        )
    lines.append(topology_and_scheme_md(engine))
    if engine == "packet":
        lines.append("### 1.3 模型假设与简化\n")
        lines.append(
            "- 端口 400Gbps，grain = 7KB（2×MTU），τ_g ≈ 143.36 ns\n"
            "- 真实 REQ/GNT/SYNC 控制报文（VL1）；末跳交换机拦截 REQ；"
            "目的侧 1 grain/τ_g + credit window + RR；源侧 FCFS grant 队列\n"
            "- UB_RG_POP：复用 RG 路径，Kickoff 叠加 Push 单向时延 + 更大 PullCredit 窗口"
            "（见 [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md)）\n"
            "- SYNC：各调度器 LOCAL → 聚合 NPU(member0) → GLOBAL 广播（与文档 §4.9 聚合点差异见正文）\n"
            "- 省略：可靠性重传、预补偿、多世代窗口、PHASE 管理面\n"
            "- Packet Spray：`UsePacketSpray` + 自由注入；软件屏障在分析阶段叠加\n"
            "- 专家与 NPU 1:1；TopK=8\n"
        )
    else:
        lines.append("### 1.3 模型假设与简化\n")
        lines.append(
            "- 端口 400Gbps（有效 50GB/s），grain = 7KB，τ_g ≈ 143.36 ns\n"
            "- 链路建模为串行化服务器 + FIFO；交换机直通 150 ns/跳，传播 50 ns/跳\n"
            "- UB_RG：目的侧按 1 grain/τ_g 授权节奏 + 源端口 FCFS\n"
            "- UB_RG_POP：同目的侧节奏；startup = RTT_rg + oneWay（Push→Grant→Pull）；"
            "PullCredit 窗口保稳态流水（见 [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md)）\n"
            "- Packet Spray：自由注入；软件屏障在分析阶段叠加\n"
            "- 专家与 NPU 1:1；TopK=8\n"
        )
    lines.append("### 1.4 参数矩阵（裁剪）\n")
    lines.append(
        "| 实验 | mode | 场景 | BatchSize | Zipf S | EP |\n"
        "|---|---|---|---|---|---|\n"
        "| 1 Dispatch | dispatch | 1/2/3 | 16,256,1024(+4096@场景1) | 0,0.3,0.7,0.9 | full |\n"
        "| 2 Combine | combine | 同实验1 | 同左 | 同左 | full |\n"
        "| 3 Roundtrip | roundtrip | 1→{32,64,128}; 2/3→{256,1024} | 256 | 同左 | 上列 |\n"
    )
    n = len(df)
    lines.append(f"\n引擎：**{engine}**；成功汇总运行数：**{n}**。原始结果：`{rel_results}/`。\n")
    if engine == "packet":
        lines.append(
            "> 逐包引擎按计划风险路径裁剪：场景1 不含 BatchSize=4096；"
            "场景2/3 仅保留 BatchSize≤256。完整 216 组矩阵由行为级引擎覆盖；"
            "逐包用于机制校验与场景1 规模对标。实验3 系统 CCT PDF 若本引擎样本未齐，"
            "报告自动回退到行为级多 seed 结果。\n"
        )

    def table_for(exp: str, scenario: int, batch: int | None = None) -> tuple[str, int | None]:
        s = df[(df["exp"] == exp) & (df["scenario"] == scenario)]
        if s.empty:
            return "_（无数据）_\n", None
        # Prefer batch=256; if still running / missing, fall back to largest available.
        if batch is not None and not (s["batch"] == batch).any():
            batch = None
        if batch is None:
            batch = int(s["batch"].max())
        s = s[s["batch"] == batch]
        if s.empty:
            return "_（无数据）_\n", None
        piv = s.pivot_table(
            index="zipf_s",
            columns="scheme",
            values=["step_us", "cct_us", "lat_p99", "hot_p99", "throughput_GBs"],
            aggfunc="mean",
        )
        return "```\n" + clean_table(piv.round(2).to_string()) + "\n```\n", batch

    lines.append("## 2. 实验1：倾斜专家流量下的 Dispatch\n")
    for sc in sorted(df[df["exp"] == "exp1_dispatch"]["scenario"].unique()):
        lines.append(f"### 2.{sc} 场景{sc}\n")
        tbl, used_batch = table_for("exp1_dispatch", int(sc), 256)
        tag = f"batch={used_batch}" if used_batch is not None else "batch=?"
        if used_batch is not None and used_batch != 256:
            tag += "（256 尚未齐，暂用已有最大 batch）"
        lines.append(f"**{tag} 对比表**\n\n")
        lines.append(tbl)
        for p in sorted(figs_dir.glob(f"exp1_dispatch_s{int(sc)}_*.png")):
            lines.append(md_img(p) + "\n")

    lines.append("## 3. 实验2：倾斜专家流量下的 Combine\n")
    for sc in sorted(df[df["exp"] == "exp2_combine"]["scenario"].unique()):
        lines.append(f"### 3.{sc} 场景{sc}\n")
        tbl, used_batch = table_for("exp2_combine", int(sc), 256)
        tag = f"batch={used_batch}" if used_batch is not None else "batch=?"
        if used_batch is not None and used_batch != 256:
            tag += "（256 尚未齐，暂用已有最大 batch）"
        lines.append(f"**{tag} 对比表**\n\n")
        lines.append(tbl)
        for p in sorted(figs_dir.glob(f"exp2_combine_s{int(sc)}_*.png")):
            lines.append(md_img(p) + "\n")

    lines.append("## 4. 实验3：系统级 Dispatch+Combine 完成时间 (CCT) PDF\n")
    lines.append(
        "横轴为**系统级一次迭代完成时间**（attention→dispatch→GEMV→combine 一个 roundtrip 步的 CCT，"
        "口径 = kickoff→最后一个 combine token 完成，取自 summary.json 的 `cct_us`），"
        "**不再是逐 token 时延**。对每个 (场景, BatchSize, Zipf S, EP) 组合，"
        "在多个随机种子下各跑一次 roundtrip，每次运行贡献一个系统 CCT 样本，"
        "以此得到系统 CCT 的概率密度分布（PDF，无 CDF）。\n"
    )
    lines.append(
        "覆盖三个组网场景（与实验设计 §4.2.3 一致）：\n"
        "- **场景1** 单层 Clos：EP ∈ {32, 64, 128}\n"
        "- **场景2** 两层 Clos：EP ∈ {256, 1024}\n"
        "- **场景3** 两层 Clos 多平面：EP ∈ {256, 1024}\n"
        "每场景单独出 PDF；另附跨场景对比图（S1-EP128 / S2-EP1024 / S3-EP1024）。"
        "线型区分方案（实线 ub_rg，点划线 ub_rg_pop，虚线 packet_spray）。\n"
    )
    pdf_df = df[df["exp"] == "exp3_pdf"].copy()
    pdf_df = pdf_df[pdf_df["cct_us"].notna() & (pdf_df["cct_us"] > 0)]
    pdf_df = pdf_df[pdf_df["batch"] < 512]
    pdf_figs_dir = figs_dir
    pdf_note = ""
    # If this engine has no exp3_pdf yet, fall back to the peer engine's samples/figures.
    if pdf_df.empty and peer_df is not None and not peer_df.empty:
        peer_pdf = peer_df[peer_df["exp"] == "exp3_pdf"].copy()
        peer_pdf = peer_pdf[peer_pdf["cct_us"].notna() & (peer_pdf["cct_us"] > 0)]
        peer_pdf = peer_pdf[peer_pdf["batch"] < 512]
        if not peer_pdf.empty:
            pdf_df = peer_pdf
            peer_engine = str(peer_pdf["engine"].iloc[0]) if "engine" in peer_pdf.columns else "peer"
            peer_root = ROOT / "results" / ("ub_rg_packet" if peer_engine == "packet" else "ub_rg")
            if (peer_root / "figures").exists():
                pdf_figs_dir = peer_root / "figures"
            pdf_note = f"（当前引擎尚无 exp3_pdf；下图暂用 **{peer_engine}** 引擎样本）\n"
    if not pdf_df.empty:
        if pdf_note:
            lines.append(pdf_note)
        stats = pdf_df.pivot_table(
            index=["scenario", "ep_size", "batch", "zipf_s"],
            columns="scheme",
            values="cct_us",
            aggfunc=["mean", "std", "count"],
        )
        lines.append("**系统 CCT 样本统计（µs，mean/std/count）**\n\n")
        lines.append("```\n" + clean_table(stats.round(2).to_string()) + "\n```\n")
        for sc in sorted(pdf_df["scenario"].unique()):
            lines.append(f"### 4.{int(sc)} 场景{int(sc)} PDF\n")
            sc_figs = sorted(pdf_figs_dir.glob(f"exp3_pdf_s{int(sc)}_b*_s*.png"))
            if sc_figs:
                for p in sc_figs:
                    lines.append(md_img(p) + "\n")
            else:
                lines.append("_（该场景 PDF 样本尚未齐）_\n")
        lines.append("### 4.4 跨场景对比 PDF（S1-EP128 / S2-EP1024 / S3-EP1024）\n")
        for p in sorted(pdf_figs_dir.glob("exp3_pdf_compare_b*_s*.png")):
            lines.append(md_img(p) + "\n")
    else:
        lines.append("_（exp3_pdf 系统 CCT 样本尚未生成，运行 `run_ub_rg_experiments.py --exp3-pdf`）_\n")
    lines.append("### 4.x Roundtrip Step vs EP（汇总）\n")
    for sc in sorted(df[df["exp"] == "exp3_roundtrip"]["scenario"].unique()):
        for p in sorted(figs_dir.glob(f"exp3_s{int(sc)}_step_vs_ep.png")):
            lines.append(md_img(p) + "\n")

    lines.append("## 5. 方案对比摘要\n")
    e1 = df[df["exp"] == "exp1_dispatch"]
    if not e1.empty:
        # Align on cells present for every scheme so legacy larger-batch ub_rg
        # rows do not dominate the mean when a new scheme only has a subset.
        align_keys = ["scenario", "batch", "zipf_s", "ep_size"]
        piv = e1.pivot_table(index=align_keys, columns="scheme", values="step_us")
        common = piv.dropna(subset=[c for c in SCHEMES if c in piv.columns], how="any")
        for sc in sorted(e1["scenario"].unique()):
            cell = common.xs(int(sc), level="scenario") if not common.empty else None
            if cell is None or cell.empty:
                s = e1[e1["scenario"] == sc]
                rg = s[s["scheme"] == "ub_rg"]["step_us"].mean()
                pop = s[s["scheme"] == "ub_rg_pop"]["step_us"].mean()
                sp = s[s["scheme"] == "packet_spray"]["step_us"].mean()
            else:
                rg = float(cell["ub_rg"].mean()) if "ub_rg" in cell.columns else float("nan")
                pop = float(cell["ub_rg_pop"].mean()) if "ub_rg_pop" in cell.columns else float("nan")
                sp = (
                    float(cell["packet_spray"].mean())
                    if "packet_spray" in cell.columns
                    else float("nan")
                )
            parts = []
            if rg == rg and rg > 0:  # not NaN
                parts.append(f"UB_RG={rg:.1f}µs")
            if pop == pop and pop > 0 and rg == rg and rg > 0:
                parts.append(f"POP={pop:.1f}µs（POP/RG={(pop/rg):.2f}×）")
            if sp == sp and sp > 0 and rg == rg and rg > 0:
                parts.append(f"Spray={sp:.1f}µs（Spray/RG={(sp/rg):.2f}×）")
            if parts:
                lines.append(
                    f"- **场景{int(sc)}** 平均 step（三方案共有参数格）："
                    + " vs ".join(parts)
                    + "\n"
                )
            # CCT / König ratio when bound is available (per-scheme, all rows)
            s = e1[e1["scenario"] == sc]
            s2 = s[s["konig_us"].notna() & (s["konig_us"] > 0)].copy()
            if not s2.empty:
                s2["ratio"] = s2["cct_us"] / s2["konig_us"]
                for scheme in SCHEMES:
                    g = s2[s2["scheme"] == scheme]["ratio"]
                    if not g.empty:
                        lines.append(
                            f"- **场景{int(sc)}** {scheme} CCT/König："
                            f"mean={g.mean():.3f}，median={g.median():.3f}\n"
                        )

    if peer_df is not None and not peer_df.empty:
        lines.append("## 6. 双引擎对比（逐包 vs 行为级）\n")
        lines.append(
            "在相同 (scenario, scheme, mode, batch, zipf_s, ep_size) 键上对齐 step_us / lat_p99。\n"
        )
        keys = ["exp", "scenario", "scheme", "mode", "batch", "zipf_s", "ep_size"]

        def _by_engine(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
            out: dict[str, pd.DataFrame] = {}
            if frame is None or frame.empty or "engine" not in frame.columns:
                return out
            for eng, g in frame.groupby("engine", dropna=False):
                name = str(eng)
                if name not in ("packet", "behavioral"):
                    continue
                out[name] = g[keys + ["step_us", "lat_p99"]].copy()
            return out

        by_eng = _by_engine(df)
        by_eng.update(_by_engine(peer_df))
        pkt = by_eng.get("packet")
        beh = by_eng.get("behavioral")
        if pkt is None or beh is None:
            lines.append("_缺少 packet 或 behavioral 一侧结果，无法做双引擎对比。_\n")
        else:
            a = pkt.rename(columns={"step_us": "step_packet", "lat_p99": "p99_packet"})
            b = beh.rename(columns={"step_us": "step_behav", "lat_p99": "p99_behav"})
            m = a.merge(b, on=keys, how="inner")
            if m.empty:
                lines.append("_无对齐样本（另一引擎结果尚未齐备）。_\n")
            else:
                m["step_ratio"] = m["step_packet"] / m["step_behav"].replace(0, np.nan)
                lines.append(
                    f"对齐样本 **{len(m)}** 组；step 比值（packet/behavioral）"
                    f"均值={m['step_ratio'].mean():.3f}，"
                    f"中位数={m['step_ratio'].median():.3f}。\n"
                )
                sample = m.head(20)
                lines.append(
                    "```\n" + clean_table(sample.round(3).to_string(index=False)) + "\n```\n"
                )
                lines.append(
                    "差异主要来自：逐包栈的静态时延（传播/转发/分配）、真实控制面报文、"
                    "以及 TP/Jetty 注入路径；行为级模型把这些折叠为常量 RTT/屏障。\n"
                )

            ratio_keys = ["exp", "scenario", "mode", "batch", "zipf_s", "ep_size"]
            for eng, frame in (("packet", pkt), ("behavioral", beh)):
                scheme_steps = frame.pivot_table(
                    index=ratio_keys,
                    columns="scheme",
                    values="step_us",
                    aggfunc="mean",
                )
                if "ub_rg" not in scheme_steps.columns:
                    continue
                ratios = []
                if "ub_rg_pop" in scheme_steps.columns:
                    pop = (
                        scheme_steps["ub_rg_pop"]
                        / scheme_steps["ub_rg"].replace(0, np.nan)
                    ).dropna()
                    if not pop.empty:
                        ratios.append(f"POP/RG={pop.mean():.3f}×")
                if "packet_spray" in scheme_steps.columns:
                    spray = (
                        scheme_steps["packet_spray"]
                        / scheme_steps["ub_rg"].replace(0, np.nan)
                    ).dropna()
                    if not spray.empty:
                        ratios.append(f"Spray/RG={spray.mean():.3f}×")
                if ratios:
                    lines.append(f"- **{eng}** 同参数格平均：" + "，".join(ratios) + "\n")

    lines.append("## 7. 结论\n")
    lines.append(
        "- UB_RG 通过目的侧授权节奏控制将完成时间压到出口瓶颈附近，并隔离热点排队。\n"
        "- UB_RG_POP（SHMEM-POP）与 RG 共享目的侧节奏/König 渐近；"
        "Push→Pull 多付一次单向启动，均匀小负载时常接近 RG，高偏斜/两层上偶发更差。\n"
        "- Packet Spray 在倾斜流量下 p99/CCT 放大更明显，软件屏障也更重。\n"
        "- 逐包引擎用于校验控制面与数据面交互；行为级引擎用于快速扫矩阵。\n"
    )
    lines.append("## 8. 复现方法\n")
    lines.append(
        "```bash\n"
        "cd ns-3-ub && ./ns3 configure --enable-modules=unified-bus --enable-mtp "
        "--disable-python -d optimized\n"
        "./ns3 build ub_rg-packet-experiment\n"
        "cd ..\n"
        "python3 gen_ub_rg_topo.py --scenario 1\n"
        "python3 run_ub_rg_experiments.py --engine packet --workers 4\n"
        "python3 run_ub_rg_experiments.py --engine packet --exp3-pdf --seeds 8 "
        "--batches 16,64,256,1024 --workers 4\n"
        "python3 analyze_ub_rg_experiments.py --engine packet\n"
        "```\n"
    )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote report {REPORT}")
    _write_html_report("".join(lines), REPORT.with_suffix(".html"), figs_dir)
    csv_path = results / "all_summaries.csv"
    df.to_csv(csv_path, index=False)
    print(f"Wrote {csv_path} ({len(df)} rows), {len(fig_paths)} figures")


def _analyze_one(results: Path) -> int:
    figs_dir = results / "figures"
    figs_dir.mkdir(parents=True, exist_ok=True)
    df = load_summaries(results)
    if df.empty:
        print("No summaries found under", results)
        return 1

    peer = None
    other = ROOT / "results" / ("ub_rg" if results.name == "ub_rg_packet" else "ub_rg_packet")
    if other.exists():
        peer = load_summaries(other)

    figs = []
    figs += plot_exp12(df, "exp1_dispatch", "Exp1 Dispatch", figs_dir)
    figs += plot_exp12(df, "exp2_combine", "Exp2 Combine", figs_dir)
    figs += plot_exp3(df, figs_dir)
    figs += plot_exp3_pdf(df, figs_dir)
    write_report(df, figs, results, figs_dir, peer)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["behavioral", "packet", "both"], default="packet")
    ap.add_argument("--results", type=str, default="", help="Override results directory")
    args = ap.parse_args()

    targets: list[Path] = []
    if args.results:
        targets = [Path(args.results)]
    elif args.engine == "both":
        # Behavioral first; packet last so docs/UB_RG仿真报告.* reflects packet.
        targets = [ROOT / "results" / "ub_rg", ROOT / "results" / "ub_rg_packet"]
    elif args.engine == "behavioral":
        targets = [ROOT / "results" / "ub_rg"]
    else:
        targets = [ROOT / "results" / "ub_rg_packet"]

    rc = 0
    for results in targets:
        if not results.exists():
            print("Skip missing", results)
            continue
        r = _analyze_one(results)
        rc = rc or r
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
