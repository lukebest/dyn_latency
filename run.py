"""Run MoE dispatch/combine dynamic-latency experiments (lossless CBFC fabric).

Experiments:
  A. hotspot sweep   rho_h in {0,0.3,0.5,0.7}      (N=16, P=1, fixed buffer)
  B. plane sweep     P in {1,2,4,8}                 (N=16, rho_h=0.5, fixed buffer)
  C. node sweep      N in {16,64,128}               (P=1, rho_h=0.5, fixed buffer)
  D. P x N grid      P in {1,2,4,8} x N in {16,64,128}, rho_h=0.5,
                     switch buffer MATCHED to the (P,N) incast fan-in
  E. buffer sweep    baseline per-port buffer 100KB..4MB per N in {16,64,128}
                     (P=1, rho_h=0.5)

Outputs under results/:
  summary.json, decomp.png, sweep.png, perrank.png,
  plane_sweep.png, node_sweep.png, grid_floor.png, buffer_match.png,
  buffer_sweep_compare.png, buffer_sweep_N{16,64,128}.png

Usage:
  python3 run.py              # all experiments
  python3 run.py --only buffer  # buffer sweep only
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np

from dynlat.scenarios import RTT, matched_buffer, base_phys, run_phase
from dynlat.workload import MoEConfig, draw_routing

US = 1e6
SCENARIOS = ["oracle", "baseline", "shmempop"]
RESULTS = os.path.join(os.path.dirname(__file__), "results")


def hot_share(routing, cfg) -> float:
    inbound = routing.count.sum(axis=0)
    return float(inbound[cfg.hot_rank] / inbound.sum())


def run_point(rho_h: float, n_planes: int = 1, n_ranks: int = 16,
              seed: int = 0, buffer_mode: str = "fixed") -> dict:
    cfg = MoEConfig(n_ranks=n_ranks, rho_h=rho_h, seed=seed)
    routing = draw_routing(cfg)
    disp = routing.dispatch_bytes()
    comb = routing.combine_bytes()
    out = {"rho_h": rho_h, "n_planes": n_planes, "n_ranks": n_ranks,
           "buffer_mode": buffer_mode,
           "hot_share": hot_share(routing, cfg),
           "dispatch_total_MB": disp.sum() / 1e6,
           "combine_total_MB": comb.sum() / 1e6,
           "phases": {}}
    for phase_name, M in (("dispatch", disp), ("combine", comb)):
        ph = {}
        for sc in SCENARIOS:
            r = run_phase(phase_name, sc, M, n_planes=n_planes, buffer_mode=buffer_mode)
            ph[sc] = {
                "makespan_us": r.makespan * US,
                "floor_us": r.floor * US,
                "incast_serialize_us": r.incast_serialize * US,
                "static_us": r.static * US,
                "congestion_us": (r.makespan - r.floor) * US,
                "buffer_KB": (r.buffer_bytes / 1024) if r.buffer_bytes != float("inf") else None,
                "credit_KB": r.credit_bytes / 1024,
                "recv_done_us": (r.recv_done * US).tolist(),
            }
        floor = ph["oracle"]["floor_us"]
        headroom = ph["baseline"]["makespan_us"] - floor
        gap = ph["shmempop"]["makespan_us"] - floor
        ph["analysis"] = {
            "incast_floor_us": floor,
            "incast_serialize_us": ph["oracle"]["incast_serialize_us"],
            "baseline_makespan_us": ph["baseline"]["makespan_us"],
            "shmempop_makespan_us": ph["shmempop"]["makespan_us"],
            "optimization_headroom_us": headroom,
            "shmempop_gap_to_floor_us": gap,
            "captured_pct": (100.0 * (ph["baseline"]["makespan_us"]
                              - ph["shmempop"]["makespan_us"]) / headroom)
                             if headroom > 1e-9 else float("nan"),
        }
        out["phases"][phase_name] = ph
    return out


# per-output-port switch buffer sweep (KB)
BUFFER_SWEEP_KB = [100, 128, 200, 256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096]
BUFFER_SWEEP_NODES = [16, 64, 128]


def run_buffer_sweep(rho_h: float = 0.5, n_planes: int = 1, n_ranks: int = 16,
                     seed: int = 0) -> list[dict]:
    """Sweep baseline switch buffer; oracle/shmempop are reference (buffer-independent)."""
    cfg = MoEConfig(n_ranks=n_ranks, rho_h=rho_h, seed=seed)
    routing = draw_routing(cfg)
    disp = routing.dispatch_bytes()
    comb = routing.combine_bytes()
    phys = base_phys(n_planes, n_ranks)
    match_kb = matched_buffer(phys, n_ranks) / 1024

    refs: dict[str, dict] = {}
    for phase_name, M in (("dispatch", disp), ("combine", comb)):
        refs[phase_name] = {}
        for sc in ("oracle", "shmempop"):
            r = run_phase(phase_name, sc, M, n_planes=n_planes)
            recv = r.recv_done * US
            refs[phase_name][sc] = {
                "makespan_us": r.makespan * US,
                "floor_us": r.floor * US,
                "congestion_us": (r.makespan - r.floor) * US,
                "cold_mean_us": float(recv[1:].mean()) if len(recv) > 1 else float(recv[0]),
            }

    points = []
    for buf_kb in BUFFER_SWEEP_KB:
        buf_b = buf_kb * 1024
        pt = {"buffer_KB": buf_kb, "rho_h": rho_h, "n_planes": n_planes,
              "n_ranks": n_ranks, "matched_buffer_KB": match_kb, "phases": {}}
        for phase_name, M in (("dispatch", disp), ("combine", comb)):
            r = run_phase(phase_name, "baseline", M, n_planes=n_planes,
                          baseline_buffer_bytes=buf_b)
            recv = r.recv_done * US
            floor = refs[phase_name]["oracle"]["floor_us"]
            pt["phases"][phase_name] = {
                "baseline": {
                    "makespan_us": r.makespan * US,
                    "floor_us": floor,
                    "congestion_us": (r.makespan * US) - floor,
                    "cold_mean_us": float(recv[1:].mean()) if len(recv) > 1 else float(recv[0]),
                    "hot_us": float(recv[0]),
                },
                "oracle": refs[phase_name]["oracle"],
                "shmempop": refs[phase_name]["shmempop"],
            }
        points.append(pt)
    return points


def run_buffer_sweeps(nodes: list[int] | None = None, **kwargs) -> dict[int, list[dict]]:
    nodes = nodes or BUFFER_SWEEP_NODES
    return {N: run_buffer_sweep(n_ranks=N, **kwargs) for N in nodes}


def main() -> None:
    parser = argparse.ArgumentParser(description="MoE dynamic latency experiments")
    parser.add_argument("--only", choices=["buffer"], default=None,
                        help="run a single experiment group")
    args = parser.parse_args()
    os.makedirs(RESULTS, exist_ok=True)

    if args.only == "buffer":
        _run_buffer_only()
        return

    print("### A. hotspot sweep (N=16, P=1) ###")
    rhos = [0.0, 0.3, 0.5, 0.7]
    rho_points = [run_point(r) for r in rhos]
    _print_tables(rho_points)

    print("\n### B. plane sweep (N=16, rho_h=0.5) ###")
    planes = [1, 2, 4, 8]
    plane_points = [run_point(0.5, n_planes=P) for P in planes]
    _print_sweep(plane_points, "n_planes", planes)

    print("\n### C. node sweep (P=1, rho_h=0.5) ###")
    nodes = [16, 64, 128]
    node_points = [run_point(0.5, n_ranks=N) for N in nodes]
    _print_sweep(node_points, "n_ranks", nodes)

    print("\n### D. P x N grid (rho_h=0.5, buffer MATCHED to fan-in) ###")
    grid = {}  # grid[P][N] = point
    for P in planes:
        grid[P] = {}
        for N in nodes:
            grid[P][N] = run_point(0.5, n_planes=P, n_ranks=N, buffer_mode="matched")
    _print_grid(grid, planes, nodes)

    print("\n### E. buffer sweep (N in {16,64,128}, P=1, rho_h=0.5, 100KB..4MB) ###")
    buffer_sweeps = run_buffer_sweeps()
    _print_buffer_sweeps(buffer_sweeps)

    summary = {"RTT_us": RTT * US, "link_Gbps": 200, "fabric": "lossless CBFC",
               "hotspot_sweep": rho_points,
               "plane_sweep": plane_points,
               "node_sweep": node_points,
               "pn_grid": {str(P): {str(N): grid[P][N] for N in nodes} for P in planes},
               "buffer_sweep": {str(N): pts for N, pts in buffer_sweeps.items()}}
    with open(os.path.join(RESULTS, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    _plots(rho_points, plane_points, planes, node_points, nodes)
    _plot_grid(grid, planes, nodes)
    _plot_buffer_sweeps(buffer_sweeps)
    print(f"\nWrote {RESULTS}/summary.json and 11 PNGs")


def _run_buffer_only() -> None:
    print("### E. buffer sweep (N in {16,64,128}, P=1, rho_h=0.5, 100KB..4MB) ###")
    buffer_sweeps = run_buffer_sweeps()
    _print_buffer_sweeps(buffer_sweeps)
    path = os.path.join(RESULTS, "summary.json")
    summary = {}
    if os.path.exists(path):
        with open(path) as fh:
            summary = json.load(fh)
    summary["buffer_sweep"] = {str(N): pts for N, pts in buffer_sweeps.items()}
    with open(path, "w") as fh:
        json.dump(summary, fh, indent=2)
    _plot_buffer_sweeps(buffer_sweeps)
    print(f"\nWrote buffer_sweep_N*.png, buffer_sweep_compare.png")


def _print_tables(points: list[dict]) -> None:
    for p in points:
        print(f"\n== rho_h={p['rho_h']} (hot share={p['hot_share']*100:.0f}%) "
              f"disp={p['dispatch_total_MB']:.1f}MB comb={p['combine_total_MB']:.1f}MB ==")
        for phase, ph in p["phases"].items():
            a = ph["analysis"]
            print(f"  {phase:8s} floor={a['incast_floor_us']:7.1f}  "
                  f"base={a['baseline_makespan_us']:7.1f}  "
                  f"pop={a['shmempop_makespan_us']:7.1f}  "
                  f"headroom={a['optimization_headroom_us']:6.1f}  "
                  f"gap={a['shmempop_gap_to_floor_us']:5.2f}  "
                  f"captured={a['captured_pct']:5.1f}%")


def _print_sweep(points: list[dict], key: str, vals: list) -> None:
    for v, p in zip(vals, points):
        for phase, ph in p["phases"].items():
            a = ph["analysis"]
            print(f"  {key}={v:<4} {phase:8s} floor={a['incast_floor_us']:7.1f}  "
                  f"base={a['baseline_makespan_us']:7.1f}  "
                  f"pop={a['shmempop_makespan_us']:7.1f}  gap={a['shmempop_gap_to_floor_us']:5.2f}")


def _saturation_buffer_kb(points: list[dict], phase: str = "dispatch",
                          tol_us: float = 1.0) -> int | None:
    """Smallest buffer where baseline makespan is within tol_us of floor."""
    floor = points[0]["phases"][phase]["oracle"]["floor_us"]
    for p in points:
        ms = p["phases"][phase]["baseline"]["makespan_us"]
        if ms <= floor + tol_us:
            return p["buffer_KB"]
    return None


def _print_buffer_sweeps(sweeps: dict[int, list[dict]]) -> None:
    for N, points in sweeps.items():
        match_kb = points[0]["matched_buffer_KB"]
        floor_d = points[0]["phases"]["dispatch"]["oracle"]["floor_us"]
        sat_d = _saturation_buffer_kb(points, "dispatch")
        sat_c = _saturation_buffer_kb(points, "combine")
        print(f"\n  --- N={N}  matched={match_kb:.0f}KB  floor={floor_d:.0f}µs  "
              f"sat_buf disp={sat_d}KB comb={sat_c}KB ---")
        for p in points:
            d = p["phases"]["dispatch"]["baseline"]
            c = p["phases"]["combine"]["baseline"]
            print(f"  buf={p['buffer_KB']:4d}KB  "
                  f"disp: makespan={d['makespan_us']:7.1f} cong={d['congestion_us']:6.1f} "
                  f"cold_mean={d['cold_mean_us']:6.1f}  "
                  f"comb: makespan={c['makespan_us']:7.1f} cong={c['congestion_us']:6.1f}")


def _print_grid(grid: dict, planes: list, nodes: list) -> None:
    """Print dispatch-phase floor, makespans and matched buffer per (P,N)."""
    print("  phase=dispatch  (floor_us | base_us | pop_us | base_buf_KB | pop_buf_KB)")
    for P in planes:
        for N in nodes:
            ph = grid[P][N]["phases"]["dispatch"]
            a = ph["analysis"]
            bb = ph["baseline"]["buffer_KB"]
            pb = ph["shmempop"]["buffer_KB"]
            print(f"  P={P:<2} N={N:<4} floor={a['incast_floor_us']:7.1f}  "
                  f"base={a['baseline_makespan_us']:7.1f}  "
                  f"pop={a['shmempop_makespan_us']:7.1f}  "
                  f"base_buf={bb:8.1f}KB  pop_buf={pb:6.1f}KB")


def _plots(rho_points, plane_points, planes, node_points, nodes) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mid = next(p for p in rho_points if p["rho_h"] == 0.5)
    cols = ["#2ca02c", "#d62728", "#1f77b4"]

    # 1) decomposition
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, phase in zip(axes, ("dispatch", "combine")):
        ph = mid["phases"][phase]
        labels = ["Oracle\n(floor)", "Baseline\n(uncoord.)", "SHMEM-POP"]
        static = [ph[s]["static_us"] for s in SCENARIOS]
        incast = [ph[s]["incast_serialize_us"] for s in SCENARIOS]
        cong = [max(0.0, ph[s]["makespan_us"] - ph[s]["floor_us"]) for s in SCENARIOS]
        x = np.arange(3)
        ax.bar(x, static, label="static (pipeline)", color="#9ecae1")
        ax.bar(x, incast, bottom=static, label="incast serialize (unoptimizable)", color="#fdae6b")
        ax.bar(x, cong, bottom=np.array(static) + np.array(incast),
               label="congestion excess (optimizable)", color="#de2d26")
        ax.set_xticks(x); ax.set_xticklabels(labels)
        ax.set_ylabel("network makespan (us)")
        ax.set_title(f"{phase} (rho_h=0.5, hot share={mid['hot_share']*100:.0f}%)")
        ax.grid(axis="y", alpha=0.3)
    axes[0].legend(loc="upper left", fontsize=8)
    fig.suptitle("Network dynamic latency decomposition (lossless CBFC) — 16 nodes, 1 switch, 200 Gbps")
    fig.tight_layout(); fig.savefig(os.path.join(RESULTS, "decomp.png"), dpi=130); plt.close(fig)

    # 2) hotspot sweep
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    rhos = [p["rho_h"] for p in rho_points]
    for ax, phase in zip(axes, ("dispatch", "combine")):
        ax.plot(rhos, [p["phases"][phase]["analysis"]["incast_floor_us"] for p in rho_points],
                "k--", marker="o", label="incast floor")
        for sc, c in zip(SCENARIOS, cols):
            ax.plot(rhos, [p["phases"][phase][sc]["makespan_us"] for p in rho_points],
                    marker="s", color=c, label=sc)
        ax.set_xlabel("hotspot share rho_h"); ax.set_ylabel("makespan (us)")
        ax.set_title(phase); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.suptitle("Makespan vs hotspot intensity"); fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "sweep.png"), dpi=130); plt.close(fig)

    # 3) per-rank dispatch completion
    fig, ax = plt.subplots(figsize=(11, 5))
    ph = mid["phases"]["dispatch"]; N = len(ph["oracle"]["recv_done_us"])
    x = np.arange(N); w = 0.27
    for k, (sc, c) in enumerate(zip(SCENARIOS, cols)):
        ax.bar(x + (k - 1) * w, ph[sc]["recv_done_us"], width=w, label=sc, color=c)
    ax.axhline(ph["oracle"]["floor_us"], ls="--", color="k", label="hot-rank incast floor")
    ax.set_xlabel("rank (0 = hot)"); ax.set_ylabel("dispatch completion (us)")
    ax.set_title("Per-rank dispatch completion (rho_h=0.5): congestion spreading")
    ax.set_xticks(x); ax.legend(fontsize=8); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(RESULTS, "perrank.png"), dpi=130); plt.close(fig)

    # 4) plane sweep: floor and scenarios vs P (shows floor ~ 1/P)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, phase in zip(axes, ("dispatch", "combine")):
        floor = [p["phases"][phase]["analysis"]["incast_floor_us"] for p in plane_points]
        ax.plot(planes, floor, "k--", marker="o", label="incast floor (~1/P)")
        for sc, c in zip(SCENARIOS, cols):
            ax.plot(planes, [p["phases"][phase][sc]["makespan_us"] for p in plane_points],
                    marker="s", color=c, label=sc)
        ax.set_xscale("log", base=2); ax.set_xticks(planes); ax.set_xticklabels(planes)
        ax.set_xlabel("number of planes P"); ax.set_ylabel("makespan (us)")
        ax.set_title(f"{phase} (N=16, rho_h=0.5)"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.suptitle("Multi-plane lower bound: incast floor scales as 1/P")
    fig.tight_layout(); fig.savefig(os.path.join(RESULTS, "plane_sweep.png"), dpi=130); plt.close(fig)

    # 5) node sweep: floor and scenarios vs N
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, phase in zip(axes, ("dispatch", "combine")):
        floor = [p["phases"][phase]["analysis"]["incast_floor_us"] for p in node_points]
        ax.plot(nodes, floor, "k--", marker="o", label="incast floor")
        for sc, c in zip(SCENARIOS, cols):
            ax.plot(nodes, [p["phases"][phase][sc]["makespan_us"] for p in node_points],
                    marker="s", color=c, label=sc)
        ax.set_xticks(nodes)
        ax.set_xlabel("number of endpoint nodes N (=EP)"); ax.set_ylabel("makespan (us)")
        ax.set_title(f"{phase} (P=1, rho_h=0.5)"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.suptitle("Node scaling (P=1, rho_h=0.5)")
    fig.tight_layout(); fig.savefig(os.path.join(RESULTS, "node_sweep.png"), dpi=130); plt.close(fig)


def _plot_grid(grid: dict, planes: list, nodes: list) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cols = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]

    # 6) P x N floor heatmap (dispatch): floor ~ N/P
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, phase in zip(axes, ("dispatch", "combine")):
        Z = np.array([[grid[P][N]["phases"][phase]["analysis"]["incast_floor_us"]
                       for N in nodes] for P in planes])
        im = ax.imshow(Z, cmap="viridis", aspect="auto", origin="lower")
        ax.set_xticks(range(len(nodes))); ax.set_xticklabels(nodes)
        ax.set_yticks(range(len(planes))); ax.set_yticklabels(planes)
        ax.set_xlabel("endpoint nodes N"); ax.set_ylabel("planes P")
        ax.set_title(f"{phase} incast floor (us)")
        for i in range(len(planes)):
            for j in range(len(nodes)):
                ax.text(j, i, f"{Z[i, j]:.1f}", ha="center", va="center",
                        color="w", fontsize=8)
        fig.colorbar(im, ax=ax, label="floor (us)")
    fig.suptitle("Incast floor over P x N grid (rho_h=0.5): floor scales as N/P")
    fig.tight_layout(); fig.savefig(os.path.join(RESULTS, "grid_floor.png"), dpi=130)
    plt.close(fig)

    # 7) matched buffer vs N for each P, vs SHMEM-POP flat (dispatch)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for P, c in zip(planes, cols):
        bufs = [grid[P][N]["phases"]["dispatch"]["baseline"]["buffer_KB"] for N in nodes]
        ax.plot(nodes, bufs, marker="o", color=c, label=f"baseline matched, P={P}")
    pop = [grid[planes[0]][N]["phases"]["dispatch"]["shmempop"]["buffer_KB"] for N in nodes]
    ax.plot(nodes, pop, "k--", marker="s", label="SHMEM-POP (any P)")
    ax.set_yscale("log"); ax.set_xticks(nodes)
    ax.set_xlabel("endpoint nodes N"); ax.set_ylabel("per-port switch buffer (KB, log)")
    ax.set_title("Switch buffer to reach the floor: baseline ~ BDP*(N-1)/P vs SHMEM-POP ~ O(BDP)")
    ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(RESULTS, "buffer_match.png"), dpi=130)
    plt.close(fig)


def _plot_buffer_sweep_one(points: list[dict], n_ranks: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bufs = [p["buffer_KB"] for p in points]
    match_kb = points[0]["matched_buffer_KB"]
    cols = {"oracle": "#2ca02c", "baseline": "#d62728", "shmempop": "#1f77b4"}

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))

    ax = axes[0, 0]
    floor = points[0]["phases"]["dispatch"]["oracle"]["floor_us"]
    pop = points[0]["phases"]["dispatch"]["shmempop"]["makespan_us"]
    base = [p["phases"]["dispatch"]["baseline"]["makespan_us"] for p in points]
    ax.plot(bufs, base, "o-", color=cols["baseline"], label="baseline makespan")
    ax.axhline(floor, ls="--", color=cols["oracle"], label=f"incast floor ({floor:.0f} µs)")
    ax.axhline(pop, ls=":", color=cols["shmempop"], label=f"SHMEM-POP ({pop:.0f} µs)")
    ax.axvline(match_kb, ls="-.", color="#888", alpha=0.7,
               label=f"matched buf ({match_kb:.0f} KB)")
    ax.set_xscale("log", base=2); ax.set_xticks(bufs); ax.set_xticklabels(bufs, rotation=45)
    ax.set_xlabel("switch per-port buffer (KB)"); ax.set_ylabel("makespan (µs)")
    ax.set_title("dispatch makespan vs switch buffer"); ax.grid(alpha=0.3); ax.legend(fontsize=7)

    ax = axes[0, 1]
    floor = points[0]["phases"]["combine"]["oracle"]["floor_us"]
    pop = points[0]["phases"]["combine"]["shmempop"]["makespan_us"]
    base = [p["phases"]["combine"]["baseline"]["makespan_us"] for p in points]
    ax.plot(bufs, base, "o-", color=cols["baseline"], label="baseline makespan")
    ax.axhline(floor, ls="--", color=cols["oracle"], label=f"incast floor ({floor:.0f} µs)")
    ax.axhline(pop, ls=":", color=cols["shmempop"], label=f"SHMEM-POP ({pop:.0f} µs)")
    ax.axvline(match_kb, ls="-.", color="#888", alpha=0.7)
    ax.set_xscale("log", base=2); ax.set_xticks(bufs); ax.set_xticklabels(bufs, rotation=45)
    ax.set_xlabel("switch per-port buffer (KB)"); ax.set_ylabel("makespan (µs)")
    ax.set_title("combine makespan vs switch buffer"); ax.grid(alpha=0.3); ax.legend(fontsize=7)

    ax = axes[1, 0]
    for phase, c in zip(("dispatch", "combine"), ("#d62728", "#ff7f0e")):
        cong = [max(0.0, p["phases"][phase]["baseline"]["congestion_us"]) for p in points]
        ax.plot(bufs, cong, "s-", color=c, label=f"{phase} congestion excess")
    ax.set_xscale("log", base=2); ax.set_xticks(bufs); ax.set_xticklabels(bufs, rotation=45)
    ax.set_xlabel("switch per-port buffer (KB)"); ax.set_ylabel("congestion excess (µs)")
    ax.set_title("optimizable dynamic latency vs buffer"); ax.grid(alpha=0.3); ax.legend(fontsize=8)

    ax = axes[1, 1]
    for phase, c in zip(("dispatch", "combine"), ("#1f77b4", "#9467bd")):
        cold = [p["phases"][phase]["baseline"]["cold_mean_us"] for p in points]
        ax.plot(bufs, cold, "d-", color=c, label=f"{phase} cold-rank mean")
    oracle_cold_d = points[0]["phases"]["dispatch"]["oracle"]["cold_mean_us"]
    ax.axhline(oracle_cold_d, ls="--", color=cols["oracle"],
               label=f"oracle cold mean ({oracle_cold_d:.0f} µs)")
    ax.set_xscale("log", base=2); ax.set_xticks(bufs); ax.set_xticklabels(bufs, rotation=45)
    ax.set_xlabel("switch per-port buffer (KB)"); ax.set_ylabel("cold-rank completion (µs)")
    ax.set_title("congestion spreading vs buffer"); ax.grid(alpha=0.3); ax.legend(fontsize=7)

    fig.suptitle(f"Switch buffer impact (baseline FIFO+CBFC, N={n_ranks}, P=1, ρ_h=0.5)")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, f"buffer_sweep_N{n_ranks}.png"), dpi=130)
    plt.close(fig)


def _plot_buffer_sweep_compare(sweeps: dict[int, list[dict]]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bufs = BUFFER_SWEEP_KB
    n_colors = {16: "#d62728", 64: "#ff7f0e", 128: "#9467bd"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    for phase, ax in zip(("dispatch", "combine"), axes):
        for N, points in sorted(sweeps.items()):
            floor = points[0]["phases"][phase]["oracle"]["floor_us"]
            pop = points[0]["phases"][phase]["shmempop"]["makespan_us"]
            match_kb = points[0]["matched_buffer_KB"]
            base = [p["phases"][phase]["baseline"]["makespan_us"] for p in points]
            c = n_colors.get(N, "#333")
            ax.plot(bufs, base, "o-", color=c, label=f"N={N} baseline")
            ax.axhline(floor, ls="--", color=c, alpha=0.35)
            ax.axvline(match_kb, ls=":", color=c, alpha=0.5)
            if N == 16:
                ax.axhline(pop, ls="-.", color="#1f77b4", alpha=0.6,
                           label=f"SHMEM-POP (N=16, {pop:.0f} µs)")
        ax.set_xscale("log", base=2); ax.set_xticks(bufs)
        ax.set_xticklabels(bufs, rotation=45, fontsize=8)
        ax.set_xlabel("switch per-port buffer (KB)"); ax.set_ylabel("makespan (µs)")
        ax.set_title(f"{phase} makespan vs buffer (all N)")
        ax.grid(alpha=0.3); ax.legend(fontsize=7)

    fig.suptitle("Buffer saturation scales with N: matched buffer and floor both grow")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "buffer_sweep_compare.png"), dpi=130)
    plt.close(fig)


def _plot_buffer_sweeps(sweeps: dict[int, list[dict]]) -> None:
    for N, points in sweeps.items():
        _plot_buffer_sweep_one(points, N)
    _plot_buffer_sweep_compare(sweeps)


if __name__ == "__main__":
    main()
