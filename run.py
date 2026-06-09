"""Run MoE dispatch/combine dynamic-latency experiments (lossless CBFC fabric).

Experiments:
  A. hotspot sweep   rho_h in {0,0.3,0.5,0.7}      (N=16, P=1)
  B. plane sweep     P in {1,2,4,8}                 (N=16, rho_h=0.5)
  C. node sweep      N in {16,64,128}               (P=1, rho_h=0.5)

Outputs under results/:
  summary.json, decomp.png, sweep.png, perrank.png,
  plane_sweep.png, node_sweep.png
"""
from __future__ import annotations

import json
import os

import numpy as np

from dynlat.scenarios import RTT, run_phase
from dynlat.workload import MoEConfig, draw_routing

US = 1e6
SCENARIOS = ["oracle", "baseline", "shmempop"]
RESULTS = os.path.join(os.path.dirname(__file__), "results")


def hot_share(routing, cfg) -> float:
    inbound = routing.count.sum(axis=0)
    return float(inbound[cfg.hot_rank] / inbound.sum())


def run_point(rho_h: float, n_planes: int = 1, n_ranks: int = 16,
              seed: int = 0) -> dict:
    cfg = MoEConfig(n_ranks=n_ranks, rho_h=rho_h, seed=seed)
    routing = draw_routing(cfg)
    disp = routing.dispatch_bytes()
    comb = routing.combine_bytes()
    out = {"rho_h": rho_h, "n_planes": n_planes, "n_ranks": n_ranks,
           "hot_share": hot_share(routing, cfg),
           "dispatch_total_MB": disp.sum() / 1e6,
           "combine_total_MB": comb.sum() / 1e6,
           "phases": {}}
    for phase_name, M in (("dispatch", disp), ("combine", comb)):
        ph = {}
        for sc in SCENARIOS:
            r = run_phase(phase_name, sc, M, n_planes=n_planes)
            ph[sc] = {
                "makespan_us": r.makespan * US,
                "floor_us": r.floor * US,
                "incast_serialize_us": r.incast_serialize * US,
                "static_us": r.static * US,
                "congestion_us": (r.makespan - r.floor) * US,
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


def main() -> None:
    os.makedirs(RESULTS, exist_ok=True)

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

    summary = {"RTT_us": RTT * US, "link_Gbps": 200, "fabric": "lossless CBFC",
               "hotspot_sweep": rho_points,
               "plane_sweep": plane_points,
               "node_sweep": node_points}
    with open(os.path.join(RESULTS, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    _plots(rho_points, plane_points, planes, node_points, nodes)
    print(f"\nWrote {RESULTS}/summary.json and 5 PNGs")


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


if __name__ == "__main__":
    main()
