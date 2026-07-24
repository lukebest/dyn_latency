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
SCHEMES = ("ub_rg", "ub_rg_pop", "packet_spray", "islip")
SCHEME_LS = {
    "ub_rg": "-",
    "ub_rg_pop": "-.",
    "packet_spray": "--",
    "islip": ":",
}
SCHEME_COLOR = {
    "ub_rg": "C0",
    "ub_rg_pop": "C2",
    "packet_spray": "C1",
    "islip": "C3",
}


def schemes_in(df: pd.DataFrame) -> list[str]:
    present = set(df["scheme"].dropna().unique()) if "scheme" in df.columns else set()
    return [s for s in SCHEMES if s in present]


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
                "gemv_us": d.get("gemv_us"),
                "e2e_us": d.get("e2e_us"),
                "e2e_step_us": d.get("e2e_step_us"),
                "start_skew_us": d.get("start_skew_us", 0.0),
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
            # Active matrix is scenarios 1 + 4; ignore legacy 2/3 result dirs.
            if row.get("scenario") in (2, 3):
                continue
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
        for scheme in schemes_in(s):
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
        for scheme in schemes_in(s):
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
        for scheme in schemes_in(s):
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


def plot_exp12_bars(df: pd.DataFrame, exp: str, tag: str, figs_dir: Path):
    """Grouped bar charts comparing schemes for Exp1/Exp2."""
    sub = df[df["exp"] == exp].copy()
    if sub.empty:
        return []
    if "start_skew_us" not in sub.columns:
        sub["start_skew_us"] = 0.0
    sub["start_skew_us"] = sub["start_skew_us"].fillna(0.0)
    figs = []
    for scenario in sorted(sub["scenario"].unique()):
        s = sub[sub["scenario"] == scenario]
        schemes = schemes_in(s)
        if not schemes:
            continue
        batches = sorted(s["batch"].unique())
        skews = sorted(s["start_skew_us"].unique())
        zipfs = sorted(s["zipf_s"].unique())
        # Representative cells: each batch × each skew, bars over schemes × zipf
        for batch in batches:
            for skew in skews:
                cell = s[(s["batch"] == batch) & np.isclose(s["start_skew_us"], skew)]
                if cell.empty:
                    continue
                fig, ax = plt.subplots(figsize=(8.5, 4.8))
                x = np.arange(len(zipfs))
                width = 0.8 / max(len(schemes), 1)
                for i, scheme in enumerate(schemes):
                    ys = []
                    for zs in zipfs:
                        g = cell[(cell["scheme"] == scheme) & np.isclose(cell["zipf_s"], zs)]
                        ys.append(float(g["step_us"].mean()) if not g.empty else np.nan)
                    ax.bar(
                        x + i * width - 0.4 + width / 2,
                        ys,
                        width=width * 0.92,
                        label=scheme,
                        color=SCHEME_COLOR.get(scheme, f"C{i}"),
                    )
                ax.set_xticks(x)
                ax.set_xticklabels([f"{z:g}" for z in zipfs])
                style_ax(
                    ax,
                    f"{tag} S{int(scenario)} bar: step_us vs Zipf "
                    f"(batch={int(batch)}, skew={skew:g}µs)",
                    "Zipf S",
                    "Step (µs)",
                )
                path = figs_dir / (
                    f"{exp}_s{int(scenario)}_bar_step_vs_zipf"
                    f"_b{int(batch)}_sk{skew:g}.png"
                )
                fig.tight_layout()
                fig.savefig(path, dpi=140)
                plt.close(fig)
                figs.append(path)

        # Cross-batch bars at mid zipf / each skew
        z_focus = 0.7 if any(np.isclose(zipfs, 0.7)) else zipfs[len(zipfs) // 2]
        for skew in skews:
            cell = s[np.isclose(s["start_skew_us"], skew) & np.isclose(s["zipf_s"], z_focus)]
            if cell.empty:
                continue
            fig, ax = plt.subplots(figsize=(8.5, 4.8))
            x = np.arange(len(batches))
            width = 0.8 / max(len(schemes), 1)
            for i, scheme in enumerate(schemes):
                ys = []
                for b in batches:
                    g = cell[(cell["scheme"] == scheme) & (cell["batch"] == b)]
                    ys.append(float(g["step_us"].mean()) if not g.empty else np.nan)
                ax.bar(
                    x + i * width - 0.4 + width / 2,
                    ys,
                    width=width * 0.92,
                    label=scheme,
                    color=SCHEME_COLOR.get(scheme, f"C{i}"),
                )
            ax.set_xticks(x)
            ax.set_xticklabels([str(int(b)) for b in batches])
            style_ax(
                ax,
                f"{tag} S{int(scenario)} bar: step_us vs Batch "
                f"(S={z_focus:g}, skew={skew:g}µs)",
                "BatchSize",
                "Step (µs)",
            )
            path = figs_dir / (
                f"{exp}_s{int(scenario)}_bar_step_vs_batch"
                f"_s{z_focus:g}_sk{skew:g}.png"
            )
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
        for scheme in schemes_in(s):
            ls = SCHEME_LS[scheme]
            for zipf_s in sorted(s["zipf_s"].unique()):
                g = s[(s["scheme"] == scheme) & np.isclose(s["zipf_s"], zipf_s)].sort_values(
                    "ep_size"
                )
                if g.empty:
                    continue
                step = g["step_us"].copy()
                if "e2e_step_us" in g.columns:
                    step = g["e2e_step_us"].fillna(step)
                if "roundtrip_step_us" in g.columns:
                    step = step.fillna(g["roundtrip_step_us"])
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
    ep_color = {32: "C0", 64: "C1", 128: "C2", 256: "C4", 512: "C5", 1024: "C3"}
    sc_color = {1: "C0", 4: "C1", 2: "C3", 3: "C2"}
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
                    for scheme in schemes_in(cell):
                        g = cell[(cell["ep_size"] == ep) & (cell["scheme"] == scheme)]
                        metric = (
                            "e2e_us"
                            if "e2e_us" in g.columns and g["e2e_us"].notna().any()
                            else "cct_us"
                        )
                        samples = g[metric].to_numpy(dtype=float)
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
                    "End-to-end CCT (µs)  "
                    "[dispatch→GEMV(Zipf,batch)→combine]",
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
        (4, 512),
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
                for scheme in schemes_in(cell):
                    g = cell[cell["scheme"] == scheme]
                    metric = (
                        "e2e_us"
                        if "e2e_us" in g.columns and g["e2e_us"].notna().any()
                        else "cct_us"
                    )
                    samples = g[metric].to_numpy(dtype=float)
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
                "End-to-end CCT (µs)  "
                "[dispatch→GEMV(Zipf,batch)→combine]",
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
        "<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;",
        "line-height:1.55;padding:0 1rem;color:#222}",
        "img{max-width:100%;height:auto;border:1px solid #ddd;margin:0.5rem 0}",
        "img[src$='.svg']{width:100%;max-width:1100px;background:#fff;margin:0.75rem 0}",
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
        elif in_ul and (line.startswith("  ") or line.startswith("\t")) and line.strip():
            # Continuation of the previous list item (wrapped markdown bullets).
            if parts and parts[-1].endswith("</li>\n"):
                prev = parts[-1][: -len("</li>\n")]
                parts[-1] = f"{prev} {_md_inline(line.strip(), html_lib, re)}</li>\n"
            else:
                parts.append(f"<li>{_md_inline(line.strip(), html_lib, re)}</li>\n")
        elif line.strip() == "":
            flush_ul()
            parts.append("<br/>\n")
        else:
            flush_ul()
            parts.append(f"<p>{_md_inline(line, html_lib, re)}</p>\n")
    flush_ul()
    flush_table()
    html_path.write_text("".join(parts), encoding="utf-8")
    print(f"Wrote {html_path}")


def code_evidence_index_md() -> str:
    """Key microarchitecture code evidence — shown near the front of reports."""
    return """## 微架构关键代码证据索引

下表把上图中的模块直接映射到仓库文件位置；阅读结果前应先能定位这些实现。

| 微架构模块 | 证据 | 文件与位置 |
|---|---|---|
| 行为级常量 / grain / 端口速率 | τ_g、50 GB/s、hop 时延 | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:29-36` |
| Zipf / TopK → grain | 负载与专家路由 | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:260-351` |
| Spray / RG / POP phase | 三方案排队与授权 | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:438-738` |
| S4 / iSLIP / 启动偏差 / GEMV | PathClass、iSLIP matching、start-skew、ComputeGemvUs | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc` |
| 行为级 CCT / König | 指标与 summary | `ns-3-ub/scratch/ub_rg-dispatch-experiment.cc:520-538, 730-812, 886-921` |
| 逐包拓扑 / S3 路由过滤 | Leaf–Spine 与 FIB | `gen_ub_rg_topo.py:47-181`（S3：`144-180`） |
| 逐包 token / scheduler map | 工作负载与挂接 | `ns-3-ub/src/unified-bus/model/ub-rg-experiment-app.cc:117-407` |
| phase / completion / watchdog | 计时与收尾 | `ns-3-ub/src/unified-bus/model/ub-rg-experiment-app.cc:439-742` |
| POP completion overlay | 非完整 Push/Pull | `ns-3-ub/src/unified-bus/model/ub-rg-experiment-app.cc:589-608, 878-887` |
| REQ pacing | 50 µs 控制注入 | `ns-3-ub/src/unified-bus/model/protocol/ub-rg-sender-agent.cc:113-181` |
| GNT → WQE / Jetty / TP | 数据注入 | `ns-3-ub/src/unified-bus/model/protocol/ub-rg-sender-agent.cc:227-376` |
| RR / credit / stale reclaim | 目的侧调度 | `ns-3-ub/src/unified-bus/model/protocol/ub-rg-scheduler.cc:93-341` |
| LOCAL / GLOBAL SYNC | 同步协议 | `protocol/ub-rg-scheduler.cc:374-409`；`protocol/ub-rg-sender-agent.cc:379-426` |
| 首 MTU 入队归还 credit | credit 语义 | `ns-3-ub/src/unified-bus/model/ub-switch.cc:453-490` |
| RG 末跳拦截 | REQ/DATA 转发 | `ns-3-ub/src/unified-bus/model/ub-switch.cc:1184-1258` |
| schedulerId 仅 6 bit | SYNC id 折叠 | `ns-3-ub/src/unified-bus/model/protocol/ub-rg-header.cc:227-236` |
| runner 矩阵 | 任务与跳过 | `run_ub_rg_experiments.py:18-145, 211-277, 340-403` |

"""


def microarchitecture_overview_md(fig_rel: str = "ub_rg_figures/ub_rg_microarchitecture.png") -> str:
    """Front-matter diagram + evidence index for HTML/MD reports."""
    return (
        "## 0. 通信微架构总览\n\n"
        "下图概括本仿真**已建模的通信微架构**与**未建模的计算微架构**。"
        "随后表格给出上图各模块对应的关键代码位置。\n\n"
        f"![UB_RG 通信微架构](./{fig_rel})\n\n"
        + code_evidence_index_md().replace(
            "## 微架构关键代码证据索引",
            "## 0.1 微架构关键代码证据索引",
            1,
        )
    )


def simulation_environment_md(engine: str) -> str:
    """Execution environment, modeled microarchitecture, and exact CCT scope."""
    engine_model = (
        "ns-3.44 逐包离散事件模型：Unified Bus 的 TP/Jetty、端口、交换机转发以及 "
        "REQ/GNT/SYNC 控制报文均进入事件队列。"
        if engine == "packet"
        else "grain 级行为离散事件模型：不逐包执行完整协议栈，而以串行化服务器、FIFO、"
        "固定传播/流水时延和控制 RTT 表示网络。"
    )
    return f"""### 1.1 仿真环境、微架构抽象与 CCT 口径

| 项目 | 配置 / 抽象 |
|---|---|
| 执行主机 | Linux 6.17.0-40-generic（x86_64） |
| 工具链 | Python 3.12.3；g++ 13.3.0；CMake 3.28.3；ns-3.44 optimized build |
| 当前报告引擎 | `{engine}`；{engine_model} |
| 并行方式 | 单次仿真保持单线程确定性；参数点由 Python `ProcessPoolExecutor` 并行 |
| 端点模型 | 每个 NPU 对应一个网络端点/专家；每 token 的每个 TopK 路由项形成一个 7 KB grain |
| 网络接口 | 每 NPU 8 个 400 Gbit/s 上联；有效 50 GB/s/端口；τ_g=7168/50e9≈143.36 ns |
| 交换结构 | 50 ns/跳传播 + 150 ns/跳流水；场景1 单层 Clos；场景4 Sparse CLOS（PFM/SW-S/SW-a-b） |
| 启动偏差 | 各 NPU 起点 ~U(0,skew)，skew∈{2,4,8} µs |
| 负载生成 | TopK=8；Zipf S；主矩阵 seed=1；Exp3 PDF 每格 96 seeds |

#### 微架构模型边界

- **已建模的是通信微架构**：NPU 端口串行化、8 平面选路、Spray 目的出口/两层 Clos 中段队列、RG nominal 授权节拍、POP 的启动时延/PullCredit，以及 BSP 屏障常量。
- **因果比较尚未闭环**：Spray 与 RG 同时改变 plane 映射、path delay 公式、jitter 和固定 barrier；当前比值是配置包差异，不能单独归因于目的侧准入。
- **计算侧（Exp3）**：`gemv_us = max_e N_e·τ_tok`（均匀 Zipf、batch=256 时约 80µs/专家）；`e2e_us = dispatch_cct + gemv_us + combine_cct`。
- **未建模**：完整 SM/HBM/cache、专家算力异构；iSLIP 仅替换 SW 匹配算法（其余同 `ub_rg`）。
- 主矩阵为 **场景1 + 场景4**（已去掉场景2/3）。

#### CCT 的准确口径

- Exp1/2：`cct_us` / `step_us` = 网络阶段（含启动偏差）+ barrier。
- Exp3：`cct_us` = 网络往返；`gemv_us` / `e2e_us` / `step_us(=e2e+barriers)` 含 Zipf×batch GEMV。

"""


def topology_and_scheme_md(engine: str) -> str:
    """组网差异 + 三方案实现差异（对齐 EXPERIMENT_REPORT_FULL_S123 结构，口径为本仓库实现）。"""
    eng_note = (
        "逐包引擎（`ub_rg-packet-experiment` + `UbRgExperimentApp`）"
        if engine == "packet"
        else "行为级引擎（`ub_rg-dispatch-experiment`）"
    )
    scenario_scope_note = (
        "主矩阵仅跑场景1与场景4；场景4 行为级按 Sparse CLOS 路径类（PFM / SW-S / SW-a-b）建模。"
        if engine != "packet"
        else "逐包场景4拓扑若未就绪，则逐包仅用于场景1 协议调试。"
    )
    return f"""### 1.2 组网方案

对齐 [UB_RG实验设计.md](./UB_RG实验设计.md) 与 [场景4_Sparse_CLOS_512P_设计说明.md](./场景4_Sparse_CLOS_512P_设计说明.md)；本报告由 {eng_note} 驱动。

> {scenario_scope_note}

| 场景 | 拓扑 | NPU | 交换 | 备注 |
|---|---|---:|---|---|
| 1 | 单层 Clos | 128 | 8 × SW128 | 8×400G；2 跳；另含 iSLIP 调度对照 |
| 4 | Sparse CLOS | 512 | 32 × SW128 | 8 Cluster×64 Server；15×400G（7 PFM+8 上联）；唯一路径 |

组网差异要点：

- **跳数 / RTT**：场景1 RTT_rg≈0.6µs；场景4 典型 SW≈0.8µs，同机 PFM 更短。
- **瓶颈**：场景1 目的侧平面下行；场景4 跨 Cluster SW 下行与 PFM 争用。
- **调度**：场景1 含 `islip`；场景4 为 `ub_rg` / `ub_rg_pop` / `packet_spray`。

### 1.3 网络方案与实现差异

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
| `ub_rg_pop` | 仿真 scheme | [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md) 的假设模型：行为级为 RG + startup + PullCredit；逐包为 RG 路径 + completion 计时 overlay |
| `packet_spray` | 仿真 scheme | 无授权准入；源上联自由注入；目的/中段 FIFO；分析阶段叠软件屏障 |
| `islip` | 仿真 scheme | 与 `ub_rg` 相同：路径钉扎 + REQ/GNT + RTT/barrier；仅将每出口独立 RR 换成每 τ_g 的 iSLIP matching（对齐 `ub_request_grant.md` §2.7） |

> **对齐的核心（设计 ↔ ub_rg）：** grain 量化、τ_g、每平面 ≤1 授权、Clos/MpClos 钉扎。
> **POP 相对 RG：** 稳态 König 渐近相同；startup = RTT_rg + oneWay（≈1.5×）；小 batch 略慢，大负载/高偏斜时 pop≈rg。
> **Spray 相对 RG：** 无目的侧节拍 → 热点队列放大，CCT/p99 与软件屏障更重。

#### 三方机制对照

| 维度 | `packet_spray` | `ub_rg` | `ub_rg_pop`（本仓库） |
|---|---|---|---|
| 调度 / 准入 | 无；源侧自由注入 | 目的侧 GNT 节奏（1/τ_g/egress） | 同 RG；多一次 Push 单向 |
| 控制通道 | 无控制面握手 | REQ → GNT → DATA（逐包真实报文；行为级折叠为 RTT） | 行为级用 `rtt_pop` 近似；逐包未发送 Push/Pull 报文，只在 RG completion 上叠 startup |
| 注入准入 | 仅源端口串行 | GNT 到才发，无预支库存 | 行为级有 `C_pop=⌈rtt_pop/τ_g⌉+margin`；逐包与 RG 使用相同 credit |
| 冷启动 | 0（立即发） | 付一次 RTT_rg | 付 RTT_rg + oneWay（Push→Grant→Pull） |
| ESC / 节拍 | 无 | 每 τ_g 每 egress ≤1 grain | 同左（König 渐近对齐 RG） |
| 数据路径 | 源序 RR 洒平面；两层含 spine→leaf 队列 | RG 平面钉扎；近零队列（σ 抖动） | 同 RG 钉扎 |
| 屏障 | 软件屏障（更重） | BSP cursor 屏障（轻） | 同 `ub_rg` |
| 实现入口 | `UsePacketSpray=true` | `Scheme::UbRg` / RG scheduler active | `Scheme::UbRgPop`；逐包复用 RG transport并在统计时追加 one-way |

#### 实验可读差异（期望趋势）

| 维度 | `ub_rg` | `ub_rg_pop` | `packet_spray` |
|---|---|---|---|
| 首包 / 小 batch | 付 RTT_rg | 略高于 RG（多 oneWay） | 常介于二者之间或更差（无节拍） |
| 大 batch / 高偏斜 | CCT 贴 König | pop/rg → 1（同节拍） | spray/rg ≫ 1，hot p99 放大 |
| 冷流隔离 | 好（按需授权） | 接近 RG | 差（热点占满下行） |
| 两层 Clos | 中段压力可控 | 偶发略差于 RG | 中段 FIFO 放大更明显 |

CLI：`--scheme=ub_rg|ub_rg_pop|packet_spray|islip`；`--start-skew-us=2|4|8`。
"""

def md_img(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return f"![{path.name}](../{rel})"


def clean_table(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines())


def executive_summary_md(df: pd.DataFrame) -> str:
    """Build an evidence-linked summary from cells shared by all three schemes."""
    lines = ["## 0.2 主要实验结论\n"]
    lines.append(
        "> 结论适用于场景1/4；Exp1/2 为网络子系统；Exp3 含 Zipf×batch GEMV straggler。\n"
    )
    e1 = df[df["exp"] == "exp1_dispatch"]
    required = ["ub_rg", "ub_rg_pop", "packet_spray"]
    if not e1.empty:
        piv = e1.pivot_table(
            index=["scenario", "batch", "zipf_s", "ep_size"],
            columns="scheme",
            values="step_us",
            aggfunc="mean",
        )
        if all(s in piv.columns for s in required):
            common = piv.dropna(subset=required)
            if not common.empty:
                pop_ratio = common["ub_rg_pop"] / common["ub_rg"].replace(0, np.nan)
                spray_ratio = common["packet_spray"] / common["ub_rg"].replace(0, np.nan)
                lines.append(
                    f"- **配置包输出差异**：Exp1 三方案共有参数格中，"
                    f"POP/RG 平均为 **{pop_ratio.mean():.3f}×**，"
                    f"Spray/RG 平均为 **{spray_ratio.mean():.3f}×**。"
                    "这是当前配置包的联合差异；plane、path delay、jitter 和 barrier "
                    "尚未统一，不能把比值单独归因于目的侧配速"
                    "（见 §7.1）。\n"
                )
                batches = sorted(common.index.get_level_values("batch").unique())
                if batches:
                    low = int(batches[0])
                    high = int(batches[-1])
                    low_ratio = pop_ratio[
                        pop_ratio.index.get_level_values("batch") == low
                    ].mean()
                    high_ratio = pop_ratio[
                        pop_ratio.index.get_level_values("batch") == high
                    ].mean()
                    lines.append(
                        f"- **POP 启动开销会被负载摊薄**：batch={low} 时 POP/RG="
                        f"**{low_ratio:.3f}×**，batch={high} 时为 **{high_ratio:.3f}×**；"
                        "结果符合“多一次 one-way 启动、稳态节拍与 RG 相同”的模型预期。\n"
                    )
    # Scenario-1 iSLIP vs ub_rg (same light barrier class).
    e1_s1 = e1[e1["scenario"] == 1] if not e1.empty else e1
    if not e1_s1.empty and "islip" in set(e1_s1["scheme"]):
        piv_i = e1_s1.pivot_table(
            index=["batch", "zipf_s", "ep_size", "start_skew_us"]
            if "start_skew_us" in e1_s1.columns
            else ["batch", "zipf_s", "ep_size"],
            columns="scheme",
            values="step_us",
            aggfunc="mean",
        )
        if "islip" in piv_i.columns and "ub_rg" in piv_i.columns:
            both = piv_i.dropna(subset=["islip", "ub_rg"])
            if not both.empty:
                ir = both["islip"] / both["ub_rg"].replace(0, np.nan)
                    lines.append(
                        f"- **场景1 iSLIP（匹配对照）**：与 `ub_rg` 共路径钉扎/REQ-GNT/"
                        f"RTT/barrier，仅 SW 仲裁不同；Exp1 iSLIP/RG 平均 **"
                        f"{ir.mean():.3f}×**（中位 {ir.median():.3f}×）。"
                    )
                    batches = sorted(both.index.get_level_values("batch").unique())
                    if len(batches) >= 2:
                        b0, b1 = int(batches[0]), int(batches[-1])
                        r0 = ir[ir.index.get_level_values("batch") == b0].mean()
                        r1 = ir[ir.index.get_level_values("batch") == b1].mean()
                        lines.append(
                            f"batch={b0} 为 **{r0:.3f}×**，batch={b1} 为 **{r1:.3f}×**。"
                        )
                    lines.append(
                        "这是文档 §2.7「每 τ_g matching」相对当前模型「每出口独立 RR」的对照。\n"
                    )
    e3 = df[df["exp"] == "exp3_roundtrip"]
    e3_s1 = e3[e3["scenario"] == 1] if not e3.empty else e3
    if not e3_s1.empty and "islip" in set(e3_s1["scheme"]) and "ub_rg" in set(e3_s1["scheme"]):
        piv3 = e3_s1.pivot_table(
            index=["ep_size", "zipf_s", "start_skew_us"]
            if "start_skew_us" in e3_s1.columns
            else ["ep_size", "zipf_s"],
            columns="scheme",
            values="step_us",
            aggfunc="mean",
        )
        if "islip" in piv3.columns and "ub_rg" in piv3.columns:
            both3 = piv3.dropna(subset=["islip", "ub_rg"])
            if not both3.empty:
                r3 = both3["islip"] / both3["ub_rg"].replace(0, np.nan)
                gemv_note = ""
                if "gemv_us" in e3_s1.columns and e3_s1["gemv_us"].notna().any():
                    g = e3_s1[e3_s1["scheme"] == "ub_rg"]
                    share = (g["gemv_us"] / g["e2e_us"].replace(0, np.nan)).mean()
                    if share == share:
                        gemv_note = (
                            f" Exp3 端到端中 GEMV 约占 e2e 的 **{share:.0%}**，"
                            "调度差异被计算 straggler 摊薄，故 iSLIP≈RG。"
                        )
                lines.append(
                    f"- **Exp3（S1）iSLIP/RG** 平均 **{r3.mean():.3f}×**。"
                    f"{gemv_note}\n"
                )
    bound = df[df["konig_us"].notna() & (df["konig_us"] > 0)].copy()
    if not bound.empty:
        bound["cct_to_konig"] = bound["cct_us"] / bound["konig_us"]
        med = bound.groupby("scheme")["cct_to_konig"].median()
        values = [
            f"{scheme}={med[scheme]:.3f}"
            for scheme in SCHEMES
            if scheme in med.index
        ]
        if values:
            lines.append(
                "- **瓶颈下界**：CCT/König 中位数为 "
                + "、".join(values)
                + "；它证明输出符合当前方程，但不是排除混杂后的硬件性能验证。\n"
            )
    lines.append(
        "- **拓扑范围**：主矩阵为场景1（Clos+iSLIP）与场景4（Sparse CLOS 512P）。\n"
    )
    lines.append(
        "- **Exp3**：端到端含 GEMV；`gemv_us` 随 Zipf 热点与 batch 变化。\n"
    )
    return "".join(lines)


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
    lines.append(
        "> **可信性状态：实现证据存在，性能结论未验证。** 行为级结果仅作为网络机制假设；"
        "方案间路由、path delay、jitter 与 barrier 混杂尚未消除，逐包性能矩阵也未通过"
        "完成守恒与跨引擎校验。绝对硬件时延与完整POP硅片实现不得据此下结论；"
        "Exp3 GEMV 为标定服务模型。详见"
        "[UB_RG仿真可信性评估报告](./UB_RG仿真可信性评估报告.html)。\n"
    )
    lines.append(microarchitecture_overview_md("ub_rg_figures/ub_rg_microarchitecture.png"))
    lines.append(executive_summary_md(df))
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
    lines.append(simulation_environment_md(engine))
    lines.append(topology_and_scheme_md(engine))
    if engine == "packet":
        lines.append("### 1.4 模型假设与简化\n")
        lines.append(
            "- 端口 400Gbps，grain = 7KB（2×MTU），τ_g ≈ 143.36 ns\n"
            "- 真实 REQ/GNT/SYNC 控制报文（VL1）；末跳交换机拦截 REQ；"
            "目的侧 1 grain/τ_g + credit window + RR；源侧 FCFS grant 队列\n"
            "- UB_RG_POP：复用 RG 路径和相同 credit，只在 completion 统计上追加单向 startup；"
            "未实现独立 Push/Pull 数据通路（见 [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md)）\n"
            "- SYNC：各调度器 LOCAL → 聚合 NPU(member0) → GLOBAL 广播（与文档 §4.9 聚合点差异见正文）\n"
            "- transport retrans 已启用；省略：完整 POP 状态机、预补偿、多世代窗口、PHASE 管理面\n"
            "- Packet Spray：`UsePacketSpray` + 自由注入；软件屏障在分析阶段叠加\n"
            "- 专家与 NPU 1:1；TopK=8\n"
        )
    else:
        lines.append("### 1.4 模型假设与简化\n")
        lines.append(
            "- 端口 400Gbps（有效 50GB/s），grain = 7KB，τ_g ≈ 143.36 ns\n"
            "- 链路建模为串行化服务器 + FIFO；交换机直通 150 ns/跳，传播 50 ns/跳\n"
            "- UB_RG：目的侧按 1 grain/τ_g 授权节奏 + 源端口 FCFS\n"
            "- UB_RG_POP：同目的侧节奏；startup = RTT_rg + oneWay（Push→Grant→Pull）；"
            "PullCredit 窗口保稳态流水（见 [SHMEM-POP技术分档.md](./SHMEM-POP技术分档.md)）\n"
            "- Packet Spray：自由注入；软件屏障在分析阶段叠加\n"
            "- 场景4 按 Sparse CLOS 路径类建模；场景1 另跑 iSLIP（同 ub_rg，仅 matching 不同）\n"
            "- 启动偏差：每 NPU ~U(0,skew)，skew∈{2,4,8}µs\n"
            "- Exp3：GEMV = max 专家 token 数 × τ_tok\n"
            "- 专家与 NPU 1:1；TopK=8\n"
        )
    lines.append("### 1.5 参数矩阵（裁剪）\n")
    lines.append(
        "| 实验 | mode | 场景 | Batch | Zipf S | EP | 启动偏差 | 调度 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| 1 Dispatch | dispatch | 1,4 | 16,256 | 0,0.3,0.7,0.9 | full | 2/4/8 µs | S1:+islip |\n"
        "| 2 Combine | combine | 同实验1 | 同左 | 同左 | full | 同左 | 同左 |\n"
        "| 3 Roundtrip+GEMV | roundtrip | 1→{32,64,128}; 4→{128,256,512} | 256 | 同左 | 上列 | 同左 | 同左 |\n"
        "| 3 PDF | roundtrip | 同上 | 16,64,256 | 同左 | 每格 96 seeds | skew=4µs | 同左 |\n"
    )

    n = len(df)
    lines.append(f"\n引擎：**{engine}**；成功汇总运行数：**{n}**。原始结果：`{rel_results}/`。\n")
    lines.append(
        "> 上表对齐当前 runner：仅场景1+4；含启动偏差与场景1 iSLIP；"
        "Exp3 输出 gemv_us/e2e_us。旧场景2/3 结果请忽略。\n"
    )
    if engine == "packet":
        lines.append(
            "> 逐包引擎按风险路径裁剪且当前完整度不足；"
            "行为级引擎覆盖完整主矩阵与 PDF。"
            "逐包目前只用于协议调试，不得单独作为绝对值校准。"
            "实验3 系统 CCT PDF 若本引擎样本未齐，报告自动回退到行为级多 seed 结果。\n"
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

    lines.append("## 4. 实验3：网络系统级 Dispatch+Combine 完成时间 (CCT) PDF\n")
    lines.append(
        "横轴优先为**端到端完成时间**（`e2e_us`/`step_us`：dispatch→GEMV→combine；"
        "GEMV 由 Zipf 专家负载与 batch 标定）。网络-only `cct_us` 仍写入 summary 供对照。"
        "对每个 (场景, BatchSize, Zipf S, EP) 组合，"
        "在多个随机种子下各跑一次 roundtrip，每次运行贡献一个系统 CCT 样本，"
        "以此得到系统 CCT 的概率密度分布（PDF，无 CDF）。\n"
    )
    lines.append(
        "覆盖三个组网场景（与实验设计 §4.2.3 一致）：\n"
        "- **场景1** 单层 Clos：EP ∈ {32, 64, 128}\n"
        "- **场景4** Sparse CLOS：EP ∈ {128, 256, 512}\n"
        "每场景单独出 PDF；另附跨场景对比图（S1-EP128 / S4-EP512）。"
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
        lines.append("### 4.4 跨场景对比 PDF（S1-EP128 / S4-EP512）\n")
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
        # Align on base schemes only; islip is S1-only and must not drop S4 cells.
        base = [c for c in ("ub_rg", "ub_rg_pop", "packet_spray") if c in piv.columns]
        common = piv.dropna(subset=base, how="any") if base else piv.iloc[0:0]
        sc_levels = (
            set(common.index.get_level_values("scenario")) if not common.empty else set()
        )
        for sc in sorted(e1["scenario"].unique()):
            cell = (
                common.xs(int(sc), level="scenario")
                if (not common.empty and int(sc) in sc_levels)
                else None
            )
            if cell is None or (hasattr(cell, "empty") and cell.empty):
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
                    "若该比值显著偏离 1，不能仅解释为“逐包栈静态开销”。当前逐包实现还含"
                    "50µs REQ pacing、10ms stale-credit 回收，且两引擎的本地专家和场景2/3"
                    "plane 映射不一致；在统一输入、完成守恒和异常门禁通过前，"
                    "这里是**交叉验证失败证据**，不是行为级绝对值校准。\n"
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
    # Data-backed iSLIP bullets (scenario 1).
    e1_s1 = df[(df["exp"] == "exp1_dispatch") & (df["scenario"] == 1)]
    e3_s1 = df[(df["exp"] == "exp3_roundtrip") & (df["scenario"] == 1)]
    islip_exp1 = ""
    islip_exp3 = ""
    if not e1_s1.empty and {"islip", "ub_rg"} <= set(e1_s1["scheme"]):
        idx = ["batch", "zipf_s", "ep_size"]
        if "start_skew_us" in e1_s1.columns:
            idx = idx + ["start_skew_us"]
        piv = e1_s1.pivot_table(index=idx, columns="scheme", values="step_us", aggfunc="mean")
        both = piv.dropna(subset=["islip", "ub_rg"])
        if not both.empty:
            ir = both["islip"] / both["ub_rg"].replace(0, np.nan)
            batches = sorted(both.index.get_level_values("batch").unique())
            batch_bits = []
            for b in batches:
                rb = ir[ir.index.get_level_values("batch") == b].mean()
                batch_bits.append(f"batch={int(b)} 为 {rb:.3f}×")
            batch_txt = "；".join(batch_bits)
            islip_exp1 = (
                f"- **场景1 iSLIP（Exp1）**：与 `ub_rg` 同路径钉扎与 REQ/GNT，"
                f"仅将每出口独立 RR 换成 iSLIP matching；共有格 step 平均 "
                f"**{ir.mean():.3f}×**（{batch_txt}）。"
                "差异应解读为调度匹配算法之差，而非另一套数据面。\n"
            )
    if not e3_s1.empty and {"islip", "ub_rg"} <= set(e3_s1["scheme"]):
        idx = ["ep_size", "zipf_s"]
        if "start_skew_us" in e3_s1.columns:
            idx = idx + ["start_skew_us"]
        piv = e3_s1.pivot_table(index=idx, columns="scheme", values="step_us", aggfunc="mean")
        both = piv.dropna(subset=["islip", "ub_rg"])
        if not both.empty:
            ir = both["islip"] / both["ub_rg"].replace(0, np.nan)
            islip_exp3 = (
                f"- **场景1 iSLIP（Exp3）**：端到端 step 相对 RG 平均 **"
                f"{ir.mean():.3f}×**；因 Zipf×batch 标定的 GEMV 占 e2e 很大比例，"
                "网络调度差异被摊薄，iSLIP 与 RG 几乎重合。\n"
            )
    lines.append(
        "- 当前 UB_RG 配置包的 CCT 更接近自定义 König 下界；"
        "与 Spray 的比值是**配置包联合差异**，不是“仅改目的侧准入”的受控因果结论"
        "（原因见 §7.1）。\n"
        "- UB_RG_POP（近似模型）与 RG 共享目的侧节奏/König 渐近；"
        "多付一次 one-way 启动，小 batch 略慢、大负载接近 RG。\n"
        + islip_exp1
        + islip_exp3
        + "- 当前 Packet Spray 配置包在倾斜流量下 p99/CCT 更大；"
        "在统一 plane/path/jitter/barrier 之前，不宜把差距全部归因于“无目的侧配速”。\n"
        "- Exp3 端到端含按 Zipf/batch 标定的 GEMV straggler；更细 HBM/算子队列仍未建模。\n"
        "- 逐包引擎可用于协议调试；性能门禁通过前不能校准行为级绝对时延。\n"
    )
    lines.append("### 7.1 为何说“不是目的侧准入的受控因果结论”\n")
    lines.append(
        "受控因果结论需要：**只改变一个机制变量**，其余路径、时延、屏障、负载相同，"
        "再比较 CCT。当前行为级里，把 scheme 从 `packet_spray` 换成 `ub_rg` "
        "会**同时**改变多处，因此 Spray/RG 比值不能解读为“目的侧准入单独带来的收益”。\n"
        "\n"
        "| 混杂维度 | `packet_spray` | `ub_rg` | 为何干扰归因 |\n"
        "|---|---|---|---|\n"
        "| **plane 映射** | 源序 RR（`AssignSprayPlane`） | 源/目的 group 钉扎（`AssignRgPlane`） | 热点落到的出口集合不同，队列长度本身就变 |\n"
        "| **path delay** | 经交换机下行 FIFO 排队推进 | 注入后按 hop 公式到达 + 近零队 | 数据面时延模型不同，不只是“有没有 grant” |\n"
        "| **jitter** | 无 RG 式 σ 抖动 | 到达叠加 `U(0,1.5)·τ_g` | 人为噪声改变尾部，混入方案差 |\n"
        "| **barrier** | 软件屏障更重（场景1 约 2.0µs） | BSP 轻屏障（场景1 约 0.4µs） | `step_us` 含屏障；即使边界 CCT 相同，step 也会因屏障差拉开 |\n"
        "\n"
        "因此报告写的是**配置包输出差异**，不是“目的侧 1/τ_g 准入”的净效应。"
        "若要做受控因果，应固定同一 plane 映射、同一 hop/队列公式、同一 jitter 与 barrier，"
        "**只开关目的侧 grant 节拍**，再比 CCT。\n"
        "\n"
        "相对地，场景1 的 **iSLIP vs `ub_rg`** 是受控的调度对照："
        "二者共用 `AssignRgPlane` 路径钉扎、同一 RTT_rg、同一 hop/jitter/barrier 与"
        "同一源侧 FCFS grant 注入；**唯一差别**是交换机每 τ_g 的授权挑选——"
        "`ub_rg` 为每目的出口独立对 src 做 RR，`islip` 为平面内 bipartite matching"
        "（request/grant/accept，对齐 `ub_request_grant.md` §2.7）。"
        "因此 iSLIP/RG 比值可归因于匹配算法，而 Spray/RG 仍不能。\n"
    )
    lines.append("## 8. 复现方法\n")
    if engine == "behavioral":
        lines.append(
            "当前报告主体由行为级引擎生成。复现默认矩阵与 Exp3 PDF：\n"
            "```bash\n"
            "cd ns-3-ub && ./ns3 configure --enable-modules=unified-bus "
            "--disable-python -d optimized\n"
            "./ns3 build ub_rg-dispatch-experiment\n"
            "cd ..\n"
            "python3 run_ub_rg_experiments.py --engine behavioral\n"
            "python3 run_ub_rg_experiments.py --engine behavioral --exp3-pdf "
            "--seeds 96 --batches 16,64,256\n"
            "python3 analyze_ub_rg_experiments.py --engine behavioral\n"
            "```\n"
        )
    else:
        lines.append(
            "逐包引擎复现（仅用于协议调试；性能门禁通过前不要当作绝对值校准）：\n"
            "```bash\n"
            "cd ns-3-ub && ./ns3 configure --enable-modules=unified-bus --enable-mtp "
            "--disable-python -d optimized\n"
            "./ns3 build ub_rg-packet-experiment\n"
            "cd ..\n"
            "python3 gen_ub_rg_topo.py --scenario 1\n"
            "python3 run_ub_rg_experiments.py --engine packet --workers 4\n"
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
    # Prefer the active skewed matrix when present (drop legacy skew=0 / huge batch).
    if "start_skew_us" in df.columns and (df["start_skew_us"].fillna(0) > 0).any():
        df = df[df["start_skew_us"].fillna(0) > 0].copy()
    if "batch" in df.columns and (df["batch"] <= 256).any():
        df = df[df["batch"] <= 256].copy()

    peer = None
    other = ROOT / "results" / ("ub_rg" if results.name == "ub_rg_packet" else "ub_rg_packet")
    if other.exists():
        peer = load_summaries(other)
        if peer is not None and not peer.empty:
            if "start_skew_us" in peer.columns and (peer["start_skew_us"].fillna(0) > 0).any():
                peer = peer[peer["start_skew_us"].fillna(0) > 0].copy()
            if "batch" in peer.columns and (peer["batch"] <= 256).any():
                peer = peer[peer["batch"] <= 256].copy()

    figs = []
    figs += plot_exp12(df, "exp1_dispatch", "Exp1 Dispatch", figs_dir)
    figs += plot_exp12_bars(df, "exp1_dispatch", "Exp1 Dispatch", figs_dir)
    figs += plot_exp12(df, "exp2_combine", "Exp2 Combine", figs_dir)
    figs += plot_exp12_bars(df, "exp2_combine", "Exp2 Combine", figs_dir)
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
