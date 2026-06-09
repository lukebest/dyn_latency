"""Run the MoE dispatch/combine dynamic-latency experiments.

Outputs:
  results/summary.json      machine-readable results (also feeds the canvas)
  results/decomp.png        latency decomposition (static / incast / congestion)
  results/sweep.png         makespan vs hotspot share
  results/perrank.png       per-rank completion (victim spreading)
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
    """fraction of token-expert dispatches landing on the hot rank."""
    inbound = routing.count.sum(axis=0)
    return float(inbound[cfg.hot_rank] / inbound.sum())


def run_point(rho_h: float, n_planes: int = 1, seed: int = 0) -> dict:
    cfg = MoEConfig(rho_h=rho_h, seed=seed)
    routing = draw_routing(cfg)
    disp = routing.dispatch_bytes()
    comb = routing.combine_bytes()
    out = {"rho_h": rho_h, "hot_share": hot_share(routing, cfg),
           "n_planes": n_planes,
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
    rhos = [0.0, 0.3, 0.5, 0.7]
    points = [run_point(r) for r in rhos]
    summary = {"RTT_us": RTT * US, "link_Gbps": 200, "n_nodes": 16,
               "points": points}
    with open(os.path.join(RESULTS, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    _print_tables(points)
    _plots(points)
    print(f"\nWrote {RESULTS}/summary.json, decomp.png, sweep.png, perrank.png")


def _print_tables(points: list[dict]) -> None:
    for p in points:
        print(f"\n================ hotspot rho_h={p['rho_h']} "
              f"(hot rank share={p['hot_share']*100:.1f}%) ================")
        print(f"  dispatch total={p['dispatch_total_MB']:.1f} MB, "
              f"combine total={p['combine_total_MB']:.1f} MB")
        for phase, ph in p["phases"].items():
            a = ph["analysis"]
            print(f"  --- {phase} ---")
            print(f"    incast floor (unoptimizable) : {a['incast_floor_us']:8.2f} us "
                  f"(serialize {a['incast_serialize_us']:.2f})")
            print(f"    baseline  makespan           : {a['baseline_makespan_us']:8.2f} us")
            print(f"    SHMEM-POP makespan           : {a['shmempop_makespan_us']:8.2f} us")
            print(f"    optimization headroom        : {a['optimization_headroom_us']:8.2f} us")
            print(f"    SHMEM-POP gap to floor       : {a['shmempop_gap_to_floor_us']:8.2f} us")
            print(f"    headroom captured by POP     : {a['captured_pct']:8.1f} %")


def _plots(points: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mid = next(p for p in points if p["rho_h"] == 0.5)

    # 1) decomposition stacked bars (dispatch & combine, 3 scenarios)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, phase in zip(axes, ("dispatch", "combine")):
        ph = mid["phases"][phase]
        labels = ["Oracle\n(floor)", "Baseline\n(uncoord.)", "SHMEM-POP"]
        static = [ph[s]["static_us"] for s in SCENARIOS]
        incast = [ph[s]["incast_serialize_us"] for s in SCENARIOS]
        cong = [max(0.0, ph[s]["makespan_us"] - ph[s]["floor_us"]) for s in SCENARIOS]
        x = np.arange(3)
        ax.bar(x, static, label="static (pipeline)", color="#9ecae1")
        ax.bar(x, incast, bottom=static, label="incast serialize (unoptimizable)",
               color="#fdae6b")
        ax.bar(x, cong, bottom=np.array(static) + np.array(incast),
               label="congestion excess (optimizable)", color="#de2d26")
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("network makespan (us)")
        ax.set_title(f"{phase}  (rho_h=0.5, hot share={mid['hot_share']*100:.0f}%)")
        ax.grid(axis="y", alpha=0.3)
    axes[0].legend(loc="upper left", fontsize=8)
    fig.suptitle("MoE network dynamic latency decomposition — 16 nodes, 1 switch, 200 Gbps")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "decomp.png"), dpi=130)
    plt.close(fig)

    # 2) sweep makespan vs rho_h
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    rhos = [p["rho_h"] for p in points]
    for ax, phase in zip(axes, ("dispatch", "combine")):
        floor = [p["phases"][phase]["analysis"]["incast_floor_us"] for p in points]
        ax.plot(rhos, floor, "k--", marker="o", label="incast floor (unoptimizable)")
        for sc, col in zip(SCENARIOS, ["#2ca02c", "#d62728", "#1f77b4"]):
            y = [p["phases"][phase][sc]["makespan_us"] for p in points]
            ax.plot(rhos, y, marker="s", color=col, label=sc)
        ax.set_xlabel("hotspot share rho_h")
        ax.set_ylabel("network makespan (us)")
        ax.set_title(phase)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle("Makespan vs hotspot intensity")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "sweep.png"), dpi=130)
    plt.close(fig)

    # 3) per-rank completion (dispatch, rho_h=0.5) -> victim spreading
    fig, ax = plt.subplots(figsize=(11, 5))
    ph = mid["phases"]["dispatch"]
    N = len(ph["oracle"]["recv_done_us"])
    x = np.arange(N)
    w = 0.27
    for k, (sc, col) in enumerate(zip(SCENARIOS, ["#2ca02c", "#d62728", "#1f77b4"])):
        ax.bar(x + (k - 1) * w, ph[sc]["recv_done_us"], width=w, label=sc, color=col)
    ax.axhline(ph["oracle"]["floor_us"], ls="--", color="k",
               label="hot-rank incast floor")
    ax.set_xlabel("rank (rank 0 = hot)")
    ax.set_ylabel("dispatch completion (us)")
    ax.set_title("Per-rank dispatch completion (rho_h=0.5): congestion spreading to cold ranks")
    ax.set_xticks(x)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "perrank.png"), dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
